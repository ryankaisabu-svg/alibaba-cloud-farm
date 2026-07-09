#!/usr/bin/env python3
"""
IAMHC Farm - Register accounts at https://api.iamhc.cn using email list.
Each account needs a UNIQUE email (no alias/dot trick -- site blocks aliases).

NOTE: api.iamhc.cn blocks Gmail dot-trick and plus addressing.
      Each registration must use a different email address.

Usage:
  python iamhc_farm.py --count 10
  python iamhc_farm.py --email-list accounts.txt --count 10
  python iamhc_farm.py --debug --count 1
"""

import sys
import os
import json
import time
import random
import string
import imaplib
import email as email_lib

# Force UTF-8 stdout/stderr (Windows cp1252 can't encode emoji)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import argparse
import re
import requests as req_lib

FARM_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(FARM_DIR, "data", "iamhc")
RESULTS_FILE = os.path.join(DATA_DIR, "iamhc_results.json")
REGISTER_URL = "https://api.iamhc.cn/register"
LOGIN_URL = "https://api.iamhc.cn/api/user/login"
TOKEN_URL = "https://api.iamhc.cn/api/token/?p=0&page_size=10"

os.makedirs(DATA_DIR, exist_ok=True)

# ── Logging ──
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
QUIET = os.getenv("QUIET", "false").lower() == "true"

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    pfx = {"INFO": "[i]", "OK": "[OK]", "ERR": "[!]", "DBG": "[?]", "WAIT": "..."}.get(level, " ")
    try:
        print(f"[{ts}] {pfx} {msg}", flush=True)
    except UnicodeEncodeError:
        print(f"[{ts}] {pfx} {msg}".encode("ascii", "replace").decode(), flush=True)

def dbg(msg):
    if DEBUG:
        log(msg, "DBG")

# ── Gmail dot trick ──
def generate_dot_trick_aliases(base_email, count=1):
    """Generate dot-trick aliases from base Gmail address.
    Gmail ignores dots in local part, so a.b.c@gmail.com = abc@gmail.com.
    We generate unique variants by inserting dots at different positions."""
    local, domain = base_email.split("@")
    aliases = set()

    # Generate by inserting dots between characters
    chars = list(local)
    n = len(chars)
    # Use binary pattern: for each non-empty subset of positions, insert dots
    # But limit to manageable combinations
    positions = list(range(1, n))  # positions between chars where dots can go
    for mask in range(1, min(2**len(positions), 2**10)):
        new_chars = list(chars)
        for i, pos in enumerate(positions):
            if mask & (1 << i):
                new_chars.insert(pos + i, ".")
        aliases.add("".join(new_chars))

    # Add no-dot version (base)
    aliases.add(local)

    result = list(aliases)
    random.shuffle(result)
    return result[:count]

def get_all_possible_aliases(base_email):
    """Get all possible dot-trick aliases (up to 2^10 = 1024 max)."""
    local, domain = base_email.split("@")
    chars = list(local)
    n = len(chars)
    positions = list(range(1, n))
    aliases = set()
    for mask in range(min(2**len(positions), 2**10)):
        new_chars = list(chars)
        dot_count = 0
        for i, pos in enumerate(positions):
            if mask & (1 << i):
                new_chars.insert(pos + dot_count, ".")
                dot_count += 1
        aliases.add("".join(new_chars) + "@" + domain)
    return sorted(aliases)

def read_otp_from_gmail(gmail_user, app_pass, alias_email, timeout=90):
    """Read OTP from Gmail via IMAP. Search for recent emails from IAMHC.
    Only reads emails received AFTER this function is called (fresh OTPs)."""
    import datetime as dt

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, app_pass)
        mail.select("INBOX")

        # Record time before we start - only read emails after this point
        start_time = time.time()
        start_dt = dt.datetime.now(dt.timezone.utc)

        while time.time() - start_time < timeout:
            try:
                status, messages = mail.search(None, "ALL")
                if not messages[0]:
                    time.sleep(3)
                    continue

                msg_ids = messages[0].split()
                for msg_id in reversed(msg_ids[-15:]):
                    status, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue
                    msg = email_lib.message_from_bytes(msg_data[0][1])

                    # Get email date - skip if older than our start time
                    msg_date_str = msg.get("Date", "")
                    try:
                        msg_dt = email_lib.utils.parsedate_to_datetime(msg_date_str)
                        if msg_dt and msg_dt.replace(tzinfo=dt.timezone.utc) < start_dt:
                            continue
                    except:
                        pass

                    subject = str(msg.get("Subject", ""))
                    from_addr = str(msg.get("From", ""))

                    # Check if this is a verification email from IAMHC
                    if any(kw in subject.lower() + from_addr.lower() for kw in
                           ["verification", "verify", "code", "otp", "iamhc", "confirm"]):
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                ct = part.get_content_type()
                                if ct == "text/plain":
                                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    break
                                elif ct == "text/html":
                                    raw = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    # Strip HTML tags
                                    body = re.sub(r"<[^>]+>", " ", raw)
                        else:
                            body = msg.get_payload(decode=True)
                            if body:
                                body = body.decode("utf-8", errors="ignore")

                        # Find 4-8 digit code
                        codes = re.findall(r"\b(\d{4,8})\b", body)
                        if codes:
                            mail.logout()
                            return codes[0]

                time.sleep(3)
            except Exception as e:
                dbg(f"IMAP poll error: {e}")
                time.sleep(3)

        mail.logout()
    except Exception as e:
        dbg(f"IMAP error: {e}")
    return None


# ── API helpers ──
def register_via_api(username, password, alias_email, verification_code):
    """Register via API endpoint (if available) for faster processing."""
    try:
        resp = req_lib.post(f"{REGISTER_URL.replace('/register', '/api/user/register')}", json={
            "username": username,
            "password": password,
            "email": alias_email,
            "verification_code": verification_code,
        }, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return data
            else:
                dbg(f"Register API error: {data.get('message')}")
        return None
    except Exception as e:
        dbg(f"Register API exception: {e}")
        return None

def get_api_key(username, password):
    """Login and get API key from console."""
    try:
        # Login
        resp = req_lib.post(LOGIN_URL, json={
            "username": username,
            "password": password,
        }, timeout=15)
        if resp.status_code != 200:
            dbg(f"Login failed: {resp.status_code} {resp.text[:200]}")
            return None

        data = resp.json()
        token = data.get("data", "")
        if not token:
            dbg(f"No token in login response: {data}")
            return None

        # Get tokens
        headers = {"Authorization": f"Bearer {token}"}
        resp = req_lib.get(TOKEN_URL, headers=headers, timeout=15)
        if resp.status_code != 200:
            dbg(f"Get tokens failed: {resp.status_code}")
            return None

        tokens_data = resp.json()
        tokens = tokens_data.get("data", [])
        if isinstance(tokens, list) and tokens:
            api_key = tokens[0].get("key", "")
            if api_key:
                return api_key

        # If no existing token, create one
        create_resp = req_lib.post("https://api.iamhc.cn/api/token/", headers=headers, json={
            "name": "farm-key",
            "remain_quota": 500000,
            "expired_time": -1,
            "unlimited_quota": True,
        }, timeout=15)
        if create_resp.status_code == 200:
            new_key = create_resp.json().get("data", {}).get("key", "")
            if new_key:
                return new_key

        return None
    except Exception as e:
        dbg(f"API key error: {e}")
        return None

def send_verification_code(alias_email):
    """Trigger verification code send via API."""
    try:
        resp = req_lib.get(
            f"https://api.iamhc.cn/api/verification?email={alias_email}&turnstile=",
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return True
            dbg(f"Verification send error: {data.get('message')}")
        dbg(f"Verification send status: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as e:
        dbg(f"Verification send error: {e}")
        return False

# ── Browser registration (fallback if API doesn't work) ──
def register_via_browser(username, password, alias_email, verification_code, headless=True):
    """Register using Playwright browser (fallback)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("playwright not installed. Install: pip install playwright && playwright install chromium", "ERR")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        try:
            page.goto(REGISTER_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("input", timeout=10000)

            # Fill username
            page.locator("input[id='username'], input[name='username']").first.fill(username)
            # Fill password
            page.locator("input[id='password'], input[name='password']").first.fill(password)
            # Fill confirm password
            page.locator("input[id='confirm_password'], input[name='confirm_password']").first.fill(password)
            # Fill email
            page.locator("input[id='email'], input[name='email']").first.fill(alias_email)

            # Click Get Verification Code
            page.locator("button:has-text('Get Verification Code')").click()
            page.wait_for_timeout(2000)

            # Fill verification code
            page.locator("input[id='verification_code'], input[name='verification_code']").first.fill(verification_code)

            # Check agreement
            page.locator("input[type='checkbox']").check()

            # Click Sign up
            page.locator("button:has-text('Sign up'):not(:disabled)").click()
            page.wait_for_timeout(3000)

            # Check for success
            url = page.url
            if "/console" in url or "/login" in url:
                return True
            content = page.content()
            if "success" in content.lower() or "console" in content.lower():
                return True

            dbg(f"Registration result URL: {url}")
            return False
        except Exception as e:
            dbg(f"Browser registration error: {e}")
            return False
        finally:
            browser.close()

# ── Results management ──
def load_results():
    if os.path.isfile(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"accounts": []}
    return {"accounts": []}

def save_results(results):
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

def add_result(entry):
    results = load_results()
    results["accounts"] = [a for a in results["accounts"]
                           if a.get("email") != entry.get("email")]
    results["accounts"].append(entry)
    save_results(results)

# ── Stats ──
_stats = {"queued": 0, "processing": 0, "created": 0, "done": 0, "failed": 0, "apikey": 0}

def print_stats():
    s = _stats
    print(f"[STATS] queued={s['queued']} processing={s['processing']} "
          f"created={s['created']} done={s['done']} failed={s['failed']} apikey={s['apikey']}", flush=True)

def load_used_aliases():
    """Load set of already-used aliases."""
    alias_file = os.path.join(DATA_DIR, "alias_index.json")
    if os.path.isfile(alias_file):
        try:
            with open(alias_file, "r") as f:
                data = json.load(f)
            return set(data.get("used", []))
        except:
            pass
    return set()

def mark_alias_used(alias):
    """Mark alias as used."""
    used = load_used_aliases()
    used.add(alias)
    alias_file = os.path.join(DATA_DIR, "alias_index.json")
    with open(alias_file, "w") as f:
        json.dump({"used": sorted(used)}, f, indent=2)

# ── Main ──
def process_account(email_addr, app_pass, headless=True):
    """Register one account. Each email must be unique (no aliases allowed)."""
    username = "iamhc_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    password = "".join(random.choices(string.ascii_letters + string.digits, k=16))

    dbg(f"[{email_addr}] Registering as {username}...")

    # Send verification code via API
    if not send_verification_code(email_addr):
        log(f"[{email_addr}] Failed to send verification code", "ERR")
        return {"success": False, "email": email_addr, "error": "verification_send_failed"}

    # Read OTP from email via IMAP
    log(f"[{email_addr}] Waiting for OTP...", "WAIT")
    otp = read_otp_from_gmail(email_addr, app_pass, email_addr, timeout=90)
    if not otp:
        log(f"[{email_addr}] OTP timeout (90s)", "ERR")
        return {"success": False, "email": email_addr, "error": "otp_timeout"}

    dbg(f"[{email_addr}] OTP: {otp}")

    # Try API registration first (faster)
    reg_result = register_via_api(username, password, email_addr, otp)
    if reg_result is None:
        # Fallback to browser
        dbg(f"[{email_addr}] API register failed, trying browser...")
        reg_result = register_via_browser(username, password, email_addr, otp, headless=headless)
        if not reg_result:
            log(f"[{email_addr}] Registration failed", "ERR")
            return {"success": False, "email": email_addr, "error": "registration_failed"}

    # Get API key
    api_key = get_api_key(username, password)

    entry = {
        "email": email_addr,
        "username": username,
        "password": password,
        "api_key": api_key or "",
        "status": "complete" if api_key else "no_key",
        "timestamp": int(time.time()),
    }
    add_result(entry)

    if api_key:
        log(f"[{email_addr}] OK! API key obtained", "OK")
        return {"success": True, "email": email_addr, "api_key": api_key, "username": username}
    else:
        log(f"[{email_addr}] Registered but no API key", "OK")
        return {"success": True, "email": email_addr, "api_key": "", "username": username}


def main():
    parser = argparse.ArgumentParser(description="IAMHC Farm - email list registration")
    parser.add_argument("--email-list", default=None, help="File with email:password per line (each email = 1 account)")
    parser.add_argument("--gmail-user", default=None, help="Gmail address (single email mode)")
    parser.add_argument("--app-pass", default=None, help="Email app password (single email or IMAP for OTP)")
    parser.add_argument("--count", type=int, default=1, help="Number of accounts to register")
    parser.add_argument("--headless", action="store_true", default=True, help="Headless browser")
    parser.add_argument("--show", action="store_true", help="Show browser")
    parser.add_argument("--debug", action="store_true", help="Debug output")
    parser.add_argument("--quiet", action="store_true", help="Quiet mode (progress counter only)")
    args = parser.parse_args()

    global DEBUG, QUIET, HEADLESS
    DEBUG = args.debug
    QUIET = args.quiet
    HEADLESS = not args.show

    # Load email list from file
    emails = []  # list of (email, password_or_none)
    if args.email_list and os.path.isfile(args.email_list):
        with open(args.email_list, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    email, pwd = line.split(":", 1)
                    emails.append((email.strip(), pwd.strip()))
                else:
                    emails.append((line.strip(), args.app_pass))
        log(f"Loaded {len(emails)} accounts from {args.email_list}")
    elif args.email_list:
        log(f"Email list file not found: {args.email_list}", "ERR")
        return
    else:
        # Single email mode
        emails = [(args.gmail_user, args.app_pass)]

    if not emails:
        log("No emails to process!", "ERR")
        return

    if len(emails) < args.count:
        args.count = len(emails)
        log(f"Only {len(emails)} emails available, adjusting count")

    log(f"IAMHC Farm Starting")
    log(f"Emails: {len(emails)} | Target: {args.count}")
    print()

    _stats["queued"] = args.count
    print_stats()

    ok = 0
    fail = 0
    for i in range(args.count):
        email_addr, email_pass = emails[i]
        _stats["processing"] += 1
        _stats["queued"] -= 1
        print_stats()

        try:
            result = process_account(email_addr, email_pass, HEADLESS)
            if result.get("success"):
                ok += 1
                _stats["created"] += 1
                _stats["done"] += 1
                if result.get("api_key"):
                    _stats["apikey"] += 1
            else:
                fail += 1
                _stats["failed"] += 1
                _stats["done"] += 1
        except Exception as e:
            fail += 1
            _stats["failed"] += 1
            _stats["done"] += 1
            log(f"Unexpected error: {e}", "ERR")

        _stats["processing"] -= 1
        print_stats()

        # Delay between accounts (rate limit: 30s on verification code)
        if i < args.count - 1:
            delay = 35  # 35s between each to avoid rate limit
            log(f"Waiting {delay}s for rate limit cooldown...", "WAIT")
            time.sleep(delay)

    print()
    log(f"Done. OK={ok} FAIL={fail} Total={args.count}")


if __name__ == "__main__":
    main()
