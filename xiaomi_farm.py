#!/usr/bin/env python3
"""
Xiaomi MiMo Farm — Orchestrator
================================
Thin runner that coordinates:
  1. Email provider (farm_headless.py)
  2. Registration + OTP (xiaomi_register.py)
  3. Login + API key (xiaomi_login.py)
  4. CAPTCHA solving (xiaomi_captcha.py)

Usage:
  python xiaomi_farm.py --show --debug
  python xiaomi_farm.py --provider gmail --show --debug --auto-captcha
  python xiaomi_farm.py --provider gmail --show --proxy http://127.0.0.1:8080

Flags:
  --show          Show browser window
  --debug         Enable debug screenshots
  --auto-captcha  Try auto-solve CAPTCHA (CapSolver/NopeCHA/audio)
  --proxy URL     Use HTTP proxy
  --provider NAME Email provider (gmail, tempmail, mailtm, tempmailio, manual)
"""

import sys
import os
import time
import json

# ─ Modules ─────────────────────────────────────────
from farm_headless import (
    GmailDotTrickProvider,
    get_provider, log, screenshot,
)

from xiaomi_register import register_xiaomi, verify_otp, generate_password, save_result
from xiaomi_login import get_api_key

# Playwright
from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

# ─ Config ──────────────────────────────────────────
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "xiaomi_results.json")

# Parse CLI flags
DEBUG = "--debug" in sys.argv
SHOW = "--show" in sys.argv
AUTO_CAPTCHA = "--auto-captcha" in sys.argv

PROXY = None
if "--proxy" in sys.argv:
    idx = sys.argv.index("--proxy")
    if idx + 1 < len(sys.argv):
        PROXY = sys.argv[idx + 1]


def main():
    log("REG", "═" * 50)
    log("REG", "  Xiaomi MiMo Farm — Registration Automation")
    log("REG", "═" * 50)

    # Parse provider — default to gmail (dot trick, all tempmail blocked by Xiaomi)
    provider_choice = "gmail"
    if "--provider" in sys.argv:
        idx = sys.argv.index("--provider")
        if idx + 1 < len(sys.argv):
            provider_choice = sys.argv[idx + 1]

    provider = get_provider(provider_choice)
    log("MAIL", f"Provider: {provider.__class__.__name__}")

    # Configure Gmail dot trick provider
    if isinstance(provider, GmailDotTrickProvider):
        provider.configure(
            gmail_user=os.environ.get("QWEN_GMAIL_USER", ""),
            app_pass=os.environ.get("QWEN_GMAIL_APP_PASS", ""),
        )
        log("MAIL", f"Gmail configured: {provider.gmail_user}")

    log("REG", f"Show: {SHOW} | Debug: {DEBUG} | Proxy: {PROXY or 'none'}")

    # NopeCHA extension path (for persistent context)
    NOPECHA_PATH = os.path.join(os.path.dirname(__file__), "nopecha-ext")
    USE_NOPECHA = AUTO_CAPTCHA and os.path.exists(os.path.join(NOPECHA_PATH, "manifest.json"))

    if USE_NOPECHA:
        log("CAPTCHA", "NopeCHA extension loaded — auto-solve enabled")

    # Launch browser
    with sync_playwright() as pw:
        if USE_NOPECHA:
            # Persistent context required for extensions
            import tempfile
            user_data_dir = tempfile.mkdtemp(prefix="xiaomi_browser_")
            context = pw.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,  # Extensions only work in headed mode
                args=[
                    "--disable-blink-features=AutomationControlled",
                    f"--disable-extensions-except={NOPECHA_PATH}",
                    f"--load-extension={NOPECHA_PATH}",
                ],
                viewport={"width": 1280, "height": 1024},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                locale="en-US",
            )
            if PROXY:
                log("REG", "Note: proxy not supported with persistent context + extensions")
            browser = context.browser
            page = context.new_page()
        else:
            launch_args = {
                "headless": not SHOW,
                "args": ["--disable-blink-features=AutomationControlled"],
            }

            if PROXY:
                launch_args["proxy"] = {"server": PROXY}
                log("REG", f"Using proxy: {PROXY}")

            browser = pw.chromium.launch(**launch_args)

            context = browser.new_context(
                viewport={"width": 1280, "height": 1024},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                locale="en-US",
            )

            if STEALTH_AVAILABLE:
                try:
                    stealth = Stealth()
                    stealth.apply_stealth_sync(context)
                except:
                    pass

            page = context.new_page()

        try:
            # Step 1-4: Register (fill form + CAPTCHA + submit)
            email, password = register_xiaomi(page, provider, auto_captcha=AUTO_CAPTCHA)
            if not email:
                log("REG", "Registration failed at email step")
                save_result({
                    "email": "FAILED",
                    "password": "",
                    "api_key": "REGISTRATION_FAILED",
                    "status": "failed",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                return

            # Step 5: OTP verification
            otp_ok = verify_otp(page, provider)
            if not otp_ok:
                log("OTP", "OTP verification failed")
                save_result({
                    "email": email,
                    "password": password,
                    "api_key": "OTP_FAILED",
                    "status": "failed",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                return

            # Step 6: Login + Get API key
            api_key = get_api_key(page, email, password)

            record = {
                "email": email,
                "password": password,
                "api_key": api_key or "NOT_FOUND",
                "status": "success" if api_key else "registered_no_apikey",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "gmail_account": provider.gmail_user if isinstance(provider, GmailDotTrickProvider) else None,
            }
            save_result(record)

            if api_key:
                log("API", f"SUCCESS! API Key: {api_key}")
                log("API", f"Account: {email} | Password: {password}")
            else:
                log("API", "Registration OK but API key not auto-found")
                log("API", f"Account saved: {email} | Password: {password}")
                log("API", "Login manually at platform.xiaomimimo.com to get API key")

        except Exception as e:
            log("REG", f"Exception: {e}")
            if DEBUG:
                try:
                    screenshot(page, "xiaomi_error.png")
                except:
                    pass
            save_result({
                "email": email if 'email' in dir() else "ERROR",
                "password": password if 'password' in dir() else "",
                "api_key": f"EXCEPTION: {e}",
                "status": "failed",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
        finally:
            if USE_NOPECHA:
                context.close()
            else:
                browser.close()

    log("REG", "Done.")


if __name__ == "__main__":
    main()
