#!/usr/bin/env python3
"""
Mistral AI Account Registration Module.
=======================================
Handles the Mistral AI (chat.mistral.ai) registration flow:
  1. Navigate to https://chat.mistral.ai/chat
  2. Click "Sign up"
  3. Enter email (gmail dot trick alias)
  4. Click "Continue"
  5. Enter password
  6. Enter first name
  7. Enter last name
  8. Click "Signup"
  9. Enter OTP code from Gmail → click "Continue"
  10. Account created

Follows the same pattern as alibaba_register.py for consistency.
"""

import sys
import os
import time
import json
import re
import string
import random
import imaplib
import email as emailmod
from email.header import decode_header
from threading import Lock

# Reuse helpers from farm_headless
from farm_headless import log
from data_paths import get_path, mark_alias_used, is_alias_used

# ─ Config ──────────────────────────────────────────

MISTRAL_CHAT_URL = "https://chat.mistral.ai/chat"

# Results files (per-tab isolated under data/mistral/)
RESULTS_FILE = get_path("mistral", "accounts.csv")
CSV_FILE = RESULTS_FILE  # CSV file path
MISTRAL_JSON = get_path("mistral", "results.json")  # NEW: JSON backup (previously CSV-only)

CSV_HEADER = "timestamp,email,password,first_name,last_name,api_key,status,gmail_account,api_key_timestamp\n"

# OTP deduplication — shared across threads to prevent OTP collision
_used_otps = set()
_otp_lock = Lock()

# Global IMAP lock — serialize Gmail IMAP access to prevent OTP cross-reading
# Only ONE thread can read Gmail at a time. Others wait their turn.
_imap_lock = Lock()

# Random name pools
FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "David", "William", "Richard",
    "Joseph", "Thomas", "Charles", "Mary", "Patricia", "Jennifer", "Linda",
    "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen",
    "Alex", "Chris", "Sam", "Jordan", "Taylor", "Morgan", "Casey",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
]


def generate_password():
    """Generate a strong password: Aa1 + random + ! (19 chars)."""
    chars = string.ascii_letters + string.digits
    pw = ''.join(random.choices(chars, k=15))
    return "Aa1" + pw + "!"


def random_name():
    """Return (first_name, last_name) randomly."""
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


# ─ OTP Reading ──────────────────────────────────────

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
    # Pattern 3: standalone 6-digit number
    for m in re.finditer(r'\b(\d{6})\b', text):
        num = m.group(1)
        if num not in ('181818', '999', '666666', '808080', '000000', '333333'):
            return num
    return None


def read_otp_from_gmail(gmail_user, app_pass, target_email, timeout=120):
    """Read OTP verification code from Gmail IMAP for Mistral AI.

    Mistral sends from noreply@mistral.ai or similar.
    OTP is a 6-digit code.

    Uses _imap_lock to serialize IMAP access — only one thread reads Gmail
    at a time to prevent OTP cross-reading between threads.
    Uses IMAP connection pooling — persistent connection with auto-reconnect.
    """
    log("MAIL", f"Waiting for Mistral OTP to {target_email}...")
    start = time.time()
    request_time = start

    # Use pooled IMAP connection (persistent, auto-reconnect on error)
    with _imap_lock:
        mail = _get_imap_connection(gmail_user, app_pass)
        if not mail:
            log("MAIL", "IMAP connection failed — cannot read OTP")
            return None

    from email.utils import parsedate_to_datetime
    from datetime import datetime, timezone

    while time.time() - start < timeout:
        # Acquire IMAP lock — only one thread can access Gmail at a time
        with _imap_lock:
            try:
                # Re-select to refresh
                mail.select("inbox")
                # Search ALL emails, get the newest ones
                _, data = mail.search(None, "ALL")
                if data[0]:
                    msg_ids = data[0].split()
                    # Only check last 5 emails, newest first
                    for num in reversed(msg_ids[-5:]):
                        _, msg_data = mail.fetch(num, "(RFC822)")
                        raw = msg_data[0][1]
                        msg = emailmod.message_from_bytes(raw)

                        # Only accept emails arrived AFTER this OTP was requested
                        date_str = msg.get("Date", "")
                        try:
                            msg_date = parsedate_to_datetime(date_str)
                            if msg_date:
                                # Convert to unix timestamp
                                msg_ts = msg_date.timestamp()
                                if msg_ts < request_time:
                                    # Email arrived before we requested OTP — skip
                                    continue
                        except:
                            pass

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

                        # Sender must be from Mistral
                        is_mistral = any(x in sender for x in [
                            "mistral", "noreply", "no-reply",
                        ])

                        if not (is_mistral and is_for_us):
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
                            with _otp_lock:
                                if otp in _used_otps:
                                    log("MAIL", f"OTP {otp} already used — skipping")
                                    continue
                                _used_otps.add(otp)
                            log("MAIL", f"OTP found for {target_email}: {otp}")
                            # Mark as seen
                            try:
                                mail.store(num, '+FLAGS', r'\Seen')
                            except Exception as e:
                                log("MAIL", f"STORE error (non-fatal): {e}")
                            return otp
            except Exception as e:
                log("MAIL", f"Gmail IMAP error: {e}")
                # Reconnect on error — reset pooled connection
                _reset_imap_connection()
                mail = _get_imap_connection(gmail_user, app_pass)
                if not mail:
                    log("MAIL", "IMAP reconnect failed — aborting OTP read")
                    return None
        # Release lock before sleeping so other threads can check
        time.sleep(1)

    log("MAIL", "OTP timeout")
    return None


# ─ IMAP Connection Pool ─────────────────────────────
# Persistent IMAP connection — login once, reuse across all threads.
# Auto-reconnect on error. Eliminates 300+ login/logout cycles.

_persistent_imap = None
_persistent_imap_user = None
_persistent_imap_pass = None


def _get_imap_connection(gmail_user, app_pass):
    """Get persistent IMAP connection. Login if needed, reuse if alive."""
    global _persistent_imap, _persistent_imap_user, _persistent_imap_pass
    _persistent_imap_user = gmail_user
    _persistent_imap_pass = app_pass

    if _persistent_imap is not None:
        # Test if connection is alive
        try:
            _persistent_imap.noop()
            return _persistent_imap
        except:
            # Connection dead — reconnect
            try:
                _persistent_imap.logout()
            except:
                pass
            _persistent_imap = None

    # Create new connection
    try:
        _persistent_imap = imaplib.IMAP4_SSL("imap.gmail.com")
        _persistent_imap.login(gmail_user, app_pass)
        _persistent_imap.select("inbox")
        log("MAIL", "IMAP connected (pooled)")
        return _persistent_imap
    except Exception as e:
        log("MAIL", f"IMAP connect error: {e}")
        _persistent_imap = None
        return None


def _reset_imap_connection():
    """Force reconnect on next _get_imap_connection call."""
    global _persistent_imap
    try:
        if _persistent_imap:
            _persistent_imap.logout()
    except:
        pass
    _persistent_imap = None


# ─ Save Results ─────────────────────────────────────

# File lock to prevent race condition when multiple threads write JSON/CSV
from threading import Lock as _FileLock
_save_lock = _FileLock()


def save_result(record, api_key=None):
    """Save or update result in CSV (single file).
    If api_key provided, updates existing record by email.
    If new record, appends to file.
    Failed accounts saved with status=failed, api_key empty (for recover mode).
    Skips duplicate saves — if email already has API key, no re-save.
    Thread-safe via _save_lock.
    """
    with _save_lock:
        import csv as _csv
        # Read existing rows
        rows = []
        if os.path.exists(CSV_FILE):
            try:
                with open(CSV_FILE, newline="") as f:
                    rows = list(_csv.DictReader(f))
            except:
                pass

        email = record.get("email", "")

        if api_key:
            # Update mode — find existing record by email, update api_key
            found = False
            for r in rows:
                if r.get("email") == email:
                    # Skip if already has API key — prevent duplicate
                    if r.get("api_key", "").strip() and r.get("status") == "complete":
                        log("SAVE", f"Skipped duplicate API key for {email} — already has key")
                        return
                    r["api_key"] = api_key
                    r["status"] = "complete"
                    r["api_key_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    found = True
                    break
            if not found:
                # Email not in file yet — add as new record with api_key
                record["api_key"] = api_key
                record["status"] = "complete"
                record["api_key_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                rows.append(record)
            log("SAVE", f"Updated {email} with API key")
        else:
            # New record mode — update if email exists, append if new
            for r in rows:
                if r.get("email") == email:
                    # Update existing record (e.g. recover mode re-processes failed alias)
                    r.update(record)
                    log("SAVE", f"Updated existing record for {email}")
                    break
            else:
                rows.append(record)
                log("SAVE", f"Saved {email} to {CSV_FILE}")

        # Rewrite entire file
        with open(CSV_FILE, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=[
                "timestamp", "email", "password", "first_name",
                "last_name", "api_key", "status", "gmail_account",
                "api_key_timestamp",
            ])
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in writer.fieldnames})

        # Also save to JSON backup (NEW — previously CSV-only)
        try:
            import json as _json
            existing = []
            if os.path.exists(MISTRAL_JSON):
                try:
                    with open(MISTRAL_JSON) as f:
                        existing = _json.load(f)
                except:
                    pass
            # Update or append
            found_json = False
            for r in existing:
                if r.get("email") == email:
                    r.update(record)
                    if api_key:
                        r["api_key"] = api_key
                        r["status"] = "complete"
                        r["api_key_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    found_json = True
                    break
            if not found_json:
                existing.append(record)
            with open(MISTRAL_JSON, "w") as f:
                _json.dump(existing, f, indent=2)
        except Exception:
            pass

        # Mark alias as used in index (dedup for gmail dot trick)
        if email:
            mark_alias_used("mistral", email)


# ─ Forgot Password Recovery ────────────────────────

def _forgot_password_recovery(page, alias_email, new_password, gmail_user, app_pass,
                               otp_queue_lock=None):
    """Forgot password recovery flow — used when signup form inputs are not found.

    Steps:
      1. Click "Forgot password" link on auth page
      2. Enter the same email again
      3. Read OTP from Gmail (reuse read_otp_from_gmail)
      4. Enter OTP
      5. Enter new password
      6. Auto-redirect to https://admin.mistral.ai/organization?profile_dialog=security
      7. Navigate to https://admin.mistral.ai/organization/api-keys
      8. Call create_api_key() — same flow as mistral_apikey.py

    Returns dict with registration result (status="registered"), or None on failure.
    The OTP queue lock is acquired during OTP read to prevent collision.
    """
    from mistral_apikey import create_api_key

    log("FPWD", f"Starting forgot password recovery for: {alias_email}")

    # ─ Step 0: Navigate to Mistral login page ─
    # In recover mode, page may be blank — navigate to auth page first
    log("FPWD", "Step 0: Navigating to Mistral login page...")
    try:
        page.goto("https://chat.mistral.ai/chat", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        # Click Sign up to get to auth page
        try:
            signup_btn = page.query_selector('button:has-text("Sign up")')
            if signup_btn and signup_btn.is_visible():
                signup_btn.click()
                time.sleep(2)
        except:
            pass
        # Wait for auth page
        try:
            page.wait_for_url("*auth.mistral.ai*", timeout=15000)
        except:
            # Try direct navigate to auth
            page.goto("https://v2.auth.mistral.ai/login", wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
        log("FPWD", f"Auth page URL: {page.url[:80]}")
    except Exception as e:
        log("FPWD", f"Navigate to login failed: {e}")

    # ─ Step 0b: Input email on login page, then click Forgot password (skip password input) ─
    # Mistral login flow: email → Continue → password page → click "Forgot password?"
    # Do NOT enter password — go straight to forgot password link.
    log("FPWD", "Step 0b: Inputting email to reveal forgot password link...")
    try:
        email_input = None
        for sel in ['input[name="email"]', 'input[type="email"]', 'input[autocomplete="username"]']:
            try:
                email_input = page.wait_for_selector(sel, timeout=5000)
                if email_input:
                    break
            except:
                pass
        if email_input:
            email_input.click()
            time.sleep(0.3)
            email_input.fill(alias_email)
            log("FPWD", f"Email filled: {alias_email}")
            # Click Continue to go to password page
            for sel in ['button:has-text("Continue")', 'button[type="submit"]']:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        log("FPWD", f"Clicked Continue via: {sel}")
                        break
                except:
                    pass
            time.sleep(3)
            log("FPWD", f"After email submit URL: {page.url[:80]}")
        else:
            log("FPWD", "Email input not found — maybe already on password page")
    except Exception as e:
        log("FPWD", f"Email input step error: {e}")

    # ─ Step 1: Click "Forgot password" link on password page ─
    # Do NOT enter password — click forgot password directly.
    log("FPWD", "Step 1: Looking for 'Forgot password' link...")
    log("FPWD", f"Current URL: {page.url[:100]}")
    try:
        body_text = page.inner_text("body")[:500]
        log("FPWD", f"Page content: {body_text}")
    except:
        pass
    fp_clicked = False
    for sel in [
        'a:has-text("Forgot password")',
        'a:has-text("Forgot Password")',
        'a:has-text("Reset password")',
        'a:has-text("Forgot?")',
        'button:has-text("Forgot password")',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("FPWD", f"Clicked 'Forgot password' via: {sel}")
                fp_clicked = True
                break
        except:
            continue

    # JS fallback — find any link/button with "forgot" text
    if not fp_clicked:
        try:
            found = page.evaluate("""
                () => {
                    const els = document.querySelectorAll('a, button, [role="link"], [role="button"]');
                    for (const el of els) {
                        const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (txt.includes('forgot') || txt.includes('reset password')) {
                            el.click();
                            return txt;
                        }
                    }
                    return null;
                }
            """)
            if found:
                log("FPWD", f"Clicked 'Forgot password' via JS eval: {found}")
                fp_clicked = True
        except:
            pass

    if not fp_clicked:
        # Check if this is a signup page (email not yet registered)
        try:
            body_text = page.inner_text("body")[:500].lower()
            if "first name" in body_text or "last name" in body_text or "signup" in body_text:
                log("FPWD", "Email not yet registered — signup form detected")
                log("FPWD", "Switching to normal registration flow...")
                return "SIGNUP_NEEDED"
        except:
            pass
        log("FPWD", "ERROR: 'Forgot password' link not found!")
        return None

    time.sleep(3)

    # ─ Step 2: Enter email again ─
    log("FPWD", f"Step 2: Entering email: {alias_email}")
    email_filled = False
    for sel in [
        'input[name="email"]',
        'input[type="email"]',
        'input[autocomplete="username"]',
        'input[placeholder*="mail"]',
    ]:
        try:
            page.wait_for_selector(sel, timeout=10000, state="visible")
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.3)
                el.fill(alias_email)
                email_filled = True
                log("FPWD", f"Email filled via: {sel}")
                break
        except:
            continue

    if not email_filled:
        log("FPWD", "ERROR: Email input not found on forgot password page!")
        return None

    # Click Continue/Submit
    log("FPWD", "Looking for submit button on forgot password page...")
    try:
        body_text = page.inner_text("body")[:500]
        log("FPWD", f"Page content after forgot pw click: {body_text}")
    except:
        pass
    for sel in [
        'button:has-text("Send me a code by email")',
        'button:has-text("Send")',
        'button:has-text("Continue")',
        'button[type="submit"]',
        'button:has-text("Reset")',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("FPWD", f"Clicked submit via: {sel}")
                break
        except:
            continue

    time.sleep(3)

    # ─ Step 3: Read OTP from Gmail ─
    log("FPWD", f"Step 3: Current URL: {page.url[:100]}")
    try:
        body_text = page.inner_text("body")[:500]
        log("FPWD", f"Page content after email submit: {body_text}")
    except:
        pass
    # Acquire OTP queue lock to serialize OTP reading
    if otp_queue_lock:
        log("FPWD", "Waiting for OTP queue lock...")
        otp_queue_lock.acquire()
        log("FPWD", "OTP queue lock acquired")

    try:
        log("FPWD", "Step 3: Waiting for OTP input field...")
        otp_input = None
        otp_selectors = [
            'input[name="code"]',
            'input[name="otp"]',
            'input[placeholder*="code"]',
            'input[placeholder*="Code"]',
            'input[placeholder*="verification"]',
            'input[autocomplete="one-time-code"]',
            'input[data-input-otp="true"]',
            'input[type="text"][maxlength="6"]',
            'input[type="number"]',
            'input[inputmode="numeric"]',
        ]

        for sel in otp_selectors:
            try:
                page.wait_for_selector(sel, timeout=10000, state="visible")
                otp_input = page.query_selector(sel)
                if otp_input and otp_input.is_visible():
                    log("FPWD", f"OTP input found via: {sel}")
                    break
            except:
                continue

        if not otp_input:
            log("FPWD", "ERROR: OTP input not found!")
            return None

        # Read OTP from Gmail
        otp = read_otp_from_gmail(gmail_user, app_pass, alias_email, timeout=30)
        if not otp:
            log("FPWD", "ERROR: Failed to get OTP from Gmail!")
            if otp_queue_lock:
                try:
                    otp_queue_lock.release()
                    log("FPWD", "OTP lock released (no OTP)")
                except:
                    pass
            return None

        # ─ Step 4: Enter OTP ─
        log("FPWD", f"Step 4: Entering OTP: {otp}")
        otp_input.click()
        time.sleep(0.3)
        otp_input.fill(otp)
        log("FPWD", f"OTP entered: {otp}")
        time.sleep(2)

        # Mistral OTP uses input-otp library — auto-submits after 6 digits.
        # No Continue/Submit button needed. Just wait for page to change.
        # Try clicking Continue ONLY if it exists (some flows have it).
        for sel in [
            'a:has-text("Continue")',
            'button:has-text("Continue")',
            'button[type="submit"]:has-text("Continue")',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    log("FPWD", f"Clicked Continue after OTP via: {sel}")
                    break
            except:
                continue

        # ─ OTP submitted — release lock so next thread can read its OTP ─
        if otp_queue_lock:
            try:
                otp_queue_lock.release()
                log("FPWD", "OTP lock released (OTP submitted)")
            except:
                pass

        # ─ Step 5: Wait for new password page to appear ─
        # After OTP auto-submit, page transitions to "Enter new password" screen.
        # Single password field only — no confirm password.
        log("FPWD", f"Step 5: Waiting for new password input...")
        pw_filled = False
        pw_selectors = [
            'input[name="password"]',
            'input[name="newPassword"]',
            'input[name="new_password"]',
            'input[type="password"]',
        ]

        for wait in range(10):  # 10 x 2s = 20s max
            for sel in pw_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        time.sleep(0.3)
                        el.fill(new_password)
                        pw_filled = True
                        log("FPWD", f"Password filled via: {sel} (after {wait*2}s)")
                        break
                except:
                    continue
            if pw_filled:
                break
            time.sleep(2)

        if not pw_filled:
            log("FPWD", "ERROR: New password input not found!")
            try:
                current_url = page.url.lower()
                log("FPWD", f"Current URL: {current_url[:100]}")
                body_text = page.inner_text("body")[:500]
                log("FPWD", f"Page content: {body_text}")
            except:
                pass
            return None

        time.sleep(1)

        # Click "Change password" button
        for sel in [
            'button:has-text("Change password")',
            'button:has-text("Change Password")',
            'button:has-text("Reset")',
            'button:has-text("Continue")',
            'button:has-text("Submit")',
            'button[type="submit"]',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    log("FPWD", f"Clicked submit via: {sel}")
                    break
            except:
                continue

        time.sleep(3)

        # ─ Step 6: Wait for redirect to console.mistral.ai/home ─
        log("FPWD", "Step 6: Waiting for redirect to console.mistral.ai/home...")
        redirect_ok = False
        for wait in range(30):
            time.sleep(2)
            try:
                current_url = page.url.lower()
                if "console.mistral.ai" in current_url:
                    log("FPWD", f"Redirected to console: {current_url[:80]}")
                    redirect_ok = True
                    break
                if "admin.mistral.ai" in current_url:
                    log("FPWD", f"Redirected to admin: {current_url[:80]}")
                    redirect_ok = True
                    break
                if "chat.mistral.ai" in current_url:
                    log("FPWD", f"Redirected to chat: {current_url[:80]}")
                    redirect_ok = True
                    break
                if "mistral.ai" in current_url and "auth.mistral" not in current_url:
                    log("FPWD", f"Redirected to: {current_url[:80]}")
                    redirect_ok = True
                    break
            except:
                continue

        if not redirect_ok:
            log("FPWD", "WARNING: No redirect — trying manual navigate to console")
            try:
                page.goto("https://console.mistral.ai/home",
                          wait_until="domcontentloaded", timeout=15000)
                time.sleep(3)
                current_url = page.url.lower()
                if "auth.mistral.ai" in current_url or "login" in current_url:
                    log("FPWD", "ERROR: Redirected to login — session NOT established!")
                    return None
                redirect_ok = True
            except:
                pass

        if not redirect_ok:
            log("FPWD", "ERROR: Failed to establish session after password reset!")
            return None

        # ─ Step 7: Navigate to console.mistral.ai/api-keys ─
        log("FPWD", "Step 7: Navigating to console.mistral.ai/api-keys...")
        try:
            page.goto("https://console.mistral.ai/api-keys",
                      wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
        except Exception as e:
            log("FPWD", f"Navigate to API keys page failed: {e}")
            return None

        # Check if redirected to login
        current_url = page.url.lower()
        if "auth.mistral.ai" in current_url or "login" in current_url:
            log("FPWD", "ERROR: Redirected to login on API keys page!")
            return None

        # ─ Step 8: Create API key — reuse mistral_apikey.create_api_key ─
        log("FPWD", "Step 8: Creating API key (reusing mistral_apikey flow)...")
        api_key = create_api_key(page, timeout=60)

        if api_key:
            log("FPWD", f"API key created: {api_key[:16]}...")
            # Save result with API key directly
            result = {
                "email": alias_email,
                "password": new_password,
                "first_name": "",
                "last_name": "",
                "api_key": api_key,
                "status": "complete",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "gmail_account": gmail_user,
                "api_key_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_result({"email": alias_email}, api_key=api_key)
            return result
        else:
            log("FPWD", "API key creation failed — account recovered but no key")
            result = {
                "email": alias_email,
                "password": new_password,
                "first_name": "",
                "last_name": "",
                "api_key": "",
                "status": "registered",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "gmail_account": gmail_user,
            }
            save_result(result)
            return result

    except Exception as e:
        log("FPWD", f"EXCEPTION in forgot password flow: {e}")
        # Ensure lock is released on exception
        if otp_queue_lock:
            try: otp_queue_lock.release()
            except: pass
        return None


# ─ Registration ─────────────────────────────────────

def register_mistral(page, alias_email, password, first_name, last_name,
                     gmail_user, app_pass, otp_queue_lock=None):
    """Full Mistral AI registration flow (steps 1-9).

    If otp_queue_lock is provided, the signup submit → OTP verify phase
    is serialized: only one browser at a time goes through OTP, preventing
    OTP email collision between threads.

    Returns dict with registration result, or None on failure.
    """
    log("MIST", f"Registering Mistral AI: {alias_email}")

    # ─ Step 1: Navigate to chat.mistral.ai ─
    log("MIST", "Step 1: Navigating to chat.mistral.ai...")
    for _try in range(3):
        try:
            page.goto(MISTRAL_CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            break
        except Exception as e:
            log("MIST", f"Navigate retry {_try+1}/3: {e}")
            if _try == 2:
                raise
            time.sleep(2)
    time.sleep(1)

    # ─ Step 1b: Accept "Vibe Terms of Service" dialog if present ─
    log("MIST", "Step 1b: Checking for Vibe Terms of Service dialog...")
    try:
        accept_btn = page.query_selector('button:has-text("Accept and continue")')
        if accept_btn and accept_btn.is_visible():
            accept_btn.click()
            log("MIST", "Accepted Vibe Terms of Service")
            time.sleep(1)
        else:
            log("MIST", "No TOS dialog found — continuing")
    except Exception as e:
        log("MIST", f"TOS dialog check: {e} (continuing)")

    # ─ Step 2: Click "Sign up" button ─
    log("MIST", "Step 2: Looking for Sign up button...")
    signup_clicked = False

    # Method 1: Playwright text selector
    for sel in [
        'button:has-text("Sign up")',
        'button:has-text("Sign Up")',
    ]:
        try:
            page.wait_for_selector(sel, timeout=10000, state="visible")
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("MIST", f"Clicked Sign up via: {sel}")
                signup_clicked = True
                break
        except:
            continue

    # Method 2: JS eval — find button by text (handles SPA/shadow DOM)
    if not signup_clicked:
        try:
            found = page.evaluate("""
                () => {
                    const btns = document.querySelectorAll('button, a');
                    for (const b of btns) {
                        const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                        if (txt === 'sign up' || txt === 'sign up') {
                            b.click();
                            return txt;
                        }
                    }
                    return null;
                }
            """)
            if found:
                log("MIST", f"Clicked Sign up via JS eval: '{found}'")
                signup_clicked = True
        except:
            pass

    if not signup_clicked:
        log("MIST", "Sign up button not found — maybe already on auth page")

    # Wait for redirect to v2.auth.mistral.ai (after clicking Sign up)
    log("MIST", "Waiting for redirect to auth.mistral.ai...")
    try:
        page.wait_for_url("*auth.mistral.ai*", timeout=15000)
        log("MIST", f"Redirected to auth page: {page.url[:80]}")
    except:
        log("MIST", f"No redirect — still on: {page.url[:80]}")

    # ─ Step 3: Fill email on auth.mistral.ai ─
    # After clicking Sign up, we should be on v2.auth.mistral.ai/login
    log("MIST", f"Step 3: Filling email: {alias_email}")
    log("MIST", f"Current URL: {page.url[:80]}")

    email_filled = False
    # The auth page has input[name="email"] with placeholder "you@example.com"
    for sel in [
        'input[name="email"]',
        'input[placeholder="you@example.com"]',
        'input[type="email"]',
        'input[autocomplete="username"]',
    ]:
        try:
            page.wait_for_selector(sel, timeout=15000, state="visible")
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.3)
                el.fill(alias_email)
                email_filled = True
                log("MIST", f"Email filled via: {sel}")
                break
        except:
            continue

    if not email_filled:
        log("MIST", "ERROR: Email input not found!")
        try:
            log("MIST", f"Page URL: {page.url}")
            body_text = page.inner_text("body")[:500]
            log("MIST", f"Page content: {body_text}")
        except:
            pass
        return None

    time.sleep(1)

    # ─ Step 4: Click "Continue" button ─
    log("MIST", "Step 4: Looking for Continue button...")
    continue_clicked = False
    for sel in [
        'button:has-text("Continue")',
        'button[type="submit"]:has-text("Continue")',
    ]:
        try:
            page.wait_for_selector(sel, timeout=10000, state="visible")
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("MIST", f"Clicked Continue via: {sel}")
                continue_clicked = True
                break
        except:
            continue

    if not continue_clicked:
        log("MIST", "Continue button not found — trying Enter")
        page.keyboard.press("Enter")
    time.sleep(3)

    # ─ Steps 5-8: Fill password, first name, last name — ALL ON SAME PAGE ─
    # After Continue, the page shows: Password + First name + Last name + Signup button
    log("MIST", "Step 5: Filling password...")
    pw_filled = False
    for sel in [
        'input[name="password"]',
        'input[type="password"]',
    ]:
        try:
            page.wait_for_selector(sel, timeout=15000, state="visible")
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.3)
                el.fill(password)
                pw_filled = True
                log("MIST", f"Password filled via: {sel}")
                break
        except:
            continue

    if not pw_filled:
        log("MIST", "ERROR: Password input not found!")
        return None

    # Step 6: First name
    log("MIST", f"Step 6: Filling first name: {first_name}")
    fn_filled = False
    for sel in [
        'input[name="firstName"]',
        'input[placeholder="John"]',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.3)
                el.fill(first_name)
                fn_filled = True
                log("MIST", f"First name filled via: {sel}")
                break
        except:
            continue

    # Step 7: Last name
    log("MIST", f"Step 7: Filling last name: {last_name}")
    ln_filled = False
    for sel in [
        'input[name="lastName"]',
        'input[placeholder="Doe"]',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.3)
                el.fill(last_name)
                ln_filled = True
                log("MIST", f"Last name filled via: {sel}")
                break
        except:
            continue

    # ─ Fallback: Forgot Password recovery flow ─
    # If first name AND last name inputs are not found, the signup form
    # may have changed or the account already exists with a different flow.
    # Use "Forgot password" to reset password via OTP, then login.
    if not fn_filled and not ln_filled:
        log("MIST", "WARNING: First name + Last name input not found")
        log("MIST", "Triggering Forgot Password recovery flow...")
        result = _forgot_password_recovery(
            page, alias_email, password, gmail_user, app_pass, otp_queue_lock
        )
        if result:
            log("MIST", f"Forgot password recovery SUCCESS: {alias_email}")
            return result
        else:
            log("MIST", "ERROR: Forgot password recovery FAILED!")
            if otp_queue_lock:
                try: otp_queue_lock.release()
                except: pass
            return None

    time.sleep(1)

    # ─ Step 8 onwards: Signup submit → OTP → redirect ─
    # Acquire OTP queue lock — only one browser submits signup at a time
    # This ensures OTP emails arrive one at a time, no collision between threads
    if otp_queue_lock:
        log("MIST", "Waiting for OTP queue lock (serialize signup submit)...")
        otp_queue_lock.acquire()
        log("MIST", "OTP queue lock acquired — proceeding with signup")

    try:
        # ─ Step 8: Click "Signup" button ─
        log("MIST", "Step 8: Clicking Signup button...")
        signup_submit = False
        for sel in [
            'button[type="submit"]:has-text("Signup")',
            'button:has-text("Signup")',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    log("MIST", f"Clicked Signup via: {sel}")
                    signup_submit = True
                    break
            except:
                continue

        if not signup_submit:
            log("MIST", "Signup button not found — trying Enter")
            page.keyboard.press("Enter")

        time.sleep(2)

        # ─ Step 9: Enter OTP from Gmail ─
        log("MIST", "Step 9: Waiting for OTP input...")

        # Wait for OTP input field to appear
        otp_input = None
        otp_selectors = [
            'input[name="code"]',
            'input[name="otp"]',
            'input[placeholder*="code"]',
            'input[placeholder*="Code"]',
            'input[placeholder*="verification"]',
            'input[autocomplete="one-time-code"]',
            'input[data-input-otp="true"]',
            'input[type="text"][maxlength="6"]',
            'input[type="number"]',
            'input[inputmode="numeric"]',
        ]

        for sel in otp_selectors:
            try:
                page.wait_for_selector(sel, timeout=5000, state="visible")
                otp_input = page.query_selector(sel)
                if otp_input and otp_input.is_visible():
                    log("MIST", f"OTP input found via: {sel}")
                    break
            except:
                continue

        if not otp_input:
            log("MIST", "ERROR: OTP input not found!")
            if otp_queue_lock:
                try: otp_queue_lock.release()
                except: pass
            return None

        # Read OTP from Gmail
        otp = read_otp_from_gmail(gmail_user, app_pass, alias_email, timeout=10)
        if not otp:
            log("MIST", "ERROR: Failed to get OTP from Gmail!")
            if otp_queue_lock:
                try: otp_queue_lock.release()
                except: pass
            return None

        # Fill OTP
        otp_input.click()
        time.sleep(0.3)
        otp_input.fill(otp)
        log("MIST", f"OTP entered: {otp}")
        time.sleep(2)

        # ─ OTP submitted — release lock so next browser can proceed ─
        if otp_queue_lock:
            try:
                otp_queue_lock.release()
                log("MIST", "OTP lock released (OTP submitted)")
            except:
                pass

        # Click "Continue" button after OTP
        log("MIST", "Looking for Continue button after OTP...")
        otp_continue = False

        for attempt in range(15):
            for sel in [
                'a:has-text("Continue")',
                'button:has-text("Continue")',
                'button[type="submit"]:has-text("Continue")',
                'input[type="submit"][value="Continue"]',
            ]:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        log("MIST", f"Clicked Continue after OTP via: {sel} (attempt {attempt+1})")
                        otp_continue = True
                        break
                except:
                    continue
            if otp_continue:
                break
            time.sleep(1)

        # JS fallback: find and click any element with "Continue" text
        if not otp_continue:
            try:
                found = page.evaluate("""
                    () => {
                        const els = document.querySelectorAll('a, button, input[type="submit"], div[role="button"]');
                        for (const el of els) {
                            const txt = (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
                            if (txt === 'continue') {
                                el.click();
                                return txt;
                            }
                        }
                        return null;
                    }
                """)
                if found:
                    log("MIST", "Clicked Continue after OTP via JS eval")
                    otp_continue = True
            except:
                pass

        if not otp_continue:
            log("MIST", "Continue after OTP not found — trying form submit methods")
            try:
                submitted = page.evaluate("""
                    () => {
                        const otpInput = document.querySelector('input[inputmode="numeric"], input[name="code"], input[name="otp"]');
                        if (otpInput && otpInput.form) {
                            otpInput.form.submit();
                            return 'form.submit()';
                        }
                        const forms = document.querySelectorAll('form');
                        if (forms.length > 0) {
                            forms[0].submit();
                            return 'form[0].submit()';
                        }
                        return null;
                    }
                """)
                if submitted:
                    log("MIST", f"OTP form submitted via JS: {submitted}")
                    otp_continue = True
            except:
                pass

        if not otp_continue:
            log("MIST", "Trying Enter on OTP field as last resort")
            try:
                otp_input.click()
                time.sleep(0.2)
            except:
                pass
            page.keyboard.press("Enter")

        # ─ Wait for redirect to chat.mistral.ai ─
        log("MIST", "Waiting for redirect to chat.mistral.ai...")
        redirect_ok = False
        for wait in range(30):
            time.sleep(2)
            try:
                current_url = page.url.lower()
                if "chat.mistral.ai" in current_url:
                    log("MIST", f"Redirected to chat.mistral.ai (after {wait*2}s)")
                    redirect_ok = True
                    break
                if "v2.auth.mistral.ai/verification" in current_url:
                    if wait % 5 == 0:
                        log("MIST", f"Still on verification page ({wait*2}s)...")
                        try:
                            el = page.query_selector('a:has-text("Continue"), button:has-text("Continue")')
                            if el and el.is_visible():
                                el.click()
                                log("MIST", f"Re-clicked Continue at {wait*2}s")
                        except:
                            pass
                        if wait == 10:
                            log("MIST", "Reloading verification page to trigger Continue button...")
                            try:
                                page.reload(wait_until="domcontentloaded", timeout=15000)
                                time.sleep(2)
                            except:
                                pass
                    continue
                if "mistral.ai" in current_url and "auth.mistral" not in current_url:
                    log("MIST", f"Redirected to: {current_url[:80]}")
                    redirect_ok = True
                    break
            except:
                continue

        current_url = page.url.lower()
        log("MIST", f"Post-registration URL: {current_url[:100]}")

        if not redirect_ok:
            log("MIST", "WARNING: Did not redirect to chat.mistral.ai — session may not be established")
            try:
                page.goto("https://chat.mistral.ai/chat", wait_until="domcontentloaded", timeout=15000)
                time.sleep(3)
                current_url = page.url.lower()
                log("MIST", f"After manual navigate: {current_url[:100]}")
                if "auth.mistral.ai" in current_url or "/login" in current_url:
                    log("MIST", "Session NOT established — redirected to login")
                    time.sleep(5)
                    current_url = page.url.lower()
                    log("MIST", f"Re-check URL: {current_url[:100]}")
                    if "chat.mistral.ai" in current_url and "auth.mistral" not in current_url:
                        redirect_ok = True
                elif "chat.mistral.ai" in current_url:
                    redirect_ok = True
            except:
                pass

    finally:
        pass  # Lock already released after OTP claimed

    result = {
        "email": alias_email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
        "api_key": "",
        "status": "registered",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gmail_account": gmail_user,
    }

    log("MIST", f"Registration SUCCESS: {alias_email}")
    return result
