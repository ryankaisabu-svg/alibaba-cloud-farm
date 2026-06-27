#!/usr/bin/env python3
"""
Qwen Cloud API Key Extraction Module.
======================================
After registration, extract API key from Qwen Cloud dashboard.

Qwen Cloud dashboard: https://home.qwencloud.com/
API keys page: https://home.qwencloud.com/api-key (or similar)

Flow:
  1. Navigate to API keys page (session from registration carries over)
  2. Click "Create API Key" (or "Generate")
  3. Extract the sk- key from the modal/page
  4. Save to results

Separated from alibaba_register.py for clean module boundaries.
"""

import sys
import os
import time
import json
import re

from farm_headless import log

# ─ Config ──────────────────────────────────────────

QWEN_HOME_URL = "https://home.qwencloud.com/"
QWEN_APIKEY_URL = "https://home.qwencloud.com/api-keys"
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "qwen_results.json")
CSV_FILE = os.path.join(os.path.dirname(__file__), "qwen_accounts.csv")


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
    log("SAVE", f"Saved to {RESULTS_FILE}")


def update_result_with_apikey(email, api_key):
    """Update an existing result record with API key."""
    results = load_results()
    for r in results:
        if r.get("email") == email:
            r["api_key"] = api_key
            r["status"] = "complete"
            r["api_key_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            break
    save_results(results)
    log("SAVE", f"Updated {email} with API key")

    # Also update CSV
    csv_file = CSV_FILE
    if os.path.exists(csv_file):
        lines = []
        with open(csv_file) as f:
            lines = f.readlines()
        with open(csv_file, "w") as f:
            for line in lines:
                if email in line:
                    # Update the api_key column (index 2)
                    parts = line.strip().split('","')
                    if len(parts) >= 3:
                        parts[2] = api_key
                        parts[3] = "complete"
                        f.write('","'.join(parts) + '\n')
                    else:
                        f.write(line)
                else:
                    f.write(line)


def dismiss_modals(page):
    """Dismiss any modal/overlay that blocks clicks."""
    for _ in range(3):
        page.evaluate("""
            () => {
                const modals = document.querySelectorAll(
                    '[class*="modal"], [role="dialog"], [class*="dialog"], [class*="overlay"]'
                );
                for (const m of modals) {
                    const rect = m.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const btns = m.querySelectorAll(
                            'button, [role="button"], .ant-modal-close, [class*="close"]'
                        );
                        for (const b of btns) {
                            const txt = (b.innerText || '').toLowerCase();
                            if (txt.includes('ok') || txt.includes('close') ||
                                txt.includes('got it') || txt.includes('confirm') ||
                                txt.includes('got') || b.className.includes('close')) {
                                b.click();
                                return true;
                            }
                        }
                    }
                }
                return false;
            }
        """)
        time.sleep(1)


def extract_api_key(page, timeout=60):
    """Extract API key from page after creating one.

    Looks for sk- prefixed strings in inputs, textareas, and element text.
    """
    log("KEY", "Searching for API key...")

    for wait in range(timeout // 2):
        # Method 1: input field with sk- value
        try:
            found = page.evaluate("""
                () => {
                    const inputs = document.querySelectorAll('input, textarea');
                    for (const inp of inputs) {
                        const val = inp.value || inp.getAttribute('value') || '';
                        if (val.startsWith('sk-') && val.length > 20) {
                            return val;
                        }
                    }
                    // Look for sk- in any element text
                    const els = document.querySelectorAll(
                        'span, div, p, code, td, [class*="modal"], [role="dialog"], [class*="key"]'
                    );
                    for (const el of els) {
                        const txt = el.innerText || el.textContent || '';
                        const m = txt.match(/sk-[A-Za-z0-9._\\-]+/);
                        if (m && m[0].length > 20) {
                            return m[0];
                        }
                    }
                    return null;
                }
            """)
        except Exception as e:
            log("KEY", f"Page error during search: {e}")
            return None

        if found:
            log("KEY", f"Found API key: {found[:30]}...")
            return found

        # Method 2: Fill description + click Generate/Create button (once at wait=5)
        if wait == 5:
            try:
                import random, string
                rand_desc = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                # Fill description field using Playwright locator (triggers React onChange)
                desc_input = None
                try:
                    # Try common selectors for the description input in modal
                    for sel in [
                        'input[placeholder*="e.g."]',
                        'input[placeholder*="Production"]',
                        'input[placeholder*="description"]',
                        'input[placeholder*="Description"]',
                        '[role="dialog"] input[type="text"]',
                        '[class*="modal"] input[type="text"]',
                    ]:
                        loc = page.locator(sel).first
                        if loc.is_visible(timeout=2000):
                            desc_input = loc
                            break
                except:
                    pass
                if desc_input:
                    desc_input.fill(rand_desc)
                    log("KEY", f"Filled description: {rand_desc}")
                    time.sleep(0.5)
                    # Press Enter to trigger React onChange and enable Generate button
                    page.keyboard.press("Enter")
                    log("KEY", "Pressed Enter after description")
                    time.sleep(1)
                else:
                    log("KEY", "No description input found in modal")

                # Click Generate Key button inside modal/dialog
                gen_clicked = page.evaluate("""
                    () => {
                        const containers = document.querySelectorAll(
                            '[class*="modal"], [role="dialog"], [class*="dialog"], [class*="drawer"], [class*="popup"]'
                        );
                        for (const container of containers) {
                            const btns = container.querySelectorAll('button, [role="button"]');
                            for (const b of btns) {
                                const txt = (b.innerText || '').trim().toLowerCase();
                                const rect = b.getBoundingClientRect();
                                if (rect.width > 0 && rect.height > 0) {
                                    if (txt.includes('generate') || txt === 'ok' || txt === 'confirm' || txt.includes('create')) {
                                        b.click();
                                        return txt;
                                    }
                                }
                            }
                        }
                        return null;
                    }
                """)
                if gen_clicked:
                    log("KEY", f"Clicked: '{gen_clicked}'")
                    time.sleep(3)
            except Exception as e:
                log("KEY", f"Generate button error: {e}")

        if wait % 5 == 0:
            log("KEY", f"Still waiting... ({wait * 2}s)")

        time.sleep(2)

    log("KEY", "No API key found after timeout")
    return None


def login_qwen(page, gmail_user, app_pass, alias_email):
    """Login to Qwen Cloud via OTP (needed after registration — session doesn't persist cross-domain).

    Flow: qwencloud.com → Log In → email → Send Code → OTP from Gmail → Next → dashboard
    """
    from alibaba_register import read_otp_from_gmail

    log("KEY", f"Logging in to Qwen Cloud as {alias_email}...")

    # Navigate to Qwen Cloud home
    page.goto(QWEN_HOME_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(3)

    # Click "Get Started" or "Log In"
    for sel in ['a:has-text("Get Started")', 'a:has-text("Log In")', 'button:has-text("Get Started")']:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("KEY", f"Clicked: {sel}")
                break
        except:
            continue

    time.sleep(3)

    # Fill email
    for sel in ['input[placeholder="Email"]', 'input[type="email"]']:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                el.fill(alias_email)
                log("KEY", f"Email filled: {alias_email}")
                break
        except:
            continue

    time.sleep(1)

    # Click "Send Code" to trigger OTP
    for sel in ['a:has-text("Send Code")', 'button:has-text("Send Code")', 'text=Send Code']:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("KEY", "Clicked Send Code")
                break
        except:
            continue

    time.sleep(2)

    # Read OTP from Gmail
    otp = read_otp_from_gmail(gmail_user, app_pass, alias_email, timeout=120)
    if not otp:
        log("KEY", "ERROR: No OTP for login!")
        return False

    log("KEY", f"Login OTP received: {otp}")

    # Enter OTP (6 separate fields)
    otp_inputs = page.query_selector_all('input[maxlength="1"], input[type="text"][maxlength="1"]')
    if len(otp_inputs) >= 6:
        for i, digit in enumerate(otp):
            if i < len(otp_inputs):
                otp_inputs[i].click()
                time.sleep(0.1)
                page.keyboard.type(digit, delay=50)
                time.sleep(0.1)
        log("KEY", f"OTP entered in {len(otp_inputs)} fields")
    else:
        # Single field fallback
        all_inputs = page.query_selector_all('input:not([placeholder="Email"])')
        if all_inputs:
            all_inputs[0].click()
            page.keyboard.type(otp, delay=50)
            log("KEY", "OTP entered in single field")

    time.sleep(1)

    # Click Next
    for sel in ['button:has-text("Next")', 'button[type="submit"]']:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible() and el.is_enabled():
                el.click()
                log("KEY", f"Clicked: {sel}")
                break
        except:
            continue

    time.sleep(3)


    # Check if there's an error message (wrong OTP, etc.)
    try:
        body_after = page.inner_text("body")[:2000].lower()
        if any(x in body_after for x in ["incorrect", "invalid", "wrong", "expired", "error"]):
            log("KEY", f"WARNING: Possible OTP error on page: {body_after[:200]}")
    except:
        pass

    # ─ Check for country selection page (onboarding step) ─
    log("KEY", "Checking for country selection / onboarding...")
    for _ in range(3):
        try:
            body_text = page.inner_text("body")[:3000].lower()
        except:
            body_text = ""

        if any(x in body_text for x in ["country", "region", "select your", "choose your"]):
            log("KEY", "Country selection page detected!")


            # Open country dropdown
            for sel in [
                '[role="combobox"]',
                '[class*="select"]',
                '[role="listbox"]',
                'input[placeholder*="select" i]',
                'input[placeholder*="country" i]',
                '[class*="dropdown"]',
            ]:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        log("KEY", f"Opened country dropdown: {sel}")
                        break
                except:
                    continue

            time.sleep(2)

            # Type Singapore in the combobox search
            log("KEY", "Typing 'Singapore' in country dropdown...")
            search_filled = False
            for sel in [
                'input[role="combobox"]',
                'input[placeholder*="search" i]',
                'input[placeholder*="select" i]',
                'input[type="text"]:visible',
            ]:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        time.sleep(0.5)
                        el.fill("")
                        time.sleep(0.2)
                        el.fill("Singapore")
                        search_filled = True
                        log("KEY", f"Typed Singapore in: {sel}")
                        break
                except:
                    continue

            if not search_filled:
                page.keyboard.type("Singapore")
                log("KEY", "Typed Singapore via keyboard")
                time.sleep(1)

            # Select Singapore: press Enter to commit the filtered first match
            time.sleep(1)
            page.keyboard.press("Enter")
            log("KEY", "Pressed Enter to select Singapore")
            time.sleep(3)

            # Check if dropdown closed and Singapore is selected
            # If still open, try clicking the Singapore option directly
            try:
                still_open = page.query_selector('[role="listbox"]:visible, [role="option"]:visible')
                if still_open:
                    log("KEY", "Dropdown still open after Enter — clicking Singapore option directly")
                    try:
                        opt = page.query_selector('[role="option"]:has-text("Singapore")')
                        if opt:
                            opt.click()
                            log("KEY", "Clicked Singapore option via Playwright")
                            time.sleep(2)
                    except:
                        pass
            except:
                pass

            # Scroll down to find Continue button + checkbox
            page.evaluate("window.scrollBy(0, 300)")
            time.sleep(1)

            # Check the agreement checkbox
            checkbox_clicked = page.evaluate("""
                () => {
                    const checks = document.querySelectorAll('input[type="checkbox"], [role="checkbox"], [class*="checkbox"]');
                    for (const c of checks) {
                        if (!c.checked) {
                            c.click();
                            return true;
                        }
                    }
                    const labels = document.querySelectorAll('label, div, span');
                    for (const l of labels) {
                        const txt = (l.innerText || '').toLowerCase();
                        if (txt.includes('agree')) {
                            l.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            if checkbox_clicked:
                log("KEY", "Agreement checkbox checked")
            else:
                log("KEY", "WARNING: Could not find/check agreement checkbox")

            time.sleep(1)


            # Click Continue — use JS evaluate as fallback
            continue_clicked = page.evaluate("""
                () => {
                    const buttons = document.querySelectorAll('button');
                    for (const b of buttons) {
                        const txt = (b.innerText || '').trim().toLowerCase();
                        if (txt === 'continue' || txt === 'confirm' || txt === 'next' || txt === 'ok') {
                            b.click();
                            return txt;
                        }
                    }
                    const rbuttons = document.querySelectorAll('[role="button"]');
                    for (const b of rbuttons) {
                        const txt = (b.innerText || '').trim().toLowerCase();
                        if (txt === 'continue' || txt === 'confirm' || txt === 'next') {
                            b.click();
                            return txt;
                        }
                    }
                    const submit = document.querySelector('button[type="submit"]');
                    if (submit) { submit.click(); return 'submit'; }
                    return null;
                }
            """)
            if continue_clicked:
                log("KEY", f"Clicked: {continue_clicked} after country selection (via JS)")
            else:
                log("KEY", "WARNING: Could not find Continue button — trying Playwright selector")
                for sel in ['button:has-text("Continue")', 'button:has-text("Confirm")', 'button[type="submit"]']:
                    try:
                        el = page.query_selector(sel)
                        if el:
                            el.click(force=True)
                            log("KEY", f"Force-clicked: {sel}")
                            break
                    except:
                        continue

            time.sleep(3)

        else:
            log("KEY", "No country selection page — continuing")
            break
        time.sleep(2)

    # ─ Wait for SO redirect to complete → land on home.qwencloud.com ─
    log("KEY", "Waiting for SO redirect to home.qwencloud.com...")
    redirected = False
    for i in range(30):
        url = page.url
        if "home.qwencloud.com" in url and "account.alibabacloud.com" not in url:
            log("KEY", f"Redirected to: {url}")
            redirected = True
            break
        if i % 5 == 0:
            log("KEY", f"Still waiting... URL: {url[:100]}")
        time.sleep(2)

    if not redirected:
        # Force navigate to home — this may trigger SO redirect
        log("KEY", "No auto-redirect — navigating to home.qwencloud.com...")
        page.goto(QWEN_HOME_URL, timeout=60000, wait_until="domcontentloaded")
        time.sleep(3)
        url = page.url
        if "home.qwencloud.com" in url and "account.alibabacloud.com" not in url:
            log("KEY", f"Now on: {url}")
            redirected = True


    if redirected:
        log("KEY", "Login SUCCESS! On home.qwencloud.com")
        return True

    # Last resort: check body for dashboard indicators
    body = ""
    try:
        body = page.inner_text("body")[:2000].lower()
    except:
        pass

    if any(x in body for x in ["dashboard", "welcome", "api key", "console", "model"]):
        log("KEY", "Login SUCCESS! On dashboard (body match).")
        return True

    log("KEY", f"Login unclear. URL: {page.url}")
    return True  # Proceed anyway


def create_api_key(page, gmail_user=None, app_pass=None, alias_email=None):
    """Navigate to API keys page and create a new API key.

    Args:
        page: Playwright page (session from registration)
        gmail_user: Gmail address (for re-login if session lost)
        app_pass: Gmail app password
        alias_email: Email alias used for registration

    Returns:
        str: API key (sk-...) or None on failure
    """
    log("KEY", "Starting API key extraction...")

    # ─ Step 1: Try navigating to API keys page ─
    log("KEY", f"Navigating to {QWEN_APIKEY_URL}...")
    page.goto(QWEN_APIKEY_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(3)


    # Check if redirected to login (session lost)
    body = ""
    try:
        body = page.inner_text("body")[:2000].lower()
    except:
        pass

    if any(x in body for x in ["log in", "sign in", "enter your email", "send code"]):
        log("KEY", "Session lost — need to login first")

        if gmail_user and app_pass and alias_email:
            # Login via OTP
            logged_in = login_qwen(page, gmail_user, app_pass, alias_email)
            if not logged_in:
                log("KEY", "Re-login failed")
                return None

            # Now try API key page again — login_qwen ensures we're on home.qwencloud.com
            log("KEY", f"Navigating to {QWEN_APIKEY_URL} after login...")
            page.goto(QWEN_APIKEY_URL, timeout=60000, wait_until="domcontentloaded")
            time.sleep(4)  # Wait for SPA to load

            # Check if still redirecting (SO → home → api-key)
            for _ in range(5):
                url = page.url
                if "account.alibabacloud.com" not in url:
                    break
                time.sleep(2)


            # Check again
            body = ""
            try:
                body = page.inner_text("body")[:2000].lower()
            except:
                pass

            if any(x in body for x in ["log in", "sign in", "send code"]):
                log("KEY", "Still on login page after re-login — giving up")
                return None
        else:
            log("KEY", "No credentials provided for re-login")
            return None

    # ─ Step 2: Dismiss any modals ─
    dismiss_modals(page)
    time.sleep(2)

    # ─ Step 2b: Click "API Keys" in sidebar to navigate to API keys page ─
    log("KEY", "Clicking 'API Keys' in sidebar...")
    api_keys_clicked = page.evaluate("""
        () => {
            const btns = document.querySelectorAll('button, [role="button"], a, span, div');
            for (const b of btns) {
                const txt = (b.innerText || '').trim().toLowerCase();
                const rect = b.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && txt === 'api keys') {
                    b.click();
                    return txt;
                }
            }
            return null;
        }
    """)
    if api_keys_clicked:
        log("KEY", f"Clicked: '{api_keys_clicked}' in sidebar")
        time.sleep(3)
    else:
        log("KEY", "Could not find 'API Keys' in sidebar")

    # ─ Step 3: Find and click "Create API Key" button ─
    log("KEY", "Looking for Create API Key button...")

    create_clicked = False
    for wait in range(10):
        clicked = page.evaluate("""
            () => {
                const btns = document.querySelectorAll('button, [role="button"], a');
                for (const b of btns) {
                    const txt = (b.innerText || '').trim().toLowerCase();
                    const rect = b.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        if (txt.includes('create') && (txt.includes('api') || txt.includes('key'))) {
                            b.click();
                            return txt;
                        }
                        if (txt === 'create' || txt === 'generate' || txt === 'new api key') {
                            b.click();
                            return txt;
                        }
                    }
                }
                return null;
            }
        """)
        if clicked:
            log("KEY", f"Clicked: '{clicked}'")
            create_clicked = True
            break
        time.sleep(2)

    if not create_clicked:
        # Maybe already on API key page with existing keys, or different layout
        log("KEY", "No Create button — checking if keys already exist...")
        existing_key = extract_api_key(page, timeout=10)
        if existing_key:
            log("KEY", "Found existing API key on page")
            return existing_key

        log("KEY", "No Create button found. Visible buttons:")
        for b in page.query_selector_all("button, [role='button'], a"):
            try:
                txt = b.inner_text()[:80].strip()
                if b.is_visible() and txt:
                    log("KEY", f"  BTN: '{txt}'")
            except:
                pass
        return None

    # ─ Step 4: Handle Create API Key form/modal ─
    log("KEY", "Waiting for Create API Key form...")
    time.sleep(3)


    # Click OK/Confirm in the form (may have workspace/description fields)
    ok_clicked = False
    for wait in range(10):
        clicked = page.evaluate("""
            () => {
                const modals = document.querySelectorAll(
                    '[class*="modal"], [role="dialog"], [class*="dialog"]'
                );
                for (const m of modals) {
                    const rect = m.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) continue;
                    const btns = m.querySelectorAll('button, [role="button"]');
                    for (const b of btns) {
                        const txt = (b.innerText || '').trim().toLowerCase();
                        const brect = b.getBoundingClientRect();
                        if (brect.width > 0 && brect.height > 0 &&
                            (txt === 'ok' || txt === 'confirm' || txt === 'create' ||
                             txt === 'submit' || txt === 'generate')) {
                            b.click();
                            return txt;
                        }
                    }
                }
                // Fallback: any visible OK/Confirm button
                const allBtns = document.querySelectorAll('button, [role="button"]');
                for (const b of allBtns) {
                    const txt = (b.innerText || '').trim().toLowerCase();
                    const brect = b.getBoundingClientRect();
                    if (brect.width > 0 && brect.height > 0 &&
                        (txt === 'ok' || txt === 'confirm' || txt === 'create')) {
                        b.click();
                        return txt;
                    }
                }
                return null;
            }
        """)
        if clicked:
            log("KEY", f"Clicked: '{clicked}' in form")
            ok_clicked = True
            break
        time.sleep(2)

    if not ok_clicked:
        log("KEY", "No OK/Confirm button found in form")

    time.sleep(3)


    # ─ Step 5: Extract API key ─
    api_key = extract_api_key(page, timeout=60)

    if api_key:
        log("KEY", f"SUCCESS! API key: {api_key[:20]}...")

        # Close the modal
        page.evaluate("""
            () => {
                const btns = document.querySelectorAll('button, [role="button"]');
                for (const b of btns) {
                    const txt = (b.innerText || '').toLowerCase();
                    const rect = b.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        if (txt.includes('ok') || txt.includes('close') ||
                            txt.includes('done') || txt.includes('confirm')) {
                            b.click();
                            return true;
                        }
                    }
                }
                return false;
            }
        """)
        log("KEY", "Closed modal")
    else:
        log("KEY", "Failed to extract API key")

    return api_key
