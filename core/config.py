"""
core/config.py — Configuration constants for Alibaba Cloud Farm.

Extracted from farm_headless.py L96-140.
"""

import sys
import os
import platform

# ─ Path setup ──────────────────────────────────────
from data_paths import get_path, get_alias_index_path, is_alias_used, mark_alias_used, get_used_count, load_alias_index, save_alias_index, migrate_legacy_files

# ─ URLs ────────────────────────────────────────────
REGISTER_URL = "https://account.alibabacloud.com/register/intl_register.htm"
LOGIN_URL = "https://account.alibabacloud.com/login/login.htm"
MODELSTUDIO_URL = "https://modelstudio.console.alibabacloud.com/ap-southeast-1?tab=dashboard#/api-key"

# ─ Results ─────────────────────────────────────────
RESULTS_FILE = get_path("alibaba", "results.json")

PROVIDER_RESULTS = {
    "tempmail":     get_path("alibaba", "results.json"),
    "mailtm":       get_path("alibaba", "results.json"),
    "tempmailio":   get_path("alibaba", "results.json"),
    "gmail":        get_path("alibaba", "results.json"),
    "outlook":      get_path("alibaba", "results.json"),
    "manual":       get_path("alibaba", "results.json"),
}

# ─ Screenshot dir ──────────────────────────────────
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ─ CLI flags ───────────────────────────────────────
DEBUG = "--debug" in sys.argv
SHOW = "--show" in sys.argv
AUTO_CAPTCHA = "--auto-captcha" in sys.argv  # auto-solve OFF by default

# ─ Browser engine selection ────────────────────────
BROWSER = "chrome"
if "--browser" in sys.argv:
    _bi = sys.argv.index("--browser")
    if _bi + 1 < len(sys.argv):
        BROWSER = sys.argv[_bi + 1].lower()
BROWSER_OPTIONS = ["chrome", "firefox", "webkit", "camoufox", "undetected-chromedriver", "rebrowser"]

# ─ Proxy ───────────────────────────────────────────
PROXY = None
if "--proxy" in sys.argv:
    idx = sys.argv.index("--proxy")
    if idx + 1 < len(sys.argv):
        PROXY = sys.argv[idx + 1]

# ─ tempmail.plus config ────────────────────────────
TEMPMAIL_API = "https://tempmail.plus/api/mails"
TEMPMAIL_DOMAINS = [
    "mailto.plus", "fexpost.com", "fexbox.org", "mailbox.in.ua",
    "rover.info", "chitthi.info", "fextemp.com", "any.pink", "merepost.com"
]
