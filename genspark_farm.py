#!/usr/bin/env python3
"""
Genspark Farm — Bulk API Key Extraction via Google OAuth

Flow per akun:
  1. Homepage → toggle sidebar → Sign In dialog
  2. Continue with Google → OAuth → email → password
  3. Redirect back → verify login → dismiss popup
  4. Scroll sidebar bottom → click person SVG → Settings popover
  5. Click Settings → API Keys → Create New Key → extract gsk-* key
  6. Save essential cookies + API key to JSON

Input:
  --email user@domain.com --pass password    Single account
  --accounts-file accounts.txt               Multiple accounts (email|password per line)
  --count N                                   Max accounts to process
  --show                                      Show browser (headless=False)

Usage:
  python genspark_farm.py --email user@domain.com --pass xxx --show
  python genspark_farm.py --accounts-file accounts.txt --count 10
"""
import time, json, random, string, re, sys, os
from playwright.sync_api import sync_playwright
from urllib.parse import urlparse

# ── Path setup ──────────────────────────────────────
FARM_DIR = os.path.dirname(os.path.abspath(__file__))
if FARM_DIR not in sys.path:
    sys.path.insert(0, FARM_DIR)
_DATA_DIR = os.path.join(FARM_DIR, "data", "genspark")
os.makedirs(_DATA_DIR, exist_ok=True)
RESULTS_FILE = os.path.join(_DATA_DIR, "genspark_results.json")
SCREENSHOT_DIR = os.path.join(FARM_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

STEALTH = """Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"""

GS_ESSENTIAL = {
    "session_id", "gslogin", "from_auth", "NA_TRIDTP",
    "agree_terms", "ai_session", "ai_user",
    "__cf_bm", "__cflb", "i18n_set", "sidebar_expanded",
}


def load_accounts(path):
    accts = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line and "|" in line:
                email, pw = line.split("|", 1)
                accts.append({"email": email.strip(), "password": pw.strip()})
    return accts


def random_key_name():
    return f"agent-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"


def human_type(el, text):
    for ch in text:
        el.type(ch, delay=random.randint(30, 120))


def parse_args():
    args = {"email": None, "password": None, "accounts_file": None,
            "count": 1, "concurrency": 1, "show": False, "proxy": None}
    i = 0
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--email" and i + 1 < len(sys.argv):
            args["email"] = sys.argv[i + 1]; i += 2
        elif a == "--pass" and i + 1 < len(sys.argv):
            args["password"] = sys.argv[i + 1]; i += 2
        elif a == "--accounts-file" and i + 1 < len(sys.argv):
            args["accounts_file"] = sys.argv[i + 1]; i += 2
        elif a == "--count" and i + 1 < len(sys.argv):
            try:
                args["count"] = int(sys.argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif a == "--concurrency" and i + 1 < len(sys.argv):
            try:
                args["concurrency"] = max(1, int(sys.argv[i + 1]))
            except ValueError:
                pass
            i += 2
        elif a == "--show":
            args["show"] = True; i += 1
        elif a == "--proxy" and i + 1 < len(sys.argv):
            args["proxy"] = sys.argv[i + 1]; i += 2
        else:
            i += 1
    return args


def run_account(browser, ctx, email, password, show_browser, idx=0, total=1):
    """Full flow for ONE account. Returns dict: success, api_key, email, error."""
    page = ctx.new_page()
    page.add_init_script(STEALTH)

    try:
        # ══ PHASE 1: LOGIN ══
        print(f"[{idx}/{total}] [1] Homepage...")
        page.goto("https://www.genspark.ai/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # [2] Sign In
        print(f"[{idx}/{total}] [2] Sign In...")
        time.sleep(3)
        clicked = False
        try:
            page.click('div[data-v-62b2c917=""]', timeout=8000)
            print(f"[{idx}/{total}]     Toggled sidebar")
            time.sleep(3)
        except:
            print(f"[{idx}/{total}]     Sidebar toggle not found")

        for tag in ["div", "span", "a", "button"]:
            els = page.query_selector_all(tag)
            for el in els:
                try:
                    if not el.is_visible():
                        continue
                    if el.inner_text().strip() == "Sign in":
                        el.click()
                        print(f"[{idx}/{total}]     Clicked 'Sign in'")
                        clicked = True
                        break
                except:
                    continue
            if clicked:
                break

        if not clicked:
            print(f"[{idx}/{total}]     Trying /new...")
            page.goto("https://www.genspark.ai/new", wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
            try:
                page.click('div[data-v-62b2c917=""]', timeout=5000)
                time.sleep(3)
            except:
                pass
            for tag in ["div", "span", "a", "button"]:
                els = page.query_selector_all(tag)
                for el in els:
                    try:
                        if not el.is_visible():
                            continue
                        if el.inner_text().strip() == "Sign in":
                            el.click()
                            clicked = True
                            break
                    except:
                        continue
                if clicked:
                    break

        if not clicked:
            return {"success": False, "email": email, "api_key": None, "error": "Sign in not found"}
        time.sleep(5)

        # [3] Continue with Google
        print(f"[{idx}/{total}] [3] Continue with Google...")
        for sel in [
            'span:has-text("Continue with Google")',
            'span:has-text("Sign in with Google")',
            'button:has-text("Google")',
            'div:has-text("Continue with Google")',
        ]:
            try:
                page.locator(sel).first.wait_for(state="visible", timeout=5000)
                page.locator(sel).first.click()
                break
            except:
                continue
        else:
            return {"success": False, "email": email, "api_key": None, "error": "Google button not found"}
        time.sleep(5)

        # [4] Account chooser
        print(f"[{idx}/{total}] [4] Account chooser...")
        try:
            akun = page.wait_for_selector("div.riDSKb", timeout=8000, state="visible")
            akun.click()
        except:
            pass

        # [5] Email
        print(f"[{idx}/{total}] [5] Email: {email}")
        inp = page.wait_for_selector('input[name="identifier"]', timeout=15000, state="visible")
        inp.click()
        time.sleep(0.8)
        human_type(inp, email)
        time.sleep(1.5)
        page.click("#identifierNext")
        time.sleep(10)

        body = page.inner_text("body")
        if "Something went wrong" in body:
            return {"success": False, "email": email, "api_key": None, "error": "Google blocked"}
        if "wrong" in body.lower():
            return {"success": False, "email": email, "api_key": None, "error": "Wrong password"}

        # [6] Password
        print(f"[{idx}/{total}] [6] Password...")
        pw_el = page.wait_for_selector('input[name="Passwd"]', timeout=15000, state="visible")
        pw_el.click()
        time.sleep(0.8)
        human_type(pw_el, password)
        time.sleep(1.5)
        page.click("#passwordNext")
        time.sleep(10)

        # Consent
        try:
            body = page.inner_text("body")
            if "Lanjutkan" in body or ("Continue" in body and "consent" in page.url.lower()):
                page.locator('button:has-text("Continue"), button:has-text("Lanjutkan")').first.click()
                time.sleep(5)
        except:
            pass

        # Wait redirect
        print(f"[{idx}/{total}] [6c] Waiting for redirect...")
        for i in range(20):
            time.sleep(1)
            url = page.url
            host = urlparse(url).hostname or ""
            if "genspark.ai" in host and "accounts.google" not in url and "login.genspark" not in url:
                print(f"[{idx}/{total}]     [+][{i+1}s] redirected")
                break
        time.sleep(5)

        # Verify login
        print(f"[{idx}/{total}] [6d] Verify...")
        page.goto("https://www.genspark.ai/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        login = page.evaluate("async()=>{const r=await fetch('/api/is_login',{credentials:'include'});return await r.text();}")
        if '"is_login":true' not in login and '"is_login": true' not in login:
            return {"success": False, "email": email, "api_key": None, "error": "Login failed"}
        print(f"[{idx}/{total}]     [+] LOGGED IN!")
        time.sleep(3)

        # [6e] Dismiss popup
        for sel in [
            'button:has-text("Not now")', 'button:has-text("Not Now")',
            'button:has-text("No thanks")', 'button:has-text("Skip")',
            'span:has-text("Not now")', 'div:has-text("Not now")',
        ]:
            try:
                if page.locator(sel).first.is_visible(timeout=2000):
                    page.locator(sel).first.click()
                    break
            except:
                continue

        # ══ PHASE 2: API KEY ══

        # [7] Avatar -> Popover -> Settings
        print(f"[{idx}/{total}] [7] Avatar -> Settings...")
        time.sleep(2)

        # Scroll sidebar to bottom
        try:
            sidebar = page.query_selector('[class*="sidebar"]') or page.query_selector("aside")
            if sidebar:
                sidebar.evaluate("el => el.scrollTop = el.scrollHeight")
                time.sleep(1)
        except:
            pass

        # Click person SVG (M19.82* + M3.5)
        avatar_clicked = False
        try:
            for svg in page.query_selector_all("svg"):
                if svg.is_visible():
                    paths = svg.query_selector_all("path")
                    if len(paths) >= 2:
                        d1 = paths[0].get_attribute("d") or ""
                        d2 = paths[1].get_attribute("d") or ""
                        if ("M19.82" in d1 or "M10.33" in d1 or "M10.3" in d1) and "M3.5" in d2:
                            svg.click()
                            avatar_clicked = True
                            break
        except:
            pass

        if not avatar_clicked:
            return {"success": False, "email": email, "api_key": None, "error": "Avatar SVG not found"}
        time.sleep(2)

        # Wait popover → click Settings
        try:
            page.wait_for_selector(".n-popover__content", timeout=8000)
        except:
            return {"success": False, "email": email, "api_key": None, "error": "Popover not rendered"}

        settings_clicked = False
        try:
            for item in page.query_selector_all(".n-popover__content div.item"):
                if item.inner_text().strip() == "Settings":
                    item.click()
                    settings_clicked = True
                    break
        except:
            pass
        if not settings_clicked:
            try:
                page.locator(".n-popover__content").locator('div:has-text("Settings")').first.click(timeout=3000)
                settings_clicked = True
            except:
                pass
        if not settings_clicked:
            return {"success": False, "email": email, "api_key": None, "error": "Settings not found"}

        # [9] API Keys nav
        print(f"[{idx}/{total}] [9] API Keys...")
        api_clicked = False
        for sel in [
            'div.settings-v2__nav-item:has-text("API Keys")',
            'span:has-text("API Keys")',
        ]:
            try:
                page.locator(sel).first.wait_for(state="visible", timeout=5000)
                page.locator(sel).first.click()
                api_clicked = True
                break
            except:
                continue
        if not api_clicked:
            try:
                for item in page.query_selector_all("div.settings-v2__nav-item"):
                    if item.is_visible() and "API Keys" in item.inner_text():
                        item.click()
                        api_clicked = True
                        break
            except:
                pass
        if not api_clicked:
            return {"success": False, "email": email, "api_key": None, "error": "API Keys nav not found"}
        time.sleep(2)

        # [10] Create New Key
        print(f"[{idx}/{total}] [10] Create New Key...")
        try:
            page.wait_for_selector("button.api-keys__btn-primary", timeout=10000, state="visible").click()
        except:
            try:
                page.locator('button:has-text("Create New Key"), button:has-text("Create")').first.click(timeout=5000)
            except:
                return {"success": False, "email": email, "api_key": None, "error": "Create button not found"}
        time.sleep(2)

        key_name = random_key_name()
        try:
            ta = page.wait_for_selector("textarea.api-keys__dialog-textarea--create", timeout=10000, state="visible")
            ta.fill(key_name)
        except:
            try:
                ta = page.wait_for_selector('textarea[placeholder="Enter key name"]', timeout=5000, state="visible")
                ta.fill(key_name)
            except:
                pass
        time.sleep(1)

        # [11] Confirm
        try:
            page.wait_for_selector("button.api-keys__dialog-btn--save", timeout=10000, state="visible").click()
        except:
            try:
                page.locator('button:has-text("Create")').first.click(timeout=5000)
            except:
                pass
        time.sleep(3)

        # [12] Extract API key
        api_key = None
        body = page.inner_text("body")
        m = re.search(r"gsk-[A-Za-z0-9+/=_-]+", body)
        if m:
            api_key = m.group(0)
        if not api_key:
            try:
                r = page.evaluate("async()=>{const x=await fetch('/api/api_tokens/org/list?page=1&page_size=100',{credentials:'include'});return await x.text();}")
                m = re.search(r"gsk-[A-Za-z0-9+/=_-]+", r)
                if m:
                    api_key = m.group(0)
            except:
                pass

        if api_key:
            print(f"[{idx}/{total}]     === API KEY: {api_key[:40]}... ===")

        # [13] Save essential cookies
        cookies = ctx.cookies()
        genspark_cookies = {}
        google_cookies = {}
        for c in cookies:
            domain = c.get("domain", "")
            if "genspark" in domain and c["name"] in GS_ESSENTIAL:
                genspark_cookies[c["name"]] = c["value"]
            elif "google" in domain:
                google_cookies[c["name"]] = c["value"]

        result = {
            "account": email,
            "api_key": api_key,
            "genspark_cookies": genspark_cookies,
            "google_cookies": google_cookies,
        }

        # Append to results file
        _save_result(result)

        return {"success": bool(api_key), "email": email, "api_key": api_key, "error": None if api_key else "API key not extracted"}

    except Exception as e:
        return {"success": False, "email": email, "api_key": None, "error": str(e)}

    finally:
        try:
            page.close()
        except:
            pass


def _load_existing_results():
    """Load existing results, return set of accounts that already have keys."""
    done = set()
    if os.path.isfile(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                results = json.load(f)
            for r in results:
                acct = r.get("account") or r.get("email", "")
                if acct and r.get("api_key"):
                    done.add(acct)
        except:
            pass
    return done


def _dedup_results():
    """Remove duplicate entries, keep latest per account (thread-safe)."""
    lock = getattr(_dedup_results, "_lock", None)
    if lock is None:
        import threading
        _dedup_results._lock = threading.Lock()
        lock = _dedup_results._lock
    with lock:
        if not os.path.isfile(RESULTS_FILE):
            return
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                results = json.load(f)
        except:
            return
        seen = {}
        for r in results:
            acct = r.get("account") or r.get("email", "")
            if acct:
                seen[acct] = r
        deduped = list(seen.values())
        if len(deduped) < len(results):
            tmp = RESULTS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(deduped, f, indent=2, ensure_ascii=False)
            os.replace(tmp, RESULTS_FILE)
            print(f"[DEDUP] {len(results)} -> {len(deduped)} entries")


def _save_result(result):
    """Append result to results JSON (thread-safe atomic write)."""
    lock = getattr(_save_result, "_lock", None)
    if lock is None:
        import threading
        _save_result._lock = threading.Lock()
        lock = _save_result._lock
    with lock:
        results = []
        if os.path.isfile(RESULTS_FILE):
            try:
                with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                    results = json.load(f)
            except:
                results = []
        results.append(result)
        tmp = RESULTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        os.replace(tmp, RESULTS_FILE)


def process_one(acct, idx, total, show_browser, proxy=None):
    """Process one account in its own browser instance (thread-safe)."""
    email = acct["email"]
    try:
        with sync_playwright() as pw:
            launch_args = {
                "headless": not show_browser,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox", "--disable-dev-shm-usage",
                ],
            }
            if proxy:
                launch_args["proxy"] = {"server": proxy}
            browser = pw.chromium.launch(**launch_args)
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale="en-US",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            )
            res = run_account(browser, ctx, email, acct["password"], show_browser, idx, total)
            ctx.close()
            browser.close()
        return res
    except Exception as e:
        return {"success": False, "email": email, "api_key": None, "error": str(e)}


def main():
    args = parse_args()
    show_browser = args["show"]
    max_count = args["count"]
    concurrency = args["concurrency"]
    proxy = args.get("proxy")

    accounts = []
    if args["email"] and args["password"]:
        accounts.append({"email": args["email"], "password": args["password"]})
    elif args["accounts_file"]:
        accounts = load_accounts(args["accounts_file"])

    if not accounts:
        print("No accounts specified.")
        print("Usage:")
        print("  python genspark_farm.py --email user@domain.com --pass PASSWORD --show")
        print("  python genspark_farm.py --accounts-file accounts.txt --count 10 --concurrency 3")
        sys.exit(1)

    accounts = accounts[:max_count]
    total = len(accounts)

    # Anti-duplicate: skip accounts that already have keys
    done = _load_existing_results()
    pending = [a for a in accounts if a["email"] not in done]
    skipped = total - len(pending)
    if skipped > 0:
        print(f"[SKIP] {skipped} accounts already have keys")
    accounts = pending
    total = len(accounts)

    if not accounts:
        print("All accounts already processed. Nothing to do.")
        _dedup_results()
        return

    print("=" * 55)
    print("GENSPARK FARM v2 (Playwright + Multi-Browser)")
    print(f"Accounts: {total} | Concurrency: {concurrency} | Show: {show_browser}")
    if proxy:
        print(f"Proxy: {proxy[:50]}...")
    print("=" * 55)

    results = {"ok": 0, "fail": 0, "errors": []}
    done_count = 0
    processing = 0

    if concurrency <= 1:
        # Sequential mode (single browser, reuse)
        with sync_playwright() as pw:
            launch_args = {
                "headless": not show_browser,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox", "--disable-dev-shm-usage",
                ],
            }
            if proxy:
                launch_args["proxy"] = {"server": proxy}
                print(f"[PROXY] {proxy[:40]}...")

            browser = pw.chromium.launch(**launch_args)
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale="en-US",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            )

            for idx, acct in enumerate(accounts):
                print(f"\n--- Account {idx+1}/{total}: {acct['email']} ---")
                res = run_account(browser, ctx, acct["email"], acct["password"], show_browser, idx + 1, total)

                if res["success"]:
                    results["ok"] += 1
                else:
                    results["fail"] += 1
                    err = res.get("error", "unknown")
                    results["errors"].append(f"{acct['email']}: {err}")
                    print(f"  FAILED: {err}")

                done_count += 1
                print(f"[STATS] ok={results['ok']} fail={results['fail']} done={done_count}/{total}")

            ctx.close()
            browser.close()
    else:
        # Parallel mode (each thread gets its own browser)
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"\nStarting {total} accounts with {concurrency} parallel browsers...")

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {}
            for idx, acct in enumerate(accounts):
                future = executor.submit(process_one, acct, idx + 1, total, show_browser, proxy)
                futures[future] = acct["email"]

            for future in as_completed(futures):
                email = futures[future]
                try:
                    res = future.result()
                    if res["success"]:
                        results["ok"] += 1
                    else:
                        results["fail"] += 1
                        err = res.get("error", "unknown")
                        results["errors"].append(f"{email}: {err}")
                except Exception as e:
                    results["fail"] += 1
                    results["errors"].append(f"{email}: {e}")

                done_count += 1
                print(f"[STATS] ok={results['ok']} fail={results['fail']} done={done_count}/{total}")

    # Summary
    print("\n" + "=" * 55)
    print(f"SUMMARY: {results['ok']} OK / {results['fail']} FAIL")
    if results["errors"]:
        print("Failures:")
        for err in results["errors"]:
            print(f"  - {err}")
    _dedup_results()
    print(f"Results: {RESULTS_FILE}")
    print("=" * 55)


if __name__ == "__main__":
    main()
