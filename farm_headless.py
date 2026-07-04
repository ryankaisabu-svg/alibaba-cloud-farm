#!/usr/bin/env python3
"""
Alibaba Cloud Farm — Multi-Provider Edition
Register new account → verify OTP → login → create API key

Email providers (fallback chain):
  1. tempmail.plus (9 domains, API, no registration needed)
  2. Outlook (via outlook_manager.py — alias + OTP reading)
  3. Manual input (user provides email + reads OTP manually)

Usage:
  python farm_headless.py                    # Run with tempmail.plus (headless)
  python farm_headless.py --show             # Visible browser (for CAPTCHA)
  python farm_headless.py --debug            # Screenshots at every step
  python farm_headless.py --provider outlook # Use Outlook instead
  python farm_headless.py --provider manual  # Manual email input
  python farm_headless.py --menu             # Interactive menu

SLIDER CAPTCHA SOLVING:
  This script now includes DYNAMIC SLIDER SOLVING for AlibabaCloud CAPTCHA.
  
  Available methods (auto-detected based on OS and installed packages):
  - Playwright Mouse (built-in, always available)
  - PyAutoGUI (Windows/Linux - pip install pyautogui)
  - pynput (Windows/Linux - pip install pynput)
  - uinput (Linux only - requires uinput kernel module)
  
  For Windows: Install PyAutoGUI for best results: pip install pyautogui
  For Linux: Install uinput: pip install python-uinput (requires root/sudo)
  
  The solver will try all available methods in order until one succeeds.

ANTI-CAPTCHA OPTIMIZATIONS:
  This script implements professional anti-detection measures to minimize CAPTCHA:
  - User-Agent: Chrome 130+ (latest stable)
  - Viewport: 1366x768 (standard laptop resolution)
  - Device Scale Factor: 1 (normal DPI)
  - Timezone: America/New_York (standard)
  - Locale: en-US (standard)
  - Permissions: geolocation, notifications (standard)
  - playwright-stealth: Applied to mask automation fingerprints
  - JavaScript anti-detection: Overrides webdriver, plugins, languages, WebGL
  - WebGL Fingerprint: Spoofed as Intel(R) UHD Graphics 620

  For best results:
  - Use --show (non-headless) mode for lowest CAPTCHA rate
  - Install playwright-stealth: uv pip install playwright-stealth
  - Use residential proxies if IP is blocked
"""

import sys
import time
import json
import re
import random
import string
import os
import platform
import subprocess
import urllib.request
import urllib.error
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

# Check for available slider solving methods
PYAUTOGUI_AVAILABLE = False
PYNPUT_AVAILABLE = False
UINPUT_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    pass

try:
    from pynput.mouse import Controller, Button
    PYNPUT_AVAILABLE = True
except ImportError:
    pass

# uinput only available on Linux
if platform.system() == 'Linux':
    try:
        import uinput
        UINPUT_AVAILABLE = True
    except ImportError:
        pass

# ─ Config ──────────────────────────────────────────
REGISTER_URL = "https://account.alibabacloud.com/register/intl_register.htm"
LOGIN_URL = "https://account.alibabacloud.com/login/login.htm"
MODELSTUDIO_URL = "https://modelstudio.console.alibabacloud.com/ap-southeast-1?tab=dashboard#/api-key"
from data_paths import get_path, get_alias_index_path, is_alias_used, mark_alias_used, get_used_count, load_alias_index, save_alias_index, migrate_legacy_files

RESULTS_FILE = get_path("alibaba", "results.json")

# Provider-specific output files (all under data/alibaba/)
PROVIDER_RESULTS = {
    "tempmail":     get_path("alibaba", "results.json"),
    "mailtm":       get_path("alibaba", "results.json"),
    "tempmailio":   get_path("alibaba", "results.json"),
    "gmail":        get_path("alibaba", "results.json"),
    "outlook":      get_path("alibaba", "results.json"),
    "manual":       get_path("alibaba", "results.json"),
}
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
DEBUG = "--debug" in sys.argv
SHOW = "--show" in sys.argv
AUTO_CAPTCHA = "--auto-captcha" in sys.argv  # auto-solve OFF by default

# Browser engine selection: --browser <name>
BROWSER = "chrome"
if "--browser" in sys.argv:
    _bi = sys.argv.index("--browser")
    if _bi + 1 < len(sys.argv):
        BROWSER = sys.argv[_bi + 1].lower()
BROWSER_OPTIONS = ["chrome", "firefox", "webkit", "camoufox", "undetected-chromedriver", "rebrowser"]

# Proxy support
PROXY = None
if "--proxy" in sys.argv:
    idx = sys.argv.index("--proxy")
    if idx + 1 < len(sys.argv):
        PROXY = sys.argv[idx + 1]

# tempmail.plus config
TEMPMAIL_API = "https://tempmail.plus/api/mails"
TEMPMAIL_DOMAINS = [
    "mailto.plus", "fexpost.com", "fexbox.org", "mailbox.in.ua",
    "rover.info", "chitthi.info", "fextemp.com", "any.pink", "merepost.com"
]

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ─ Human-like delay helpers ──────────────────────────
# Replaces fixed time.sleep() with randomized delays to mimic human behaviour.
# Bot detectors flag perfectly-timed intervals; jitter breaks the pattern.

def human_delay(min_s=0.8, max_s=2.5):
    """Random pause that mimics human think-time between actions."""
    time.sleep(random.uniform(min_s, max_s))

def human_pause_short():
    """Micro-pause between rapid field interactions (click→fill→tab)."""
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


def log(step, msg):
    ts = time.strftime("%H:%M:%S")
    try:
        print(f"  [{ts}] [{step}] {msg}", flush=True)
    except UnicodeEncodeError:
        # Fallback: replace non-ASCII chars for cp1252 terminals
        safe = msg.encode("ascii", "replace").decode("ascii")
        print(f"  [{ts}] [{step}] {safe}", flush=True)


def screenshot(page, name):
    path = os.path.join(SCREENSHOT_DIR, name)
    try:
        page.screenshot(path=path)
        log("SHOT", f"Saved {name}")
    except:
        pass


# ════════════════════════════════════════════════════
# ─ Email Providers ─────────────────────────────────
# ════════════════════════════════════════════════════

class TempMailProvider:
    """tempmail.plus — 9 domains, API-based, no registration needed."""

    def __init__(self):
        self.email = None
        self.domain = None
        self.seen_ids = set()

    def generate_email(self):
        name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.domain = random.choice(TEMPMAIL_DOMAINS)
        self.email = f"{name}@{self.domain}"
        log("MAIL", f"tempmail.plus: {self.email}")
        return self.email

    def read_otp(self, timeout=120):
        log("MAIL", f"Waiting for OTP to {self.email}...")
        start = time.time()
        while time.time() - start < timeout:
            try:
                url = f"{TEMPMAIL_API}?email={self.email}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())

                mail_list = data.get("mail_list", [])
                for msg in mail_list:
                    msg_id = msg.get("mail_id")
                    if not msg_id or msg_id in self.seen_ids:
                        continue
                    self.seen_ids.add(msg_id)

                    # Fetch full email
                    detail_url = f"{TEMPMAIL_API}/{msg_id}?email={self.email}"
                    req2 = urllib.request.Request(detail_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req2, timeout=15) as resp2:
                        detail = json.loads(resp2.read())

                    body = detail.get("text", "") or ""
                    subject = detail.get("subject", "") or ""
                    html = detail.get("html", "") or ""
                    full_text = body + " " + subject + " " + html

                    # Find 6-digit OTP
                    otp = self._extract_otp(full_text)
                    if otp:
                        log("MAIL", f"OTP found: {otp}")
                        return otp
            except Exception as e:
                log("MAIL", f"Error: {e}")
            time.sleep(5)
        log("MAIL", "OTP timeout")
        return None

    def _extract_otp(self, text):
        # Try span-wrapped code first
        m = re.search(r'>\s*(\d{6})\s*</span>', text)
        if m:
            return m.group(1)
        # Try "code" / "verification" context
        m = re.search(r'(?:code|verification|otp)[^<]*?(\d{6})', text, re.IGNORECASE)
        if m:
            return m.group(1)
        # Try bare 6-digit number
        for m in re.finditer(r'\b(\d{6})\b', text):
            num = m.group(1)
            if num not in ('181818', '999', '666666', '808080', '000000'):
                return num
        return None


class MailTmProvider:
    """mail.tm — free API, create account + receive OTP. Domains rotate."""

    MAILTM_API = "https://api.mail.tm"

    def __init__(self):
        self.email = None
        self.password = None
        self.token = None
        self.account_id = None
        self.seen_ids = set()

    def _get_domains(self):
        try:
            req = urllib.request.Request(f"{self.MAILTM_API}/domains",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            return [d["domain"] for d in data.get("hydra:member", [])]
        except:
            return ["web-library.net"]

    def generate_email(self):
        domains = self._get_domains()
        name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.password = "Temp" + ''.join(random.choices(string.ascii_letters + string.digits, k=8)) + "1!"
        domain = random.choice(domains) if domains else "web-library.net"
        self.email = f"{name}@{domain}"

        try:
            data = json.dumps({"address": self.email, "password": self.password}).encode()
            req = urllib.request.Request(f"{self.MAILTM_API}/accounts", data=data,
                                         headers={"User-Agent": "Mozilla/5.0",
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            self.account_id = result.get("id")

            # Get auth token
            data2 = json.dumps({"address": self.email, "password": self.password}).encode()
            req2 = urllib.request.Request(f"{self.MAILTM_API}/token", data=data2,
                                          headers={"User-Agent": "Mozilla/5.0",
                                                   "Content-Type": "application/json"})
            with urllib.request.urlopen(req2, timeout=10) as resp2:
                self.token = json.loads(resp2.read()).get("token")

            log("MAIL", f"mail.tm: {self.email}")
            return self.email
        except Exception as e:
            log("MAIL", f"mail.tm create error: {e}")
            return None

    def read_otp(self, timeout=120):
        if not self.token:
            log("MAIL", "mail.tm: no token")
            return None
        log("MAIL", f"Waiting for OTP to {self.email}...")
        start = time.time()
        while time.time() - start < timeout:
            try:
                req = urllib.request.Request(f"{self.MAILTM_API}/messages",
                    headers={"User-Agent": "Mozilla/5.0",
                             "Authorization": f"Bearer {self.token}"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                for msg in data.get("hydra:member", []):
                    msg_id = msg.get("id")
                    if not msg_id or msg_id in self.seen_ids:
                        continue
                    self.seen_ids.add(msg_id)

                    # Fetch full message
                    req2 = urllib.request.Request(f"{self.MAILTM_API}/messages/{msg_id}",
                        headers={"User-Agent": "Mozilla/5.0",
                                 "Authorization": f"Bearer {self.token}"})
                    with urllib.request.urlopen(req2, timeout=10) as resp2:
                        detail = json.loads(resp2.read())

                    body = detail.get("text", "") or ""
                    subject = detail.get("subject", "") or ""
                    intro = detail.get("intro", "") or ""
                    full_text = body + " " + subject + " " + intro

                    otp = self._extract_otp(full_text)
                    if otp:
                        log("MAIL", f"OTP found: {otp}")
                        return otp
            except Exception as e:
                log("MAIL", f"mail.tm error: {e}")
            time.sleep(5)
        log("MAIL", "OTP timeout")
        return None

    def _extract_otp(self, text):
        m = re.search(r'>\s*(\d{6})\s*</span>', text)
        if m:
            return m.group(1)
        m = re.search(r'(?:code|verification|otp)[^<]*?(\d{6})', text, re.IGNORECASE)
        if m:
            return m.group(1)
        for m in re.finditer(r'\b(\d{6})\b', text):
            num = m.group(1)
            if num not in ('181818', '999', '666666', '808080', '000000'):
                return num
        return None


class TempMailIoProvider:
    """temp-mail.io — free API, random-looking domains (not obvious disposable).

    Domains like wnbaldwy.com, yzcalo.com, etc — less likely to be blocklisted.
    API: https://api.internal.temp-mail.io/api/v3/
    """

    API = "https://api.internal.temp-mail.io/api/v3"

    def __init__(self):
        self.email = None
        self.token = None
        self.seen_ids = set()

    def generate_email(self):
        try:
            payload = json.dumps({"min_name_length": 10, "max_name_length": 10}).encode()
            req = urllib.request.Request(f"{self.API}/email/new", data=payload,
                                         headers={"User-Agent": "Mozilla/5.0",
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            self.email = data.get("email")
            self.token = data.get("token")
            if self.email and self.token:
                log("MAIL", f"temp-mail.io: {self.email}")
                return self.email
            log("MAIL", f"temp-mail.io: missing email/token in response: {data}")
            return None
        except Exception as e:
            log("MAIL", f"temp-mail.io create error: {e}")
            return None

    def read_otp(self, timeout=120):
        if not self.email or not self.token:
            log("MAIL", "temp-mail.io: no email/token")
            return None
        log("MAIL", f"Waiting for OTP to {self.email}...")
        start = time.time()
        while time.time() - start < timeout:
            try:
                req = urllib.request.Request(
                    f"{self.API}/email/{self.email}/messages",
                    headers={"User-Agent": "Mozilla/5.0",
                             "Authorization": f"Bearer {self.token}"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                # data is a list of message objects
                if isinstance(data, list):
                    for msg in data:
                        msg_id = msg.get("id")
                        if not msg_id or msg_id in self.seen_ids:
                            continue
                        self.seen_ids.add(msg_id)
                        body = msg.get("body_text", "") or ""
                        subject = msg.get("subject", "") or ""
                        full_text = body + " " + subject
                        otp = self._extract_otp(full_text)
                        if otp:
                            log("MAIL", f"OTP found: {otp}")
                            return otp
            except Exception as e:
                log("MAIL", f"temp-mail.io error: {e}")
            time.sleep(5)
        log("MAIL", "OTP timeout")
        return None

    def _extract_otp(self, text):
        m = re.search(r'>\s*(\d{6})\s*</span>', text)
        if m:
            return m.group(1)
        m = re.search(r'(?:code|verification|otp)[^<]*?(\d{6})', text, re.IGNORECASE)
        if m:
            return m.group(1)
        for m in re.finditer(r'\b(\d{6})\b', text):
            num = m.group(1)
            if num not in ('181818', '999', '666666', '808080', '000000'):
                return num
        return None


class GmailDotTrickProvider:
    """Gmail dot trick — generate aliases from 1 Gmail account via IMAP.

    Uses dots in username to create unique-looking addresses that all
    deliver to the same Gmail inbox. Xiaomi sees @gmail.com = accepted.

    Anti-duplikat via alias_index.json (O(1) lookup) + CSV fallback.
    Tab: "alibaba" (shared with Qwen Cloud registration).
    """

    # Which tab's alias index to use for dedup
    _TAB = "alibaba"

    # Aliases known to be already registered (manual / prior runs before tracking)
    # Set via QWEN_SKIP_ALIASES env var (comma-separated)
    _env_skip = os.environ.get("QWEN_SKIP_ALIASES", "")
    SKIP_ALIASES = set(
        alias.strip() for alias in _env_skip.split(",") if alias.strip()
    )

    def __init__(self):
        self.gmail_user = None
        self.app_pass = None
        self.base_username = None
        self.email = None
        self._combo_iter = None
        self._aliases_lock = None

    def configure(self, gmail_user, app_pass):
        """Set Gmail credentials. Call before generate_email()."""
        self.gmail_user = gmail_user
        self.app_pass = app_pass
        self.base_username = gmail_user.split("@")[0]
        self._aliases_lock = None  # set externally if multi-threaded

    def set_lock(self, lock):
        """Set a threading.Lock for thread-safe file access."""
        self._aliases_lock = lock

    def _load_csv_emails(self):
        """Load all emails from alias_index.json (O(1)) + CSV fallback (thread-safe)."""
        import csv as _csv
        emails = set()
        
        # Primary: alias_index.json (fast O(1) lookup)
        index = load_alias_index(self._TAB)
        emails.update(k for k in index.get("aliases", {}).keys())
        
        # Fallback: also scan CSV for any aliases not in index yet
        csv_path = get_path(self._TAB, "accounts.csv")
        if self._aliases_lock:
            with self._aliases_lock:
                if os.path.exists(csv_path):
                    with open(csv_path, newline="") as f:
                        for r in _csv.DictReader(f):
                            emails.add(r.get("email", "").strip())
        else:
            if os.path.exists(csv_path):
                with open(csv_path, newline="") as f:
                    for r in _csv.DictReader(f):
                        emails.add(r.get("email", "").strip())
        return emails

    def _generate_alias(self):
        """Generate next dot-trick alias (skip no-dot alias and already-used in CSV)."""
        import itertools
        if self._combo_iter is None:
            positions = len(self.base_username) - 1
            self._combo_iter = itertools.product([False, True], repeat=positions)

        # Load existing emails from CSV for anti-duplikat
        existing = self._load_csv_emails()
        existing.update(self.SKIP_ALIASES)

        for combo in self._combo_iter:
            # Skip first combo (all False = no dots)
            if not any(combo):
                continue
            result = self.base_username[0]
            for i, dot in enumerate(combo):
                if dot:
                    result += "."
                result += self.base_username[i + 1]
            alias = f"{result}@gmail.com"
            if alias not in existing:
                return alias
        return None  # exhausted

    def generate_email(self):
        if not self.gmail_user or not self.app_pass:
            log("MAIL", "Gmail: not configured. Call configure() first.")
            return None
        alias = self._generate_alias()
        if not alias:
            log("MAIL", "Gmail: all aliases exhausted!")
            return None
        self.email = alias
        # Mark alias as used in index (thread-safe dedup)
        mark_alias_used(self._TAB, alias, base_gmail=self.gmail_user)
        log("MAIL", f"Gmail dot trick: {alias}")
        return alias

    def read_otp(self, timeout=120):
        if not self.email:
            log("MAIL", "Gmail: no email set")
            return None
        log("MAIL", f"Waiting for OTP to {self.email}...")

        # Thread-safe OTP reading: only one thread accesses IMAP at a time
        # and we track used OTPs to avoid stealing another thread's OTP
        if self._aliases_lock:
            with self._aliases_lock:
                return self._read_otp_impl(timeout)
        return self._read_otp_impl(timeout)

    # Track OTPs already returned to prevent cross-thread OTP theft
    _used_otps = set()
    _used_otps_lock = None

    def _read_otp_impl(self, timeout=120):
        # Track which message IDs we've already checked
        checked_ids = set()
        start = time.time()
        while time.time() - start < timeout:
            try:
                import imaplib
                mail = imaplib.IMAP4_SSL("imap.gmail.com")
                mail.login(self.gmail_user, self.app_pass)
                mail.select("inbox")
                # Search ALL recent emails (not just UNSEEN — seen flag may be set)
                _, data = mail.search(None, "ALL")
                if data[0]:
                    msg_ids = data[0].split()
                    # Check last 10 emails, newest first
                    for num in reversed(msg_ids[-10:]):
                        if num in checked_ids:
                            continue
                        _, msg_data = mail.fetch(num, "(RFC822)")
                        raw = msg_data[0][1]
                        import email as emailmod
                        msg = emailmod.message_from_bytes(raw)
                        # Check To, Delivered-To, X-Original-To headers
                        to_addr = " ".join([
                            msg.get("To", ""),
                            msg.get("Delivered-To", ""),
                            msg.get("X-Original-To", ""),
                        ]).lower()
                        sender = msg.get("From", "").lower()
                        subject = msg.get("Subject", "")
                        # Must be from Qwen Cloud / Alibaba and addressed to our alias
                        alias_base = self.email.lower().replace(".", "")
                        is_qwen = any(x in sender for x in ["qwen", "alibaba", "account", "noreply", "notice"])
                        is_for_us = alias_base in to_addr.replace(".", "")
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
                        otp = self._extract_otp(full_text)
                        if otp:
                            # Check if this OTP was already used by another thread
                            if otp in GmailDotTrickProvider._used_otps:
                                checked_ids.add(num)
                                continue
                            GmailDotTrickProvider._used_otps.add(otp)
                            log("MAIL", f"OTP found from {sender[:40]}: {otp}")
                            mail.logout()
                            return otp
                        checked_ids.add(num)
                mail.logout()
            except Exception as e:
                log("MAIL", f"Gmail IMAP error: {e}")
            time.sleep(5)
        log("MAIL", "OTP timeout")
        return None

    def _extract_otp(self, text):
        m = re.search(r'>\s*(\d{6})\s*</span>', text)
        if m:
            return m.group(1)
        m = re.search(r'(?:code|verification|otp)[^<]*?(\d{6})', text, re.IGNORECASE)
        if m:
            return m.group(1)
        for m in re.finditer(r'\b(\d{6})\b', text):
            num = m.group(1)
            if num not in ('181818', '999', '666666', '808080', '000000'):
                return num
        return None


class OutlookProvider:
    """Outlook — uses outlook_manager.py for alias + OTP reading."""

    def __init__(self):
        self.email = None
        self._manager = None

    def generate_email(self):
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            import outlook_manager
            self._manager = outlook_manager.OutlookManager()
            self.email = self._manager.create_alias()
            if self.email:
                log("MAIL", f"Outlook alias: {self.email}")
                return self.email
        except Exception as e:
            log("MAIL", f"Outlook error: {e}")
        return None

    def read_otp(self, timeout=120):
        if self._manager:
            return self._manager.read_otp(self.email, timeout=timeout)
        return None


class ManualProvider:
    """Manual — user provides email and reads OTP."""

    def generate_email(self):
        print("\n  +---------------------------------------------+")
        print("  |  MANUAL EMAIL INPUT                         |")
        print("  |  Enter an email address that can receive    |")
        print("  |  verification codes:                        |")
        print("  +---------------------------------------------+")
        email = input("  Email: ").strip()
        if not email or "@" not in email:
            log("MAIL", "Invalid email")
            return None
        self.email = email
        log("MAIL", f"Manual email: {email}")
        return email

    def read_otp(self, timeout=300):
        print(f"\n  +---------------------------------------------+")
        print(f"  |  ENTER OTP CODE                              |")
        print(f"  |  Check inbox for {self.email:<28s} |")
        print(f"  |  Enter the 6-digit verification code:        |")
        print(f"  +---------------------------------------------+")
        try:
            otp = input("  OTP code: ").strip()
            if re.match(r'^\d{6}$', otp):
                log("MAIL", f"Manual OTP: {otp}")
                return otp
            log("MAIL", "Invalid OTP format")
        except:
            pass
        return None


def get_provider(choice=None):
    """Get email provider by choice or interactive menu."""
    if choice == "tempmail":
        return TempMailProvider()
    elif choice == "mailtm":
        return MailTmProvider()
    elif choice == "tempmailio":
        return TempMailIoProvider()
    elif choice == "gmail":
        return GmailDotTrickProvider()
    elif choice == "outlook":
        return OutlookProvider()
    elif choice == "manual":
        return ManualProvider()
    elif choice is None:
        return TempMailProvider()  # Default
    return TempMailProvider()


# ════════════════════════════════════════════════════
# ─ CLI Menu ────────────────────────────────────────
# ════════════════════════════════════════════════════

def show_menu():
    """Interactive CLI menu with provider selection."""
    print()
    print("  +===========================================================+")
    print("  |          ALIBABA CLOUD FARM - MULTI-PROVIDER              |")
    print("  +===========================================================+")
    print("  |                                                           |")
    print("  |  Email Provider:                                          |")
    print("  |                                                           |")
    print("  |  [1] tempmail.plus  (9 domains, API, recommended)         |")
    print("  |      Domains: mailto.plus, fexpost.com, fexbox.org,      |")
    print("  |                rover.info, chitthi.info, any.pink, ...   |")
    print("  |                                                           |")
    print("  |  [2] mail.tm        (free API, account-based)            |")
    print("  |      Domains: web-library.net (rotating)                 |")
    print("  |                                                           |")
    print("  |  [3] Outlook        (alias + OTP via Playwright)         |")
    print("  |      Requires existing Outlook account                    |")
    print("  |                                                           |")
    print("  |  [4] Manual         (you provide email + OTP)            |")
    print("  |                                                           |")
    print("  +-----------------------------------------------------------+")
    print("  |  Options:                                                 |")
    print("  |  --show     Visible browser (for CAPTCHA solving)        |")
    print("  |  --debug    Screenshots at every step                    |")
    print("  |  --headless Run without browser (no CAPTCHA solving)     |")
    print("  +===========================================================+")
    print()

    while True:
        try:
            choice = input("  Choose provider [1-4] (default 1): ").strip()
        except:
            choice = "1"
        if choice in ("", "1"):
            return TempMailProvider()
        elif choice == "2":
            return MailTmProvider()
        elif choice == "3":
            return OutlookProvider()
        elif choice == "4":
            return ManualProvider()
        print("  Invalid choice. Enter 1, 2, 3, or 4.")


# ════════════════════════════════════════════════════
# ─ Frame Helpers ───────────────────────────────────
# ════════════════════════════════════════════════════

def find_passport_frame(page):
    """Find passport iframe on Alibaba Cloud pages."""
    for frame in page.frames[1:]:
        if "passport.alibabacloud.com" in (frame.url or ""):
            return frame
    return None


def find_login_frame(page):
    """Find login frame — passport iframe, any iframe with login fields, or main page.
    
    Alibaba Cloud login page (account.alibabacloud.com/login) has the form directly
    in the main page (NOT in an iframe). The form uses:
    - Account field: input with placeholder "Enter your email"
    - Password field: input[type='password'] with placeholder "Enter your password"
    - Submit: button with text "Sign In"
    
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

    # Check 3: main page — new Alibaba login form (direct, no iframe)
    try:
        # New style: placeholder-based selectors
        if page.query_selector("input[placeholder*='Enter your email']") or \
           page.query_selector("input[placeholder*='email']") and \
           page.query_selector("input[type='password']"):
            return page
    except:
        pass

    # Check 4: main page — old style selectors
    try:
        if page.query_selector("#fm-login-id") or \
           page.query_selector("input[name='loginId']") or \
           page.query_selector("input[placeholder*='email']") or \
           page.query_selector("input[type='password']"):
            return page
    except:
        pass

    return None


# ════════════════════════════════════════════════════
# ─ Slider Solving Functions ────────────────────────────
# ════════════════════════════════════════════════════

def find_slider_handle(page, frame=None):
    """Search all frames for slider handle (Baxia/NC/risk_slider).
    Returns: (element, frame, selector) or (None, None, None)
    """
    # Selectors for AlibabaCloud risk_slider (newer Baxia)
    risk_selectors = [
        '#nc_1_n1z', '.nc_iconfont.btn_slide', '.btn_slide',
        'span.nc_iconfont', '#nc_1_n1z_em', '.nc-iconfont',
        '#nc_1__scale_text', '#risk_slider_container .nc_iconfont',
        '#risk_slider_container .btn_slide',
        '#risk_slider_container [role="slider"]',
        '#risk_slider_container .slider-btn',
        '#risk_slider_container .sliderBtn',
        '#baxia-dialog .nc_iconfont',
        '#baxia-dialog .btn_slide',
        '.baxia-captcha .nc_iconfont',
        '.baxia-captcha .btn_slide',
        # Generic slider selectors
        '[data-role="sliderHandle"]',
        '.slider-handle',
        '.slide-verify-slider',
        '#aliyunCaptcha-btn',
        '.nc-container .nc_iconfont',
    ]
    
    # Search in the provided frame first
    frames_to_search = []
    if frame:
        frames_to_search.append(frame)
    frames_to_search.extend(page.frames)
    
    for f in frames_to_search:
        for sel in risk_selectors:
            try:
                el = f.query_selector(sel)
                if el:
                    box = el.bounding_box()
                    if box and box['width'] > 0 and box['height'] > 0:
                        return el, f, sel
            except:
                pass
    return None, None, None

def solve_slider_playwright(page, frame=None):
    """Solve slider using Playwright's built-in mouse actions."""
    log("SLIDER", "Attempting Playwright mouse solver...")
    
    # Wait for slider widget to finish loading (up to 10s)
    log("SLIDER", "Waiting for slider widget to render...")
    for wait_i in range(10):
        el, target_frame, sel = find_slider_handle(page, frame)
        if el:
            break
        time.sleep(1)
        if wait_i == 4:
            log("SLIDER", "Still waiting for slider handle...")
    
    if not el:
        # Log all visible elements in #risk_slider_container for debugging
        if frame:
            try:
                container = frame.query_selector("#risk_slider_container")
                if container:
                    inner = container.inner_html()
                    log("SLIDER", f"risk_slider_container innerHTML (first 500 chars): {inner[:500]}")
            except:
                pass
        log("SLIDER", "Playwright: No slider handle found after 10s wait")
        return False
    
    try:
        box = el.bounding_box()
        if not box:
            log("SLIDER", "Playwright: No bounding box")
            return False
        
        # Calculate drag distance - try to find track
        track = None
        if target_frame:
            for track_sel in ['#nc_1__scale_text', '.nc_scale', '#nc_1_n1t', '.nc-track']:
                try:
                    track = target_frame.query_selector(track_sel)
                    if track:
                        track_box = track.bounding_box()
                        if track_box:
                            drag_dist = track_box['width'] - box['width']
                            break
                except:
                    pass
        
        if track is None:
            drag_dist = 300  # Default drag distance
        
        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2
        end_x = start_x + drag_dist
        
        log("SLIDER", f"Playwright: Handle at ({start_x:.0f},{start_y:.0f}), drag {drag_dist:.0f}px")
        
        # Move to slider handle
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        
        # Drag with steps for human-like movement
        steps = 20
        for i in range(1, steps + 1):
            current_x = start_x + (drag_dist * i / steps)
            page.mouse.move(current_x, start_y)
            time.sleep(0.05)
        
        page.mouse.up()
        time.sleep(2)
        
        # Check if solved
        el2, _, _ = find_slider_handle(page, target_frame)
        if not el2:
            log("SLIDER", "Playwright: Slider solved!")
            return True
        else:
            log("SLIDER", "Playwright: Slider still visible")
            return False
            
    except Exception as e:
        log("SLIDER", f"Playwright: Error - {e}")
        return False

def solve_slider_pyautogui(page, frame=None):
    """Solve slider using PyAutoGUI."""
    if not PYAUTOGUI_AVAILABLE:
        log("SLIDER", "PyAutoGUI not available")
        return False
    
    log("SLIDER", "Attempting PyAutoGUI solver...")
    
    import pyautogui
    
    el, found_frame, sel = find_slider_handle(page, frame)
    if not el:
        log("SLIDER", "PyAutoGUI: No slider handle found")
        return False
    
    try:
        box = el.bounding_box()
        if not box:
            log("SLIDER", "PyAutoGUI: No bounding box")
            return False
        
        # Calculate drag distance
        track = None
        if found_frame:
            for track_sel in ['#nc_1__scale_text', '.nc_scale', '#nc_1_n1t',
                              '#risk_slider_container .nc_scale',
                              '#risk_slider_container .scale_text',
                              '.nc_scale', '.scale_text']:
                try:
                    track = found_frame.query_selector(track_sel)
                    if track:
                        track_box = track.bounding_box()
                        if track_box:
                            drag_dist = track_box['width'] - box['width']
                            break
                except:
                    pass
        
        if track is None:
            drag_dist = 300
        
        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2
        end_x = start_x + drag_dist
        
        log("SLIDER", f"PyAutoGUI: Dragging from ({start_x:.0f},{start_y:.0f}) to ({end_x:.0f},{start_y:.0f})")
        
        # Move and drag
        pyautogui.moveTo(start_x, start_y, duration=0.5)
        pyautogui.mouseDown()
        pyautogui.moveTo(end_x, start_y, duration=1.0)
        pyautogui.mouseUp()
        time.sleep(2)
        
        # Check if solved
        el2, _, _ = find_slider_handle(page, found_frame)
        if not el2:
            log("SLIDER", "PyAutoGUI: Slider solved!")
            return True
        else:
            log("SLIDER", "PyAutoGUI: Slider still visible")
            return False
            
    except Exception as e:
        log("SLIDER", f"PyAutoGUI: Error - {e}")
        return False

def solve_slider_pynput(page, frame=None):
    """Solve slider using pynput."""
    if not PYNPUT_AVAILABLE:
        log("SLIDER", "pynput not available")
        return False
    
    log("SLIDER", "Attempting pynput solver...")
    
    from pynput.mouse import Controller, Button
    
    mouse = Controller()
    
    el, found_frame, sel = find_slider_handle(page, frame)
    if not el:
        log("SLIDER", "pynput: No slider handle found")
        return False
    
    try:
        box = el.bounding_box()
        if not box:
            log("SLIDER", "pynput: No bounding box")
            return False
        
        # Calculate drag distance
        drag_dist = 300  # Default
        if found_frame:
            for track_sel in ['#nc_1__scale_text', '.nc_scale',
                              '#risk_slider_container .nc_scale',
                              '#risk_slider_container .scale_text']:
                try:
                    track = found_frame.query_selector(track_sel)
                    if track:
                        track_box = track.bounding_box()
                        if track_box:
                            drag_dist = track_box['width'] - box['width']
                            break
                except:
                    pass
        
        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2
        
        log("SLIDER", f"pynput: Dragging from ({start_x:.0f},{start_y:.0f}) for {drag_dist:.0f}px")
        
        # Move and drag
        mouse.position = (start_x, start_y)
        mouse.press(Button.left)
        mouse.move(drag_dist, 0)  # Move right
        mouse.release(Button.left)
        time.sleep(2)
        
        # Check if solved
        el2, _, _ = find_slider_handle(page, found_frame)
        if not el2:
            log("SLIDER", "pynput: Slider solved!")
            return True
        else:
            log("SLIDER", "pynput: Slider still visible")
            return False
            
    except Exception as e:
        log("SLIDER", f"pynput: Error - {e}")
        return False

def solve_slider_uinput(page, frame=None):
    """Solve slider using uinput (Linux only)."""
    if not UINPUT_AVAILABLE or platform.system() != 'Linux':
        log("SLIDER", "uinput not available or not on Linux")
        return False
    
    log("SLIDER", "Attempting uinput solver...")
    
    import uinput
    
    el, found_frame, sel = find_slider_handle(page, frame)
    if not el:
        log("SLIDER", "uinput: No slider handle found")
        return False
    
    try:
        box = el.bounding_box()
        if not box:
            log("SLIDER", "uinput: No bounding box")
            return False
        
        # Create virtual mouse
        with uinput.Device([
            uinput.ABS_X + (0, 65535),
            uinput.ABS_Y + (0, 65535),
            uinput.BTN_LEFT,
            uinput.REL_X,
            uinput.REL_Y
        ]) as device:
            start_x = int(box['x'] + box['width'] / 2)
            start_y = int(box['y'] + box['height'] / 2)
            drag_dist = 300
            
            # Move to position (absolute)
            device.emit_click(uinput.ABS_X, start_x)
            device.emit_click(uinput.ABS_Y, start_y)
            
            # Press mouse button
            device.emit_click(uinput.BTN_LEFT)
            time.sleep(0.1)
            
            # Drag
            steps = 20
            for i in range(1, steps + 1):
                move_dist = int(drag_dist * i / steps)
                device.emit(uinput.REL_X, move_dist)
                time.sleep(0.05)
            
            # Release
            device.emit_click(uinput.BTN_LEFT)
            time.sleep(2)
        
        # Check if solved
        el2, _, _ = find_slider_handle(page, found_frame)
        if not el2:
            log("SLIDER", "uinput: Slider solved!")
            return True
        else:
            log("SLIDER", "uinput: Slider still visible")
            return False
            
    except Exception as e:
        log("SLIDER", f"uinput: Error - {e}")
        return False

def solve_baxia_slider_dynamic(page, frame=None, headless=False):
    """
    Dynamic slider solver - tries all available methods in order.
    Returns: True if solved, False if failed, "SLIDER" if needs manual
    """
    log("SLIDER", "=" * 50)
    log("SLIDER", "DYNAMIC SLIDER SOLVER - AlibabaCloud")
    log("SLIDER", "=" * 50)
    
    # Define solving methods in priority order
    methods = []
    
    # Always try Playwright first (built-in, no dependencies)
    methods.append(("Playwright Mouse", solve_slider_playwright))
    
    # Add OS-specific methods
    if platform.system() == 'Windows':
        if PYAUTOGUI_AVAILABLE:
            methods.append(("PyAutoGUI", solve_slider_pyautogui))
        if PYNPUT_AVAILABLE:
            methods.append(("pynput", solve_slider_pynput))
    elif platform.system() == 'Linux':
        if UINPUT_AVAILABLE:
            methods.append(("uinput", solve_slider_uinput))
        if PYAUTOGUI_AVAILABLE:
            methods.append(("PyAutoGUI", solve_slider_pyautogui))
        if PYNPUT_AVAILABLE:
            methods.append(("pynput", solve_slider_pynput))
    
    log("SLIDER", f"OS: {platform.system()}")
    log("SLIDER", f"Available methods: {[name for name, _ in methods]}")
    
    # Try each method
    for method_name, solver_func in methods:
        log("SLIDER", f"Trying {method_name}...")
        try:
            if solver_func(page, frame):
                log("SLIDER", f"SUCCESS with {method_name}!")
                return True
        except Exception as e:
            log("SLIDER", f"{method_name} failed: {e}")
        
        time.sleep(1)  # Brief pause between attempts
    
    # If headless and no methods worked
    if headless:
        log("SLIDER", "No automatic solver available in headless mode")
        return "SLIDER"
    
    # Manual fallback
    log("SLIDER", "All automatic methods failed - manual solve required")
    return False


def handle_captcha(page, frame, headless=True, timeout=120):
    """Handle various CAPTCHA types: slider, press-and-hold, nested iframe.
    Returns: True if solved/passed, False if blocked, "SLIDER" if can't solve."""
    start = time.time()
    while time.time() - start < timeout:
        # Check 1: Slider CAPTCHA (#risk_slider_container)
        if frame:
            slider = frame.query_selector("#risk_slider_container")
            if slider:
                try:
                    if slider.is_visible():
                        box = slider.bounding_box()
                        if box and box['width'] > 50 and box['height'] > 20:
                            log("CAPTCHA", f"Slider detected ({box['width']:.0f}x{box['height']:.0f})")
                            screenshot(page, "captcha_slider.png")
                            
                            # Auto-slider DISABLED — always go to manual path for bug testing
                            # if AUTO_CAPTCHA and solve_baxia_slider_dynamic(page, frame, headless):
                            #     log("CAPTCHA", "Slider solved automatically!")
                            #     return True

                            if headless:
                                return "SLIDER"
                            else:
                                log("CAPTCHA", ">>> SLIDER CAPTCHA DETECTED! <<<")
                                log("CAPTCHA", "Automation PAUSED — drag slider manually in browser")
                                log("CAPTCHA", "Script berhenti total. Tidak ada DOM query.")
                                log("CAPTCHA", "")
                                try:
                                    input("  [Drag slider di browser, lalu tekan Enter...] ")
                                except (EOFError, KeyboardInterrupt):
                                    pass
                                # Grace period: cek 5 detik setelah Enter
                                for g in range(5):
                                    time.sleep(1)
                                    if _captcha_solved(page, frame):
                                        log("CAPTCHA", "Slider solved!")
                                        return True
                                log("CAPTCHA", "Slider still visible")
                                return "SLIDER"
                except:
                    pass

        # Check 2: Press-and-Hold CAPTCHA (hsprotect iframe)
        for f in page.frames:
            furl = (f.url or "").lower()
            if "hsprotect" in furl or "fpt.live" in furl:
                try:
                    hold_btn = f.query_selector(
                        "button:has-text('Press'), [role='button']:has-text('Press'), "
                        "button:has-text('hold'), [role='button']:has-text('hold')"
                    )
                    if hold_btn:
                        box = hold_btn.bounding_box()
                        if box and box['width'] > 0:
                            log("CAPTCHA", f"Press-and-Hold button found ({box['width']:.0f}x{box['height']:.0f})")
                            screenshot(page, "captcha_hold.png")
                            if headless:
                                return "HOLD"
                            else:
                                log("CAPTCHA", ">>> PRESS AND HOLD BUTTON IN BROWSER! <<<")
                                # Auto-solve is DISABLED
                                log("CAPTCHA", "Press-and-hold auto-solve is DISABLED — manual solve required")
                except:
                    pass

        # Check 3: Main page press-and-hold (not in iframe)
        try:
            hold_btn = page.query_selector(
                "button:has-text('Press'), [role='button']:has-text('Press'), "
                "button:has-text('hold'), [role='button']:has-text('hold')"
            )
            if hold_btn:
                box = hold_btn.bounding_box()
                if box and box['width'] > 0:
                    log("CAPTCHA", "Press-and-Hold on main page")
                    if headless:
                        return "HOLD"
                    # Auto-solve DISABLED — manual only
                    # elif AUTO_CAPTCHA:
                    #     page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                    #     page.mouse.down()
                    #     time.sleep(5)
                    #     page.mouse.up()
                    #     time.sleep(3)
                    #     if _captcha_solved(page, frame):
                    #         return True

                    # Manual solve path for Press-and-Hold
                    log("CAPTCHA", ">>> PRESS-AND-HOLD CAPTCHA DETECTED! <<<")
                    log("CAPTCHA", "Automation PAUSED — hold button manually in browser")
                    log("CAPTCHA", "")
                    try:
                        input("  [Hold button di browser, lalu tekan Enter...] ")
                    except (EOFError, KeyboardInterrupt):
                        pass
                    for g in range(5):
                        time.sleep(1)
                        if _captcha_solved(page, frame):
                            log("CAPTCHA", "Hold CAPTCHA solved!")
                            return True
                    log("CAPTCHA", "Hold CAPTCHA still visible")
                    return "HOLD"
        except:
            pass

        # Check 4: Nested iframe baxia-dialog (login/OTP CAPTCHA — slider puzzle)
        # Baxia can appear in the passport iframe OR in a nested iframe inside it
        baxia_frames = []
        if frame:
            baxia_frames.append(frame)
        # Also check nested iframes inside passport frame
        if frame:
            try:
                nested_iframes = frame.query_selector_all("iframe")
                for ni in nested_iframes:
                    try:
                        ni_frame = ni.content_frame()
                        if ni_frame:
                            baxia_frames.append(ni_frame)
                    except:
                        pass
            except:
                pass

        for bf in baxia_frames:
            try:
                baxia = bf.query_selector("#baxia-dialog-content, .baxia-dialog, .nc_iconfont, #nc_1_wrapper, .nc_wrapper")
                if baxia:
                    try:
                        is_vis = baxia.is_visible()
                    except:
                        is_vis = True
                    if is_vis:
                        log("CAPTCHA", "Baxia dialog detected")
                        screenshot(page, "captcha_baxia.png")
                        
                        # Auto-slider DISABLED — always go to manual path for bug testing
                        # if AUTO_CAPTCHA and solve_baxia_slider_dynamic(page, bf, headless):
                        #     log("CAPTCHA", "Baxia slider solved automatically!")
                        #     return True
                        
                        if headless:
                            return "BAXIA"
                        else:
                            log("CAPTCHA", ">>> SOLVE BAXIA SLIDER IN BROWSER! <<<")
                            log("CAPTCHA", "Automation PAUSED — drag slider manually in browser")
                            log("CAPTCHA", "")
                            try:
                                input("  [Drag slider baxia di browser, lalu tekan Enter...] ")
                            except (EOFError, KeyboardInterrupt):
                                pass
                            for g in range(5):
                                time.sleep(1)
                                if _captcha_solved(page, frame):
                                    log("CAPTCHA", "Baxia solved!")
                                    return True
                            log("CAPTCHA", "Baxia still visible")
                            return "BAXIA"
            except:
                pass

        time.sleep(2)

    return True  # No CAPTCHA found — proceed


def _captcha_solved(page, frame):
    """Check if CAPTCHA was solved (page advanced or CAPTCHA disappeared)."""
    # Collect all frames to check: main page + passport frame + nested iframes
    frames_to_check = [page]
    if frame:
        frames_to_check.append(frame)
        # Check nested iframes inside passport frame
        try:
            for ni in frame.query_selector_all("iframe"):
                try:
                    child = ni.content_frame()
                    if child:
                        frames_to_check.append(child)
                except:
                    pass
        except:
            pass
    # Also check all page frames (covers baxia-dialog iframe)
    frames_to_check.extend(page.frames)
    
    for f in frames_to_check:
        try:
            # Check if tabs appeared (page advanced)
            tabs = f.query_selector_all("li[role='tab']")
            if len(tabs) > 0:
                return True
            # Check if slider disappeared
            slider = f.query_selector("#risk_slider_container")
            if slider:
                try:
                    if not slider.is_visible():
                        time.sleep(1)
                        tabs = f.query_selector_all("li[role='tab']")
                        if len(tabs) > 0:
                            return True
                        # Slider hidden = likely solved
                        return True
                except:
                    pass
        except:
            pass
    # Check URL change
    url = page.url.lower()
    if "login" in url or "console" in url or "dashboard" in url:
        return True
    return False


# ════════════════════════════════════════════════════
# ─ Registration ────────────────────────────────────
# ════════════════════════════════════════════════════

def generate_password():
    """Alibaba password: Aa1 + 15 random + _ = 19 chars."""
    chars = string.ascii_letters + string.digits
    return "Aa1" + ''.join(random.choices(chars, k=15)) + "_"


def register(page, email, password, headless=True):
    """Register new Alibaba Cloud account via Model Studio entry point.

    Anti-CAPTCHA flow: Model Studio → Log In → Sign Up Now (with oauth_callback)
    → passport iframe. This route avoids triggering the Baxia slider that
    appears when accessing the register page directly.

    Returns True/False/"CAPTCHA".
    """
    # ─ Anti-CAPTCHA entry: go through Model Studio → Log In → Sign Up ─
    log("REG", "Step 0: Opening Model Studio (anti-CAPTCHA entry)...")
    try:
        page.goto("https://modelstudio.console.alibabacloud.com/",
                   timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        log("REG", f"Model Studio load warning: {e}")
    human_pause_long()  # was time.sleep(5)

    # Step 1: Click "Log In" button (div.unlogin__dDTzS)
    log("REG", "Step 1: Clicking 'Log In' button...")
    login_btn_clicked = False
    for attempt in range(15):
        try:
            # Selector: div.unlogin__dDTzS contains "Log In" text
            btn = page.query_selector("div.unlogin__dDTzS")
            if btn and btn.is_visible():
                btn.click()
                login_btn_clicked = True
                log("REG", f"Clicked 'Log In' (attempt {attempt+1})")
                break
        except:
            pass
        # Fallback: try by text
        try:
            el = page.get_by_text("Log In", exact=False).first
            if el and el.is_visible():
                el.click()
                login_btn_clicked = True
                log("REG", f"Clicked 'Log In' via text (attempt {attempt+1})")
                break
        except:
            pass
        human_delay(1.0, 2.5)  # was time.sleep(2) — retry loop

    if not login_btn_clicked:
        log("REG", "WARNING: 'Log In' button not found — trying direct register URL")
        screenshot(page, "reg_00a_no_login_btn.png")
        try:
            page.goto(REGISTER_URL, timeout=120000, wait_until="domcontentloaded")
        except:
            pass
        human_pause_long()  # was time.sleep(5)
    else:
        # Step 2: Wait for "Sign Up Now" link to appear (after clicking Log In,
        # a login dialog opens with a "Sign Up Now" link that has oauth_callback)
        log("REG", "Step 2: Looking for 'Sign Up Now' link...")
        signup_url_found = None
        for attempt in range(20):
            try:
                # The link href contains register/intl_register.htm with oauth_callback
                link = page.query_selector("a[href*='register/intl_register.htm']")
                if link and link.is_visible():
                    signup_url_found = link.get_attribute("href")
                    log("REG", f"Found Sign Up link (attempt {attempt+1})")
                    link.click()
                    break
            except:
                pass
            # Fallback: search by text
            try:
                el = page.get_by_text("Sign Up", exact=False).first
                if el and el.is_visible():
                    href = el.evaluate("e => e.href || e.getAttribute('href') || ''")
                    if href and "register" in href:
                        signup_url_found = href
                    el.click()
                    log("REG", f"Clicked 'Sign Up' via text (attempt {attempt+1})")
                    break
            except:
                pass
            human_delay(1.0, 2.5)  # was time.sleep(2) — retry loop

        if signup_url_found:
            log("REG", f"Sign Up URL: {signup_url_found[:120]}")

        # Wait for register page to load (may auto-navigate after click)
        human_pause_long()  # was time.sleep(5)

        # If page didn't auto-navigate, goto the signup URL directly
        if "register" not in page.url.lower() and signup_url_found:
            log("REG", "Auto-navigate didn't happen — opening signup URL directly...")
            try:
                page.goto(signup_url_found, timeout=120000, wait_until="domcontentloaded")
            except:
                pass
            human_pause_long()  # was time.sleep(5)
        elif "register" not in page.url.lower() and not signup_url_found:
            log("REG", "No signup link found — trying direct register URL...")
            try:
                page.goto(REGISTER_URL, timeout=120000, wait_until="domcontentloaded")
            except:
                pass
            human_pause_long()  # was time.sleep(5)
    screenshot(page, "reg_00_initial.png")

    # Step 3: Wait for passport iframe
    frame = None
    for wait in range(20):
        frame = find_passport_frame(page)
        if frame:
            log("REG", f"Passport frame found ({wait*2}s)")
            break
        try:
            page.wait_for_selector("iframe[src*='passport']", timeout=3000)
        except:
            pass
        if wait == 5:
            log("REG", f"Current URL: {page.url[:100]}")
            screenshot(page, "reg_00b_debug.png")
        human_delay(1.0, 2.5)  # was time.sleep(2) — retry loop

    if not frame:
        log("REG", "ERROR: No passport frame!")
        screenshot(page, "fail_reg.png")
        return False

    # Step 2: Select "Individual Account" + click Next
    log("REG", "Selecting Individual Account...")
    label = None
    for _ in range(15):
        try:
            label = frame.query_selector("label:has-text('Individual')")
            if label and label.is_visible():
                break
        except:
            pass
        human_delay(1.0, 2.5)  # was time.sleep(2) — retry loop
        frame = find_passport_frame(page)
        if not frame:
            break

    if not label:
        log("REG", "ERROR: Individual label not found!")
        screenshot(page, "fail_individual.png")
        return False

    label.click()
    human_delay(0.8, 2.0)  # was time.sleep(2)

    # Click Next — it's an <A> tag with class "entity__btn-next"
    next_link = frame.query_selector(".entity__btn-next") or \
                frame.query_selector("a:has-text('Next')")
    if next_link:
        next_link.click()
        log("REG", "Clicked Next")
    human_pause_long()  # was time.sleep(5)

    # Step 3: Fill email + password form
    log("REG", "Filling registration form...")
    frame = find_passport_frame(page)
    if not frame:
        log("REG", "ERROR: Lost passport frame!")
        return False
    human_pause_medium()  # was time.sleep(3)

    email_field = frame.query_selector("#email") or \
                  frame.query_selector("input[name='email']")
    pw_field = frame.query_selector("#password") or \
               frame.query_selector("input[name='password']")
    confirm_field = frame.query_selector("#confirmPwd") or \
                    frame.query_selector("input[name='confirmPwd']")

    if not email_field or not pw_field:
        log("REG", "ERROR: Form fields not found!")
        screenshot(page, "fail_fields.png")
        return False

    email_field.click()
    human_pause_short()  # was time.sleep(0.3)
    email_field.fill(email)
    human_pause_short()  # was time.sleep(0.5)

    pw_field.click()
    human_pause_short()  # was time.sleep(0.3)
    pw_field.fill(password)
    human_pause_short()  # was time.sleep(0.5)

    if confirm_field:
        confirm_field.click()
        human_pause_short()  # was time.sleep(0.3)
        confirm_field.fill(password)
    human_delay(1.0, 2.5)  # was time.sleep(2)

    pw_val = pw_field.evaluate("el => el.value")
    log("REG", f"Password verify: len={len(pw_val)} match={pw_val == password}")

    # Step 4: Click Sign Up
    signup_btn = None
    for b in frame.query_selector_all("button"):
        if "sign up" in b.inner_text().lower():
            signup_btn = b
            break
    if not signup_btn:
        log("REG", "ERROR: No Sign Up button!")
        return False
    signup_btn.click()
    log("REG", "Clicked Sign Up")
    screenshot(page, "reg_02_after_signup.png")

    # Scroll passport iframe into view so user can see CAPTCHA
    try:
        iframe_el = page.query_selector("iframe[src*='passport']")
        if iframe_el:
            iframe_el.scroll_into_view_if_needed()
            human_scroll_pause()  # was time.sleep(1)
    except:
        pass

    # Step 5: Wait for page advance or CAPTCHA
    for wait in range(30):
        human_delay(1.5, 3.0)  # was time.sleep(2) — polling loop
        frame = find_passport_frame(page)
        if not frame:
            continue

        # Check if page advanced (tabs appeared)
        tabs = frame.query_selector_all("li[role='tab']")
        if len(tabs) > 0:
            log("REG", f"Success! Page advanced ({wait*2}s)")
            return True

        # Check for CAPTCHA
        captcha_result = handle_captcha(page, frame, headless=headless, timeout=10)
        if captcha_result == "SLIDER":
            return "SLIDER"
        elif captcha_result == "HOLD":
            return "HOLD"
        elif captcha_result == "BAXIA":
            return "BAXIA"

        # Check for errors
        try:
            err_el = frame.query_selector("[class*='error'], [class*='alert'], [class*='msg']")
            if err_el and err_el.is_visible():
                err_text = err_el.inner_text().strip()
                if err_text and len(err_text) > 2:
                    log("REG", f"Validation: {err_text[:200]}")
                    if "cannot be used" in err_text.lower() or "another email" in err_text.lower():
                        return "EMAIL_BLOCKED"
        except:
            pass

    log("REG", "Timeout — registration failed")
    return False


# ════════════════════════════════════════════════════
# ─ Email Verification (OTP) ────────────────────────
# ════════════════════════════════════════════════════

def verify_email(page, provider, headless=True):
    """After registration form advances, do email verification step."""
    log("OTP", "Email verification tab...")

    frame = find_passport_frame(page)
    if not frame:
        log("OTP", "ERROR: No passport frame!")
        return False

    # Click email verification tab (usually tab[1])
    tabs = frame.query_selector_all("li[role='tab']")
    if len(tabs) >= 2:
        tabs[1].click()
        log("OTP", "Clicked tab[1] (email mode)")
        human_pause_medium()  # was time.sleep(3)
    else:
        log("OTP", f"WARNING: Only {len(tabs)} tabs")

    # Select Singapore
    frame = find_passport_frame(page)
    selects = frame.query_selector_all("select")
    for sel in selects:
        for opt in sel.query_selector_all("option"):
            if "singapore" in opt.inner_text().lower():
                sel.select_option(value=opt.get_attribute("value"))
                log("OTP", "Selected Singapore")
                break

    # Click Send
    for b in frame.query_selector_all("button, [role='button']"):
        txt = b.inner_text()[:50].lower()
        if "send" in txt and b.is_visible():
            b.click()
            log("OTP", "Clicked Send")
            break
    human_pause_medium()  # was time.sleep(3)

    # Read OTP from provider
    otp = provider.read_otp(timeout=120)
    if not otp:
        log("OTP", "ERROR: No OTP received!")
        return False

    # Fill OTP
    frame = find_passport_frame(page)
    otp_input = frame.query_selector("#emailCaptcha") or \
                frame.query_selector("input[name='emailCaptcha']") or \
                frame.query_selector("input[placeholder*='code']") or \
                frame.query_selector("input[placeholder*='verification']") or \
                frame.query_selector("input[name*='code']")

    if not otp_input:
        all_inputs = frame.query_selector_all("input")
        for inp in all_inputs:
            try:
                if not inp.is_visible():
                    continue
                inp_id = (inp.get_attribute("id") or "").lower()
                inp_name = (inp.get_attribute("name") or "").lower()
                if "email" == inp_id or "email" == inp_name or "country" in inp_id:
                    continue
                if inp.get_attribute("type") == "checkbox":
                    continue
                otp_input = inp
                break
            except:
                pass

    if otp_input:
        otp_input.click()
        human_pause_short()  # was time.sleep(0.3)
        for ch in otp:
            page.keyboard.type(ch, delay=human_type_delay())
        human_pause_short()  # was time.sleep(0.5)
        log("OTP", f"Typed OTP: {otp}")
    else:
        log("OTP", "ERROR: No OTP input field!")
        return False

    # Check agreement checkbox + click final Sign Up (frame may detach on redirect)
    try:
        frame = find_passport_frame(page) or frame
        checkbox = frame.query_selector("input[type='checkbox']")
        if checkbox and not checkbox.is_checked():
            checkbox.click()
    except Exception as e:
        log("OTP", f"Checkbox check skipped: {e}")

    try:
        frame = find_passport_frame(page) or frame
        for b in frame.query_selector_all("button, [role='button']"):
            txt = b.inner_text().lower()
            if "sign up" in txt or "confirm" in txt or "register" in txt:
                b.click()
                log("OTP", "Clicked final Sign Up")
                break
    except Exception as e:
        log("OTP", f"Sign Up click skipped: {e}")
    human_pause_long()  # was time.sleep(8)

    # Check for CAPTCHA after Sign Up (frame may have detached — re-find)
    frame = find_passport_frame(page)
    if frame:
        try:
            captcha_result = handle_captcha(page, frame, headless=headless, timeout=30)
            if captcha_result in ("SLIDER", "HOLD", "BAXIA"):
                return captcha_result
        except Exception as e:
            log("OTP", f"CAPTCHA check skipped: {e}")

    # Check post-register URL
    post_url = page.url
    log("OTP", f"Post-register URL: {post_url}")
    screenshot(page, "otp_02_registered.png")

    parsed = urlparse(post_url)
    path = parsed.path.lower()

    if "register" in path and "success" not in path:
        log("OTP", "Still on register path — waiting for redirect...")
        human_pause_long()  # was time.sleep(10)
        post_url = page.url
        parsed = urlparse(post_url)
        path = parsed.path.lower()
        log("OTP", f"URL after wait: {post_url[:120]}")

    if "login" in path or "success" in path or "dashboard" in path or "console" in path:
        log("OTP", "Registration complete! (redirected)")
        return True

    if "register" in path and "success" not in path:
        log("OTP", "WARNING: Still on register page — checking errors...")
        try:
            frame = find_passport_frame(page)
            if frame:
                err = frame.query_selector("[class*='error'], [class*='alert'], [class*='msg']")
                if err:
                    log("OTP", f"Error: {err.inner_text()[:200]}")
        except:
            pass
        return False

    log("OTP", "Registration complete!")
    return True


# ════════════════════════════════════════════════════
# ─ Login ───────────────────────────────────────────
# ════════════════════════════════════════════════════

def auto_login(page, email, password, timeout=60, headless=True):
    """Login via passport iframe OR main page form. Returns True on success.
    
    Alibaba Cloud login page has evolved:
    - Old: form inside passport iframe (#fm-login-id, #fm-login-password)
    - New: form directly on main page (placeholder="Enter your email", etc.)
    
    This function handles both cases.
    """
    log("LOGIN", f"Attempting login for {email}...")

    # Wait for login page to load
    human_pause_medium()  # was time.sleep(3)

    # Try to find login form — check iframe first, then main page
    frame = None
    for wait in range(15):
        frame = find_login_frame(page)
        if frame:
            break
        human_delay(1.0, 2.5)  # was time.sleep(2) — retry loop

    if not frame:
        log("LOGIN", "ERROR: No login form found (iframe or main page)!")
        log("LOGIN", f"Current URL: {page.url[:100]}")
        screenshot(page, "login_no_form.png")
        return False

    is_main_page = (frame == page)
    log("LOGIN", f"Found login form in: {'main page' if is_main_page else 'iframe'}")
    if not is_main_page:
        log("LOGIN", f"  iframe URL: {frame.url[:80]}")
    human_delay(0.8, 2.0)  # was time.sleep(2)

    # Find login fields — try multiple selector strategies
    login_id = None
    pw_field = None
    submit_btn = None

    # Selector list: new style first, then old style
    email_selectors = [
        "input[placeholder*='Enter your email']",
        "input[placeholder*='email' i]",
        "input[placeholder*='account' i]",
        "#fm-login-id",
        "input[name='loginId']",
        "input[name='account']",
        "input[type='text']",
    ]
    pw_selectors = [
        "input[placeholder*='Enter your password']",
        "input[placeholder*='password' i]",
        "#fm-login-password",
        "input[name='password']",
        "input[type='password']",
    ]
    submit_selectors = [
        "#fm-login-submit",
        "button[type='submit']",
        "button:has-text('Sign In')",
        "button:has-text('Sign in')",
        "button:has-text('Login')",
        "input[type='submit']",
        "[role='button']:has-text('Sign In')",
    ]

    for attempt in range(10):
        try:
            # Find email field
            for sel in email_selectors:
                login_id = frame.query_selector(sel)
                if login_id:
                    try:
                        if login_id.is_visible():
                            break
                    except:
                        break
                login_id = None

            # Find password field
            for sel in pw_selectors:
                pw_field = frame.query_selector(sel)
                if pw_field:
                    try:
                        if pw_field.is_visible():
                            break
                    except:
                        break
                pw_field = None

            if login_id and pw_field:
                break
        except:
            pass
        human_delay(1.0, 2.5)  # was time.sleep(2) — retry loop
        # Re-find frame (it may have loaded)
        frame = find_login_frame(page) or frame

    if not login_id or not pw_field:
        log("LOGIN", "ERROR: Login fields not found!")
        screenshot(page, "login_no_fields.png")
        return False

    # Fill email
    login_id.click()
    human_pause_short()  # was time.sleep(0.3)
    login_id.fill(email)
    human_pause_short()  # was time.sleep(0.5)
    log("LOGIN", f"Email filled: {email}")

    # Fill password
    pw_field.click()
    human_pause_short()  # was time.sleep(0.3)
    pw_field.fill(password)
    human_pause_short()  # was time.sleep(0.5)

    try:
        pw_val = pw_field.evaluate("el => el.value")
        log("LOGIN", f"Password filled: len={len(pw_val)} match={pw_val == password}")
    except:
        log("LOGIN", "Password filled (verify skipped)")

    if DEBUG:
        screenshot(page, "login_01_before_submit.png")

    # Find and click submit button
    for sel in submit_selectors:
        try:
            submit_btn = frame.query_selector(sel)
            if submit_btn:
                try:
                    if submit_btn.is_visible():
                        break
                except:
                    break
            submit_btn = None
        except:
            pass

    if submit_btn:
        submit_btn.click()
        log("LOGIN", "Clicked Sign In")
    else:
        # Try clicking by text
        try:
            btn = frame.query_selector("button:has-text('Sign In')") or \
                  frame.query_selector("button:has-text('Sign in')") or \
                  frame.query_selector("button:has-text('Login')")
            if btn:
                btn.click()
                log("LOGIN", "Clicked Sign In (text search)")
            else:
                page.keyboard.press("Enter")
                log("LOGIN", "Pressed Enter (no button found)")
        except:
            page.keyboard.press("Enter")
            log("LOGIN", "Pressed Enter (fallback)")

    # Wait for redirect or CAPTCHA
    start = time.time()
    while time.time() - start < timeout:
        human_delay(1.5, 3.0)  # was time.sleep(2) — polling loop
        url = page.url.lower()
        if "login" not in url and "signin" not in url and "passport" not in url:
            log("LOGIN", f"SUCCESS! URL: {page.url[:80]}")
            return True

        # Check for CAPTCHA
        frame = find_login_frame(page)
        if frame:
            err = frame.query_selector(".form-error, .notice-error, [class*='error']")
            if err and err.is_visible():
                err_text = err.inner_text().strip()
                if err_text and len(err_text) > 2:
                    log("LOGIN", f"Error: {err_text[:200]}")
                    return False

            captcha_result = handle_captcha(page, frame, headless=headless, timeout=10)
            if captcha_result in ("SLIDER", "HOLD", "BAXIA"):
                if not headless:
                    log("LOGIN", ">>> SOLVE CAPTCHA IN BROWSER! <<<")
                    for sw in range(60):
                        human_delay(1.0, 2.5)  # was time.sleep(2) — CAPTCHA wait
                        url = page.url.lower()
                        if "login" not in url and "signin" not in url and "passport" not in url:
                            log("LOGIN", f"SUCCESS after CAPTCHA! URL: {page.url[:80]}")
                            return True
                        if sw % 5 == 0 and sw > 0:
                            log("LOGIN", f"Waiting... ({sw*2}s)")
                    return False
                return False

    log("LOGIN", f"TIMEOUT ({timeout}s)")
    return False


# ════════════════════════════════════════════════════
# ─ API Key Creation ────────────────────────────────
# ════════════════════════════════════════════════════

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


def create_api_key(page, timeout=60):
    """Navigate to Model Studio, click Create API Key, return key string."""
    log("API", "Navigating to Model Studio API Key page...")
    try:
        page.goto(MODELSTUDIO_URL, timeout=30000, wait_until="commit")
    except:
        pass
    human_pause_long()  # was time.sleep(8)
    log("API", f"URL: {page.url[:100]}")

    if "login" in page.url.lower() or "signin" in page.url.lower() or "passport" in page.url.lower():
        log("API", "Redirected to login — need to login first")
        return "NEED_LOGIN"

    # Wait for SPA to render
    log("API", "Waiting for SPA to render...")
    for wait in range(30):
        human_delay(1.5, 3.0)  # was time.sleep(2) — polling loop
        try:
            has_content = page.evaluate("""
                () => {
                    const body = document.body;
                    if (!body) return false;
                    const text = body.innerText || '';
                    if (text.trim().length < 50) return false;
                    if text.includes('API') || text.includes('Key') || text.includes('Create') ||
                        text.includes('Dashboard') || text.includes('Model') || text.includes('Sign In')) return true;
                    return false;
                }
            """)
            if has_content:
                log("API", f"SPA rendered ({wait*2}s)")
                break
        except:
            pass
        if wait % 5 == 0:
            log("API", f"Still loading... ({wait*2}s)")

    screenshot(page, "api_01_loaded.png")

    # Wait for initializing to finish
    log("API", "Waiting for model service init...")
    for wait in range(45):
        human_delay(1.5, 3.0)  # was time.sleep(2) — polling loop
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
                log("API", f"Model service ready ({wait*2}s)")
                break
        except:
            pass

    screenshot(page, "api_02_after_init.png")

    # Check if this is actually a login page (Model Studio SPA may redirect to login
    # without changing URL — the page shows "Sign In" form instead of Model Studio)
    lf = find_login_frame(page)
    if lf:
        has_email = lf.query_selector("input[placeholder*='email' i]") or \
                    lf.query_selector("#fm-login-id") or \
                    lf.query_selector("input[name='loginId']")
        has_pw = lf.query_selector("input[type='password']")
        if has_email and has_pw:
            log("API", "Login form detected on Model Studio page — need to login first")
            return "NEED_LOGIN"

    # Also check page text for login indicators
    try:
        page_text = page.evaluate("() => (document.body && document.body.innerText) || ''")
        if "Sign In" in page_text and "Enter your email" in page_text:
            log("API", "Login page detected via text content — need to login first")
            return "NEED_LOGIN"
    except:
        pass

    # Click "API Key" in sidebar (SPA needs navigation to API Key tab)
    log("API", "Clicking 'API Key' in sidebar...")
    api_key_tab_clicked = False
    for attempt in range(10):
        try:
            # Try clicking the "API Key" menu item in sidebar
            clicked = page.evaluate("""
                () => {
                    const els = document.querySelectorAll('a, span, div, li, [role="menuitem"], [role="tab"]');
                    for (const el of els) {
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (txt === 'API Key' || txt === 'API-key' || txt === 'apikey') {
                            el.click();
                            return txt;
                        }
                    }
                    return null;
                }
            """)
            if clicked:
                log("API", f"Clicked sidebar: '{clicked}'")
                api_key_tab_clicked = True
                break
        except:
            pass
        human_scroll_pause()  # was time.sleep(1)

    if not api_key_tab_clicked:
        log("API", "Sidebar 'API Key' not found — trying URL hash navigation...")
        try:
            page.evaluate("window.location.hash = '#/api-key'")
        except:
            pass

    human_pause_long()  # was time.sleep(5)
    screenshot(page, "api_03_after_sidebar.png")

    # Check if redirected to login during sidebar navigation
    try:
        page_text = page.evaluate("() => (document.body && document.body.innerText) || ''")
        if "Sign In" in page_text and "Enter your email" in page_text:
            log("API", "Login page after sidebar click — need to login first")
            return "NEED_LOGIN"
    except:
        pass

    # Find and click "Create API Key"
    log("API", "Looking for Create API Key button...")
    create_clicked = False
    for wait in range(timeout):
        try:
            btn = page.evaluate("""
                () => {
                    function searchAll(root) {
                        const els = root.querySelectorAll('button, span, a, div, [role="button"], .next-btn, .ant-btn');
                        for (const el of els) {
                            const txt = (el.innerText || el.textContent || '').trim();
                            if ((txt.toLowerCase().includes('create') && txt.toLowerCase().includes('api')) ||
                                txt.toLowerCase().includes('create api key')) {
                                el.click();
                                return txt;
                            }
                        }
                        return null;
                    }
                    return searchAll(document);
                }
            """)
            if btn:
                log("API", f"Clicked: '{btn}'")
                create_clicked = True
                break
        except:
            pass

        if wait == 5:
            try:
                el = page.get_by_text("Create API Key", exact=False).first
                if el:
                    el.click()
                    log("API", "Clicked 'Create API Key' via Playwright")
                    create_clicked = True
                    break
            except:
                pass

        human_scroll_pause()  # was time.sleep(1)

    if not create_clicked:
        log("API", "'Create API Key' button not found — checking existing key...")
        existing = scan_for_api_key(page)
        if existing:
            log("API", "Found existing API key")
            return existing
        screenshot(page, "api_03_no_create_debug.png")
        return None

    # Wait for popup + click OK
    human_pause_medium()  # was time.sleep(3)
    screenshot(page, "api_04_popup.png")

    log("API", "Looking for OK button in popup...")
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
                log("API", f"Clicked '{ok}' in popup")
                ok_clicked = True
                break
        except:
            pass
        human_scroll_pause()  # was time.sleep(1)

    if not ok_clicked:
        log("API", "OK button not found — trying Enter...")
        try:
            page.keyboard.press("Enter")
        except:
            pass

    # Wait for API key to appear
    log("API", "Waiting for API key to appear...")
    screenshot(page, "api_05_waiting.png")

    for wait in range(30):
        human_delay(1.5, 3.0)  # was time.sleep(2) — polling loop
        found = scan_for_api_key(page)
        if found:
            log("API", "API Key found!")
            screenshot(page, "api_06_success.png")
            return found
        if wait % 5 == 0:
            log("API", f"Waiting... ({wait*2}s)")
            if DEBUG:
                screenshot(page, f"api_05_waiting_{wait*2}s.png")

    log("API", "API key not found after 60s")
    screenshot(page, "api_07_timeout.png")
    return None


# ════════════════════════════════════════════════════
# ─ Supply Userinfo (Security Info) ──────────────────
# ════════════════════════════════════════════════════

def handle_supply_userinfo(page, headless=False):
    """Handle the supply_userinfo security page after registration/login.

    Alibaba may require security questions or phone verification before
    allowing access to the console. We try to fill and skip these.
    """
    log("SEC", "Handling supply_userinfo page...")
    screenshot(page, "supply_userinfo_01.png")
    human_pause_medium()  # was time.sleep(3)

    # Wait for page to fully load
    for _ in range(10):
        human_delay(1.0, 2.5)  # was time.sleep(2) — retry loop
        current_url = page.url.lower()
        if "supply_userinfo" not in current_url:
            log("SEC", f"Page left supply_userinfo → {current_url[:80]}")
            return True
        break

    # Check for passport iframe (security form may be inside)
    frame = find_passport_frame(page)

    # Strategy 1: Look for "Skip" or "Later" button
    skip_selectors = [
        "text=Skip",
        "text=Later",
        "text=Not now",
        "text=Continue",
        "text=Next",
        "a:has-text('Skip')",
        "a:has-text('Later')",
        "a:has-text('Continue')",
        "button:has-text('Skip')",
        "button:has-text('Later')",
        "button:has-text('Continue')",
        "[class*='skip']",
        "[class*='later']",
    ]

    search_frames = [page]
    if frame:
        search_frames.append(frame)

    for sf in search_frames:
        try:
            for sel in skip_selectors:
                btn = sf.query_selector(sel)
                if btn and btn.is_visible():
                    log("SEC", f"Found skip button: {btn.inner_text().strip()[:30]}")
                    btn.click()
                    human_pause_medium()  # was time.sleep(3)
                    if "supply_userinfo" not in page.url.lower():
                        log("SEC", "Skipped security info!")
                        return True
                    log("SEC", "Skip didn't work, trying next...")
        except:
            pass

    # Strategy 2: Fill security questions if present
    security_questions = [
        "What was the name of your first pet?",
        "What is your favorite book?",
        "What was the make of your first car?",
        "What is your mother's maiden name?",
        "What was the name of your first school?",
        "In what city were you born?",
    ]

    # Check for security question dropdowns or inputs
    for sf in search_frames:
        try:
            # Look for dropdown selects (security question selection)
            selects = sf.query_selector_all("select")
            if selects:
                log("SEC", f"Found {len(selects)} select dropdowns")
                for i, sel in enumerate(selects):
                    try:
                        # Select first option that's not empty
                        options = sel.query_selector_all("option")
                        for opt in options[1:]:  # Skip first (usually placeholder)
                            val = opt.get_attribute("value") or ""
                            if val:
                                sel.select_option(value=val)
                                log("SEC", f"Selected question {i+1}")
                                break
                    except:
                        pass

                # Fill answer inputs
                answers = ["Buddy", "Dune", "Toyota", "Smith", "Lincoln", "Jakarta"]
                inputs = sf.query_selector_all("input[type='text'], input:not([type])")
                for i, inp in enumerate(inputs):
                    if i < len(answers):
                        try:
                            inp.fill(answers[i])
                            log("SEC", f"Filled answer {i+1}: {answers[i]}")
                        except:
                            pass

                # Click submit
                for b in sf.query_selector_all("button, a[role='button']"):
                    txt = (b.inner_text() or "").strip().lower()
                    if any(w in txt for w in ["submit", "confirm", "save", "ok", "next", "continue"]):
                        log("SEC", f"Clicking: {txt[:30]}")
                        b.click()
                        human_pause_medium()  # was time.sleep(3)
                        if "supply_userinfo" not in page.url.lower():
                            log("SEC", "Security info submitted!")
                            return True
                        break
        except:
            pass

    # Strategy 3: Look for phone verification and try to skip
    for sf in search_frames:
        try:
            # Check if there's a phone number field
            phone_input = sf.query_selector("input[type='tel'], input[name*='phone'], input[id*='phone']")
            if phone_input:
                log("SEC", "Phone verification found — need user input in browser")
                if not headless:
                    log("SEC", ">>> FILL PHONE OR SKIP IN BROWSER! <<<")
                    for w in range(30):
                        human_delay(1.0, 2.5)  # was time.sleep(2) — manual wait loop
                        if "supply_userinfo" not in page.url.lower():
                            log("SEC", "Security page left!")
                            return True
                        if w % 5 == 0 and w > 0:
                            log("SEC", f"Waiting... ({w*2}s)")
        except:
            pass

    # Strategy 4: Check if this is actually a login page disguised as supply_userinfo
    # Sometimes Alibaba redirects to supply_userinfo URL but shows a login form
    # because the session has expired
    login_frame = find_login_frame(page)
    if login_frame:
        has_email = login_frame.query_selector("input[placeholder*='email' i]") or \
                    login_frame.query_selector("#fm-login-id") or \
                    login_frame.query_selector("input[name='loginId']")
        has_pw = login_frame.query_selector("input[type='password']")
        if has_email and has_pw:
            log("SEC", "Login form detected on supply_userinfo page — session expired!")
            screenshot(page, "supply_userinfo_login_form.png")
            return False

    # Strategy 5: Just wait and check if page auto-advances
    log("SEC", "Waiting for page to advance...")
    for w in range(15):
        human_delay(1.0, 2.5)  # was time.sleep(2) — polling loop
        if "supply_userinfo" not in page.url.lower():
            log("SEC", "Security page auto-advanced!")
            return True

    log("SEC", "Could not bypass supply_userinfo — manual intervention needed")
    screenshot(page, "supply_userinfo_stuck.png")
    return False


# ════════════════════════════════════════════════════
# ─ Results ─────────────────────────────────────────
# ════════════════════════════════════════════════════

def load_results(results_file=None):
    """Load results from JSON file. Uses provider-specific file if specified."""
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
    file_to_save = results_file or RESULTS_FILE
    with open(file_to_save, "w") as f:
        json.dump(results, f, indent=2)


# ════════════════════════════════════════════════════
# ─ Main ────────────────────────────────────────────
# ════════════════════════════════════════════════════

def main():
    global BROWSER  # line 2775 reassigns BROWSER on Firefox fallback — must declare global
    # Determine provider first to set results file
    provider_choice = None
    if "--provider" in sys.argv:
        idx = sys.argv.index("--provider")
        if idx + 1 < len(sys.argv):
            provider_choice = sys.argv[idx + 1]
    
    # Set provider-specific results file
    results_file = PROVIDER_RESULTS.get(provider_choice, RESULTS_FILE) if provider_choice else RESULTS_FILE
    
    results = load_results(results_file)

    if "--menu" in sys.argv or (provider_choice is None and sys.stdin.isatty()):
        provider = show_menu()
    else:
        provider = get_provider(provider_choice)

    # Parse Gmail credentials if using GmailDotTrickProvider
    if provider_choice == "gmail":
        gmail_user = None
        app_pass = None
        if "--gmail" in sys.argv:
            idx = sys.argv.index("--gmail")
            if idx + 1 < len(sys.argv):
                gmail_user = sys.argv[idx + 1]
        if "--apppass" in sys.argv:
            idx = sys.argv.index("--apppass")
            if idx + 1 < len(sys.argv):
                app_pass = sys.argv[idx + 1]
        
        if gmail_user and app_pass:
            provider.configure(gmail_user, app_pass)
            log("CONFIG", f"Gmail credentials configured: {gmail_user}")
        else:
            log("ERROR", "Gmail provider requires --gmail and --apppass arguments")
            print("Usage: python farm_headless.py --provider gmail --gmail user@gmail.com --apppass '**** **** **** ****'")
            return

    headless = not SHOW  # --show = visible browser

    print()
    print(f"  ===========================================")
    print(f"  | ALIBABA CLOUD FARM - MULTI-PROVIDER     |")
    print(f"  ===========================================")
    print(f"  Provider:  {provider.__class__.__name__}")
    print(f"  Results:   {results_file}")
    print(f"  Existing:  {len(results)} accounts")
    print(f"  Browser:   {BROWSER} ({'visible' if SHOW else 'headless'})")
    print(f"  Auto-CAPTCHA: {'ON' if AUTO_CAPTCHA else 'OFF'}")
    print(f"  Debug:     {'ON' if DEBUG else 'OFF'}")
    print(f"  ===========================================")
    print()

    with sync_playwright() as p:
        # ── Browser engine dispatch ──
        # Each engine has different capabilities and anti-detection needs.
        # Camoufox has built-in fingerprint spoofing — don't override UA/WebGL.
        # playwright-stealth only works on Chromium — skip for Firefox/WebKit/Camoufox.
        # Firefox/WebKit use their own UA — don't force Chrome UA.
        launch_common_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        proxy_arg = {"server": PROXY} if PROXY else None
        if proxy_arg:
            log("MAIN", f"Using proxy: {PROXY}")

        # Flags to control context setup per-engine
        use_chrome_ua = True       # Force Chrome 130 UA (Chromium-based only)
        use_stealth = True          # playwright-stealth (Chromium only)
        use_webgl_spoof = True      # WebGL fingerprint override (Chromium only)
        use_manual_fingerprint = True  # UA + viewport + timezone override

        if BROWSER == "firefox":
            browser = p.firefox.launch(headless=headless, proxy=proxy_arg)
            use_chrome_ua = False
            use_stealth = False
            use_webgl_spoof = False
            log("BROWSER", "Firefox engine (native fingerprint)")
        elif BROWSER == "webkit":
            browser = p.webkit.launch(headless=headless, proxy=proxy_arg)
            use_chrome_ua = False
            use_stealth = False
            use_webgl_spoof = False
            log("BROWSER", "WebKit engine (native fingerprint)")
        elif BROWSER == "camoufox":
            try:
                from camoufox.sync_api import NewBrowser
                # Camoufox via NewBrowser — uses existing Playwright instance
                # Camoufox has built-in fingerprint spoofing — don't override anything
                browser = NewBrowser(p, headless=headless, proxy=proxy_arg)
                use_chrome_ua = False
                use_stealth = False
                use_webgl_spoof = False
                use_manual_fingerprint = False  # Camoufox handles all fingerprinting
                log("BROWSER", "Camoufox launched (Firefox-based, built-in anti-detect)")
            except ImportError:
                log("BROWSER", "Camoufox not installed — fallback to Chrome")
                browser = p.chromium.launch(headless=headless, channel="chrome", args=launch_common_args, proxy=proxy_arg)
        elif BROWSER == "undetected-chromedriver":
            try:
                import undetected_chromedriver as uc
                log("BROWSER", "undetected-chromedriver not Playwright-compatible — fallback to Chrome")
                browser = p.chromium.launch(headless=headless, channel="chrome", args=launch_common_args, proxy=proxy_arg)
            except ImportError:
                log("BROWSER", "undetected-chromedriver not installed — fallback to Chrome")
                browser = p.chromium.launch(headless=headless, channel="chrome", args=launch_common_args, proxy=proxy_arg)
        elif BROWSER == "rebrowser":
            try:
                from rebrowser_playwright import sync_playwright as rb_sync
                log("BROWSER", "rebrowser-patches mode (Chromium with CDP leak patches)")
                browser = p.chromium.launch(headless=headless, channel="chrome", args=launch_common_args, proxy=proxy_arg)
            except ImportError:
                log("BROWSER", "rebrowser-patches not installed — fallback to Chrome")
                browser = p.chromium.launch(headless=headless, channel="chrome", args=launch_common_args, proxy=proxy_arg)
        else:  # chrome (default)
            browser = p.chromium.launch(headless=headless, channel="chrome", args=launch_common_args, proxy=proxy_arg)
            log("BROWSER", "Chrome Vanilla + playwright-stealth")

        # ── Context setup (engine-aware) ──
        context_args = {}

        if use_manual_fingerprint:
            # Only set UA for Chromium-based browsers
            if use_chrome_ua:
                context_args["user_agent"] = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0.0.0 Safari/537.36"
                )
            # Camoufox/Firefox rejects viewport with isMobile in Playwright 1.61+
            # Camoufox has built-in fingerprint spoofing — don't override viewport
            if BROWSER not in ("camoufox", "firefox"):
                context_args["viewport"] = {"width": 1366, "height": 768}
                context_args["device_scale_factor"] = 1
            context_args["locale"] = "en-US"
            context_args["timezone_id"] = "America/New_York"
            if BROWSER not in ("camoufox", "firefox"):
                context_args["permissions"] = ["geolocation", "notifications"]

        # Camoufox/Firefox: Playwright 1.61+ sends viewport.isMobile which Camoufox rejects
        # Use no_viewport=True for Firefox-based engines
        if BROWSER in ("camoufox", "firefox"):
            context_args["no_viewport"] = True

        # Firefox-based browsers hang on new_page() on this Windows machine
        # Use a timeout wrapper to detect hang and fallback to Chrome
        _firefox_hang = False
        if BROWSER in ("camoufox", "firefox"):
            import threading
            result = {"context": None, "page": None, "error": None}
            def _try_create():
                try:
                    result["context"] = browser.new_context(**context_args)
                    result["page"] = result["context"].new_page()
                except Exception as e:
                    result["error"] = e
            t = threading.Thread(target=_try_create, daemon=True)
            t.start()
            t.join(timeout=15)  # 15 second timeout
            if t.is_alive():
                _firefox_hang = True
                log("BROWSER", "Firefox/Camoufox new_page() hung >15s — fallback to Chrome")
            elif result["error"]:
                _firefox_hang = True
                log("BROWSER", f"Firefox/Camoufox failed ({result['error']}) — fallback to Chrome")
            else:
                context = result["context"]
                page = result["page"]

        if _firefox_hang or BROWSER not in ("camoufox", "firefox"):
            if _firefox_hang:
                # Fallback to Chrome
                try:
                    browser.close()
                except Exception:
                    pass
                BROWSER = "chrome"
                use_chrome_ua = True
                use_stealth = True
                use_webgl_spoof = True
                use_manual_fingerprint = True
                browser = p.chromium.launch(headless=headless, channel="chrome", args=launch_common_args, proxy=proxy_arg)
                context_args = {"viewport": {"width": 1366, "height": 768}, "device_scale_factor": 1,
                                "locale": "en-US", "timezone_id": "America/New_York",
                                "permissions": ["geolocation", "notifications"],
                                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"}
            context = browser.new_context(**context_args)
            page = context.new_page()
        if STEALTH_AVAILABLE and use_stealth:
            stealth = Stealth()
            stealth.apply_stealth_sync(context)
        
        # JavaScript anti-detection (Chromium-only — skip for Firefox/WebKit/Camoufox)
        if use_webgl_spoof:
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                // Override WebGL fingerprint
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel(R) UHD Graphics 620';
                    if (parameter === 37446) return 'Google Inc. (Intel)'; 
                    return getParameter(parameter);
                };
            """)

        try:
            # Step 1: Generate email + password
            email = provider.generate_email()
            if not email:
                log("MAIN", "Failed to generate email — exiting")
                return

            password = generate_password()
            log("GEN", f"Email: {email}")
            log("GEN", f"Password: {password}")

            # Step 2: Register
            reg_ok = register(page, email, password, headless=headless)

            if reg_ok in ("SLIDER", "HOLD", "BAXIA"):
                log("MAIN", f"CAPTCHA blocked: {reg_ok}")
                result = {
                    "email": email,
                    "password": password,
                    "api_key": f"REG_{reg_ok}",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                results.append(result)
                save_results(results, results_file)
                screenshot(page, f"fail_{reg_ok.lower()}.png")

            elif reg_ok == "EMAIL_BLOCKED":
                log("MAIN", "Email domain blocked by Alibaba!")
                log("MAIN", "Try with --menu to select a different provider")
                result = {
                    "email": email,
                    "password": password,
                    "api_key": "EMAIL_BLOCKED",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                results.append(result)
                save_results(results, results_file)

            elif not reg_ok:
                log("MAIN", "Registration failed!")
                result = {
                    "email": email,
                    "password": password,
                    "api_key": "REG_FAILED",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                results.append(result)
                save_results(results, results_file)
                screenshot(page, "fail_reg.png")

            else:
                # Step 3: Email verification (OTP)
                otp_ok = verify_email(page, provider, headless=headless)

                if otp_ok in ("SLIDER", "HOLD", "BAXIA"):
                    log("MAIN", f"CAPTCHA during OTP: {otp_ok}")
                    result = {
                        "email": email,
                        "password": password,
                        "api_key": f"OTP_{otp_ok}",
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    results.append(result)
                    save_results(results, results_file)

                elif not otp_ok:
                    log("MAIN", "Email verification failed!")
                    result = {
                        "email": email,
                        "password": password,
                        "api_key": "OTP_FAILED",
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    results.append(result)
                    save_results(results, results_file)
                    screenshot(page, "fail_otp.png")

                else:
                    # Step 4: Post-registration → Model Studio → API Key
                    #
                    # After OTP verification, Alibaba redirects to:
                    # - supply_userinfo page (security info) → need to handle/skip
                    # - login.htm (session expired) → need to login
                    # - Model Studio (direct access, session still active) → best case
                    #
                    # The successful account (pfn441xod5) went directly to Model Studio
                    # without needing to login. Session from registration was sufficient.

                    log("MAIN", "Post-registration: waiting for redirect to settle...")
                    time.sleep(8)  # Give Alibaba time to set session cookies

                    # Check current URL after OTP
                    post_otp_url = page.url.lower()
                    log("MAIN", f"Post-OTP URL: {post_otp_url[:120]}")

                    # Strategy A: Try direct Model Studio access (session from registration might be active)
                    log("MAIN", "Strategy A: Direct Model Studio (no login)...")
                    try:
                        page.goto(MODELSTUDIO_URL, timeout=30000, wait_until="domcontentloaded")
                    except:
                        pass
                    time.sleep(8)
                    current_url = page.url.lower()
                    log("MAIN", f"Model Studio URL: {current_url[:120]}")

                    # Check if we hit supply_userinfo (security info page)
                    if "supply_userinfo" in current_url:
                        log("MAIN", "Redirected to supply_userinfo — filling security info...")
                        security_ok = handle_supply_userinfo(page, headless=headless)
                        if security_ok:
                            log("MAIN", "Security info handled! Retrying Model Studio...")
                            time.sleep(3)
                            try:
                                page.goto(MODELSTUDIO_URL, timeout=30000, wait_until="domcontentloaded")
                            except:
                                pass
                            time.sleep(8)
                            current_url = page.url.lower()
                            log("MAIN", f"After security: {current_url[:120]}")

                    # Check if we need login
                    # Login pages have /login/ or /signin/ in URL
                    # supply_userinfo is NOT a login page — it's a security setup page
                    # Model Studio may also show login form WITHOUT changing URL (SPA redirect)
                    needs_login = ("login" in current_url and "login.htm" in current_url) or \
                                  "/signin" in current_url or \
                                  ("passport" in current_url and "modelstudio" not in current_url)

                    # Also check if login form is visible on the page (SPA may show login
                    # without changing URL — Model Studio does this when session is invalid)
                    def _has_login_form(pg):
                        """Check if page has a visible login form (email + password fields)."""
                        lf = find_login_frame(pg)
                        if not lf:
                            return False
                        has_email = lf.query_selector("input[placeholder*='email' i]") or \
                                    lf.query_selector("#fm-login-id") or \
                                    lf.query_selector("input[name='loginId']")
                        has_pw = lf.query_selector("input[type='password']")
                        return bool(has_email and has_pw)

                    if not needs_login and _has_login_form(page):
                        log("MAIN", "Login form detected on page (SPA hidden redirect)!")
                        needs_login = True

                    def _do_login_and_get_api_key(pg, email, password, headless):
                        """Login then navigate to Model Studio and create API key.
                        Returns (api_key_string, status_string)."""
                        log("MAIN", "Login required — navigating to login page...")
                        try:
                            pg.goto(LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
                        except:
                            pass
                        time.sleep(5)
                        log("MAIN", f"Login page URL: {pg.url[:100]}")

                        login_ok = auto_login(pg, email, password, timeout=60, headless=headless)

                        if not login_ok:
                            log("MAIN", "First login failed — retrying with fresh page...")
                            try:
                                pg.goto(LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
                            except:
                                pass
                            time.sleep(5)
                            login_ok = auto_login(pg, email, password, timeout=60, headless=headless)

                        if not login_ok:
                            log("MAIN", "Login failed — cannot proceed")
                            return None, "LOGIN_FAILED"

                        log("MAIN", "Login OK! Waiting 5s then Model Studio...")
                        time.sleep(5)

                        # Check for supply_userinfo after login
                        post_login_url = pg.url.lower()
                        if "supply_userinfo" in post_login_url:
                            log("MAIN", "Supply_userinfo after login — handling...")
                            handle_supply_userinfo(pg, headless=headless)
                            time.sleep(3)

                        try:
                            pg.goto(MODELSTUDIO_URL, timeout=30000, wait_until="commit")
                        except:
                            pass
                        time.sleep(8)
                        log("MAIN", f"Model Studio URL: {pg.url[:100]}")

                        # Check if Model Studio actually loaded (not a hidden login page)
                        ms_url = pg.url.lower()
                        if "login" in ms_url or "signin" in ms_url:
                            log("MAIN", "Redirected to login — session invalid")
                            return None, "NEED_LOGIN"

                        if _has_login_form(pg):
                            log("MAIN", "Hidden login form on Model Studio page — session invalid")
                            return None, "NEED_LOGIN"

                        log("MAIN", "Model Studio loaded! Creating API key...")
                        return create_api_key(pg, timeout=30), None

                    if needs_login:
                        api_key, status = _do_login_and_get_api_key(page, email, password, headless)
                        if status:
                            api_key = status
                    else:
                        # Direct access worked!
                        log("MAIN", "Direct Model Studio access! Creating API key...")
                        api_key = create_api_key(page, timeout=30)

                    # Retry if needed
                    if api_key == "NEED_LOGIN":
                        log("MAIN", "Retrying login + Model Studio...")
                        api_key, status = _do_login_and_get_api_key(page, email, password, headless)
                        if status:
                            api_key = status

                    # Save result
                    result = {
                        "email": email,
                        "password": password,
                        "api_key": api_key or "NOT_FOUND",
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    results.append(result)
                    save_results(results, results_file)

                    if api_key and api_key.startswith("sk-"):
                        log("MAIN", f"SUCCESS! API Key: {api_key}")
                    else:
                        log("MAIN", f"No API key. Status: {api_key or 'NOT_FOUND'}")

                    # Keep page open for 60s
                    log("MAIN", ">>> PAGE KEPT OPEN FOR 60s — CHECK BROWSER! <<<")
                    screenshot(page, "final_state.png")
                    for i in range(60):
                        time.sleep(1)
                        if i % 10 == 0 and i > 0:
                            log("MAIN", f"Browser still open... {i}s / 60s")

        except Exception as e:
            log("MAIN", f"EXCEPTION: {e}")
            try:
                screenshot(page, "exception.png")
            except:
                pass
        finally:
            try:
                context.close()
            except:
                pass
            try:
                browser.close()
            except:
                pass

    # Kill chrome
    import subprocess
    subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'],
                   stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    log("MAIN", "Chrome killed.")

    print(f"\n{'='*50}")
    print(f"DONE")
    print(f"Total accounts in results.json: {len(results)}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
