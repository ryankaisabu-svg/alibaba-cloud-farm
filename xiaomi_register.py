"""
Xiaomi Account Registration & OTP Verification Module.

Handles the Xiaomi account registration flow (email fill, password, CAPTCHA)
and OTP verification after registration.
Extracted from xiaomi_farm.py as part of modular refactoring.
"""

import sys
import os
import time
import json
import re
import random
import string

# Reuse helpers from farm_headless
from farm_headless import log, screenshot, SCREENSHOT_DIR

# CAPTCHA handling from xiaomi_captcha module
from xiaomi_captcha import wait_for_captcha

DEBUG = "--debug" in sys.argv

# ─ Config ──────────────────────────────────────────

XIAOMI_REGISTER_URL = (
    "https://global.account.xiaomi.com/fe/service/register?"
    "_group=DEFAULT"
    "&_sign=iV9Q5kxBqXGdbkb6kmapXvJrkZM%3D"
    "&serviceParam=%7B%22checkSafePhone%22%3Afalse%2C%22checkSafeAddress%22%3Afalse%2C%22lsrp_score%22%3A0.0%7D"
    "&showActiveX=false&theme=&needTheme=false&bizDeviceType="
    "&_locale=en_US&source=&region=US&sid=api-platform"
    "&qs=%253Fcallback%253Dhttps%25253A%25252F%25252Fplatform.xiaomimimo.com%25252Fsts%25253Fsign%253DM7gfywevl3CG5YTTcZDifhK6IK8%2525253D%252526followup%253Dhttps%2525253A%2525252F%2525252Fplatform.xiaomimimo.com%2525252Fconsole%2525252Fbalance%2526sid%253Dapi-platform"
    "&callback=https%3A%2F%2Fplatform.xiaomimimo.com%2Fsts%3Fsign%3DM7gfywevl3CG5YTTcZDifhK6IK8%253D%26followup%3Dhttps%253A%252F%252Fplatform.xiaomimimo.com%252Fconsole%252Fbalance"
    "&_uRegion=US"
)

# tempmail.plus config — domains known to work with Xiaomi registration
# Note: mailbox.in.ua is REJECTED by Xiaomi ("This email address isn't supported")
# mailto.plus is the most mainstream domain and most likely to be accepted
TEMPMAIL_DOMAINS_XIAOMI = [
    "mailto.plus", "fexpost.com", "fexbox.org",
    "rover.info", "fextemp.com", "any.pink", "merepost.com",
    # "mailbox.in.ua" — REJECTED by Xiaomi
    # "chitthi.info" — also rejected (unusual TLD)
]


# ─ Helpers ──────────────────────────────────────────

def save_result(record):
    """Save result to JSON + CSV (dual backup for safety)."""
    from data_paths import get_path
    results_file = get_path("xiaomi", "results.json")
    # 1. Save to JSON
    results = []
    if os.path.exists(results_file):
        try:
            with open(results_file) as f:
                results = json.load(f)
        except:
            pass
    results.append(record)
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    log("API", f"Saved to {results_file}")

    # 2. Also append to CSV (easy to open in Excel, survives JSON corruption)
    csv_file = get_path("xiaomi", "accounts.csv")
    header = "timestamp,email,password,api_key,status,gmail_account\n"
    row = (
        f'"{record.get("timestamp","")}","{record.get("email","")}",'
        f'"{record.get("password","")}","{record.get("api_key","")}",'
        f'"{record.get("status","")}","{record.get("gmail_account","")}"\n'
    )
    if not os.path.exists(csv_file):
        with open(csv_file, "w") as f:
            f.write(header)
    with open(csv_file, "a") as f:
        f.write(row)
    log("API", f"Saved to {csv_file}")


def generate_password():
    """Generate a strong password for Xiaomi account."""
    upper = random.choice(string.ascii_uppercase)
    lower = ''.join(random.choices(string.ascii_lowercase, k=6))
    digit = ''.join(random.choices(string.digits, k=4))
    special = random.choice("!@#$%")
    return f"{upper}{lower}{digit}{special}"


# ─ Registration ──────────────────────────────────────────

def register_xiaomi(page, provider, auto_captcha=False):
    """Main registration flow for Xiaomi MiMo."""
    # Generate email — use provider's own generation
    # (mail.tm creates real account with password, tempmail.plus just uses API)
    email = provider.generate_email()
    if not email:
        log("MAIL", "Failed to generate email")
        return None, None

    password = generate_password()
    log("REG", f"Password: {password}")

    # Navigate to registration page
    log("REG", "Navigating to Xiaomi registration...")
    page.goto(XIAOMI_REGISTER_URL, wait_until="networkidle", timeout=60000)
    time.sleep(2)

    if DEBUG:
        screenshot(page, "xiaomi_01_register.png")

    # Look for "Sign up" tab/link — Xiaomi shows both Sign in and Sign up
    try:
        # Click "Sign up" tab
        signup_tabs = page.query_selector_all("a, button, span, div")
        for el in signup_tabs:
            text = (el.inner_text() or "").strip().lower()
            if text == "sign up":
                el.click()
                log("REG", "Clicked 'Sign up' tab")
                time.sleep(2)
                break
    except Exception as e:
        log("REG", f"Sign up tab: {e}")

    if DEBUG:
        screenshot(page, "xiaomi_02_signup_form.png")

    # Fill email/phone field
    log("REG", f"Filling email: {email}")
    email_filled = False

    # Try multiple selectors for email input
    email_selectors = [
        'input[placeholder="Email"]',
        'input[type="email"]',
        'input[name="email"]',
        'input[name="user"]',
        'input[placeholder*="mail"]',
        'input[placeholder*="Email"]',
        'input[placeholder*="account"]',
        'input[placeholder*="Account"]',
        '#email',
        '#user',
        '.input-wrap input',
    ]

    for sel in email_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                el.fill(email)
                email_filled = True
                log("REG", f"Email filled via: {sel}")
                break
        except:
            continue

    if not email_filled:
        # Try iframe
        for frame in page.frames:
            for sel in email_selectors:
                try:
                    el = frame.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        el.fill(email)
                        email_filled = True
                        log("REG", f"Email filled via iframe: {sel}")
                        break
                except:
                    continue
            if email_filled:
                break

    if not email_filled:
        log("REG", "Could not find email input field")
        if DEBUG:
            screenshot(page, "xiaomi_error_no_email.png")
        return None, None

    time.sleep(1)

    # Check the agreement checkbox if present
    try:
        checkboxes = page.query_selector_all('input[type="checkbox"]')
        for cb in checkboxes:
            if not cb.is_checked():
                cb.click()
                log("REG", "Checked agreement checkbox")
                time.sleep(0.5)
    except:
        pass

    # Fill password fields BEFORE submitting (Xiaomi shows password fields
    # on the same page as email, not after submit)
    log("REG", "Looking for password fields...")
    pw_selectors = [
        'input[placeholder*="new password"]',
        'input[placeholder*="New password"]',
        'input[placeholder*="Enter your new password"]',
        'input[type="password"]',
        'input[name="password"]',
        '#password',
    ]

    pw_filled = False
    for sel in pw_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.fill(password)
                pw_filled = True
                log("REG", f"Password filled via: {sel}")
                break
        except:
            continue

    if pw_filled:
        # Look for confirm password
        pw_inputs = page.query_selector_all('input[type="password"]')
        if len(pw_inputs) >= 2:
            try:
                pw_inputs[1].fill(password)
                log("REG", "Confirm password filled")
            except:
                pass
        time.sleep(1)

    # Click "Next" button (Xiaomi uses button[type="submit"] with text "Next")
    submit_selectors = [
        'button[type="submit"]',
        'button:has-text("Next")',
        'button:has-text("Sign up")',
        'button:has-text("Submit")',
        '.mi-button--primary:not(:disabled)',
        'a:has-text("Sign up")',
        '.btn-submit',
        '#submit',
    ]

    submitted = False
    for sel in submit_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                submitted = True
                log("REG", f"Clicked submit: {sel}")
                break
        except:
            continue

    if not submitted:
        # Try pressing Enter
        page.keyboard.press("Enter")
        log("REG", "Pressed Enter to submit")
        submitted = True

    time.sleep(3)

    if DEBUG:
        screenshot(page, "xiaomi_03_after_submit.png")

    # Check for Google reCAPTCHA Enterprise (Xiaomi uses miverify wrapper)
    time.sleep(2)
    recaptcha_present = page.evaluate("""() => {
        // Check for reCAPTCHA iframe
        const iframes = document.querySelectorAll('iframe[src*="recaptcha"]');
        if (iframes.length > 0) return true;

        // Check for miverify overlay
        const miverify = document.querySelector('.miverify_wind, .miverify_panel_showRecaptcha');
        if (miverify) {
            const style = window.getComputedStyle(miverify);
            if (style.display !== 'none' && style.visibility !== 'hidden') return true;
        }

        // Check for g-recaptcha-response textarea
        if (document.getElementById('g-recaptcha-response')) return true;

        return false;
    }""")

    if recaptcha_present:
        log("CAPTCHA", "Google reCAPTCHA Enterprise detected!")
        if DEBUG:
            screenshot(page, "xiaomi_03_captcha.png")
        captcha_solved = wait_for_captcha(page, timeout=300, auto_solve=auto_captcha)
        if not captcha_solved:
            log("CAPTCHA", "Failed to solve reCAPTCHA — aborting")
            return None, None
        time.sleep(3)
        if DEBUG:
            screenshot(page, "xiaomi_04_captcha_solved.png")
    else:
        log("REG", "No CAPTCHA detected, continuing...")
        if DEBUG:
            screenshot(page, "xiaomi_03_after_submit.png")

    return email, password


# ─ OTP Verification ──────────────────────────────────────────

def verify_otp(page, provider):
    """Wait for OTP and enter it."""
    log("OTP", "Waiting for OTP email...")
    otp = provider.read_otp(timeout=120)

    if not otp:
        log("OTP", "No OTP received")
        return False

    log("OTP", f"OTP received: {otp}")

    # Find OTP input field
    otp_selectors = [
        'input[name="code"]',
        'input[name="otp"]',
        'input[name="verifyCode"]',
        'input[placeholder*="code"]',
        'input[placeholder*="Code"]',
        'input[placeholder*="OTP"]',
        'input[placeholder*="verification"]',
        'input[type="text"][maxlength="6"]',
        'input[type="tel"][maxlength="6"]',
        '.code-input input',
        '#code',
    ]

    otp_filled = False
    for sel in otp_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.fill(otp)
                otp_filled = True
                log("OTP", f"OTP filled via: {sel}")
                break
        except:
            continue

    if not otp_filled:
        # Try individual digit inputs
        digit_inputs = page.query_selector_all('input[maxlength="1"]')
        if digit_inputs and len(digit_inputs) >= 6:
            for i, digit in enumerate(otp[:len(digit_inputs)]):
                digit_inputs[i].fill(digit)
            otp_filled = True
            log("OTP", "OTP filled via individual digit inputs")

    if not otp_filled:
        # Try typing on focused element
        page.keyboard.type(otp)
        otp_filled = True
        log("OTP", "OTP typed via keyboard")

    time.sleep(1)

    # Click verify/submit
    submit_selectors = [
        'button:has-text("Verify")',
        'button:has-text("Submit")',
        'button:has-text("Confirm")',
        'button:has-text("Next")',
        'button[type="submit"]',
    ]

    for sel in submit_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                log("OTP", f"Clicked verify: {sel}")
                break
        except:
            continue

    time.sleep(3)

    if DEBUG:
        screenshot(page, "xiaomi_05_otp_verified.png")

    log("OTP", "OTP submitted")
    return True
