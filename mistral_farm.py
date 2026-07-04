#!/usr/bin/env python3
"""
Mistral AI Farm — Orchestrator
===============================
Thin runner that coordinates:
  1. Email provider — Gmail dot trick (farm_headless.py)
  2. Registration + OTP (mistral_register.py)
  3. API key extraction (mistral_apikey.py)

Usage:
  python mistral_farm.py --count 10
  python mistral_farm.py --gmail user@gmail.com --apppass xxxx --count 5
  python mistral_farm.py --concurrency 3 --show

Flags:
  --count N       Number of accounts to register (default: 5)
  --proxy URL     Use HTTP proxy
  --gmail USER    Gmail address (from QWEN_GMAIL_USER env var)
  --apppass PASS  Gmail app password (from QWEN_GMAIL_APP_PASS env var)
  --concurrency N Parallel browsers (default: 2)
  --show          Show browser (default: headless)
"""

import sys
import os
import time
import json

# ─ Modules ─────────────────────────────────────────
from farm_headless import GmailDotTrickProvider, log
from mistral_register import register_mistral, save_result, generate_password, random_name, RESULTS_FILE
from mistral_apikey import create_api_key, load_results

# Playwright
from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

# ─ Config ──────────────────────────────────────────
DEFAULT_GMAIL = os.environ.get("QWEN_GMAIL_USER", "")
DEFAULT_APP_PASS = os.environ.get("QWEN_GMAIL_APP_PASS", "")
DEFAULT_COUNT = 5
DEFAULT_CONCURRENCY = 2

# Parse CLI flags
COUNT = DEFAULT_COUNT
PROXY = None
GMAIL_USER = DEFAULT_GMAIL
APP_PASS = DEFAULT_APP_PASS
HEADLESS = True
CONCURRENCY = DEFAULT_CONCURRENCY

if "--count" in sys.argv:
    idx = sys.argv.index("--count")
    if idx + 1 < len(sys.argv):
        try:
            COUNT = int(sys.argv[idx + 1])
        except ValueError:
            pass

if "--proxy" in sys.argv:
    idx = sys.argv.index("--proxy")
    if idx + 1 < len(sys.argv):
        PROXY = sys.argv[idx + 1]

if "--gmail" in sys.argv:
    idx = sys.argv.index("--gmail")
    if idx + 1 < len(sys.argv):
        GMAIL_USER = sys.argv[idx + 1]

if "--apppass" in sys.argv:
    idx = sys.argv.index("--apppass")
    if idx + 1 < len(sys.argv):
        APP_PASS = sys.argv[idx + 1]

if "--show" in sys.argv:
    HEADLESS = False

if "--concurrency" in sys.argv:
    idx = sys.argv.index("--concurrency")
    if idx + 1 < len(sys.argv):
        try:
            CONCURRENCY = max(1, int(sys.argv[idx + 1]))
        except ValueError:
            pass

# ─ Recover: auto-detect failed aliases in CSV ─


def load_recover_aliases():
    """Load aliases from CSV with status=failed (tried but no API key).
    Returns list of alias emails to process via forgot password.
    """
    import csv as _csv

    failed = []
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, newline="") as f:
            for r in _csv.DictReader(f):
                status = r.get("status", "").strip().lower()
                if status == "failed":
                    failed.append(r.get("email", "").strip())
    return failed


def main():
    log("MIST", "=" * 50)
    log("MIST", "  Mistral AI Farm — Registration Automation")
    log("MIST", "=" * 50)

    # Configure Gmail dot trick provider
    provider = GmailDotTrickProvider()
    provider.configure(gmail_user=GMAIL_USER, app_pass=APP_PASS)
    from threading import Lock
    _aliases_lock = Lock()
    provider.set_lock(_aliases_lock)

    log("MAIL", f"Gmail configured: {provider.gmail_user}")
    log("MAIL", f"Base username: {provider.base_username}")
    log("MIST", f"Proxy: {PROXY or 'none'}")
    log("MIST", f"Browser: {'headless' if HEADLESS else 'visible'}")
    log("MIST", f"Concurrency: {CONCURRENCY} browser(s)")

    # ─ Auto-detect mode: recover failed aliases first, then new registrations ─
    global COUNT
    recover_aliases = load_recover_aliases()
    if recover_aliases:
        log("MIST", f"Found {len(recover_aliases)} failed aliases in CSV — RECOVER mode")
        COUNT = min(len(recover_aliases), COUNT) if COUNT > 0 else len(recover_aliases)
        recover_aliases = recover_aliases[:COUNT] if COUNT > 0 else recover_aliases
        log("MIST", f"Recover aliases to process: {len(recover_aliases)}")
        if len(recover_aliases) == 0:
            log("MIST", "No aliases to recover — exiting")
            return
    else:
        recover_aliases = []
        log("MIST", "No failed aliases — normal registration mode")

    log("MIST", f"Target: {COUNT} accounts")

    if not GMAIL_USER or not APP_PASS:
        log("MIST", "ERROR: Gmail credentials not configured!")
        log("MIST", "Set QWEN_GMAIL_USER and QWEN_GMAIL_APP_PASS in .env or pass --gmail/--apppass")
        return

    # Check existing results
    existing = load_results()
    log("MIST", f"Previous accounts: {len(existing)}")
    log("MIST", f"Target: {COUNT} accounts")

    success_count = 0
    fail_count = 0
    apikey_count = 0
    done_count = 0
    processing = 0
    queued = COUNT

    # Thread-safe lock for shared state
    from threading import Lock
    from concurrent.futures import ThreadPoolExecutor, as_completed
    stats_lock = Lock()

    # ─ OTP queue lock — serialize signup submit to prevent OTP collision ─
    # Only ONE browser can be in the "submit signup → wait OTP → verify OTP" phase
    # at a time. Other browsers wait their turn before submitting signup.
    # This ensures OTP emails arrive one at a time, no cross-reading.
    otp_queue_lock = Lock()

    def process_one(attempt_num, playwright_pw=None, shared_browser=None, recover_alias=None):
        """Process a single account registration in a thread.
        If shared_browser is provided, reuse it (context reuse mode).
        If recover_alias is provided, use forgot password flow for that alias.
        """
        nonlocal success_count, fail_count, apikey_count, done_count, processing

        if recover_alias:
            # ─ Recover mode: use provided alias, go straight to forgot password ─
            alias_email = recover_alias
            password = generate_password()

            # Double-check: skip if alias already in CSV with API key (race condition guard)
            try:
                import csv as _csv
                if os.path.exists(RESULTS_FILE):
                    with open(RESULTS_FILE, newline="") as f:
                        for r in _csv.DictReader(f):
                            if r.get("email", "").strip() == alias_email and r.get("api_key", "").strip():
                                log("MIST", f"[ATTEMPT {attempt_num}] SKIP {alias_email} — already has API key in CSV")
                                return ("skipped", alias_email)
            except:
                pass

            log("MIST", f"[ATTEMPT {attempt_num}] RECOVER Alias: {alias_email}")
        else:
            # ─ Normal mode: generate alias from dot trick ─
            # Pre-check: skip aliases already in CSV with API key
            existing_emails = set()
            try:
                import csv as _csv
                if os.path.exists(RESULTS_FILE):
                    with open(RESULTS_FILE, newline="") as f:
                        for r in _csv.DictReader(f):
                            if r.get("api_key", "").strip():
                                existing_emails.add(r.get("email", "").strip())
            except:
                pass

            with stats_lock:
                alias_email = provider.generate_email()
            if not alias_email:
                log("MAIL", "No more aliases available!")
                return None

            # Skip alias if already registered with API key — try next alias
            skip_tries = 0
            while alias_email in existing_emails and skip_tries < 50:
                skip_tries += 1
                log("MIST", f"[ATTEMPT {attempt_num}] Alias {alias_email} already in CSV — skipping")
                with stats_lock:
                    alias_email = provider.generate_email()
                if not alias_email:
                    log("MAIL", "No more aliases available!")
                    return None

            if skip_tries >= 50:
                log("MIST", f"[ATTEMPT {attempt_num}] Too many duplicates skipped — giving up")
                return None

            # Generate password and random names
            password = generate_password()
            first_name, last_name = random_name()
            log("MIST", f"[ATTEMPT {attempt_num}] Alias: {alias_email}")
            log("MIST", f"[ATTEMPT {attempt_num}] Name: {first_name} {last_name}")

        # Browser context reuse: use shared browser, create new context per account
        own_browser = False
        if shared_browser:
            browser = shared_browser
        else:
            # Fallback: own browser (legacy mode)
            own_browser = True
            pw = sync_playwright().start()
            launch_args = {
                "headless": HEADLESS,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if PROXY:
                launch_args["proxy"] = {"server": PROXY}
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
        log("MIST", f"[ATTEMPT {attempt_num}] Browser launched (headless={HEADLESS})")

        try:
            if recover_alias:
                # ── Recover mode: go straight to forgot password flow ──
                log("MIST", f"[ATTEMPT {attempt_num}] RECOVER: Forgot password flow...")
                from mistral_register import _forgot_password_recovery
                result = _forgot_password_recovery(
                    page, alias_email, password, GMAIL_USER, APP_PASS,
                    otp_queue_lock=otp_queue_lock
                )

                if not result:
                    log("MIST", f"[ATTEMPT {attempt_num}] RECOVER FAILED: Forgot password returned None")
                    return ("failed", alias_email)

                # Email not yet registered — switch to normal registration
                if result == "SIGNUP_NEEDED":
                    log("MIST", f"[ATTEMPT {attempt_num}] Email not registered — normal registration...")
                    first_name, last_name = random_name()
                    log("MIST", f"[ATTEMPT {attempt_num}] Name: {first_name} {last_name}")
                    result = register_mistral(
                        page, alias_email, password, first_name, last_name,
                        GMAIL_USER, APP_PASS, otp_queue_lock=otp_queue_lock
                    )
                    if not result:
                        log("MIST", f"[ATTEMPT {attempt_num}] Registration FAILED")
                        save_result({
                            "email": alias_email,
                            "password": password,
                            "first_name": first_name,
                            "last_name": last_name,
                            "api_key": "REGISTRATION_FAILED",
                            "status": "failed",
                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "gmail_account": GMAIL_USER,
                        })
                        return ("failed", alias_email)

                    log("MIST", f"[ATTEMPT {attempt_num}] Registration SUCCESS!")
                    save_result(result)

                    if result.get("api_key"):
                        log("MIST", f"[ATTEMPT {attempt_num}] API KEY EXTRACTED: {result['api_key']}")
                        return ("apikey", alias_email)

                    # Phase 2: API key extraction
                    log("MIST", f"[ATTEMPT {attempt_num}] Phase 2: Extracting API key...")
                    api_key = create_api_key(page, timeout=60)
                    if api_key:
                        save_result({"email": alias_email}, api_key=api_key)
                        log("MIST", f"[ATTEMPT {attempt_num}] API KEY EXTRACTED: {api_key}")
                        return ("apikey", alias_email)
                    else:
                        log("MIST", f"[ATTEMPT {attempt_num}] API key extraction FAILED")
                        save_result({"email": alias_email}, api_key="")
                        return ("success", alias_email)

                log("MIST", f"[ATTEMPT {attempt_num}] RECOVER SUCCESS!")
                if result.get("api_key"):
                    log("MIST", f"[ATTEMPT {attempt_num}] API KEY EXTRACTED: {result['api_key']}")
                    return ("apikey", alias_email)
                else:
                    return ("success", alias_email)

            # ── Phase 1: Registration (parallel) ──
            log("MIST", f"[ATTEMPT {attempt_num}] Phase 1: Registration...")
            result = register_mistral(
                page, alias_email, password, first_name, last_name,
                GMAIL_USER, APP_PASS, otp_queue_lock=otp_queue_lock
            )

            if not result:
                log("MIST", f"[ATTEMPT {attempt_num}] FAILED: Registration returned None")
                save_result({
                    "email": alias_email,
                    "password": password,
                    "first_name": first_name,
                    "last_name": last_name,
                    "api_key": "REGISTRATION_FAILED",
                    "status": "failed",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "gmail_account": GMAIL_USER,
                })
                return ("failed", alias_email)

            log("MIST", f"[ATTEMPT {attempt_num}] Registration SUCCESS!")
            save_result(result)

            # ─ Skip Phase 2 if forgot password already created API key ─
            if result.get("api_key"):
                log("MIST", f"[ATTEMPT {attempt_num}] API key already obtained via forgot password flow — skipping Phase 2")
                log("MIST", f"[ATTEMPT {attempt_num}] API KEY EXTRACTED: {result['api_key']}")
                return ("apikey", alias_email)

            # ── Phase 2: API Key extraction ──
            log("MIST", f"[ATTEMPT {attempt_num}] Phase 2: Extracting API key...")

            api_key = create_api_key(page, timeout=60)

            if api_key:
                save_result({"email": alias_email}, api_key=api_key)
                log("MIST", f"[ATTEMPT {attempt_num}] API KEY EXTRACTED: {api_key}")
                return ("apikey", alias_email)
            else:
                log("MIST", f"[ATTEMPT {attempt_num}] API key extraction FAILED — account registered but no key")
                return ("success", alias_email)

        except Exception as e:
            log("MIST", f"[ATTEMPT {attempt_num}] EXCEPTION: {e}")
            save_result({
                "email": alias_email,
                "password": password,
                "first_name": first_name,
                "last_name": last_name,
                "api_key": f"EXCEPTION: {e}",
                "status": "failed",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "gmail_account": GMAIL_USER,
            })
            return ("failed", alias_email)
        finally:
            log("MIST", f"[ATTEMPT {attempt_num}] Cleaning up context...")
            try:
                page.close()
                context.close()
            except:
                pass
            # Only close browser if we own it (legacy mode)
            if own_browser:
                try:
                    browser.close()
                    pw.stop()
                except:
                    pass
            log("MIST", f"[ATTEMPT {attempt_num}] Context closed")

    # ─ Parallel execution with ThreadPoolExecutor ─
    # Browser context reuse: launch CONCURRENCY browsers once, reuse for all accounts
    log("MIST", f"Starting {COUNT} accounts with {CONCURRENCY} parallel browsers")
    log("MIST", f"Mode: Browser context reuse (1 browser per worker, context per account)")

    # Each worker thread gets its own persistent browser instance
    # Thread-local storage: 1 Playwright + 1 Browser per worker thread
    import threading
    _tls = threading.local()

    def get_worker_browser():
        """Get or create a persistent browser for this worker thread."""
        if not hasattr(_tls, 'browser'):
            # First call in this thread — launch browser
            _tls.pw = sync_playwright().start()
            launch_args = {
                "headless": HEADLESS,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if PROXY:
                launch_args["proxy"] = {"server": PROXY}
            _tls.browser = _tls.pw.chromium.launch(**launch_args)
            log("MIST", f"[WORKER] Browser launched for thread {threading.get_ident()}")
        return _tls.browser

    def process_one_reused(attempt_num, recover_alias=None):
        """Wrapper that passes the shared browser to process_one."""
        browser = get_worker_browser()
        return process_one(attempt_num, shared_browser=browser, recover_alias=recover_alias)

    def cleanup_worker_browser():
        """Close browser at thread exit."""
        if hasattr(_tls, 'browser'):
            try:
                _tls.browser.close()
                _tls.pw.stop()
            except:
                pass

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {}

        if recover_aliases:
            # ─ Recover mode: submit one task per recover alias ─
            for attempt, alias in enumerate(recover_aliases, 1):
                future = executor.submit(process_one_reused, attempt, alias)
                futures[future] = attempt
                queued -= 1
                if attempt % 50 == 0 or attempt == COUNT:
                    print(f"[STATS] submitted={attempt}/{COUNT} queued={queued} created={success_count} done={done_count} failed={fail_count} apikey={apikey_count}", flush=True)
        else:
            # ─ Normal mode: generate aliases ─
            for attempt in range(1, COUNT + 1):
                future = executor.submit(process_one_reused, attempt)
                futures[future] = attempt
                queued -= 1
                if attempt % 50 == 0 or attempt == COUNT:
                    print(f"[STATS] submitted={attempt}/{COUNT} queued={queued} created={success_count} done={done_count} failed={fail_count} apikey={apikey_count}", flush=True)

        for future in as_completed(futures):
            attempt_num = futures[future]
            try:
                result = future.result()
                if result:
                    status, email = result
                    if status == "apikey":
                        success_count += 1
                        apikey_count += 1
                    elif status == "success":
                        success_count += 1
                    elif status == "failed":
                        fail_count += 1
            except Exception as e:
                log("MIST", f"Thread error: {e}")
                fail_count += 1

            done_count += 1
            print(f"[STATS] done={done_count}/{COUNT} created={success_count} failed={fail_count} apikey={apikey_count}", flush=True)

    # ─ Summary ─
    log("MIST", "")
    log("MIST", "=" * 60)
    log("MIST", "FINAL SUMMARY")
    log("MIST", "=" * 60)
    log("MIST", f"Target accounts : {COUNT}")
    log("MIST", f"Concurrency     : {CONCURRENCY} browser(s)")
    log("MIST", f"Registered      : {success_count}")
    log("MIST", f"With API key    : {apikey_count}")
    log("MIST", f"Failed          : {fail_count}")
    log("MIST", "")

    # Load ALL results and separate into 3 categories
    final_results = load_results()

    # ─ Category 1: Complete (registered + API key) ─
    with_keys = [r for r in final_results if r.get("api_key")
                 and r.get("api_key") not in ("REGISTRATION_FAILED",)
                 and not r.get("api_key", "").startswith("EXCEPTION")
                 and r.get("status") == "complete"]

    # ─ Category 2: Registered but no API key ─
    no_keys = [r for r in final_results if r.get("status") == "registered"
               and not r.get("api_key")]

    # ─ Category 3: Failed (no API key, status=failed) ─
    failed_aliases = [r for r in final_results if r.get("status") == "failed"]

    log("MIST", f"With API key    : {len(with_keys)}")
    log("MIST", f"Registered, no key: {len(no_keys)}")
    log("MIST", f"Failed (recoverable): {len(failed_aliases)}")
    log("MIST", f"Total in CSV    : {len(final_results)}")
    log("MIST", "=" * 60)


if __name__ == "__main__":
    main()
