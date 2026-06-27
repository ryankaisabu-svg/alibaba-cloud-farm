#!/usr/bin/env python3
"""
Alibaba Cloud account farm — Camoufox automation with proxy.
Loop: register → verify email → create API key.
If slider appears → skip + restart from beginning.
"""

import sys
import time
import json
import re
import random
import string
import math
import os
import subprocess
import urllib.request
import urllib.error
from playwright.sync_api import sync_playwright
try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

# ─ uinput virtual mouse for slider solve ─
try:
    import uinput
    UINPUT_AVAILABLE = True
except Exception:
    UINPUT_AVAILABLE = False

# ─ Global virtual mouse ─
_virtual_mouse = None

# ─ Config ───────────
# Mail.tm API — free disposable email with REST API.
# No credentials needed — we create accounts on the fly.
# Each attempt creates a new mail.tm account, uses it for Alibaba registration,
# then reads OTP via mail.tm API.

MAILTM_API = "https://api.mail.tm"
MAILTM_TOKEN = None  # Set per-attempt
MAILTM_EMAIL = None  # Set per-attempt
MAILTM_PASSWORD = None  # Set per-attempt

# Try loading .env if python-dotenv is available (not required for mail.tm)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

REGISTER_URL = "https://account.alibabacloud.com/register/intl_register.htm"

MAX_ATTEMPTS = 20  # Max registration attempts per run
RESULTS_FILE = os.environ.get("RESULTS_FILE", "results.json")
MODELSTUDIO_URL = "https://modelstudio.console.alibabacloud.com/"

# ── Helpers ──────────────────────────────────────────────────
def generate_email():
    """Create a new mail.tm account and return the email address."""
    global MAILTM_TOKEN, MAILTM_EMAIL, MAILTM_PASSWORD
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    
    # Get available domain
    req = urllib.request.Request(f"{MAILTM_API}/domains", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req) as resp:
        domains = json.loads(resp.read())
        domain = domains[0]["domain"] if domains else "web-library.net"
    
    email = f"{name}@{domain}"
    password = "Aa1" + ''.join(random.choices(string.ascii_letters + string.digits, k=12)) + "!"
    
    # Create account
    data = json.dumps({"address": email, "password": password}).encode()
    req = urllib.request.Request(f"{MAILTM_API}/accounts", data=data, headers={
        "Content-Type": "application/json",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(req) as resp:
        json.loads(resp.read())
    
    # Get token
    data = json.dumps({"address": email, "password": password}).encode()
    req = urllib.request.Request(f"{MAILTM_API}/token", data=data, headers={
        "Content-Type": "application/json",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(req) as resp:
        token_data = json.loads(resp.read())
        MAILTM_TOKEN = token_data["token"]
    
    MAILTM_EMAIL = email
    MAILTM_PASSWORD = password
    print(f"[MAIL] Created: {email}")
    return email

def generate_password():
    """Password: 8-20 chars, upper+lower+digit+special. Alibaba max 20 chars.
    Use only symbols that don't need Shift on US keyboard layout."""
    chars = string.ascii_letters + string.digits
    pw = ''.join(random.choices(chars, k=15))
    # Use underscore as special char (no Shift needed, always typeable)
    # Total: Aa1 (3) + 15 + _ (1) = 19 chars
    pw = "Aa1" + pw + "_"
    return pw


def read_otp_from_api(target_email, timeout=120):
    """Read OTP verification code from mail.tm API."""
    print(f"[MAIL] Waiting for OTP to {target_email}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(f"{MAILTM_API}/messages", headers={
                "Authorization": f"Bearer {MAILTM_TOKEN}",
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req) as resp:
                messages = json.loads(resp.read())
            
            for msg in messages[:10]:
                msg_id = msg.get("id")
                if not msg_id:
                    continue
                
                # Get full message
                req2 = urllib.request.Request(f"{MAILTM_API}/messages/{msg_id}", headers={
                    "Authorization": f"Bearer {MAILTM_TOKEN}",
                    "Accept": "application/json"
                })
                with urllib.request.urlopen(req2) as resp2:
                    detail = json.loads(resp2.read())
                
                body = detail.get("text", "") or detail.get("html", "")
                subject = detail.get("subject", "")
                body += " " + subject
                
                # Find OTP — 6 digit code
                otp_match = re.search(r'>\s*(\d{6})\s*</span>', body)
                if not otp_match:
                    otp_match = re.search(r'(?:code|verification)[^<]*?(\d{6})', body, re.IGNORECASE)
                if not otp_match:
                    for m in re.finditer(r'\b(\d{6})\b', body):
                        num = m.group(1)
                        if num not in ('181818', '999', '666666', '808080'):
                            otp_match = m
                            break
                
                if otp_match:
                    code = otp_match.group(1)
                    print(f"[MAIL] Found OTP: {code} for {target_email}")
                    # Delete the message
                    try:
                        req3 = urllib.request.Request(f"{MAILTM_API}/messages/{msg_id}", method="DELETE", headers={
                            "Authorization": f"Bearer {MAILTM_TOKEN}"
                        })
                        urllib.request.urlopen(req3)
                    except:
                        pass
                    return code
                    
        except Exception as e:
            print(f"[MAIL] Error: {e}")
        time.sleep(5)
    print("[MAIL] Timeout waiting for OTP")
    return None


def find_register_frame(page):
    """Find the passport.alibabacloud.com iframe — skip main page frame."""
    for frame in page.frames[1:]:
        if "passport.alibabacloud.com" in frame.url:
            return frame
    return None


def find_login_frame(page):
    """Find passport iframe on login page (same as register but login URL)."""
    for frame in page.frames[1:]:
        if "passport.alibabacloud.com" in frame.url:
            return frame
    return None


def auto_login(page, email, password, timeout=60):
    """Auto-fill login form in passport iframe and submit.
    Returns True if login succeeded (URL changed away from login page)."""
    print(f"  [LOGIN] Attempting auto-login for {email}...")

    # Wait for passport iframe to load
    frame = None
    for wait in range(15):
        frame = find_login_frame(page)
        if frame:
            break
        time.sleep(2)

    if not frame:
        print("  [LOGIN] ERROR: No passport iframe found!")
        return False

    print(f"  [LOGIN] Found iframe: {frame.url[:80]}")

    # Wait for form to render
    time.sleep(3)

    # Find login fields — mini_login.htm uses #fm-login-id and #fm-login-password
    login_id = None
    pw_field = None
    submit_btn = None

    for attempt_sel in range(10):
        try:
            login_id = frame.query_selector("#fm-login-id") or \
                       frame.query_selector("input[name='loginId']") or \
                       frame.query_selector("input[placeholder*='email']") or \
                       frame.query_selector("input[type='text']")
            pw_field = frame.query_selector("#fm-login-password") or \
                       frame.query_selector("input[name='password']") or \
                       frame.query_selector("input[type='password']")
            submit_btn = frame.query_selector("#fm-login-submit") or \
                         frame.query_selector("button[type='submit']") or \
                         frame.query_selector("input[type='submit']")

            if login_id and pw_field:
                break
        except:
            pass
        time.sleep(2)

    if not login_id or not pw_field:
        print("  [LOGIN] ERROR: Login fields not found!")
        # Debug: list all inputs
        try:
            for inp in frame.query_selector_all("input"):
                print(f"  [LOGIN]   INPUT: id={inp.get_attribute('id')} name={inp.get_attribute('name')} type={inp.get_attribute('type')}")
        except:
            pass
        return False

    # Fill email
    try:
        current_val = login_id.evaluate("el => el.value")
    except:
        current_val = ""
    if current_val != email:
        login_id.click()
        time.sleep(0.3)
        # Clear first
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        time.sleep(0.2)
        for ch in email:
            page.keyboard.type(ch, delay=20)
        time.sleep(0.5)
    print(f"  [LOGIN] Email filled: {email}")

    # Fill password
    pw_field.click()
    time.sleep(0.3)
    page.keyboard.press("Control+a")
    page.keyboard.press("Delete")
    time.sleep(0.2)
    for ch in password:
        page.keyboard.type(ch, delay=20)
    time.sleep(0.5)

    # Verify password
    pw_val = pw_field.evaluate("el => el.value")
    print(f"  [LOGIN] Password filled: len={len(pw_val)} match={pw_val == password}")

    # Click submit
    if submit_btn:
        submit_btn.click()
        print("  [LOGIN] Clicked Sign In")
    else:
        # Try pressing Enter
        page.keyboard.press("Enter")
        print("  [LOGIN] Pressed Enter")

    # Wait for redirect (login success = URL changes away from login page)
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(2)
        url = page.url.lower()
        if "login" not in url and "signin" not in url and "passport" not in url:
            print(f"  [LOGIN] ✅ Login success! URL: {page.url[:80]}")
            return True

        # Check for error messages in frame
        try:
            frame = find_login_frame(page)
            if frame:
                err = frame.query_selector(".form-error, .notice-error, [class*='error']")
                if err and err.is_visible():
                    err_text = err.inner_text().strip()
                    if err_text and len(err_text) > 2:
                        print(f"  [LOGIN] ⚠️ Error: {err_text[:200]}")
                        return False
        except:
            pass

    print(f"  [LOGIN] ❌ Login timeout ({timeout}s)")
    return False


def auto_create_api_key(page, timeout=60):
    """Auto-click 'Create API Key' button, then 'OK' in popup, then detect sk- key.
    Returns API key string or None."""
    print("  [8] Looking for Create API Key button...")

    # First: wait for "Initializing" to finish (loading spinner)
    print("  [8] Waiting for model service init to finish...")
    for wait in range(45):  # 90s max
        time.sleep(2)
        try:
            still_loading = page.evaluate("""
                () => {
                    const body = document.body;
                    if (!body) return true;
                    const text = body.innerText || '';
                    return text.includes('Initializing') || text.includes('Loading...');
                }
            """)
            if not still_loading:
                print(f"  [8] Model service ready ({wait*2}s)")
                break
        except:
            pass
        if wait % 5 == 0:
            print(f"  [8] Still initializing... ({wait*2}s)")

    safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "step8_after_init.png"))

    # Try to find and click "Create API Key" button
    # Search in ALL elements including shadow DOM
    create_clicked = False
    for wait in range(timeout):
        try:
            # Method 1: Search buttons/spans/divs for "Create" + "API" text
            btn = page.evaluate("""
                () => {
                    // Helper to search through shadow DOM too
                    function searchAll(root) {
                        const els = root.querySelectorAll('button, span, a, div, [role="button"], .next-btn, .ant-btn');
                        for (const el of els) {
                            const txt = (el.innerText || el.textContent || '').trim();
                            if ((txt.toLowerCase().includes('create') && txt.toLowerCase().includes('api')) ||
                                txt.toLowerCase().includes('create api key') ||
                                txt.toLowerCase().includes('create api-key')) {
                                el.click();
                                return txt;
                            }
                        }
                        // Search inside iframes
                        const iframes = root.querySelectorAll('iframe');
                        for (const iframe of iframes) {
                            try {
                                const doc = iframe.contentDocument;
                                if (doc) {
                                    const innerEls = doc.querySelectorAll('button, span, a, div, [role="button"]');
                                    for (const el of innerEls) {
                                        const txt = (el.innerText || el.textContent || '').trim();
                                        if ((txt.toLowerCase().includes('create') && txt.toLowerCase().includes('api')) ||
                                            txt.toLowerCase().includes('create api key')) {
                                            el.click();
                                            return txt;
                                        }
                                    }
                                }
                            } catch(e) {}
                        }
                        return null;
                    }
                    return searchAll(document);
                }
            """)
            if btn:
                print(f"  [8] Clicked: '{btn}'")
                create_clicked = True
                break
        except:
            pass
        
        # Method 2: Try Playwright's built-in text search
        if wait == 5:
            try:
                print("  [8] Trying Playwright text selector...")
                el = page.get_by_text("Create API Key", exact=False).first
                if el:
                    el.click()
                    print("  [8] Clicked 'Create API Key' via Playwright")
                    create_clicked = True
                    break
            except:
                pass
        
        time.sleep(1)

    if not create_clicked:
        print("  [8] 'Create API Key' button not found — checking if key already exists...")
        existing = scan_for_api_key(page)
        if existing:
            print(f"  [8] Found existing API key on page")
            return existing
        
        # Take debug screenshot
        safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "step8_no_create_debug.png"))
        print(f"  [8] Page URL: {page.url[:100]}")
        try:
            body_text = page.evaluate("() => (document.body.innerText || '').substring(0, 500)")
            print(f"  [8] Page text: {body_text[:200]}")
        except:
            pass
        return None

    # Wait for popup dialog
    time.sleep(3)

    # Click "OK" in the confirmation popup
    ok_clicked = False
    for wait in range(20):
        try:
            ok = page.evaluate("""
                () => {
                    const els = document.querySelectorAll('button, span, a, div, [role="button"], .next-btn, .ant-btn');
                    for (const el of els) {
                        const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (txt === 'ok' || txt === 'confirm' || txt === 'confirm creation' || txt === '确定') {
                            el.click();
                            return txt;
                        }
                    }
                    return false;
                }
            """)
            if ok:
                print(f"  [8] Clicked '{ok}' in popup")
                ok_clicked = True
                break
        except:
            pass
        time.sleep(1)

    if not ok_clicked:
        print("  [8] 'OK' button not found — trying Enter key...")
        try:
            page.keyboard.press("Enter")
        except:
            pass

    # Wait for API key to appear
    print("  [8] Waiting for API key to appear...")
    for wait in range(30):
        time.sleep(2)
        found = scan_for_api_key(page)
        if found:
            print(f"  [8] ✅ API Key detected: {found[:30]}...")
            return found
        if wait % 5 == 0:
            print(f"  [8] Waiting... ({wait*2}s)")

    return None


def scan_for_api_key(page):
    """Scan page DOM for sk- API key. Returns key string or None."""
    try:
        found = page.evaluate("""
            () => {
                // Check input/textarea values
                const inputs = document.querySelectorAll('input, textarea');
                for (const el of inputs) {
                    const val = el.value || el.getAttribute('value') || '';
                    if (val.startsWith('sk-') && val.length > 20) return val;
                }
                // Check all elements' text
                const els = document.querySelectorAll('*');
                for (const el of els) {
                    const txt = el.innerText || el.textContent || '';
                    const m = txt.match(/sk-[A-Za-z0-9._\\-]+/);
                    if (m && m[0].length > 20) return m[0];
                }
                // Check clipboard-related elements
                const clips = document.querySelectorAll('[class*="key"], [class*="token"], [class*="secret"], [data-key]');
                for (const el of clips) {
                    const txt = el.innerText || el.textContent || el.getAttribute('data-key') || '';
                    const m = txt.match(/sk-[A-Za-z0-9._\\-]+/);
                    if (m && m[0].length > 20) return m[0];
                }
                return null;
            }
        """)
        return found
    except:
        return None


def load_results():
    """Load existing results."""
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE) as f:
                return json.load(f)
        except:
            pass
    return []


def save_results(results):
    """Save results to file."""
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


def safe_screenshot(page, path):
    """Take screenshot safely — won't crash if page is closed."""
    try:
        page.screenshot(path=path)
    except Exception:
        pass


# ── uinput virtual mouse + slider solver ─────────────────────

def setup_virtual_mouse(width=1920, height=1080):
    """Setup uinput virtual mouse for OS-level drag."""
    global _virtual_mouse
    if not UINPUT_AVAILABLE:
        return None
    try:
        subprocess.run(['modprobe', 'uinput'], stderr=subprocess.PIPE, check=False)
        _virtual_mouse = uinput.Device([
            uinput.BTN_LEFT,
            uinput.ABS_X + (0, width, 0, 0),
            uinput.ABS_Y + (0, height, 0, 0),
        ])
        time.sleep(0.5)
        print("[MOUSE] Virtual mouse ready")
        return _virtual_mouse
    except Exception as e:
        print(f"[MOUSE] Setup failed: {e}")
        return None


def _cubic_bezier(t, p0, p1, p2, p3):
    return (
        (1 - t) ** 3 * p0
        + 3 * (1 - t) ** 2 * t * p1
        + 3 * (1 - t) * t ** 2 * p2
        + t ** 3 * p3
    )


def _bezier_path(start_x, end_x, y, steps):
    dist = abs(end_x - start_x)
    cp_off = random.uniform(-8, 8)
    cp1_x = start_x + dist * random.uniform(0.2, 0.4)
    cp1_y = y + cp_off
    cp2_x = start_x + dist * random.uniform(0.6, 0.8)
    cp2_y = y + cp_off * random.uniform(-0.5, 0.5)
    return [
        (_cubic_bezier(i / steps, start_x, cp1_x, cp2_x, end_x),
         _cubic_bezier(i / steps, y, cp1_y, cp2_y, y))
        for i in range(steps + 1)
    ]


def _speed_profile(steps):
    delays = []
    for i in range(steps):
        t = i / max(steps - 1, 1)
        speed = (1 - math.cos(t * math.pi)) / 2
        delays.append(max(0.005, 1.0 - (speed * 0.75) + random.gauss(0, 0.05)))
    return delays


def humanly_drag(mouse, start_x, end_x, y, duration=1.2):
    """Human-behavior slider drag using xdotool (reliable in Xvfb)."""
    import subprocess
    
    steps = max(35, min(int(50 + random.gauss(0, 8)), 80))
    print(f"  [DRAG] {start_x:.0f}→{end_x:.0f}, {steps} steps, {duration:.2f}s (xdotool)")

    # Move to start
    subprocess.run(['xdotool', 'mousemove', str(int(start_x)), str(int(y))], check=False)
    time.sleep(0.3)

    # Mouse down
    subprocess.run(['xdotool', 'mousedown', '1'], check=False)
    time.sleep(0.2)

    # Drag with bezier path + tremor + speed profile
    path = _bezier_path(start_x, end_x, y, steps)
    delays = _speed_profile(steps)

    for i, (px, py) in enumerate(path):
        tremor = 1.2 if i < 5 else (0.6 if i < steps - 5 else 0.4)
        fx = int(round(px + random.gauss(0, tremor)))
        fy = int(round(py + random.gauss(0, tremor * 0.6)))
        subprocess.run(['xdotool', 'mousemove', str(fx), str(fy)], check=False)

        step_delay = (duration / steps) * delays[min(i, len(delays) - 1)]
        if random.random() < 0.04 and 5 < i < steps - 5:
            step_delay *= random.uniform(2.5, 4.0)
        time.sleep(max(0.004, step_delay))

    # Mouse up
    subprocess.run(['xdotool', 'mouseup', '1'], check=False)
    time.sleep(0.3)
    print("  [DRAG] Done")


def find_slider_handle(page):
    """Search all frames for baxia slider handle."""
    for frame in page.frames:
        for sel in ['#nc_1_n1z', '.nc_iconfont.btn_slide', '.btn_slide',
                     '#nc_1_n1z', 'span.nc_iconfont']:
            try:
                el = frame.query_selector(sel)
                if el:
                    box = el.bounding_box()
                    if box and box['width'] > 0:
                        return el, frame, sel
            except:
                pass
    return None, None, None


def solve_slider(page, mouse):
    """Find and solve baxia slider using uinput virtual mouse."""
    if not mouse:
        print("  [SLIDER] No virtual mouse — can't solve")
        return False

    # Wait for slider to appear
    el, frame, sel = None, None, None
    for wait in range(10):
        el, frame, sel = find_slider_handle(page)
        if el:
            break
        time.sleep(2)

    if not el:
        print("  [SLIDER] No slider found")
        return False

    print(f"  [SLIDER] Found '{sel}' in frame {frame.url[:50]}")

    # Get handle position
    box = el.bounding_box()
    if not box:
        print("  [SLIDER] No bounding box")
        return False

    # Get slider track for drag distance
    track = frame.query_selector("#nc_1__scale_text") or \
            frame.query_selector(".nc_scale") or \
            frame.query_selector("#nc_1_n1t")
    if track:
        track_box = track.bounding_box()
        drag_dist = track_box['width'] - box['width']
    else:
        drag_dist = 300

    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    end_x = start_x + drag_dist

    print(f"  [SLIDER] Handle at ({start_x:.0f},{start_y:.0f}), drag {drag_dist:.0f}px")
    safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "slider_before_drag.png"))

    # Drag!
    humanly_drag(mouse, start_x, end_x, start_y, duration=1.5)

    time.sleep(3)
    safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "slider_after_drag.png"))
    # Check if slider is gone
    el2, _, _ = find_slider_handle(page)
    if not el2:
        print("  [SLIDER] ✅ SOLVED!")
        return True
    else:
        print("  [SLIDER] ❌ Still visible after drag")
        return False


def register_one_attempt(context):
    """Single registration attempt. Returns dict with account info or None if slider."""
    page = context.new_page()
    
    test_email = generate_email()
    test_password = generate_password()
    print(f"  Email: {test_email}")
    
    # ─ Step 1: Navigate ─
    print("  [1] Navigating...")
    page.goto(REGISTER_URL, timeout=120000, wait_until="domcontentloaded")
    
    # Wait for passport iframe — proxy is slower, wait up to 30s
    frame = None
    for wait in range(15):
        try:
            page.wait_for_selector("iframe[src*='passport']", timeout=5000)
        except:
            pass
        time.sleep(2)
        frame = find_register_frame(page)
        if frame:
            print(f"  [1] Frame found after {wait*2}s")
            break
    if not frame:
        print("  [1] ERROR: No passport frame!")
        page.close()
        return None
    
    # ─ Step 2: Individual + Next ─
    print("  [2] Individual account...")
    label = None
    for _ in range(10):
        label = frame.query_selector("label:has-text('Individual')")
        if label and label.is_visible():
            break
        time.sleep(2)
        frame = find_register_frame(page)
        if not frame:
            break
    if not label:
        print("  [2] ERROR: Individual label not found!")
        page.close()
        return None
    label.click()
    time.sleep(2)
    next_link = frame.query_selector("a:has-text('Next')")
    if next_link:
        next_link.click()
    time.sleep(5)
    
    # ─ Step 3: Fill form + Sign Up ─
    print("  [3] Filling form...")
    frame = find_register_frame(page)
    time.sleep(3)
    
    email_field = frame.query_selector("#email")
    pw_field = frame.query_selector("#password")
    confirm_field = frame.query_selector("#confirmPwd")
    
    if not email_field or not pw_field:
        print("  [3] ERROR: Fields not found!")
        page.close()
        return None
    
    email_field.click()
    time.sleep(0.3)
    email_field.fill(test_email)
    time.sleep(0.5)
    
    pw_field.click()
    time.sleep(0.3)
    pw_field.fill(test_password)
    time.sleep(0.5)
    
    if confirm_field:
        confirm_field.click()
        time.sleep(0.3)
        confirm_field.fill(test_password)
    time.sleep(2)
    
    # Verify password was filled
    pw_val = pw_field.evaluate("el => el.value")
    print(f"  [3] Password verify: len={len(pw_val)} match={pw_val == test_password}")
    
    # Click Sign Up
    signup_btn = None
    for b in frame.query_selector_all("button"):
        if "sign up" in b.inner_text().lower():
            signup_btn = b
            break
    if not signup_btn:
        print("  [3] ERROR: No Sign Up button!")
        page.close()
        return None
    signup_btn.click()
    print("  [3] Clicked Sign Up")
    
    # Take screenshot right after click
    safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "step3_after_signup.png"))
    
    # ─ Check: slider, success, or error ─
    for wait in range(15):
        time.sleep(2)
        frame = find_register_frame(page)
        if not frame:
            continue
        
        tabs = frame.query_selector_all("li[role='tab']")
        if len(tabs) > 0:
            print(f"  [3] ✅ Success! Page advanced ({wait*2}s)")
            break
        
        # Check for error messages
        try:
            err_el = frame.query_selector("[class*='error'], [class*='alert'], [class*='msg'], [class*='tip'], [class*='warn']")
            if err_el and err_el.is_visible():
                err_text = err_el.inner_text().strip()
                if err_text and len(err_text) > 2:
                    print(f"  [3] ⚠️ Validation: {err_text[:200]}")
        except:
            pass
        
        slider = frame.query_selector("#risk_slider_container")
        if slider and slider.is_visible() and wait >= 3:
            print(f"  [3] ⚠️ Slider detected — MANUAL SOLVE MODE")
            print(f"  [3] 👉 Solve the slider in the browser window!")
            print(f"  [3] ⏳ Waiting up to 120 seconds for you to solve it...")
            # Wait for user to manually solve the slider
            slider_solved = False
            for manual_wait in range(60):  # 120 seconds (2s * 60)
                time.sleep(2)
                frame = find_register_frame(page)
                if not frame:
                    continue
                # Check if slider is gone (solved) or page advanced
                slider_still = frame.query_selector("#risk_slider_container")
                tabs = frame.query_selector_all("li[role='tab']")
                if len(tabs) > 0:
                    print(f"  [3] ✅ Page advanced after manual solve!")
                    slider_solved = True
                    break
                if slider_still and not slider_still.is_visible():
                    print(f"  [3] ✅ Slider disappeared — checking page...")
                    time.sleep(2)
                    frame = find_register_frame(page)
                    if frame:
                        tabs = frame.query_selector_all("li[role='tab']")
                        if len(tabs) > 0:
                            print(f"  [3] ✅ Page advanced after manual solve!")
                            slider_solved = True
                            break
                if manual_wait % 5 == 0 and manual_wait > 0:
                    print(f"  [3] ⏳ Still waiting... ({manual_wait*2}s elapsed)")
            
            if slider_solved:
                break
            print(f"  [3] ❌ Manual solve timeout — SKIP")
            page.close()
            return "SLIDER"
    else:
        print("  [3] ❌ Timeout — no tabs, no slider")
        page.close()
        return None
    
    # ─ Step 4: Email verification tab ─
    print("  [4] Email verification tab...")
    frame = find_register_frame(page)
    tabs = frame.query_selector_all("li[role='tab']")
    if len(tabs) >= 2:
        tabs[1].click()
        print("  [4] Clicked tab[1] (email mode)")
        time.sleep(3)
    else:
        print(f"  [4] WARNING: Only {len(tabs)} tabs")
    
    # ─ Step 5: Singapore + Send ─
    print("  [5] Singapore + Send...")
    frame = find_register_frame(page)
    selects = frame.query_selector_all("select")
    for sel in selects:
        for opt in sel.query_selector_all("option"):
            if "singapore" in opt.inner_text().lower():
                sel.select_option(value=opt.get_attribute("value"))
                print("  [5] Selected Singapore")
                break
    
    # Click Send
    for b in frame.query_selector_all("button, [role='button']"):
        txt = b.inner_text()[:50].lower()
        if "send" in txt and b.is_visible():
            b.click()
            print("  [5] Clicked Send")
            break
    time.sleep(3)
    
    # ─ Step 6: OTP ─
    print("  [6] Reading OTP...")
    otp = read_otp_from_api(test_email, timeout=120)
    if not otp:
        print("  [6] ERROR: No OTP!")
        page.close()
        return None
    
    frame = find_register_frame(page)
    # OTP is a single input field with id=emailCaptcha
    otp_input = frame.query_selector("#emailCaptcha") or \
                frame.query_selector("input[name='emailCaptcha']") or \
                frame.query_selector("input[placeholder*='code']") or \
                frame.query_selector("input[placeholder*='verification']") or \
                frame.query_selector("input[name*='code']") or \
                frame.query_selector("input[name*='captcha']")
    
    if not otp_input:
        # Fallback: find the visible input that's NOT email/country/checkbox
        all_inputs = frame.query_selector_all("input")
        for inp in all_inputs:
            try:
                if not inp.is_visible():
                    continue
                inp_id = (inp.get_attribute("id") or "").lower()
                inp_name = (inp.get_attribute("name") or "").lower()
                if "email" == inp_id or "email" == inp_name or "country" in inp_id or "country" in inp_name:
                    continue  # Skip email and country fields
                if inp.get_attribute("type") == "checkbox":
                    continue
                otp_input = inp
                print(f"  [6] Found OTP input (fallback): id={inp.get_attribute('id')} name={inp.get_attribute('name')}")
                break
            except:
                pass
    
    if otp_input:
        otp_input.click()
        time.sleep(0.3)
        for ch in otp:
            page.keyboard.type(ch, delay=30)
        time.sleep(0.5)
        # Verify
        otp_val = otp_input.evaluate("el => el.value")
        print(f"  [6] Typed OTP: {otp} (verify: len={len(otp_val)})")
    else:
        print(f"  [6] ❌ No OTP input found!")
        # Debug: list all inputs
        for inp in frame.query_selector_all("input"):
            try:
                print(f"  [6]   INPUT: type={inp.get_attribute('type')} id={inp.get_attribute('id')} name={inp.get_attribute('name')} placeholder={inp.get_attribute('placeholder')} visible={inp.is_visible()}")
            except:
                pass
    
    # Check agreement
    checkbox = frame.query_selector("input[type='checkbox']")
    if checkbox and not checkbox.is_checked():
        checkbox.click()
    
    # Click Sign Up (Step 2)
    for b in frame.query_selector_all("button, [role='button']"):
        txt = b.inner_text().lower()
        if "sign up" in txt or "confirm" in txt or "register" in txt:
            b.click()
            print(f"  [6] Clicked final Sign Up")
            break
    time.sleep(8)
    
    # Check if slider appeared after Sign Up click
    try:
        body_check = page.inner_text("body")[:2000].lower()
        if "slider" in body_check or "verify" in body_check or "drag" in body_check:
            print("  [6] ⚠️ Slider detected after Sign Up — MANUAL SOLVE MODE")
            print("  [6] 👉 Solve the slider in the browser window!")
            for sw in range(120):
                time.sleep(1)
                if sw % 10 == 0 and sw > 0:
                    print(f"  [6] ⏳ Waiting for slider solve... ({sw}s)")
            print("  [6] Slider wait done")
            time.sleep(5)
    except:
        pass
    
    # Verify registration completed — check if page changed
    post_url = page.url
    print(f"  [6] Post-register URL: {post_url}")
    safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "step6_registered.png"))
    
    # Wait longer for redirect
    if "register" in post_url:
        print("  [6] Still on register page — waiting 10s for redirect...")
        time.sleep(10)
        post_url = page.url
        print(f"  [6] URL after wait: {post_url}")
    
    # Check if still on register page (registration failed)
    if "register" in post_url:
        try:
            body = page.inner_text("body")[:1000]
        except:
            body = ""
        if "verification code" in body.lower() or "sign up" in body.lower():
            print("  [6] ⚠️ Still on register page — checking for errors...")
            frame = find_register_frame(page)
            if frame:
                err = frame.query_selector("[class*='error'], [class*='alert'], [class*='msg']")
                if err:
                    print(f"  [6] Error: {err.inner_text()[:200]}")
            print("  [6] ❌ Registration may have failed")
            page.close()
            return None
    
    # ─ Step 7: Go directly to Model Studio API Key page ─
    # Session from register usually lost → need to auto-login
    print("  [7] Going to Model Studio API Key page...")
    try:
        page.goto("https://modelstudio.console.alibabacloud.com/ap-southeast-1?tab=dashboard#/api-key", timeout=30000, wait_until="commit")
    except:
        pass
    time.sleep(8)
    print(f"  [7] URL: {page.url[:100]}")

    # Check if redirected to login
    if "login" in page.url.lower() or "signin" in page.url.lower() or "passport" in page.url.lower():
        print("  [7] Session lost — auto-login...")

        # Auto-login
        login_ok = auto_login(page, test_email, test_password, timeout=60)

        if not login_ok:
            # Retry: navigate to login page directly
            print("  [7] Retry: navigating to login page directly...")
            try:
                page.goto("https://account.alibabacloud.com/login/login.htm", timeout=30000, wait_until="domcontentloaded")
            except:
                pass
            time.sleep(5)
            login_ok = auto_login(page, test_email, test_password, timeout=60)

        if not login_ok:
            print("  [7] ❌ Auto-login failed! Giving up.")
            safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "step7_login_failed.png"))
            page.close()
            return {
                "email": test_email,
                "password": test_password,
                "api_key": "LOGIN_FAILED",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }

        # Login success — navigate to Model Studio API Key page
        print("  [7] Navigating to Model Studio API Key page...")
        try:
            page.goto("https://modelstudio.console.alibabacloud.com/ap-southeast-1?tab=dashboard#/api-key", timeout=30000, wait_until="commit")
        except:
            pass
        time.sleep(10)

    safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "step7_loaded.png"))
    print(f"  [7] Final URL: {page.url[:100]}")

    # ─ Step 7c: Wait for SPA to fully render ─
    # Model Studio is a SPA — needs time to load JS + render
    print("  [7c] Waiting for SPA to render...")
    spa_ready = False
    for wait in range(30):  # 60s max
        time.sleep(2)
        try:
            # Check if page has real content (not just loading spinner)
            has_content = page.evaluate("""
                () => {
                    const body = document.body;
                    if (!body) return false;
                    const text = body.innerText || '';
                    // Loading spinner pages have very little text
                    if (text.trim().length < 50) return false;
                    // Check for common dashboard elements
                    if (text.includes('API') || text.includes('Key') || text.includes('Create') ||
                        text.includes('Dashboard') || text.includes('Model')) return true;
                    return false;
                }
            """)
            if has_content:
                print(f"  [7c] SPA rendered ({wait*2}s)")
                spa_ready = True
                break
        except:
            pass
        if wait % 5 == 0:
            print(f"  [7c] Still loading... ({wait*2}s)")

    if not spa_ready:
        print("  [7c] ⚠️ SPA not fully rendered after 60s — trying anyway...")

    # CRITICAL: Re-check URL after SPA wait — session may have expired during load
    if "login" in page.url.lower() or "passport" in page.url.lower():
        print("  [7c] ⚠️ Session expired during SPA load — auto-login...")
        login_ok = auto_login(page, test_email, test_password, timeout=60)
        if not login_ok:
            print("  [7c] Retry login on direct page...")
            try:
                page.goto("https://account.alibabacloud.com/login/login.htm", timeout=30000, wait_until="domcontentloaded")
            except:
                pass
            time.sleep(5)
            login_ok = auto_login(page, test_email, test_password, timeout=60)
        
        if login_ok:
            print("  [7c] ✅ Login OK — re-navigate to Model Studio...")
            try:
                page.goto("https://modelstudio.console.alibabacloud.com/ap-southeast-1?tab=dashboard#/api-key", timeout=30000, wait_until="commit")
            except:
                pass
            time.sleep(8)
            # Wait for SPA again (shorter)
            for wait in range(20):
                time.sleep(2)
                try:
                    r = page.evaluate("() => { const t = document.body?.innerText || ''; return t.trim().length > 50; }")
                    if r:
                        print(f"  [7c] SPA re-rendered ({wait*2}s)")
                        break
                except:
                    pass
        else:
            print("  [7c] ❌ Auto-login failed!")
            safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "step7c_login_fail.png"))
            page.close()
            return {
                "email": test_email,
                "password": test_password,
                "api_key": "LOGIN_FAILED",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }

    safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "step7c_rendered.png"))

    # ─ Step 8: Auto-click "Create API Key" + "OK" ─
    api_key = auto_create_api_key(page, timeout=30)

    safe_screenshot(page, os.path.join(os.path.dirname(__file__), "screenshots", "step9_final.png"))

    if api_key:
        print(f"  [9] ✅ API KEY: {api_key[:20]}...")
    else:
        print("  [9] ❌ No API key found")

    page.close()

    return {
        "email": test_email,
        "password": test_password,
        "api_key": api_key or "NOT_FOUND",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }


def main():
    results = load_results()
    print(f"=== Alibaba Cloud Farm ===")
    print(f"Existing accounts: {len(results)}")
    print(f"No proxy — direct VPS IP")
    print(f"Slider solver: {'uinput' if UINPUT_AVAILABLE else 'DISABLED'}")
    print(f"Max attempts: {MAX_ATTEMPTS}")
    print()

    # Setup virtual mouse for slider solving
    mouse = setup_virtual_mouse()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel='chrome', args=[
            '--disable-blink-features=AutomationControlled',
            '--no-first-run',
            '--no-default-browser-check',
        ])
        
        success_count = 0
        slider_count = 0
        fail_count = 0
        
        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"\n{'='*50}")
            print(f"ATTEMPT {attempt}/{MAX_ATTEMPTS}")
            print(f"{'='*50}")
            
            # New context per attempt — prevents TargetClosedError if previous page crashed
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800},
                locale='en-US',
            )
            if STEALTH_AVAILABLE:
                stealth = Stealth()
                stealth.apply_stealth_sync(context)
            
            try:
                result = register_one_attempt(context)
            except Exception as e:
                print(f"  → EXCEPTION: {e}")
                result = None
            
            if result == "SLIDER":
                slider_count += 1
                print(f"  → Slider detected, skipping (total: {slider_count})")
            elif result and isinstance(result, dict):
                results.append(result)
                save_results(results)
                if result.get("api_key", "").startswith("sk-"):
                    success_count += 1
                    print(f"  → ✅ SUCCESS! Total accounts: {success_count}")
                    print(f"  → Email: {result['email']}")
                    print(f"  → API Key: {result['api_key'][:30]}...")
                else:
                    fail_count += 1
                    print(f"  → ⚠️ Account registered but no API key: {result.get('api_key', 'unknown')}")
            else:
                fail_count += 1
                print(f"  → ❌ Failed (total fails: {fail_count})")
            
            # Close context to free resources
            try:
                context.close()
            except:
                pass
        
        browser.close()
    
    print(f"\n{'='*50}")
    print(f"DONE: {success_count} success, {slider_count} slider, {fail_count} fail")
    print(f"Total accounts in results.json: {len(results)}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
