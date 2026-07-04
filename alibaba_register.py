#!/usr/bin/env python3
"""
Qwen Cloud Account Registration Module.
========================================
Handles the Qwen Cloud (qwencloud.com) registration flow:
  1. Enter email (gmail dot trick alias)
  2. Receive OTP via Gmail IMAP
  3. Enter 6-digit OTP → validate
  4. Account created (session carries to dashboard)

URL: https://www.qwencloud.com/ → Get Started → Sign Up

Flow is MUCH simpler than Alibaba Cloud Console:
  - No password needed (OTP-based)
  - No slider/CAPTCHA
  - No iframe (direct page, not passport.alibabacloud.com iframe)
  - Gmail dot trick WORKS (each alias = separate Qwen Cloud account)

Extracted as standalone module for clean separation from Xiaomi farm.
"""

import sys
import os
import time
import json
import re
import imaplib
import email as emailmod
from email.header import decode_header
from threading import Lock

# Reuse helpers from farm_headless
from farm_headless import log
from data_paths import get_path, mark_alias_used, is_alias_used

# ─ Config ──────────────────────────────────────────

QWEN_SIGNUP_URL = "https://home.qwencloud.com/"

# Results files (per-tab isolated)
RESULTS_FILE = get_path("qwen", "results.json")
CSV_FILE = get_path("qwen", "accounts.csv")

# OTP deduplication — shared across threads to prevent OTP collision
_used_otps = set()
_otp_lock = Lock()


# ─ Helpers ──────────────────────────────────────────

def save_result(record):
    """Save result to JSON + CSV (dual backup)."""
    # 1. JSON
    results = []
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE) as f:
                results = json.load(f)
        except:
            pass
    results.append(record)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    log("SAVE", f"Saved to {RESULTS_FILE}")

    # 2. CSV
    header = "timestamp,email,api_key,status,gmail_account\n"
    row = (
        f'"{record.get("timestamp", "")}","{record.get("email", "")}",'
        f'"{record.get("api_key", "")}","{record.get("status", "")}",'
        f'"{record.get("gmail_account", "")}"\n'
    )
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w") as f:
            f.write(header)
    with open(CSV_FILE, "a") as f:
        f.write(row)
    log("SAVE", f"Saved to {CSV_FILE}")


def read_otp_from_gmail(gmail_user, app_pass, target_email, timeout=120):
    """Read OTP verification code from Gmail IMAP for Qwen Cloud.

    Qwen Cloud sends from noreply@alibabacloud.com or similar.
    OTP is a 6-digit code.
    """
    log("MAIL", f"Waiting for Qwen OTP to {target_email}...")
    start = time.time()
    checked_ids = set()
    # Record start time — only accept OTPs received AFTER this moment
    # This prevents reading old OTP emails from previous attempts
    _search_since = time.time()

    while time.time() - start < timeout:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(gmail_user, app_pass)
            mail.select("inbox")
            # Search for UNSEEN emails only (new OTPs)
            _, data = mail.search(None, "(UNSEEN)")
            if data[0]:
                msg_ids = data[0].split()
                for num in reversed(msg_ids[-10:]):
                    if num in checked_ids:
                        continue
                    _, msg_data = mail.fetch(num, "(RFC822)")
                    raw = msg_data[0][1]
                    msg = emailmod.message_from_bytes(raw)

                    # Check To/Delivered-To headers for our alias
                    # Gmail strips dots, so all dot-trick aliases match the same base.
                    # We rely on _used_otps to ensure each OTP is only claimed once.
                    to_addr = " ".join([
                        msg.get("To", ""),
                        msg.get("Delivered-To", ""),
                        msg.get("X-Original-To", ""),
                    ]).lower()
                    sender = msg.get("From", "").lower()
                    subject = msg.get("Subject", "")

                    # Match: alias base (dots removed) in To header
                    alias_base = target_email.lower().replace(".", "")
                    to_base = to_addr.replace(".", "")
                    is_for_us = alias_base in to_base

                    # Sender must be from Alibaba/Qwen
                    is_qwen = any(x in sender for x in [
                        "alibaba", "qwen", "noreply", "no-reply",
                        "account", "verification",
                    ])

                    if not (is_qwen and is_for_us):
                        checked_ids.add(num)
                        continue

                    # Extract body
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            ct = part.get_content_type()
                            if ct == "text/plain":
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                break
                            elif ct == "text/html" and not body:
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    else:
                        payload = msg.get_payload(decode=True)
                        body = payload.decode("utf-8", errors="ignore") if payload else ""

                    full_text = body + " " + subject
                    otp = _extract_otp(full_text)
                    if otp:
                        # Check if this OTP was already claimed by another thread
                        with _otp_lock:
                            if otp in _used_otps:
                                log("MAIL", f"OTP {otp} already used by another thread — skipping")
                                checked_ids.add(num)
                                continue
                            _used_otps.add(otp)
                        log("MAIL", f"OTP found from {sender[:50]}: {otp}")
                        # Delete the email so future threads don't see it
                        mail.store(num, '+FLAGS', '\\Deleted')
                        mail.expunge()
                        mail.logout()
                        return otp
                    checked_ids.add(num)
            mail.logout()
        except Exception as e:
            log("MAIL", f"Gmail IMAP error: {e}")
        time.sleep(5)

    log("MAIL", "OTP timeout")
    return None


def _extract_otp(text):
    """Extract 6-digit OTP from email text."""
    # Pattern 1: >NNNNNN</span> (HTML styled code)
    m = re.search(r'>\s*(\d{6})\s*</span>', text)
    if m:
        return m.group(1)
    # Pattern 2: near "code" or "verification" keyword
    m = re.search(r'(?:code|verification|otp)[^<]*?(\d{6})', text, re.IGNORECASE)
    if m:
        return m.group(1)
    # Pattern 3: standalone 6-digit number (exclude known false positives)
    for m in re.finditer(r'\b(\d{6})\b', text):
        num = m.group(1)
        if num not in ('181818', '999', '666666', '808080', '000000', '333333'):
            return num
    return None


# ─ Registration ──────────────────────────────────────────
def register_qwen_phase1(page, alias_email, gmail_user, app_pass):
    """Phase 1: Navigate + Signup + Fill email + Click Next.
    Runs in PARALLEL across threads.
    Returns True if on OTP page, False on failure.
    """
    log("REG", f"Registering Qwen Cloud: {alias_email}")

    # ─ Step 1: Navigate to Qwen Cloud ─
    log("REG", "Navigating to qwencloud.com...")
    for _try in range(3):
        try:
            page.goto(QWEN_SIGNUP_URL, wait_until="domcontentloaded", timeout=30000)
            break
        except Exception as e:
            log("REG", f"Navigate retry {_try+1}/3: {e}")
            if _try == 2:
                raise
            time.sleep(2)
    time.sleep(3)

    # ─ Step 2: Wait for SSO page, then click "Sign Up" ─
    log("REG", "Waiting for SSO page to load...")
    signup_clicked = False
    for sel in [
        'a:has-text("Sign Up")',
        'text=Sign Up',
        'a:has-text("sign up")',
    ]:
        try:
            page.wait_for_selector(sel, timeout=15000, state="visible")
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("REG", f"Clicked Sign Up link: {sel}")
                signup_clicked = True
                break
        except:
            continue

    if not signup_clicked:
        log("REG", "Sign Up link not found — checking if already on signup page...")

    time.sleep(3)

    # ─ Step 3: Fill email ─
    log("REG", f"Filling email: {alias_email}")
    email_filled = False

    email_selectors = [
        'input[placeholder="Email"]',
        'input[type="email"]',
        'input[name="email"]',
        'input[placeholder*="mail"]',
        'input[placeholder*="Email"]',
        '#email',
    ]

    log("REG", "Waiting for email input to appear...")
    for sel in email_selectors:
        try:
            page.wait_for_selector(sel, timeout=15000, state="visible")
            log("REG", f"Email input found via: {sel}")
            break
        except:
            continue

    for sel in email_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.3)
                el.fill(alias_email)
                email_filled = True
                log("REG", f"Email filled via: {sel}")
                break
        except:
            continue

    if not email_filled:
        try:
            log("REG", f"Page URL: {page.url}")
            log("REG", f"Page title: {page.title()}")
            body_text = page.inner_text("body")[:500]
            log("REG", f"Page content: {body_text}")
        except:
            pass
        log("REG", "ERROR: Could not fill email!")
        return False

    time.sleep(1)

    # NOTE: "Click Next" moved to phase 2 — must be inside queue lock
    # so OTP email is triggered one at a time
    log("REG", "Phase 1 complete — email filled, waiting for OTP queue")
    return True


def register_qwen_phase2(page, alias_email, gmail_user, app_pass):
    """Phase 2: Click Next + Read OTP + Enter OTP + Validate + Country + Result.
    Runs in QUEUE (one at a time) to prevent OTP collision.
    Returns dict with result, or None on failure.
    """
    # ─ Step 4b: Click Next (triggers OTP email) — inside queue lock ─
    log("REG", "Clicking Next (inside OTP queue)...")
    next_clicked = False
    for sel in [
        'button:has-text("Next")',
        'button[type="submit"]',
        'button:has-text("Continue")',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible() and el.is_enabled():
                el.click()
                next_clicked = True
                log("REG", f"Clicked: {sel}")
                break
        except:
            continue

    if not next_clicked:
        try:
            page.evaluate("""() => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    if (b.innerText.trim() === 'Next' || b.innerText.trim() === 'Continue') {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")
            next_clicked = True
            log("REG", "Clicked Next via JS")
        except:
            pass

    if not next_clicked:
        log("REG", "ERROR: Next button not found!")
        return None

    time.sleep(3)

    # ─ Step 5: Read OTP from Gmail (serialized — one thread at a time) ─
    log("REG", "Waiting for OTP email...")
    otp = read_otp_from_gmail(gmail_user, app_pass, alias_email, timeout=120)
    if not otp:
        log("REG", "ERROR: No OTP received!")
        return None

    log("REG", f"OTP received: {otp}")

    # ─ Step 6: Enter OTP (6 separate input boxes) ─
    log("REG", "Entering OTP...")

    otp_inputs = page.query_selector_all('input[maxlength="1"], input[type="text"][maxlength="1"]')
    if not otp_inputs:
        otp_inputs = page.query_selector_all('input:not([placeholder="Email"])')

    if len(otp_inputs) >= 6:
        for i, digit in enumerate(otp):
            if i < len(otp_inputs):
                otp_inputs[i].click()
                time.sleep(0.1)
                page.keyboard.type(digit, delay=50)
                time.sleep(0.1)
        log("REG", f"OTP entered in {len(otp_inputs)} fields")
    else:
        log("REG", f"Found {len(otp_inputs)} inputs, trying single field...")
        if otp_inputs:
            otp_inputs[0].click()
            page.keyboard.type(otp, delay=50)
        else:
            log("REG", "ERROR: No OTP input fields found!")
            return None

    time.sleep(1)

    # ─ Step 7: Click Validate ─
    log("REG", "Clicking Validate...")
    validate_clicked = False
    for sel in [
        'button:has-text("Validate")',
        'button:has-text("Verify")',
        'button:has-text("Submit")',
        'button:has-text("Confirm")',
        'button[type="submit"]',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible() and el.is_enabled():
                el.click()
                validate_clicked = True
                log("REG", f"Clicked: {sel}")
                break
        except:
            continue

    if not validate_clicked:
        log("REG", "Validate button not found, may have auto-submitted")
        time.sleep(5)
    else:
        time.sleep(3)

    # ─ Step 7b: Handle country/region selection (onboarding) ─
    log("REG", "Checking for country/region selection page...")
    time.sleep(3)

    try:
        body_check = page.inner_text("body")[:3000].lower()
    except:
        body_check = ""

    if any(x in body_check for x in ["country", "region", "select your"]):
        log("REG", "Country/region selection page detected!")

        country_opened = False
        for sel in [
            '[class*="select"]',
            '[role="combobox"]',
            '[role="listbox"]',
            'div:has-text("Select your country")',
            'input[placeholder*="select" i]',
            'input[placeholder*="country" i]',
            '[class*="dropdown"]',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    log("REG", f"Opened country dropdown: {sel}")
                    country_opened = True
                    break
            except:
                continue

        if not country_opened:
            page.evaluate("""
                () => {
                    const els = document.querySelectorAll('div, span, button');
                    for (const e of els) {
                        const txt = (e.innerText || '').trim();
                        if (txt.includes('Select your country') || txt.includes('country/region')) {
                            e.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            log("REG", "Tried fallback click for country dropdown")

        time.sleep(2)

        log("REG", "Typing 'Singapore' in country dropdown...")

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
                    log("REG", f"Typed Singapore in: {sel}")
                    break
            except:
                continue

        if not search_filled:
            page.keyboard.type("Singapore")
            log("REG", "Typed Singapore via keyboard")
            time.sleep(1)

        time.sleep(1)
        page.keyboard.press("Enter")
        log("REG", "Pressed Enter to select Singapore")
        time.sleep(3)

        try:
            still_open = page.query_selector('[role="listbox"]:visible, [role="option"]:visible')
            if still_open:
                log("REG", "Dropdown still open after Enter — clicking Singapore option directly")
                try:
                    opt = page.query_selector('[role="option"]:has-text("Singapore")')
                    if opt:
                        opt.click()
                        log("REG", "Clicked Singapore option via Playwright")
                        time.sleep(2)
                except:
                    pass
        except:
            pass

        page.evaluate("window.scrollBy(0, 300)")
        time.sleep(1)
        time.sleep(1)

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
            log("REG", "Agreement checkbox checked")
        else:
            log("REG", "WARNING: Could not find/check agreement checkbox")

        time.sleep(1)

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
            log("REG", f"Clicked: {continue_clicked} after country selection (via JS)")
        else:
            log("REG", "WARNING: Could not find Continue button — trying Playwright selector")
            for sel in ['button:has-text("Continue")', 'button:has-text("Confirm")', 'button[type="submit"]']:
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click(force=True)
                        log("REG", f"Force-clicked: {sel}")
                        break
                except:
                    continue

        time.sleep(3)
    else:
        log("REG", "No country selection page — continuing")

    # ─ Step 7c: Wait for redirect after registration ─
    log("REG", "Waiting for registration to complete...")
    for _wait in range(15):
        time.sleep(2)
        post_url = page.url
        if "account.alibabacloud.com" not in post_url:
            log("REG", f"Redirected away from SSO: {post_url}")
            break
        for btn_text in ["Confirm", "OK", "Continue", "Submit", "Get Started", "Finish"]:
            try:
                el = page.query_selector(f'button:has-text("{btn_text}")')
                if el and el.is_visible() and el.is_enabled():
                    el.click()
                    log("REG", f"Clicked {btn_text} button on post-registration page")
                    time.sleep(2)
                    break
            except:
                continue

    # ─ Step 8: Check result ─
    post_url = page.url
    log("REG", f"Post-validate URL: {post_url}")

    body_text = ""
    try:
        body_text = page.inner_text("body")[:2000].lower()
    except:
        pass

    if any(x in body_text for x in ["dashboard", "welcome", "qwen", "api key", "console", "home"]):
        log("REG", "SUCCESS! Account registered and logged in!")
        return {
            "email": alias_email,
            "status": "registered",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gmail_account": gmail_user,
        }

    if any(x in body_text for x in ["verification code", "enter the code", "sign up", "log in"]):
        log("REG", "WARNING: Still on signup/OTP page — may have failed")
        err = page.query_selector("[class*='error'], [class*='alert'], [class*='msg']")
        if err:
            log("REG", f"Error: {err.inner_text()[:200]}")
        return None

    if "qwencloud.com" in post_url and "account.alibabacloud.com" not in post_url:
        log("REG", "SUCCESS! Redirected to Qwen Cloud!")
        return {
            "email": alias_email,
            "status": "registered",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gmail_account": gmail_user,
        }

    log("REG", f"Unclear result. URL: {post_url}, body: {body_text[:200]}")

    return {
        "email": alias_email,
        "status": "unclear",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gmail_account": gmail_user,
    }


def register_qwen(page, gmail_user, app_pass, alias_email):
    """Legacy entry point — calls phase1 + phase2 sequentially.
    Kept for backward compatibility with xiaomi_farm.py etc.
    """
    if not register_qwen_phase1(page, alias_email, gmail_user, app_pass):
        return None
    return register_qwen_phase2(page, alias_email, gmail_user, app_pass)
