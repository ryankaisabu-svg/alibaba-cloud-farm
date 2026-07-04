#!/usr/bin/env python3
"""
Qwen Cloud Farm — Orchestrator
===============================
Thin runner that coordinates:
  1. Email provider — Gmail dot trick (farm_headless.py)
  2. Registration + OTP (alibaba_register.py)
  3. API key extraction (alibaba_apikey.py)

Usage:
  python alibaba_farm.py --count 10
  python alibaba_farm.py --proxy http://127.0.0.1:8080

Flags:
  --count N       Number of accounts to register (default: 5)
  --proxy URL     Use HTTP proxy
  --gmail USER    Gmail address (from QWEN_GMAIL_USER env var)
  --apppass PASS  Gmail app password (from QWEN_GMAIL_APP_PASS env var)
"""

import sys
import os
import time
import json

# ─ Modules ─────────────────────────────────────────
from farm_headless import GmailDotTrickProvider, log
from alibaba_register import register_qwen, save_result
from alibaba_apikey import create_api_key, update_result_with_apikey, load_results

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

# Parse CLI flags
COUNT = DEFAULT_COUNT
PROXY = None
GMAIL_USER = DEFAULT_GMAIL
APP_PASS = DEFAULT_APP_PASS

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

# Show browser flag (--show = visible, default = headless)
HEADLESS = True
if "--show" in sys.argv:
    HEADLESS = False

# Concurrency flag (parallel browsers)
CONCURRENCY = 1
if "--concurrency" in sys.argv:
    idx = sys.argv.index("--concurrency")
    if idx + 1 < len(sys.argv):
        try:
            CONCURRENCY = max(1, int(sys.argv[idx + 1]))
        except ValueError:
            pass


def main():
    log("QWEN", "=" * 50)
    log("QWEN", "  Qwen Cloud Farm — Registration Automation")
    log("QWEN", "=" * 50)

    # Configure Gmail dot trick provider
    provider = GmailDotTrickProvider()
    provider.configure(gmail_user=GMAIL_USER, app_pass=APP_PASS)
    from threading import Lock
    _aliases_lock = Lock()
    provider.set_lock(_aliases_lock)
    log("MAIL", f"Gmail configured: {provider.gmail_user}")
    log("MAIL", f"Base username: {provider.base_username}")
    log("QWEN", f"Proxy: {PROXY or 'none'}")
    log("QWEN", f"Browser: {'headless' if HEADLESS else 'visible'}")
    log("QWEN", f"Concurrency: {CONCURRENCY} browser(s)")
    log("QWEN", f"Target: {COUNT} accounts")

    if not GMAIL_USER or not APP_PASS:
        log("QWEN", "ERROR: Gmail credentials not configured!")
        log("QWEN", "Set QWEN_GMAIL_USER and QWEN_GMAIL_APP_PASS in .env or pass --gmail/--apppass")
        return

    # Check existing results
    existing = load_results()
    log("QWEN", f"Existing accounts: {len(existing)}")

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

    # OTP queue lock — phase 2 runs one at a time to prevent OTP collision
    otp_queue_lock = Lock()

    def process_one(attempt_num):
        """Process a single account registration in a thread.

        Phase 1 (parallel): navigate + signup + email + click Next
        Phase 2 (queue): read OTP + validate + country + result (one at a time)
        """
        nonlocal success_count, fail_count, apikey_count, done_count, processing

        with stats_lock:
            alias_email = provider.generate_email()
        if not alias_email:
            log("MAIL", "No more aliases available!")
            return None

        log("QWEN", f"[ATTEMPT {attempt_num}] Alias: {alias_email}")

        # Each thread: own Playwright, own browser, own context, own page
        from playwright.sync_api import sync_playwright as _spw

        with _spw() as pw:
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
            log("QWEN", f"[ATTEMPT {attempt_num}] Browser launched (headless={HEADLESS})")

            try:
                # ── PHASE 1: Parallel — navigate + signup + email + Next ──
                log("QWEN", f"[ATTEMPT {attempt_num}] Step 1/5: Navigating to Qwen Cloud...")
                from alibaba_register import register_qwen_phase1, register_qwen_phase2
                phase1_ok = register_qwen_phase1(page, alias_email, GMAIL_USER, APP_PASS)

                if not phase1_ok:
                    log("QWEN", f"[ATTEMPT {attempt_num}] FAILED: Phase 1 error")
                    save_result({
                        "email": alias_email,
                        "api_key": "REGISTRATION_FAILED",
                        "status": "failed",
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "gmail_account": GMAIL_USER,
                    })
                    return ("failed", alias_email)

                log("QWEN", f"[ATTEMPT {attempt_num}] Phase 1 done — waiting for OTP queue...")

                # ── PHASE 2: Queue — OTP + validate + country (one at a time) ──
                with otp_queue_lock:
                    log("QWEN", f"[ATTEMPT {attempt_num}] Step 2/5: OTP queue — processing...")
                    result = register_qwen_phase2(page, alias_email, GMAIL_USER, APP_PASS)

                if not result:
                    log("QWEN", f"[ATTEMPT {attempt_num}] FAILED: Registration returned None")
                    save_result({
                        "email": alias_email,
                        "api_key": "REGISTRATION_FAILED",
                        "status": "failed",
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "gmail_account": GMAIL_USER,
                    })
                    return ("failed", alias_email)

                if result.get("status") == "registered":
                    log("QWEN", f"[ATTEMPT {attempt_num}] Step 2/5: Registration SUCCESS!")
                    save_result(result)

                    log("QWEN", f"[ATTEMPT {attempt_num}] Step 3/5: Waiting for dashboard to load...")
                    time.sleep(3)

                    log("QWEN", f"[ATTEMPT {attempt_num}] Step 4/5: Extracting API key...")
                    api_key = create_api_key(page, gmail_user=GMAIL_USER, app_pass=APP_PASS, alias_email=alias_email)

                    if api_key:
                        update_result_with_apikey(alias_email, api_key)
                        log("QWEN", f"[ATTEMPT {attempt_num}] Step 5/5: API KEY EXTRACTED: {api_key}")
                        return ("apikey", alias_email)
                    else:
                        log("QWEN", f"[ATTEMPT {attempt_num}] Step 5/5: API key extraction FAILED — account registered but no key")
                        return ("success", alias_email)
                else:
                    log("QWEN", f"[ATTEMPT {attempt_num}] Unclear status: {result.get('status')}")
                    save_result(result)
                    return ("success", alias_email)

            except Exception as e:
                log("QWEN", f"[ATTEMPT {attempt_num}] EXCEPTION: {e}")
                save_result({
                    "email": alias_email,
                    "api_key": f"EXCEPTION: {e}",
                    "status": "failed",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "gmail_account": GMAIL_USER,
                })
                return ("failed", alias_email)
            finally:
                log("QWEN", f"[ATTEMPT {attempt_num}] Cleaning up browser...")
                try:
                    page.close()
                    context.close()
                    browser.close()
                except:
                    pass
                log("QWEN", f"[ATTEMPT {attempt_num}] Browser closed")

    # ─ Parallel execution with ThreadPoolExecutor ─
    log("QWEN", f"Starting {COUNT} accounts with {CONCURRENCY} parallel browsers")

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {}

        for attempt in range(1, COUNT + 1):
            future = executor.submit(process_one, attempt)
            futures[future] = attempt
            queued -= 1
            processing += 1
            print(f"[STATS] queued={queued} processing={processing} created={success_count} done={done_count} failed={fail_count} apikey={apikey_count}")

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
                log("QWEN", f"Thread error: {e}")
                fail_count += 1

            done_count += 1
            processing -= 1
            print(f"[STATS] queued={queued} processing={processing} created={success_count} done={done_count} failed={fail_count} apikey={apikey_count}")

    # ─ Summary ─
    log("QWEN", "")
    log("QWEN", "=" * 60)
    log("QWEN", "FINAL SUMMARY")
    log("QWEN", "=" * 60)
    log("QWEN", f"Target accounts : {COUNT}")
    log("QWEN", f"Concurrency     : {CONCURRENCY} browser(s)")
    log("QWEN", f"Registered      : {success_count}")
    log("QWEN", f"With API key    : {apikey_count}")
    log("QWEN", f"Failed          : {fail_count}")
    log("QWEN", "")

    # List all successful accounts with API keys
    final_results = load_results()
    accounts_with_keys = [r for r in final_results if r.get("api_key", "").startswith("sk-")]
    if accounts_with_keys:
        log("QWEN", f"--- API Keys ({len(accounts_with_keys)} total) ---")
        for i, r in enumerate(accounts_with_keys, 1):
            log("QWEN", f"  {i}. {r.get('email', '?')} => {r.get('api_key', '?')}")
    else:
        log("QWEN", "No API keys extracted.")

    accounts_no_keys = [r for r in final_results if r.get("status") == "registered" and not r.get("api_key", "").startswith("sk-")]
    if accounts_no_keys:
        log("QWEN", f"--- Registered but no API key ({len(accounts_no_keys)}) ---")
        for i, r in enumerate(accounts_no_keys, 1):
            log("QWEN", f"  {i}. {r.get('email', '?')}")

    failed_accounts = [r for r in final_results if r.get("status") == "failed"]
    if failed_accounts:
        log("QWEN", f"--- Failed ({len(failed_accounts)}) ---")
        for i, r in enumerate(failed_accounts, 1):
            log("QWEN", f"  {i}. {r.get('email', '?')}")

    log("QWEN", "")
    log("QWEN", f"Total accounts in qwen_results.json: {len(final_results)}")
    log("QWEN", f"CSV file: qwen_accounts.csv")
    log("QWEN", "=" * 60)


# ── GUI Integration ─────────────────────────────────────────
def run_qwen_farm(args):
    """
    Wrapper function untuk GUI integration.
    
    Args:
        args: Object dengan attributes:
            - gmail: Gmail address
            - apppass: Gmail app password
            - count: Number of accounts
            - concurrency: Parallel browsers
            - proxy: HTTP proxy (optional)
            - show: Show browser (bool)
            - debug: Debug mode (bool)
    """
    global GMAIL_USER, APP_PASS, COUNT, CONCURRENCY, PROXY, HEADLESS
    
    # Override globals dengan args dari GUI
    GMAIL_USER = args.gmail
    APP_PASS = args.apppass
    COUNT = args.count
    CONCURRENCY = args.concurrency
    PROXY = args.proxy
    HEADLESS = not args.show
    
    # Jalankan farming
    main()


if __name__ == "__main__":
    main()
