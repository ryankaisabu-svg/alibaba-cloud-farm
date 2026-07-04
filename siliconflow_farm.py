#!/usr/bin/env python3
"""
SiliconFlow Farm — Bulk API Key Extraction via GSuite Google OAuth
================================================================

Flow per akun:
  1. Navigate to SiliconFlow CN/EN login page
  2. Click "Continue with Google" / Google OAuth button
  3. Login with GSuite account (email + password) on Google's auth page
  4. Handle any consent/permission screen
  5. After redirect back to SiliconFlow → navigate to API Keys page
  6. Create new API key → extract key
  7. Save results

Input: text file with one account per line:  email|password
       Or CLI: --accounts-file accounts.txt
       Or single: --email user@domain.com --pass password

Usage:
  python siliconflow_farm.py --accounts-file gsuite_accounts.txt --count 5 --show
  python siliconflow_farm.py --email user@gsuite.com --pass xxxxx --show --debug
"""

import sys
import os
import time
import json
import re
import random
import string
import threading
import time as _time
import csv as _csv

# ── Global TOS Click Queue ──────────────────────────────
# Only 1 browser clicks TOS at a time to avoid Google rate-limit detection
_tos_lock = threading.Lock()
_last_tos_click_time = 0
_TOS_COOLDOWN_SECONDS = 2  # Minimum seconds between TOS clicks (was 3, now 2 for balance)
_TOS_MAX_WAIT = 60  # Max seconds a browser will wait for TOS lock (prevent infinite block)

# ── File I/O Lock ─────────────────────────────────────
# Prevent race condition when multiple threads write to same file simultaneously
_file_lock = threading.Lock()

# ── Async Save Queue ───────────────────────────────────
# Save results in background thread so browser workers don't block on file I/O
_save_queue = None  # initialized lazily in _get_save_queue()
_BATCH_SIZE = 10      # flush to disk every N results
_BATCH_TIMEOUT = 30   # flush to disk every N seconds even if < N results

def _get_save_queue():
    """Lazy-init a background thread that processes save requests from a queue."""
    global _save_queue
    if _save_queue is None:
        import queue as _q
        _save_queue = _q.Queue()

        # In-memory batch buffer — accumulate saves, write once per batch
        _batch_buffer = []
        _last_flush_time = _time.time()

        def _flush_batch(buffer_list):
            """Write all accumulated results to disk in one go."""
            if not buffer_list:
                return
            try:
                # ── Merge ALL batched results at once into JSON ──
                existing = load_results()
                email_map = {r.get("email", ""): i for i, r in enumerate(existing)}
                for result in buffer_list:
                    em = result.get("email", "")
                    if em in email_map:
                        old_status = existing[email_map[em]].get("status", "")
                        new_status = result.get("status", "")
                        if old_status == "complete" and new_status != "complete":
                            continue  # keep existing success
                        existing[email_map[em]] = result
                    else:
                        existing.append(result)
                        email_map[em] = len(existing) - 1
                save_results(existing)

                # ── Append CSV rows ──
                for result in buffer_list:
                    append_csv(result.get("email", ""), result.get("api_key", ""),
                               result.get("status", "unknown"))

                # ── Sync master CSV once for entire batch ──
                for result in buffer_list:
                    try:
                        _sync_master_csv(result)
                    except Exception:
                        pass

                # ── Mark all done ──
                for result in buffer_list:
                    mark_email_done(result["email"])

                log("BATCH", f"Flushed {len(buffer_list)} results to disk")
            except Exception as e:
                log("BATCH", f"Flush error (non-critical): {e}")

        def _save_worker():
            """Background thread: drain save queue and batch-flush to disk."""
            while True:
                try:
                    result = _save_queue.get()
                    if result is _SENTINEL:
                        # Shutdown: flush remaining buffer before exit
                        _flush_batch(_batch_buffer)
                        _batch_buffer.clear()
                        break
                    _batch_buffer.append(result)
                    _save_queue.task_done()

                    # Flush conditions: batch full OR timeout elapsed
                    now = _time.time()
                    should_flush = (
                        len(_batch_buffer) >= _BATCH_SIZE or
                        (now - _last_flush_time) >= _BATCH_TIMEOUT
                    )
                    if should_flush:
                        _flush_batch(_batch_buffer)
                        _batch_buffer.clear()
                        _last_flush_time = now

                except Exception as e:
                    log("ASYNC", f"Save worker error (non-critical): {e}")

        _t = threading.Thread(target=_save_worker, daemon=True, name="SaveWorker")
        _t.start()
        log("SF", f"Background save thread started (batch={_BATCH_SIZE}, timeout={_BATCH_TIMEOUT}s)")
    return _save_queue

_SENTINEL = object()  # unique sentinel for queue shutdown

# ─ Path setup ──────────────────────────────────────
FARM_DIR = os.path.dirname(os.path.abspath(__file__))
if FARM_DIR not in sys.path:
    sys.path.insert(0, FARM_DIR)


# ─ Config ──────────────────────────────────────────
LOGIN_URL = "https://account.siliconflow.com/en/login"
API_KEYS_URL_COM = "https://cloud.siliconflow.com/account/ak"      # .com (EN)
API_KEYS_URL_CN = "https://cloud.siliconflow.cn/account/ak"       # .cn (CN)
# Will be resolved at runtime based on where we land after OAuth
_DATA_DIR = os.path.join(FARM_DIR, "data", "siliconflow")
os.makedirs(_DATA_DIR, exist_ok=True)
RESULTS_FILE = os.path.join(_DATA_DIR, "siliconflow_results.json")
CSV_FILE = os.path.join(_DATA_DIR, "siliconflow_keys.csv")
ACCOUNTS_FILE = os.path.join(_DATA_DIR, "gsuite_accounts.txt")

# CLI flags
COUNT = 1
PROXY = None
ACCOUNTS_PATH = None
SINGLE_EMAIL = None
SINGLE_PASS = None
HEADLESS = True
DEBUG = False
CONCURRENCY = 1

for i, arg in enumerate(sys.argv):
    if arg == "--count" and i + 1 < len(sys.argv):
        try: COUNT = int(sys.argv[i + 1])
        except: pass
    elif arg == "--proxy" and i + 1 < len(sys.argv):
        PROXY = sys.argv[i + 1]
    elif arg == "--accounts-file" and i + 1 < len(sys.argv):
        ACCOUNTS_PATH = sys.argv[i + 1]
    elif arg == "--email" and i + 1 < len(sys.argv):
        SINGLE_EMAIL = sys.argv[i + 1]
    elif arg == "--pass" and i + 1 < len(sys.argv):
        SINGLE_PASS = sys.argv[i + 1]
    elif arg == "--show":
        HEADLESS = False
    elif arg == "--debug":
        DEBUG = True
    elif arg == "--concurrency" and i + 1 < len(sys.argv):
        try: CONCURRENCY = max(1, int(sys.argv[i + 1]))
        except: pass


def log(step, msg):
    """Thread-safe log that gracefully handles closed stdout (e.g. GUI redirect ended)."""
    try:
        ts = time.strftime("%H:%M:%S")
        # Strip emoji/non-ASCII for Windows console compatibility
        safe_msg = msg.encode("ascii", "replace").decode("ascii")
        print(f"  [{ts}] [{step}] {safe_msg}", flush=True)
    except (OSError, IOError, ValueError):
        pass  # Stdout closed or redirected by GUI — silently ignore


# ════════════════════════════════════════════════════
# Human-like interaction helpers
# ════════════════════════════════════════════════════

import random as _rnd

_RND = _rnd.Random()


def human_delay(min_s=0.3, max_s=0.8):
    """Random pause to mimic human thinking/reading time."""
    time.sleep(_RND.uniform(min_s, max_s))


def human_type(page, text, min_delay=40, max_delay=120):
    """Type text with variable speed, occasional pauses and small mistakes.
    
    Simulates real typing: not uniform speed, sometimes pauses mid-word,
    occasionally types wrong then backspaces (5% chance per char).
    """
    for i, ch in enumerate(text):
        # Occasional longer pause (thinking)
        if _RND.random() < 0.08:
            time.sleep(_RND.uniform(0.3, 0.7))
        
        # Occasional typo + correction (~3% per character)
        if _RND.random() < 0.03 and ch.isalnum() and i > 2:
            # Type wrong char
            wrong = _RND.choice('qwertyuiopasdfghjklzxcvbnm')
            page.keyboard.press(wrong)
            time.sleep(_RND.uniform(50, 120) / 1000)
            # Backspace and correct
            page.keyboard.press("Backspace")
            time.sleep(_RND.uniform(80, 200) / 1000)
        
        page.keyboard.press(ch)
        time.sleep(_RND.uniform(min_delay, max_delay) / 1000)


def human_click(page, element, selector_desc=""):
    """Click with human-like pre-hover delay."""
    if not element:
        return False
    try:
        # Brief hover/pause before clicking
        time.sleep(_RND.uniform(0.15, 0.45))
        try:
            element.click()
        except Exception:
            # If normal click fails, try JS click
            page.evaluate("""(el) => { el.click(); }""", element)
        return True
    except Exception:
        return False


def safe_query(page, selector, browser_idx=0):
    """Safe DOM query that returns None on navigation/context errors instead of crashing."""
    try:
        return page.query_selector(selector)
    except Exception:
        return None


def safe_evaluate(page, expression, browser_idx=0):
    """Safe JS evaluate that returns None on context destruction."""
    try:
        return page.evaluate(expression)
    except Exception:
        return None


def smooth_scroll(page, pixels=None, direction="down", max_scrolls=3):
    """Scroll in small increments like a human would."""
    for _ in range(max_scrolls if pixels is None else 1):
        amount = pixels or _RND.randint(80, 250)
        dy = amount if direction == "down" else -amount
        page.mouse.wheel(0, dy)
        time.sleep(_RND.uniform(0.3, 0.6))


def screenshot(page, name):
    """Save screenshot if debug mode."""
    if not DEBUG:
        return
    path = os.path.join(FARM_DIR, "screenshots", f"sf_{name}.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        page.screenshot(path=path)
        log("SHOT", f"Saved {name}")
    except Exception:
        pass


# ════════════════════════════════════════════════════
# Results persistence
# ════════════════════════════════════════════════════

def load_results():
    """Load results from JSON. Returns list, never fails."""
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _backup_results():
    """Create a .bak copy of the current results file before writing.
    
    Prevents data loss if the write is interrupted (crash/kill/OOM).
    Keeps only the last 3 backups to avoid disk bloat.
    """
    if not os.path.exists(RESULTS_FILE):
        return
    import shutil as _shutil
    bak_dir = os.path.dirname(RESULTS_FILE)
    base = os.path.splitext(os.path.basename(RESULTS_FILE))[0]
    
    # Rotate: delete oldest .bak if we already have 3
    existing_baks = sorted(
        [f for f in os.listdir(bak_dir) if f.startswith(base + ".bak")],
        reverse=True
    )
    for old in existing_baks[2:]:
        try:
            os.remove(os.path.join(bak_dir, old))
        except OSError:
            pass
    
    # Create new backup with timestamp
    ts = time.strftime("%Y%m%d%H%M%S")
    bak_path = os.path.join(bak_dir, f"{base}.bak.{ts}")
    try:
        _shutil.copy2(RESULTS_FILE, bak_path)
    except (OSError, IOError):
        pass  # Non-critical — don't block the save


def save_results(results):
    """Save full results list to JSON. Creates backup first."""
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    _backup_results()
    with _file_lock:
        # Write to temp file first, then rename — atomic on most filesystems
        tmp_path = RESULTS_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        # Atomic replace
        os.replace(tmp_path, RESULTS_FILE)
    log("SAVE", f"Saved {len(results)} results to {RESULTS_FILE}")


def append_csv(email, api_key, status="complete"):
    """Append one row to the SiliconFlow keys CSV with a running count."""
    os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)
    file_exists = os.path.isfile(CSV_FILE)
    
    count = 1
    if file_exists:
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = _csv.reader(f)
            rows = list(reader)
            data_rows = [r for r in rows if len(r) >= 2 and r[0].lower() != "email"]
            count = len(data_rows) + 1
    
    with _file_lock:
        with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
            writer = _csv.writer(f)
        if not file_exists:
            writer.writerow(["#", "email", "api_key", "status", "timestamp"])
        writer.writerow([count, email, api_key, status, time.strftime("%Y-%m-%d %H:%M:%S")])


def _sync_master_csv(result):
    """Auto-sync a completed result into master_accounts.csv.

    Called after every successful save_result().
    - Adds/updates email with valid sk- key
    - Removes row if status changed from complete → failed (rare)
    - Preserves passwords from existing CSV rows
    """
    MASTER_CSV = os.path.join(_DATA_DIR, "master_accounts.csv")
    try:
        email = result.get("email", "").strip()
        api_key = result.get("api_key", "").strip()
        status = result.get("status", "").strip()

        if not email:
            return

        is_valid = (status == "complete" and api_key.startswith("sk-")
                    and len(api_key) > 10)

        # Load current CSV (or start fresh)
        rows = []
        pw_map = {}  # preserve known passwords
        if os.path.isfile(MASTER_CSV):
            with open(MASTER_CSV, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)  # skip header
                for r in reader:
                    if len(r) >= 2 and r[1].strip():
                        em = r[1].strip()
                        pw = r[2].strip() if len(r) > 2 else "kukunaga123"
                        key = r[3].strip() if len(r) > 3 else ""
                        st = r[4].strip() if len(r) > 4 else ""
                        if em:
                            pw_map[em] = pw
                            rows.append({"email": em, "password": pw,
                                         "api_key": key, "status": st})

        existing_emails = {r["email"] for r in rows}

        if is_valid:
            new_row = {
                "email": email,
                "password": pw_map.get(email, "kukunaga123"),
                "api_key": api_key,
                "status": "complete",
            }
            if email in existing_emails:
                rows = [new_row if r["email"] == email else r for r in rows]
            else:
                rows.append(new_row)
        elif email in existing_emails:
            # Failed result — remove or mark as NO_API_KEY
            rows = [r for r in rows if r["email"] != email]

        # Re-number + write (thread-safe with _file_lock)
        rows.sort(key=lambda r: r["email"])
        with open(MASTER_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["#", "email", "password", "api_key", "status"])
            for i, r in enumerate(rows, 1):
                writer.writerow([i, r["email"], r["password"],
                                 r["api_key"], r["status"]])

        log("SYNC", f"master_accounts.csv synced ({len(rows)} rows)")
    except Exception as sync_err:
        log("SYNC", f"Sync error (non-critical): {sync_err}")


def _do_save_result(result):
    """Actual file I/O for saving a result. Always runs inside _file_lock or on background thread.

    Merges with existing data, writes JSON + CSV + syncs master CSV in a SINGLE lock.
    """
    try:
        with _file_lock:
            # ── 1. Save/merge results.json ──
            results = load_results()

            existing_emails = {r.get("email", ""): i for i, r in enumerate(results)}

            if result.get("email", "") in existing_emails:
                idx = existing_emails[result["email"]]
                old_status = results[idx].get("status", "")
                new_status = result.get("status", "")

                if old_status == "complete" and new_status != "complete":
                    log("SAVE", f"Keeping existing 'complete' for {result['email']} (not downgrading to {new_status})")
                    return

                results[idx] = result
                log("SAVE", f"Updated result for {result['email']}: {old_status} -> {new_status}")
            else:
                results.append(result)
                log("SAVE", f"Appended new result for {result['email']}: {result.get('status','?')}")

            save_results(results)

            # ── 2. Append CSV (inside same lock) ──
            append_csv(result.get("email", ""), result.get("api_key", ""), result.get("status", "unknown"))

            # ── 3. Sync master CSV (inside same lock) ──
            _sync_master_csv(result)

        # ── 4. Mark done (quick append) ──
        mark_email_done(result["email"])
    except Exception as e:
        log("SAVE", f"Error saving result (non-critical): {e}")


def save_result(result):
    """Public API: enqueue result for async background save.

    Returns IMMEDIATELY — does not block the calling browser worker thread.
    The actual file I/O happens on the SaveWorker background thread.
    """
    q = _get_save_queue()
    q.put(result)


def mark_email_done(email):
    track_file = os.path.join(_DATA_DIR, "done_emails.txt")
    os.makedirs(_DATA_DIR, exist_ok=True)
    with _file_lock:
        with open(track_file, "a", encoding="utf-8") as f:
            f.write(email + "\n")


def load_done_emails():
    track_file = os.path.join(_DATA_DIR, "done_emails.txt")
    if os.path.exists(track_file):
        with open(track_file, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def _load_successful_emails():
    """Load set of emails that already have a valid sk- API key from results.json.

    These accounts will be SKIPPED during farming — no need to re-process.
    """
    results = load_results()
    successful = set()
    for r in results:
        status = r.get("status", "").strip()
        api_key = r.get("api_key", "").strip()
        email = r.get("email", "").strip()
        if status == "complete" and api_key.startswith("sk-") and len(api_key) > 10:
            successful.add(email)
    return successful


# ════════════════════════════════════════════════════
# Account loading — file format: email|password
# ════════════════════════════════════════════════════

def load_accounts(path, count=None):
    done = load_done_emails()
    # Also get emails that already have valid keys → skip these too
    has_key = _load_successful_emails()

    accounts = []
    skipped_done = 0
    skipped_haskey = 0

    if not os.path.exists(path):
        log("LOAD", f"Accounts file not found: {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                email = parts[0].strip()
                password = parts[1].strip()
                if not email:
                    continue
                # Skip: already processed (in done_emails.txt) but FAILED
                # We allow re-processing of failed accounts by NOT skipping them here.
                # Only skip done emails that succeeded — but done_emails doesn't track that,
                # so we rely on _load_successful_emails() for the smart skip.
                if email in done and email in has_key:
                    skipped_haskey += 1
                    continue
                # Skip: already has valid API key (success dedup)
                if email in has_key:
                    skipped_haskey += 1
                    log(f"LOAD", f"SKIP (has key): {email}")
                    continue
                # Skip: marked as done BUT also check if it was a failure
                # If it's in done_emails but NOT in has_key, let it through for retry
                if email in done:
                    skipped_done += 1
                    # Still allow retry — only skip if it has a key
                    pass

                accounts.append((email, password))
                if count and len(accounts) >= count:
                    break

    total_in_file = sum(1 for l in open(path, encoding="utf-8")
                        if l.strip() and "|" in l.strip() and not l.strip().startswith("#"))
    log("LOAD", f"Loaded {len(accounts)} accounts from {path}")
    log("LOAD", f"  File total: {total_in_file} | Skipped (has key): {skipped_haskey} | To farm: {len(accounts)}")

    return accounts


# ════════════════════════════════════════════════════
# Core flow: single account via Google OAuth
# ════════════════════════════════════════════════════

def run_single(email_addr, password, browser_idx=0):
    """Run full SiliconFlow farm flow via Google OAuth login.
    
    Args:
        email_addr: Full GSuite email (e.g. riyadifasalidia@gamaa.id)
        password: Account password (for Google sign-in)
        browser_idx: Index for logging
    
    Returns dict: {email, api_key, status, timestamp}
    """
    result = {
        "email": email_addr,
        "api_key": "",
        "status": "failed",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = context = page = None
        try:
            # Launch browser — fresh context per account to avoid session collision
            kwargs = {"headless": HEADLESS}
            if PROXY:
                kwargs["proxy"] = {"server": PROXY}

            browser = p.chromium.launch(**kwargs)

            # ── Fix #2: Rotate User-Agent per browser to reduce fingerprinting
            _user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            ]
            _ua = _user_agents[browser_idx % len(_user_agents)]

            context = browser.new_context(
                user_agent=_ua,
                viewport={"width": 1280 + (browser_idx * 37) % 200, "height": 800 + (browser_idx * 23) % 100},
                locale="en-SG",
                timezone_id="Asia/Singapore",
                geolocation={"latitude": 1.3521, "longitude": 103.8198},  # Singapore
                permissions=["geolocation"],
            )
            page = context.new_page()

            # ── Fix #4: Clear ALL cookies/storage before login ──
            # Prevents session collision between accounts on reused browser contexts
            try:
                context.clear_cookies()
                log(f"A{browser_idx}", "Cleared all cookies for fresh session")
            except Exception:
                pass  # non-critical, context might not be fully ready yet

            # Block unnecessary resources for speed + lower detection
            try:
                page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff2,woff,ttf,eot}", lambda route: route.abort())
            except Exception:
                pass

            # ── Step 1: Go to SiliconFlow login page ──
            log(f"A{browser_idx}", "Navigating to SiliconFlow login...")
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            human_delay(2.0, 4.0)
            screenshot(page, "step1_sf_login")

            # ── Step 2: Click "Continue with Google" ──
            log(f"A{browser_idx}", "Clicking Continue with Google...")
            
            google_clicked = False
            google_selectors = [
                'button:has-text("Continue with Google")',
                'button:has-text("Google")',
                'button:has-text("Sign in with Google")',
                '[value*="google" i]',
                'div[role="button"]:has-text("Google")',
                'a:has-text("Google")',
            ]
            
            for sel in google_selectors:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    human_click(page, btn, f"Google OAuth: {sel}")
                    google_clicked = True
                    log(f"A{browser_idx}", f"Clicked Google OAuth: {sel}")
                    break
            
            if not google_clicked:
                # JS fallback — find anything Google-related
                clicked_text = page.evaluate("""() => {
                    const els = document.querySelectorAll('button, a, [role="button"], div[class*="oauth"], div[class*="social"]');
                    for (const el of els) {
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (/google/i.test(txt)) {
                            el.click(); return txt;
                        }
                    }
                    // Check for any button with Google logo/image inside
                    const imgs = document.querySelectorAll('img');
                    for (const img of imgs) {
                        if (/google/i.test(img.src || img.alt || '')) {
                            const parent = img.closest('button, a, [role="button"], div');
                            if (parent) { parent.click(); return 'img-google-parent'; }
                        }
                    }
                    return null;
                }""")
                if clicked_text:
                    google_clicked = True
                    log(f"A{browser_idx}", f"Clicked via JS: {clicked_text}")

            if not google_clicked:
                raise Exception("'Continue with Google' button not found on SiliconFlow page")

            # Wait for redirect to Google sign-in page
            log(f"A{browser_idx}", "Waiting for Google sign-in page...")
            
            already_on_sf = False
            
            try:
                # Google redirects to accounts.google.com or similar
                page.wait_for_url("**/accounts.google.com/**", timeout=20000)
            except PWTimeout:
                # Maybe already logged in or different URL pattern
                current = page.url
                log(f"A{browser_idx}", f"URL after click: {current}")
                
                if "siliconflow" in current.lower():
                    # Still on SiliconFlow — check if we're actually logged in
                    # by looking for user menu / avatar / dashboard elements
                    is_logged_in = page.evaluate("""() => {
                        // Check for logged-in indicators: user menu, avatar, logout, etc.
                        const indicators = [
                            '[class*="avatar"]', '[class*="user"]', '[class*="menu"]',
                            '[class*="logout"]', '[class*="profile"]',
                            'a[href*="/me"]', 'a[href*="/account"]',
                            // SiliconFlow specific: sidebar nav items that only show when logged in
                            '[class*="sidebar"]', '[class*="nav-menu"]',
                        ];
                        for (const sel of indicators) {
                            const el = document.querySelector(sel);
                            if (el && el.offsetParent !== null) return true;
                        }
                        // Also check if we're NOT on the login page anymore
                        return !window.location.pathname.includes('/login') &&
                               !window.location.pathname.includes('/signin');
                    }""")
                    
                    if is_logged_in:
                        log(f"A{browser_idx}", "Already logged into SiliconFlow! Skipping Google OAuth.")
                        already_on_sf = True
                    else:
                        # Still on login page but Google click didn't redirect
                        # Maybe the button opened a popup/new window?
                        log(f"A{browser_idx}", "Still on login page, waiting a bit more...")
                        time.sleep(3)
                        
                        # Re-check URL after wait
                        current = page.url
                        if "accounts.google.com" in current or "google.com/signin" in current:
                            log(f"A{browser_idx}", "Now on Google sign-in page (late redirect)")
                        elif "siliconflow" in current.lower():
                            # Try clicking again — maybe first click was swallowed
                            log(f"A{browser_idx}", "Retrying Google OAuth click...")
                            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)
                            time.sleep(3)
                            for sel in google_selectors:
                                btn = page.query_selector(sel)
                                if btn and btn.is_visible():
                                    human_click(page, btn, f"Google OAuth retry: {sel}")
                                    time.sleep(4)
                                    break
                else:
                    # Some other domain, wait more
                    time.sleep(3)

            time.sleep(3)
            screenshot(page, "step2_google_signin")

            # ── Step 3: Handle Google Sign-In page ──
            if already_on_sf:
                log(f"A{browser_idx}", "Already authenticated, skipping Google login")
            else:
                current_url = page.url

                if "accounts.google.com" in current_url or "google.com/signin" in current_url:
                    log(f"A{browser_idx}", "On Google sign-in page, entering credentials...")
                    
                    google_login(page, email_addr, password, browser_idx)
                    human_delay(1.5, 3.0)
                    screenshot(page, "step3_google_loggedin")
            
            # ── Step 4: Wait for redirect back to SiliconFlow ──
            log(f"A{browser_idx}", "Waiting for redirect to SiliconFlow...")
            
            # Poll for URL change away from Google domain
            for wait_i in range(30):
                cur = page.url
                if "siliconflow" in cur.lower():
                    log(f"A{browser_idx}", f"Redirected to SiliconFlow: {cur[:80]}")
                    break
                # Check if stuck on some intermediate page
                if "consent" in cur.lower() or "accountselection" in cur.lower():
                    handle_google_consent_or_selection(page, browser_idx)
                time.sleep(2)
            else:
                # Timeout — check where we are
                final_url = page.url
                log(f"A{browser_idx}", f"After Google auth, final URL: {final_url}")
                screenshot(page, "step4_redirect_timeout")

            # Extra wait for full page load (SiliconFlow dashboard can be heavy)
            page.wait_for_load_state("networkidle", timeout=30000)
            human_delay(2.0, 4.0)  # Give extra time for SPA rendering
            screenshot(page, "step4_after_auth")

            # ── Step 4b: Verify we actually landed on SiliconFlow ──
            final_url = page.url
            log(f"A{browser_idx}", f"After OAuth, on URL: {final_url[:80]}")
            
            # If still stuck on Google (speedbump, TOS, etc.) — try to proceed or fail
            if "google.com" in final_url.lower() or "accounts.google" in final_url.lower():
                log(f"A{browser_idx}", f"WARNING: Still on Google page (not SiliconFlow yet): {final_url[:60]}")
                
                # ── TOS Queue: Acquire lock before clicking (prevent simultaneous TOS clicks) ──
                log(f"A{browser_idx}", "Waiting for TOS click queue...")
                with _tos_lock:
                    # Cooldown: wait since last TOS click by any browser
                    global _last_tos_click_time
                    _now = _time.time()
                    _wait = _TOS_COOLDOWN_SECONDS - (_now - _last_tos_click_time)
                    if _wait > 0:
                        log(f"A{browser_idx}", f"TOS cooldown: waiting {_wait:.1f}s...")
                        _time.sleep(_wait)
                    
                    log(f"A{browser_idx}", "TOS queue acquired, clicking now...")
                    
                    # Try clicking Continue/Agree buttons via simple selector first (fast)
                    tos_clicked = False
                    for sel in [
                        'button:has-text("I Understand")', 'button:has-text("I understand")',
                        'button:has-text("I Agree")', 'button:has-text("I agree")',
                        'button:has-text("Continue")', 'button:has-text("Agree")',
                        'button:has-text("Accept")', 'button:has-text("Lanjutkan")',
                        'button:has-text("Setuju")', 'a:has-text("Continue")',
                    ]:
                        btn = page.query_selector(sel)
                        if btn and btn.is_visible():
                            btn.click()
                            log(f"A{browser_idx}", f"Clicked TOS via selector: {sel}")
                            tos_clicked = True
                            time.sleep(3)
                            break
                    
                    if not tos_clicked:
                        # JS fallback for speedbump pages
                        try:
                            clicked = page.evaluate("""() => {
                                var words = ['i understand', 'i agree', 'i accept', 'continue', 'agree', 'accept', 'lanjutkan'];
                                var btns = document.querySelectorAll('button, [role="button"], a');
                                for (var i = 0; i < btns.length; i++) {
                                    var t = (btns[i].innerText || '').trim().toLowerCase();
                                    for (var w = 0; w < words.length; w++) {
                                        if (t === words[w] || t.startsWith(words[w]) || t.includes(words[w])) {
                                            if (btns[i].offsetParent !== null) {
                                                btns[i].click(); return t;
                                            }
                                        }
                                    }
                                }
                                return null;
                            }""")
                            if clicked:
                                log(f"A{browser_idx}", f"Clicked TOS via JS: {clicked}")
                                time.sleep(3)
                            else:
                                log(f"A{browser_idx}", "No TOS button found on page")
                        except Exception as e:
                            log(f"A{browser_idx}", f"TOS JS error: {str(e)[:80]}")
                    
                    # After first click, try AGAIN for second button (Lanjutkan/Continue)
                    # Google speedbump has 2-step: I Understand → Continue
                    time.sleep(1)
                    still_google = "google.com" in page.url.lower() or "accounts.google" in page.url.lower()
                    if still_google and tos_clicked:
                        log(f"A{browser_idx}", "Still on Google after 1st click, trying 2nd button...")
                        try:
                            for sel2 in [
                                'button:has-text("Continue")', 'button:has-text("Lanjutkan")',
                                'button:has-text("Accept")', 'a:has-text("Continue")',
                            ]:
                                btn2 = page.query_selector(sel2)
                                if btn2 and btn2.is_visible():
                                    btn2.click()
                                    log(f"A{browser_idx}", f"Clicked 2nd TOS button: {sel2}")
                                    time.sleep(4)
                                    break
                        except Exception as nav_err:
                            # "Execution context destroyed" = navigation in progress — this is GOOD!
                            err_str = str(nav_err).lower()
                            if "context" in err_str or "navigation" in err_str or "detached" in err_str:
                                log(f"A{browser_idx}", f"TOS click triggered navigation (expected): {str(nav_err)[:60]}")
                            else:
                                log(f"A{browser_idx}", f"2nd TOS click error: {str(nav_err)[:80]}")
                            # Wait for navigation to complete (reduced from 4s)
                            time.sleep(2)
                    
                    # Update global TOS cooldown timestamp
                    _last_tos_click_time = _time.time()
                    log(f"A{browser_idx}", "TOS queue released (lock freed)")
                    
                # Re-check URL after TOS attempt
                final_url = page.url
                log(f"A{browser_idx}", f"After TOS attempt, URL: {final_url[:80]}")
            
            # If STILL not on SiliconFlow — fail fast
            log(f"A{browser_idx}", f"DEBUG: Checking if siliconflow in URL: '{final_url.lower()[:50]}' -> {'siliconflow' in final_url.lower()}")
            if "siliconflow" not in final_url.lower():
                result["status"] = f"STUCK_ON_GOOGLE: {final_url[:60]}"
                log(f"A{browser_idx}", f"FATAL: Could not reach SiliconFlow. Stuck at: {final_url[:80]}")
                log(f"A{browser_idx}", "DEBUG: About to return STUCK_ON_GOOGLE result now!")
                return result
            else:
                log(f"A{browser_idx}", f"DEBUG: siliconflow FOUND in URL, continuing to API Keys page")
            
            if "siliconflow.com" in final_url and "siliconflow.cn" not in final_url:
                api_keys_target = API_KEYS_URL_COM
                log(f"A{browser_idx}", f"Using .com domain for API keys")
            else:
                api_keys_target = API_KEYS_URL_CN
                log(f"A{browser_idx}", f"Using .cn domain for API keys")
            
            log(f"A{browser_idx}", f"Navigating to API Keys page: {api_keys_target}")
            page.goto(api_keys_target, wait_until="domcontentloaded", timeout=30000)
            
            # Wait with relaxed timeout — some pages load slow
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except:
                log(f"A{browser_idx}", "networkidle timeout, continuing anyway...")
            
            human_delay(2.0, 4.0)  # Extra wait for API Keys page to fully render
            screenshot(page, "step5_apikeys")

            # ── Step 6: Create API Key & Extract (with retry) ──
            api_key = None
            for extract_attempt in range(3):
                api_key = create_api_key(page, browser_idx)
                if api_key:
                    break
                # Detect rate limit or error message on page
                rate_msg = page.evaluate("""() => {
                    var body = (document.body.innerText || document.body.textContent || '');
                    var msgs = ['rate limit', 'too many', '频率', '超出', 'exceed',
                               'maximum', 'quota', '限制', '次数', 'limit reach'];
                    for (var i=0; i<msgs.length; i++) {
                        if (body.toLowerCase().indexOf(msgs[i]) !== -1) return body.substring(body.indexOf(msgs[i]), body.indexOf(msgs[i])+80);
                    }
                    // Check for toast/notification error
                    var toasts = document.querySelectorAll('.ant-notification, .ant-message, [class*="toast"], [class*="notice"]');
                    for (var t=0; t<toasts.length; t++) {
                        var txt = (toasts[t].innerText || '').trim();
                        if (txt.length > 3 && (txt.toLowerCase().indexOf('limit') !== -1 || txt.indexOf('错误') !== -1 || txt.indexOf('失败') !== -1))
                            return '[TOAST] ' + txt;
                    }
                    return null;
                }""")
                if rate_msg:
                    log(f"A{browser_idx}", f"⚠ RATE LIMIT DETECTED: {rate_msg[:100]}")
                    result["status"] = f"RATE_LIMIT: {rate_msg[:60]}"
                    screenshot(page, "error_ratelimit")
                    break
                if extract_attempt < 2:
                    log(f"A{browser_idx}", f"Extract attempt {extract_attempt+1} failed, retrying in 3s...")
                    time.sleep(3)
                    # Try refreshing the API keys page
                    page.goto(page.url, wait_until="domcontentloaded", timeout=15000)
                    try: page.wait_for_load_state("networkidle", timeout=15000)
                    except: pass
                    human_delay(2.0, 3.0)

            if api_key:
                result["api_key"] = api_key
                result["status"] = "complete"
                log(f"A{browser_idx}", f"+ SUCCESS! API Key: {api_key[:35]}...")
            elif not result["status"].startswith("RATE_LIMIT"):
                result["status"] = "NO_API_KEY"
                log(f"A{browser_idx}", "Failed to extract API key after 3 attempts")
                screenshot(page, "error_noapikey")

        except PWTimeout as e:
            log(f"A{browser_idx}", f"Playwright Timeout: {e}")
            result["status"] = f"TIMEOUT: {e}"
            try: screenshot(page, "error_timeout")
            except: pass
        except Exception as e:
            log(f"A{browser_idx}", f"ERROR: {e}")
            result["status"] = f"ERROR: {e}"
            try: screenshot(page, "error_exception")
            except: pass
        finally:
            # ── Fix #3: Force cleanup — prevent resource leak across accounts
            try:
                if page:
                    page.close()  # close page first (frees memory)
            except: pass
            try:
                if context:
                    context.clear_cookies()
                    context.close()  # clear cookies then close context
            except: pass
            try:
                if browser:
                    browser.close()  # force close browser process
            except: pass

            # Force garbage collection to free RAM between accounts
            import gc
            gc.collect()
            if browser_idx % 5 == 0:
                log(f"A{browser_idx}", "Garbage collected after account batch")

    save_result(result)
    # mark_email_done() already called inside save_result() — no need to call again here
    return result


# ════════════════════════════════════════════════════
# Google Login Handler
# ════════════════════════════════════════════════════

def google_login(page, email_addr, password, browser_idx=0):
    """Handle Google sign-in form (email → password → possible challenges).
    
    Supports multiple Google sign-in page layouts:
      - Standard: email input → Next → password input → Next
      - Combined: email+password on one page
      - With username selector (multi-account)
    """
    
    # ── Enter email ──
    log(f"A{browser_idx}", f"Entering email: {email_addr}")
    
    email_input = (
        page.query_selector('input[type="email"]') or
        page.query_selector('input[name="identifier"]') or
        page.query_selector('input[name="email"]') or
        page.query_selector('input[id="identifierId"]') or
        page.query_selector('#identifierId') or
        page.query_selector('input[name="Email"]')
    )
    
    if email_input:
        try:
            email_input.click()
        except Exception as click_err:
            log(f"A{browser_idx}", f"Email input click note: {click_err}")
        email_input.fill("")
        human_delay(0.4, 1.0)  # Pause before typing (like reading the field)
        human_type(page, email_addr, min_delay=50, max_delay=130)
        human_delay(0.3, 0.7)
        
        # Press Enter or click Next
        next_btn = (
            page.query_selector('button:has-text("Next")') or
            page.query_selector('#identifierNext') or
            page.query_selector('button[type="submit"]')
        )
        if next_btn:
            human_click(page, next_btn, "Next after email")
        else:
            page.keyboard.press("Enter")
        
        log(f"A{browser_idx}", "Email submitted, waiting for password field...")
        human_delay(2.0, 4.0)  # Wait for password field to appear
    else:
        # Might be combined form or already at password step
        log(f"A{browser_idx}", "No email input found, might be on password step already")
    
    screenshot(page, "google_email_entered")
    
    # ── Enter password ──
    log(f"A{browser_idx}", "Entering password...")
    
    pw_input = (
        page.query_selector('input[type="password"]') or
        page.query_selector('input[name="Passwd"]') or
        page.query_selector('input[name="password"]') or
        page.query_selector('#password') or
        page.query_selector('input[name="Password"]')
    )
    
    # If password field not visible yet, wait a moment and retry
    if not pw_input:
        for retry in range(5):
            time.sleep(2)
            pw_input = (
                page.query_selector('input[type="password"]') or
                page.query_selector('input[name="Passwd"]') or
                page.query_selector('input[name="password"]')
            )
            if pw_input:
                break
    
    if pw_input:
        # Use JS fill instead of .click() + .fill() to avoid stale element errors
        # Google's password input can detach from DOM between query and click
        try:
            pw_input.click()
            log(f"A{browser_idx}", "Password input clicked OK")
        except Exception as click_err:
            log(f"A{browser_idx}", f"Password click failed, using JS fallback: {str(click_err)[:60]}")
            try:
                page.evaluate("(el) => { if(el) el.focus(); el.click(); }", pw_input)
            except Exception:
                pass
        
        human_delay(0.3, 0.6)
        
        # Try normal fill first, fallback to JS type
        try:
            pw_input.fill("")
        except Exception as fill_err:
            log(f"A{browser_idx}", f"Normal fill failed, trying JS: {str(fill_err)[:60]}")
            page.evaluate("""() => {
                var el = document.querySelector('input[type="password"]');
                if(el) { el.focus(); el.value = ''; }
            }""")
        
        human_delay(0.4, 0.8)
        human_type(page, password, min_delay=40, max_delay=100)
        human_delay(0.3, 0.6)
        
        # Submit — try multiple methods to ensure it actually clicks
        submit_btn = (
            page.query_selector('#passwordNext') or
            page.query_selector('button:has-text("Next")') or
            page.query_selector('button[type="submit"]')
        )
        if submit_btn:
            try:
                # Method 1: normal human click
                human_click(page, submit_btn, "Submit password")
                log(f"A{browser_idx}", "Password Next clicked (method 1: human_click)")
            except Exception as click_err:
                log(f"A{browser_idx}", f"human_click failed on Next button: {str(click_err)[:60]}")
                # Method 2: JS force click
                try:
                    page.evaluate("(el) => el.click();", submit_btn)
                    log(f"A{browser_idx}", "Password Next clicked (method 2: JS evaluate)")
                except Exception as js_err:
                    log(f"A{browser_idx}", f"JS click also failed: {str(js_err)[:60]}")
                    # Method 3: keyboard Enter (most reliable fallback)
                    page.keyboard.press("Enter")
                    log(f"A{browser_idx}", "Password submitted via keyboard Enter (method 3)")
            
            # Verify: wait a moment and check if we moved past password page
            # NOTE: context may be destroyed if click triggered navigation — that's OK!
            human_delay(1.5, 3.0)
            try:
                still_on_password = (
                    page.query_selector('input[type="password"]') is not None and 
                    page.query_selector('input[type="password"]').is_visible()
                )
            except Exception as verify_err:
                # "Execution context destroyed" = navigation happened (GOOD!)
                log(f"A{browser_idx}", f"Password submit triggered navigation: {str(verify_err)[:60]}")
                still_on_password = False
            
            if still_on_password:
                log(f"A{browser_idx}", "WARNING: Still on password page! Retrying with JS dispatch...")
                # Method 4: dispatchEvent (most aggressive)
                try:
                    page.evaluate("""() => {
                        var btn = document.querySelector('#passwordNext') || 
                                 Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === 'Next');
                        if(btn) { btn.dispatchEvent(new MouseEvent('click', {bubbles:true})); return true; }
                        return false;
                    }""")
                    log(f"A{browser_idx}", "Retried with dispatchEvent")
                    time.sleep(3)
                except Exception as e:
                    log(f"A{browser_idx}", f"dispatchEvent error: {e}")
                    # Last resort: focus button + press Enter
                    page.evaluate("""() => {
                        var btn = document.querySelector('#passwordNext') ||
                                 Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === 'Next');
                        if(btn) btn.focus();
                    }""")
                    page.keyboard.press("Enter")
                    log(f"A{browser_idx}", "Submitted via focus+Enter")
        else:
            log(f"A{browser_idx}", "No submit button found, using keyboard Enter only")
            page.keyboard.press("Enter")
        
        log(f"A{browser_idx}", "Password submitted, waiting for auth completion...")
    else:
        log(f"A{browser_idx}", "WARNING: No password input found!")
        # Try pressing Enter anyway
        page.keyboard.press("Enter")
    
    screenshot(page, "google_password_entered")
    
    # ── Handle post-login screens ──
    try:
        handle_post_login_challenges(page, browser_idx)
    except Exception as post_err:
        log(f"A{browser_idx}", "Post-login handler error (continuing): {post_err}")
        time.sleep(2)


def handle_post_login_challenges(page, browser_idx=0):
    """Handle various Google post-login screens: consent, 2FA prompts, etc."""
    time.sleep(2)
    
    for attempt in range(15):
        try:
            cur_url = page.url
            
            if "google.com" not in cur_url:
                log(f"A{browser_idx}", f"Left Google domain -> {cur_url[:60]}")
                return
            
            if attempt < 5:
                screenshot(page, f"postlogin_attempt_{attempt}")
            
            # ── Consent / permission screen (MULTI-LANGUAGE) ──
            consent_clicked = False
            
            for sel in [
                'button:has-text("Continue")',
                'button:has-text("Allow")',
                'button:has-text("Agree")',
                'button:has-text("Accept")',
                'button:has-text("Lanjutkan")',
                '#approve_select',
                '#submit_approve_access',
            ]:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    log(f"A{browser_idx}", f"Found consent button: {sel}, clicking...")
                    human_click(page, btn, sel)
                    consent_clicked = True
                    time.sleep(3)
                    break
            
            if consent_clicked:
                continue
            
            # ── Account selection screen ──
            acct_btns = page.query_selector_all('ul li[data-email], div[data-email], [role="link"][data-email]')
            if acct_btns:
                log(f"A{browser_idx}", f"Account selection screen ({len(acct_btns)} accounts)")
                acct_btns[0].click()
                time.sleep(3)
                continue
            
            # ── JS fallback ──
            if attempt in (2, 6, 10):
                js_action = page.evaluate("""() => {
                    var consentWords = [
                        'continue', 'allow', 'agree', 'accept', 'lanjutkan'
                    ];
                    var buttons = document.querySelectorAll('button');
                    for (var bi = 0; bi < buttons.length; bi++) {
                        var b = buttons[bi];
                        var txt = (b.innerText || '').trim().toLowerCase();
                        var isConsent = false;
                        for (var ci = 0; ci < consentWords.length; ci++) {
                            if (txt === consentWords[ci]) { isConsent = true; break; }
                        }
                        if (isConsent && b.offsetParent !== null && !b.disabled) {
                            b.click(); return 'clicked:' + txt;
                        }
                    }
                    
                    var submits = document.querySelectorAll(
                        'button[type="submit"], input[type="submit"], form button:not([disabled])'
                    );
                    for (var si = 0; si < submits.length; si++) {
                        var s = submits[si];
                        if (s.offsetParent !== null) { s.click(); return 'submit'; }
                    }
                    return null;
                }""")
                
                if js_action:
                    log(f"A{browser_idx}", f"Post-login JS action: {js_action}")
                    time.sleep(3)
            
            time.sleep(2)
        
        except Exception as e:
            if "context was destroyed" in str(e) or "navigation" in str(e).lower():
                log(f"A{browser_idx}", f"Navigation detected at attempt {attempt}, waiting...")
                time.sleep(4)
                continue
            elif attempt % 8 == 0:
                log(f"A{browser_idx}", f"Post-login error (attempt {attempt}): {e}")
    
    log(f"A{browser_idx}", "Post-login handling completed (or timed out)")


def handle_google_consent_or_selection(page, browser_idx=0):
    time.sleep(2)
    
    page.evaluate("""() => {
        for (var bi = 0; bi < document.querySelectorAll('button').length; bi++) {
            var b = document.querySelectorAll('button')[bi];
            var t = (b.innerText || '').trim().toLowerCase();
            if ((t === 'continue' || t === 'allow' || t === 'agree' ||
                 t === 'accept') && !b.disabled) {
                b.click(); return;
            }
        }
    }""")
    time.sleep(3)


# ════════════════════════════════════════════════════
# API Key Creation + Extraction
# ════════════════════════════════════════════════════

def _reveal_first_key(page, browser_idx):
    """Click the first eye-invisible icon on the page to reveal a key, then read it."""
    try:
        reveal_result = page.evaluate("""() => {
            var selectors = [
                '.anticon-eye-invisible',
                '[aria-label="eye-invisible"]',
                'span.anticon-eye-invisible',
                '.anticon[data-icon="eye-invisible"]',
                'svg[data-icon="eye-invisible"]'
            ];
            for (var si = 0; si < selectors.length; si++) {
                var els = document.querySelectorAll(selectors[si]);
                for (var i = 0; i < els.length; i++) {
                    if (els[i].offsetParent !== null) {
                        els[i].click();
                        return {clicked: true, method: selectors[si]};
                    }
                }
            }
            var allEls = document.querySelectorAll('[class*="eye-invis"], [aria-label*="eye"]');
            for (var k = 0; k < allEls.length; k++) {
                if (allEls[k].offsetParent !== null) {
                    allEls[k].click();
                    return {clicked: true, method: 'fallback'};
                }
            }
            return {clicked: false};
        }""")
        
        if not reveal_result.get("clicked"):
            log(f"A{browser_idx}", f"No eye icon found: {reveal_result}")
            return None
        
        log(f"A{browser_idx}", f"Eye icon clicked ({reveal_result.get('method')})")
        time.sleep(1.5)
        
        revealed_key = page.evaluate("""() => {
            var tds = document.querySelectorAll('td, span, div, code, input');
            for (var ti = 0; ti < tds.length; ti++) {
                var txt = ((tds[ti].innerText || tds[ti].textContent || tds[ti].value || '')).trim();
                if (txt.match(/^sk-[A-Za-z0-9]{30,}$/)) {
                    return txt;
                }
            }
            return null;
        }""")
        
        if revealed_key and len(revealed_key) >= 20 and "*" not in revealed_key:
            log(f"A{browser_idx}", f"*** REVEALED KEY: {revealed_key[:45]}... ***")
            return revealed_key
        else:
            log(f"A{browser_idx}", f"Key not fully revealed: {(str(revealed_key)[:40] if revealed_key else 'None')}")
            return None
            
    except Exception as e:
        log(f"A{browser_idx}", f"Reveal error: {e}")
        return None


def create_api_key(page, browser_idx=0):
    """Get exactly 1 API key for this account.
    
    Phase 0: If keys already exist on page -> reveal first one -> DONE (no new key created)
    Phase 1: No keys exist -> create new -> reveal via eye icon -> DONE
    
    Always returns exactly 1 key string or None.
    """
    try:
        # ── Phase 0: Check if API keys already exist ──
        existing_keys = page.evaluate("""() => {
            var cells = document.querySelectorAll('td, div[class*="key"], span');
            var masked = [];
            for (var i = 0; i < cells.length; i++) {
                var txt = (cells[i].innerText || cells[i].textContent || '').trim();
                if (/^sk-[a-z]\\*{2,}/i.test(txt) || /^sk-[A-Za-z0-9]{30,}$/.test(txt)) {
                    masked.push(txt);
                }
            }
            return {count: masked.length, samples: masked.slice(0, 5)};
        }""")
        
        key_count = existing_keys.get("count", 0)
        
        if key_count > 0:
            log(f"A{browser_idx}", f"Found {key_count} existing key(s) — reusing FIRST one")
            revealed = _reveal_first_key(page, browser_idx)
            if revealed:
                log(f"A{browser_idx}", f"Reused API Key: {revealed[:35]}...")
                return revealed
            else:
                log(f"A{browser_idx}", "Could not reveal existing key, will create new")
        else:
            log(f"A{browser_idx}", "No existing keys — creating new API Key")
        
        # ── Phase 1: Create new API Key ──
        log(f"A{browser_idx}", "Looking for Create API Key button...")

        create_clicked = False
        for sel in [
            'button:has-text("Create API Key")',
            'button:has-text("New API Key")',
            'button:has-text("\u521b\u5efa")',
            'button:has-text("\u65b0\u589e")',
            'button:has-text("Create New Key")',
            'button:has-text("Generate")',
            'a:has-text("Create")',
            '[class*="btn"]:has-text("Create")',
        ]:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                create_clicked = True
                log(f"A{browser_idx}", f"Clicked create: {sel}")
                break

        if not create_clicked:
            js_res = page.evaluate("""() => {
                for (const el of document.querySelectorAll('button, a[href], [role="button"]')) {
                    const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                    if (txt.includes('create') || txt.includes('new') ||
                        txt.includes('\u521b\u5efa') || txt.includes('\u65b0\u589e') ||
                        txt.includes('generate')) {
                        el.click(); return txt;
                    }
                }
                for (const el of document.querySelectorAll('[class*="add"], [class*="new"], [class*="create"]')) {
                    if (el.offsetParent !== null && el.offsetWidth > 0) {
                        el.click(); return el.className;
                    }
                }
                return null;
            }""")
            if js_res:
                create_clicked = True
                log(f"A{browser_idx}", f"Clicked create via JS: {js_res}")

        if not create_clicked:
            log(f"A{browser_idx}", "No create button found — trying existing keys")
            return _reveal_first_key(page, browser_idx)

        time.sleep(2)
        screenshot(page, "step6_create_modal")

        # Fill name input in modal
        name_filled = False
        for sel in [
            'input[placeholder*="Name"]',
            'input[placeholder*="name" i]',
            'input[placeholder*="\u540d\u79f0" i]',
            '[role="dialog"] input:not([type="hidden"])',
            '.ant-modal input:not([type="hidden"])',
            '[class*="modal"] input:not([type="hidden"])',
        ]:
            ni = page.query_selector(sel)
            if ni and ni.is_visible():
                rand_name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                try:
                    ni.click()
                except Exception:
                    page.evaluate("(el) => { if(el) el.focus(); }", ni)
                
                human_delay(0.3, 0.6)
                ni.fill("")
                human_delay(0.15, 0.3)
                page.keyboard.type(rand_name, delay=25)
                human_delay(0.2, 0.4)
                
                actual_val = ni.input_value() if hasattr(ni, 'input_value') else ""
                log(f"A{browser_idx}", f"Filled key name: {rand_name} (verified: {actual_val[:20]})")
                name_filled = True
                break

        if not name_filled:
            log(f"A{browser_idx}", "No name input found in modal")

        # Click Create button inside modal via JS dispatchEvent (Ant Design overlay-safe)
        click_result = page.evaluate("""() => {
            var allButtons = document.querySelectorAll('button');
            for (var bi = 0; bi < allButtons.length; bi++) {
                var btn = allButtons[bi];
                var txt = (btn.innerText || '').trim();
                if (txt === 'Create API Key' || txt.toLowerCase() === 'create api key') {
                    var rect = btn.getBoundingClientRect();
                    if (rect.width > 10 && rect.height > 10) {
                        ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(evt) {
                            btn.dispatchEvent(new MouseEvent(evt, {
                                bubbles: true, cancelable: true, view: window,
                                clientX: rect.left + rect.width / 2,
                                clientY: rect.top + rect.height / 2
                            }));
                        });
                        return {clicked: true, text: txt};
                    }
                }
            }
            return {clicked: false};
        }""")
        
        log(f"A{browser_idx}", f"Modal Create click: {click_result}")
        
        # Wait for modal to close (max 10s)
        for w in range(10):
            time.sleep(1)
            still_open = page.evaluate("""() => {
                var ms = document.querySelectorAll('.ant-modal-wrap');
                for (var i = 0; i < ms.length; i++) {
                    var r = ms[i].getBoundingClientRect();
                    if (ms[i].offsetParent !== null && r.width > 100 && r.height > 100) return true;
                }
                return false;
            }""")
            if not still_open:
                log(f"A{browser_idx}", f"Modal closed after {w+1}s")
                break
        
        time.sleep(1)
        
        # ── Extract key via eye icon (ONLY reliable method) ──
        revealed = _reveal_first_key(page, browser_idx)
        if revealed:
            log(f"A{browser_idx}", f"SUCCESS! API Key = {revealed[:45]}...")
            return revealed
        
        # Last resort fallbacks
        log(f"A{browser_idx}", "Eye icon failed, trying fallback extraction...")
        api_key = extract_key_from_page(page, browser_idx)
        return api_key

    except Exception as e:
        log(f"A{browser_idx}", f"Error creating API key: {e}")
        return None

def extract_key_from_page(page, browser_idx=0):
    """Extract API key string from current page DOM.
    
    SiliconFlow masks keys as sk-d****. Must click cell to copy to clipboard.
    """
    
    # Strategy 1: Look for unmasked key in inputs (unlikely but try first)
    found = page.evaluate("""() => {
        var inputs = document.querySelectorAll('input, textarea');
        for (var ii = 0; ii < inputs.length; ii++) {
            var val = inputs[ii].value || '';
            if (val.length > 20 && val.indexOf('sk-') === 0 && !val.includes('*')) return val;
        }
        return null;
    }""")
    if found and len(found) >= 20 and "*" not in found:
        log(f"A{browser_idx}", f"Extracted key from input: {found[:45]}...")
        return found
    
    # Strategy 2: Click the masked key cell to copy full key to clipboard
    # The column header says "API Key (click to copy)"
    log(f"A{browser_idx}", "Clicking masked key cell to copy...")
    
    click_result = page.evaluate("""() => {
        // Find table cells containing masked sk-* patterns
        var tds = document.querySelectorAll('td, div, span');
        var clicked = null;
        
        for (var ti = 0; ti < tds.length; ti++) {
            var el = tds[ti];
            var txt = (el.innerText || el.textContent || '').trim();
            
            // Match: sk-d*** or sk-t*** etc
            if (/^sk-[a-z]\\*{2,}[a-z]{4}$/i.test(txt)) {
                el.click();
                clicked = txt;
                break;
            }
        }
        
        return clicked;
    }""")
    
    if click_result:
        log(f"A{browser_idx}", f"Clicked key cell: {click_result}")
        time.sleep(1)
    
    # Strategy 3: Read clipboard using Playwright's built-in method
    for clip_attempt in range(3):
        try:
            # Method A: page.evaluate with clipboard API
            clip_text = page.evaluate("async () => { try { return await navigator.clipboard.readText(); } catch(e) { return ''; } }")
            if clip_text and len(clip_text) > 20 and "sk-" in clip_text and "*" not in clip_text:
                log(f"A{browser_idx}", f"Got key from clipboard (JS): {clip_text[:45]}...")
                return clip_text
        except Exception:
            pass
        
        # Method B: Playwright's native clipboard read (if permissions granted)
        try:
            clip_text = page.clipboard_text()
            if clip_text and len(clip_text) > 20 and "sk-" in clip_text:
                log(f"A{browser_idx}", f"Got key from clipboard (PW): {clip_text[:45]}...")
                return clip_text
        except Exception:
            pass
        
        time.sleep(0.5)
    
    # Strategy 4: Try intercepting the copy event to capture the real value
    log(f"A{browser_idx}", "Trying clipboard intercept...")
    
    intercepted = page.evaluate("""() => {
        // Set up a listener before clicking
        window.__capturedKey = null;
        
        // Find and click the key cell again
        var tds = document.querySelectorAll('td');
        for (var ti = 0; ti < tds.length; ti++) {
            var txt = (tds[ti].innerText || '').trim();
            if (/^sk-[a-z]\\*+[a-z]+$/i.test(txt)) {
                // Intercept the next copy
                var prevHandler = tds[ti].oncopy || null;
                tds[ti].addEventListener('copy', function(e) {
                    var data = e.clipboardData || window.clipboardData;
                    window.__capturedKey = data.getData('text');
                    e.preventDefault();
                    e.stopPropagation();
                    return false;
                }, true);
                
                tds[ti].click();
                return 'intercepted_click';
            }
        }
        return 'not_found';
    }""")
    
    if intercepted == "intercepted_click":
        time.sleep(1)
        captured = page.evaluate("() => window.__capturedKey")
        if captured and len(captured) > 20 and "sk-" in captured:
            log(f"A{browser_idx}", f"Intercepted key: {captured[:45]}...")
            return captured
    
    # Strategy 5: Use fetch/API to get keys directly
    log(f"A{browser_idx}", "Trying API endpoint for keys...")
    try:
        api_keys = page.evaluate("""async () => {
            try {
                var resp = await fetch('/api/v1/user/token', { credentials: 'include' });
                if (resp.ok) {
                    var data = await resp.json();
                    if (data.data && Array.isArray(data.data)) {
                        // Return most recent key
                        var tokens = data.data.filter(function(t) { return t.token; });
                        if (tokens.length > 0) return tokens[tokens.length - 1].token;
                    }
                }
            } catch(e) {}
            
            // Try other common endpoints
            var endpoints = [
                '/v1/user/tokens',
                '/api/v1/tokens',
                '/account/ak/list',
            ];
            
            for (var ei = 0; ei < endpoints.length; ei++) {
                try {
                    var r = await fetch(endpoints[ei], { credentials: 'include' });
                    if (r.ok) {
                        var d = await r.json();
                        var str = JSON.stringify(d);
                        var m = str.match(/sk-[A-Za-z0-9]{30,}/);
                        if (m) return m[0];
                    }
                } catch(e2) {}
            }
            
            return null;
        }""")
    
    except Exception as api_err:
        log(f"A{browser_idx}", f"API fetch error: {api_err}")
    
    # Last resort: return masked key indicator
    log(f"A{browser_idx}", "Could not extract full unmasked key")
    return None


def run_farm():
    """Main orchestrator for the SiliconFlow farm."""


# ════════════════════════════════════════════════════
# Main Orchestrator
# ════════════════════════════════════════════════════

def main():
    log("SF", "=" * 55)
    log("SF", "  SiliconFlow Farm — Bulk API Key via Google OAuth")
    log("SF", "=" * 55)
    log("SF", f"  Count: {COUNT} | Concurrency: {CONCURRENCY} | Headless: {HEADLESS}")

    accounts = []

    if SINGLE_EMAIL and SINGLE_PASS:
        accounts = [(SINGLE_EMAIL, SINGLE_PASS)]
        log("SF", f"  Single account mode: {SINGLE_EMAIL}")
    elif ACCOUNTS_PATH:
        accounts = load_accounts(ACCOUNTS_PATH, count=COUNT)
    else:
        default_path = ACCOUNTS_FILE
        if os.path.exists(default_path):
            accounts = load_accounts(default_path, count=COUNT)
        else:
            log("SF", "ERROR: No accounts source!")
            log("SF", "  Provide: --email user@domain.com --pass password")
            log("SF", "  Or:     --accounts-file accounts.txt")
            sys.exit(1)

    if not accounts:
        log("SF", "ERROR: No accounts available!")
        sys.exit(1)

    # Smart count cap: never process more than we have after dedup
    actual_count = min(len(accounts), COUNT) if COUNT else len(accounts)
    accounts = accounts[:actual_count]

    # Smart concurrency: don't open more browsers than needed
    actual_concurrency = min(CONCURRENCY, len(accounts)) if len(accounts) > 0 else 1

    log("SF", f"  Accounts to farm: {len(accounts)} (Count={COUNT}, after dedup from file)")
    log("SF", f"  Browser concurrency: {actual_concurrency} (requested={CONCURRENCY})")
    if len(accounts) < CONCURRENCY and CONCURRENCY > 1:
        log("SF", f"  ⚠ Only {len(accounts)} accounts — reduced browsers from {CONCURRENCY} to {actual_concurrency}")

    success_count = 0
    fail_count = 0

    def worker(idx, email_addr, pw):
        nonlocal success_count, fail_count
        try:
            result = run_single(email_addr, pw, browser_idx=idx)
            # Check status flexibly — "complete" or any status with a valid sk- key
            has_key = (result.get("status") == "complete" or
                      (str(result.get("api_key", "")).startswith("sk-") and
                       len(str(result.get("api_key", ""))) > 10))
            if has_key:
                success_count += 1
                try:
                    print(f"\n  + [{result['email']}] API Key: {result['api_key']}\n")
                except (OSError, IOError, ValueError):
                    pass
            else:
                fail_count += 1
                try:
                    print(f"  X [{result['email']}] Status: {result['status']}\n")
                except (OSError, IOError, ValueError):
                    pass
        except Exception as e:
            fail_count += 1
            # Guard against I/O errors on closed stdout (GUI redirect)
            err_msg = str(e)
            if "closed" not in err_msg.lower() and "I/O" not in err_msg.upper():
                log(f"W{idx}", f"Worker error: {e}")
            else:
                log(f"W{idx}", f"Worker error: I/O on closed file (stdout redirect ended)")

    if CONCURRENCY <= 1:
        for i, (email_addr, pw) in enumerate(accounts):
            worker(i, email_addr, pw)
    else:
        # ── Continuous Worker Pool ───────────────────────
        # Instead of batch-wait-batch, use a shared queue:
        # Each browser finishes → immediately picks next account.
        # No staggered delays, no waiting for slow browsers.
        
        import queue as _queue
        
        account_queue = _queue.Queue()
        for i, (email_addr, pw) in enumerate(accounts):
            account_queue.put((i, email_addr, pw))
        
        active_count = [0]  # mutable counter for active threads
        queue_lock = threading.Lock()
        all_done = threading.Event()
        
        def pool_worker(brow_idx):
            """Worker that pulls from shared queue until empty."""
            while True:
                try:
                    idx, email_addr, pw = account_queue.get_nowait()
                except _queue.Empty:
                    break
                
                with queue_lock:
                    log(f"A{brow_idx}", f"Processing: {email_addr}")
                
                worker(idx, email_addr, pw)
                account_queue.task_done()
            
            with queue_lock:
                active_count[0] -= 1
                if active_count[0] == 0 and account_queue.empty():
                    all_done.set()
                log(f"A{brow_idx}", "Browser finished all assigned tasks")
        
        # Launch initial workers = actual_concurrency (smart cap)
        # STAGGERED: don't launch all browsers at once — spread over 8-15s
        # This prevents Google from seeing 5 simultaneous logins from same IP
        active_count[0] = actual_concurrency
        threads = []
        stagger_delay = max(3, 15 // actual_concurrency) if actual_concurrency > 1 else 0
        for b in range(actual_concurrency):
            t = threading.Thread(target=pool_worker, args=(b,))
            t.daemon = True
            threads.append(t)
            t.start()
            log(f"SF", f"Browser {b} launched (stagger: +{stagger_delay}s next)")
            # Stagger: wait before launching next browser
            if b < actual_concurrency - 1 and stagger_delay > 0:
                time.sleep(stagger_delay)
        
        # Wait until ALL accounts processed
        account_queue.join()  # wait for queue to drain

        # Wait for remaining workers to finish their last task
        for t in threads:
            t.join(timeout=60)

    # ── Flush async save queue before reporting DONE ──
    # With batch mode, most data is already flushed. Just drain remaining.
    if _save_queue is not None:
        pending = _save_queue.qsize()
        if pending > 0:
            log("SF", f"Flushing {pending} remaining results to disk...")
        # Send sentinel → triggers final buffer flush inside SaveWorker
        _save_queue.put(_SENTINEL)
        time.sleep(0.5)  # give SaveWorker time to flush + exit

    log("SF", "=" * 55)
    log("SF", f"DONE! Success: {success_count} | Failed: {fail_count} | Total: {len(accounts)}")
    log("SF", f"Results saved to: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
