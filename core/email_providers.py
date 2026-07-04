"""
core/email_providers.py — Email provider classes for Alibaba Cloud Farm.

Extracted from farm_headless.py L194-731.
Provides: TempMailProvider, MailTmProvider, TempMailIoProvider,
          GmailDotTrickProvider, OutlookProvider, ManualProvider,
          get_provider() factory.

All providers implement:
    generate_email() -> str|None
    read_otp(timeout=120) -> str|None
"""

import sys
import time
import json
import re
import random
import string
import os
import urllib.request
import urllib.error

# ─ Imports from farm_headless.py top-level ──
# These are normally available in the global module scope.
# We import them lazily to avoid circular imports.

# Config constants needed by providers
TEMPMAIL_API = "https://tempmail.plus/api/mails"
TEMPMAIL_DOMAINS = [
    "mailto.plus", "fexpost.com", "fexbox.org", "mailbox.in.ua",
    "rover.info", "chitthi.info", "fextemp.com", "any.pink", "merepost.com"
]

# data_paths imports (for GmailDotTrickProvider)
from data_paths import (
    get_path, get_alias_index_path, is_alias_used, mark_alias_used,
    get_used_count, load_alias_index, save_alias_index, migrate_legacy_files
)


def log(step, msg):
    """Minimal log — avoids circular import with core/helpers.py."""
    ts = time.strftime("%H:%M:%S")
    try:
        print(f"  [{ts}] [{step}] {msg}", flush=True)
    except UnicodeEncodeError:
        safe = msg.encode("ascii", "replace").decode("ascii")
        print(f"  [{ts}] [{step}] {safe}", flush=True)


# ─ Shared OTP extraction logic (was duplicated 4x in farm_headless.py) ──
_OTP_BLACKLIST = ('181818', '999', '666666', '808080', '000000')

def extract_otp(text):
    """Extract 6-digit OTP from email text using 3 regex strategies.

    1. Span-wrapped: >123456</span>
    2. Context: 'code'/'verification'/'otp' followed by 6 digits
    3. Bare 6-digit number (excluding known false positives)
    """
    m = re.search(r'>\s*(\d{6})\s*</span>', text)
    if m:
        return m.group(1)
    m = re.search(r'(?:code|verification|otp)[^<]*?(\d{6})', text, re.IGNORECASE)
    if m:
        return m.group(1)
    for m in re.finditer(r'\b(\d{6})\b', text):
        num = m.group(1)
        if num not in _OTP_BLACKLIST:
            return num
    return None


# ════════════════════════════════════════════════════
# ─ tempmail.plus ────────────────────────────────────
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

                    otp = extract_otp(full_text)
                    if otp:
                        log("MAIL", f"OTP found: {otp}")
                        return otp
            except Exception as e:
                log("MAIL", f"Error: {e}")
            time.sleep(5)
        log("MAIL", "OTP timeout")
        return None

    def _extract_otp(self, text):
        return extract_otp(text)


# ════════════════════════════════════════════════════
# ─ mail.tm ───────────────────────────────────────────
# ════════════════════════════════════════════════════

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

                    otp = extract_otp(full_text)
                    if otp:
                        log("MAIL", f"OTP found: {otp}")
                        return otp
            except Exception as e:
                log("MAIL", f"mail.tm error: {e}")
            time.sleep(5)
        log("MAIL", "OTP timeout")
        return None

    def _extract_otp(self, text):
        return extract_otp(text)


# ════════════════════════════════════════════════════
# ─ temp-mail.io ─────────────────────────────────────
# ════════════════════════════════════════════════════

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
                        otp = extract_otp(full_text)
                        if otp:
                            log("MAIL", f"OTP found: {otp}")
                            return otp
            except Exception as e:
                log("MAIL", f"temp-mail.io error: {e}")
            time.sleep(5)
        log("MAIL", "OTP timeout")
        return None

    def _extract_otp(self, text):
        return extract_otp(text)


# ════════════════════════════════════════════════════
# ─ Gmail dot trick ─────────────────────────────────
# ════════════════════════════════════════════════════

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
                        otp = extract_otp(full_text)
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
        return extract_otp(text)


# ════════════════════════════════════════════════════
# ─ Outlook (via outlook_manager.py) ─────────────────
# ════════════════════════════════════════════════════

class OutlookProvider:
    """Outlook — uses outlook_manager.py for alias + OTP reading."""

    def __init__(self):
        self.email = None
        self._manager = None

    def generate_email(self):
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


# ════════════════════════════════════════════════════
# ─ Manual ───────────────────────────────────────────
# ════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════
# ─ Factory ─────────────────────────────────────────
# ════════════════════════════════════════════════════

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
