"""
core/helpers.py — Utility helpers for Alibaba Cloud Farm.

Extracted from farm_headless.py:
  - L142-188: human_delay, human_pause_*, human_type_delay, log, screenshot
  - L1530-1533: generate_password
  - L787-841: find_passport_frame, find_login_frame
  - L2146-2167: scan_for_api_key
  - L2573-2589: load_results, save_results
"""

import os
import sys
import time
import json
import random
import string


# ─ Human-like delay helpers ──────────────────────────
# Replaces fixed time.sleep() with randomized delays to mimic human behaviour.
# Bot detectors flag perfectly-timed intervals; jitter breaks the pattern.

def human_delay(min_s=0.8, max_s=2.5):
    """Random pause that mimics human think-time between actions."""
    time.sleep(random.uniform(min_s, max_s))


def human_pause_short():
    """Micro-pause between rapid field interactions (click->fill->tab)."""
    time.sleep(random.uniform(0.2, 0.6))


def human_pause_medium():
    """Medium pause after submitting a form or waiting for page transition."""
    time.sleep(random.uniform(2.0, 4.5))


def human_pause_long():
    """Longer pause after page load or navigation."""
    time.sleep(random.uniform(4.0, 7.0))


def human_type_delay():
    """Random per-keystroke delay for typing (ms)."""
    return random.randint(45, 120)


def human_scroll_pause():
    """Pause after scrolling element into view."""
    time.sleep(random.uniform(0.5, 1.5))


# ─ Logging ──────────────────────────────────────────

def log(step, msg):
    """Timestamped console log with Unicode fallback for cp1252 terminals."""
    ts = time.strftime("%H:%M:%S")
    try:
        print(f"  [{ts}] [{step}] {msg}", flush=True)
    except UnicodeEncodeError:
        safe = msg.encode("ascii", "replace").decode("ascii")
        print(f"  [{ts}] [{step}] {safe}", flush=True)


# ─ Screenshot ───────────────────────────────────────

def screenshot(page, name):
    """Save screenshot to SCREENSHOT_DIR."""
    from core.config import SCREENSHOT_DIR
    path = os.path.join(SCREENSHOT_DIR, name)
    try:
        page.screenshot(path=path)
        log("SHOT", f"Saved {name}")
    except:
        pass


# ─ Password generation ──────────────────────────────

def generate_password():
    """Alibaba password: Aa1 + 15 random + _ = 19 chars."""
    chars = string.ascii_letters + string.digits
    return "Aa1" + ''.join(random.choices(chars, k=15)) + "_"


# ─ Frame helpers ────────────────────────────────────

def find_passport_frame(page):
    """Find passport iframe on Alibaba Cloud pages."""
    for frame in page.frames[1:]:
        if "passport.alibabacloud.com" in (frame.url or ""):
            return frame
    return None


def find_login_frame(page):
    """Find login frame -- passport iframe, any iframe with login fields, or main page.

    Alibaba Cloud login page (account.alibabacloud.com/login) has the form directly
    in the main page (NOT in an iframe). The form uses:
    - Account field: input with placeholder 'Enter your email'
    - Password field: input[type='password'] with placeholder 'Enter your password'
    - Submit: button with text 'Sign In'

    Older passport iframe forms use: #fm-login-id, #fm-login-password, #fm-login-submit
    """
    # Check 1: passport iframe
    frame = find_passport_frame(page)
    if frame:
        return frame

    # Check 2: any iframe with login fields
    for frame in page.frames[1:]:
        try:
            if frame.query_selector("#fm-login-id") or \
               frame.query_selector("input[name='loginId']") or \
               frame.query_selector("input[type='password']"):
                return frame
        except:
            pass

    # Check 3: main page -- new Alibaba login form (direct, no iframe)
    try:
        if page.query_selector("input[placeholder*='Enter your email']") or \
           page.query_selector("input[placeholder*='email']") and \
           page.query_selector("input[type='password']"):
            return page
    except:
        pass

    # Check 4: main page -- old style selectors
    try:
        if page.query_selector("#fm-login-id") or \
           page.query_selector("input[name='loginId']") or \
           page.query_selector("input[placeholder*='email']") or \
           page.query_selector("input[type='password']"):
            return page
    except:
        pass

    return None


# ─ API key scanner ──────────────────────────────────

def scan_for_api_key(page):
    """Scan page DOM for sk- API key."""
    try:
        found = page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input, textarea');
                for (const el of inputs) {
                    const val = el.value || el.getAttribute('value') || '';
                    if (val.startsWith('sk-') && val.length > 20) return val;
                }
                const els = document.querySelectorAll('*');
                for (const el of els) {
                    const txt = el.innerText || el.textContent || '';
                    const m = txt.match(/sk-[A-Za-z0-9._\\-]+/);
                    if (m && m[0].length > 20) return m[0];
                }
                return null;
            }
        """)
        return found
    except:
        return None


# ─ Results persistence ──────────────────────────────

def load_results(results_file=None):
    """Load results from JSON file. Uses provider-specific file if specified."""
    from core.config import RESULTS_FILE
    file_to_load = results_file or RESULTS_FILE
    if os.path.exists(file_to_load):
        try:
            with open(file_to_load) as f:
                return json.load(f)
        except:
            pass
    return []


def save_results(results, results_file=None):
    """Save results to JSON file. Uses provider-specific file if specified."""
    from core.config import RESULTS_FILE
    file_to_save = results_file or RESULTS_FILE
    with open(file_to_save, "w") as f:
        json.dump(results, f, indent=2)
