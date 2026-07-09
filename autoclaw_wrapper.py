#!/usr/bin/env python3
r"""
autoclaw_wrapper.py — Bridge between alibaba-cloud-farm GUI and autoclaw-autologin.

This wrapper is spawned as a subprocess by the AutoClawTab GUI. It:
  1. Starts the AutoClaw proxy server (port 31000 + callback 18432) in a thread
  2. Runs autoclaw_autologin.py batch login against the provided accounts file
  3. Reads tokens.json from the autoclaw-autologin project dir
  4. Writes normalized results to data/autoclaw/autoclaw_results.json
  5. Emits [STATS] lines for the GUI dashboard

Usage (called by GUI):
  python autoclaw_wrapper.py --accounts-file <path> [--headless] [--concurrent N]
  python autoclaw_wrapper.py --email <email> --pass <pw> [--headless]
  python autoclaw_wrapper.py --proxy-only   # just start proxy, no login
  python autoclaw_wrapper.py --stop          # stop running proxy

Requirements:
  - AutoClaw project at ./autoclaw/ (proxy.py, autoclaw_autologin.py, auth.py, config.py)
  - Python 3.13 global (for cloakbrowser + flask)
  - CloakBrowser binary at ~/.cloakbrowser/
"""
import sys
import os
import json
import time
import signal
import threading
import subprocess
import argparse

# Force UTF-8 stdout/stderr (Windows cp1252 can't encode emoji)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

# ── Paths ──────────────────────────────────────────
FARM_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(FARM_DIR, "data", "autoclaw")
RESULTS_FILE = os.path.join(DATA_DIR, "autoclaw_results.json")
ACCOUNTS_CSV = os.path.join(DATA_DIR, "autoclaw_accounts.csv")
# AutoClaw project files (now self-contained inside this project)
AUTOCLAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autoclaw")
PROXY_SCRIPT = os.path.join(AUTOCLAW_DIR, "proxy.py")
LOGIN_SCRIPT = os.path.join(AUTOCLAW_DIR, "autoclaw_autologin.py")

# Ensure autoclaw modules are importable (auth.py, config.py, etc.)
if AUTOCLAW_DIR not in sys.path:
    sys.path.insert(0, AUTOCLAW_DIR)

# tokens.json may be written to several locations depending on cwd when
# autoclaw_autologin.py runs. Search all known candidates.
_TOKENS_CANDIDATES = [
    os.path.join(AUTOCLAW_DIR, "tokens.json"),                      # subfolder (primary)
    os.path.join(os.path.expanduser("~"), "autoclaw-autologin", "tokens.json"),  # home clone (legacy)
    os.path.join(os.path.expanduser("~"), "tokens.json"),           # home root
    os.path.join(os.getcwd(), "tokens.json"),                       # process cwd
    os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "autoclaw"), "tokens.json"),  # project autoclaw dir (fallback)
]

def find_tokens_json():
    """Return the first existing tokens.json path, or None."""
    for p in _TOKENS_CANDIDATES:
        if os.path.isfile(p):
            return p
    # Last resort: search 2 levels up from AUTOCLAW_DIR
    d = AUTOCLAW_DIR
    for _ in range(3):
        cand = os.path.join(d, "tokens.json")
        if os.path.isfile(cand):
            return cand
        d = os.path.dirname(d)
    return None

TOKENS_FILE = find_tokens_json() or _TOKENS_CANDIDATES[0]

# Python 3.13 global (has flask, cloakbrowser, aiohttp, playwright)
PY313 = r"C:\Users\Dhipa\AppData\Local\Programs\Python\Python313\python.exe"

# Fallback: try system python if 3.13 not found
if not os.path.isfile(PY313):
    PY313 = sys.executable

PROXY_BASE = "http://localhost:31000"

# ── Ensure data dir exists ─────────────────────────
os.makedirs(DATA_DIR, exist_ok=True)


def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    pfx = {"INFO": "[i]", "OK": "[OK]", "ERR": "[!]", "DBG": "[?]", "WAIT": "..."}.get(level, " ")
    try:
        print(f"[{ts}] {pfx} {msg}", flush=True)
    except UnicodeEncodeError:
        # Fallback: strip non-ASCII if encoding still fails
        safe = f"[{ts}] {pfx} {msg}".encode("ascii", "replace").decode()
        print(safe, flush=True)


def emit_stats(queued=0, processing=0, created=0, done=0, failed=0, apikey=0):
    """Emit [STATS] line for GUI dashboard parser."""
    print(f"[STATS] queued={queued} processing={processing} created={created} "
          f"done={done} failed={failed} apikey={apikey}", flush=True)


# ── Results JSON management ────────────────────────

def load_results():
    """Load existing results. Returns list."""
    try:
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("accounts", []) if isinstance(data, dict) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_results(results):
    """Save results to JSON (atomic)."""
    tmp = RESULTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    os.replace(tmp, RESULTS_FILE)


def merge_token_into_results(token_entry):
    """Merge a token entry from tokens.json into our results.json.
    Uses normalized email for dedup (lowercase + strip).
    """
    from auth import normalize_email

    results = load_results()
    email = normalize_email(token_entry.get("email", ""))
    if not email:
        return

    access = token_entry.get("access_token", "")
    refresh = token_entry.get("refresh_token", "")
    user_id = token_entry.get("user_id", "")
    device_id = token_entry.get("device_id", "")

    # Remove existing entry for same email (normalized)
    results = [r for r in results if normalize_email(r.get("email", "")) != email]

    # Add new entry
    has_token = bool(access and access.strip())
    results.append({
        "email": email,
        "api_key": access,  # reuse api_key field for consistency with GUI
        "access_token": access,
        "refresh_token": refresh,
        "user_id": str(user_id),
        "device_id": device_id,
        "status": "complete" if has_token else "no_token",
        "timestamp": int(time.time()),
    })

    save_results(results)


def sync_from_tokens():
    """Full reconcile: tokens.json is SINGLE source of truth.
    Rebuilds results.json as an exact mirror of tokens.json.
    - Adds accounts from tokens.json not yet in results.json
    - Removes accounts from results.json that no longer exist in tokens.json
    - Updates fields for existing accounts
    """
    from auth import normalize_email

    # Re-scan: tokens.json may appear after first successful login
    tokens_path = find_tokens_json()
    if not tokens_path:
        log("tokens.json not found in any known location", "ERR")
        return 0

    try:
        with open(tokens_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"Failed to read tokens.json: {e}", "ERR")
        return 0

    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    if not accounts:
        log("No accounts in tokens.json", "WAIT")
        return 0

    # Build normalized email set from tokens.json
    token_emails = set()
    for entry in accounts:
        email = normalize_email(entry.get("email", ""))
        if email:
            token_emails.add(email)

    # Load existing results, remove entries not in tokens.json (stale cleanup)
    results = load_results()
    results = [r for r in results if normalize_email(r.get("email", "")) in token_emails]

    # Merge/update all token entries into results
    for entry in accounts:
        email = normalize_email(entry.get("email", ""))
        if not email:
            continue
        # Remove existing entry for same email
        results = [r for r in results if normalize_email(r.get("email", "")) != email]
        # Add fresh entry from tokens.json
        access = entry.get("access_token", "")
        results.append({
            "email": email,
            "api_key": access,
            "access_token": access,
            "refresh_token": entry.get("refresh_token", ""),
            "user_id": str(entry.get("user_id", "")),
            "device_id": entry.get("device_id", ""),
            "status": "complete" if access and access.strip() else "no_token",
            "timestamp": int(time.time()),
        })

    save_results(results)
    log(f"Synced {len(results)} accounts from {tokens_path}", "OK")
    return len(results)

_proxy_proc = None
_proxy_thread = None


def is_proxy_running():
    """Check if proxy is healthy via /health endpoint."""
    import urllib.request
    try:
        r = urllib.request.urlopen(f"{PROXY_BASE}/health", timeout=3)
        return r.status == 200
    except Exception:
        return False


def start_proxy():
    """Start the AutoClaw proxy server in background thread."""
    global _proxy_proc

    if is_proxy_running():
        log("Proxy already running", "OK")
        return True

    if not os.path.isfile(PROXY_SCRIPT):
        log(f"proxy.py not found at {PROXY_SCRIPT}", "ERR")
        return False

    log("Starting AutoClaw proxy on :31000...", "WAIT")

    # Start proxy as subprocess (it runs Flask blocking server)
    _proxy_proc = subprocess.Popen(
        [PY313, PROXY_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=AUTOCLAW_DIR,
    )

    # Wait for proxy to be ready (max 20s)
    for i in range(40):
        if is_proxy_running():
            log(f"Proxy ready (took {i*0.5:.1f}s)", "OK")
            return True
        time.sleep(0.5)

    log("Proxy failed to start within 20s", "ERR")
    # Print proxy output for debugging
    if _proxy_proc and _proxy_proc.poll() is not None:
        out = _proxy_proc.stdout.read(2000) if _proxy_proc.stdout else ""
        log(f"Proxy output: {out}", "ERR")
    return False


def stop_proxy():
    """Stop the proxy subprocess."""
    global _proxy_proc
    if _proxy_proc:
        log("Stopping proxy...", "WAIT")
        _proxy_proc.terminate()
        try:
            _proxy_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proxy_proc.kill()
        _proxy_proc = None
        log("Proxy stopped", "OK")


# ── Batch login ────────────────────────────────────

def load_accounts_file(path):
    """Load email:password pairs from file (one per line, # comments).

    Accepts both separators:
      - email:password  (colon, standard)
      - email|password  (pipe, GSuite export format)
    """
    if not os.path.isfile(path):
        log(f"Accounts file not found: {path}", "ERR")
        return []

    accounts = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # Accept both : and | as separator
                if "|" in line:
                    parts = line.split("|", 1)
                elif ":" in line:
                    parts = line.split(":", 1)
                else:
                    continue
                if len(parts) == 2 and parts[0] and parts[1]:
                    accounts.append(f"{parts[0]}:{parts[1]}")
    return accounts


def run_batch_login(accounts, headless=True, concurrent=1, proxy_list=None,
                    max_attempts=3, quiet=False):
    """Run autoclaw_autologin.py batch login via subprocess.

    Returns: list of result dicts (from our results.json after sync).
    proxy_list: optional path to file with proxy URLs (one per line) for IP rotation.
    max_attempts: max login attempts per account on 630014/stale-state (default 3).
    quiet: suppress per-account logs, show progress counter only.
    """
    if not os.path.isfile(LOGIN_SCRIPT):
        log(f"autoclaw_autologin.py not found at {LOGIN_SCRIPT}", "ERR")
        return []

    # Build args
    args = [PY313, LOGIN_SCRIPT]
    # Pass accounts as positional args (email:password pairs)
    args.extend(accounts)
    args.extend(["--headless"] if headless else [])
    args.extend(["--concurrent", str(concurrent)])
    args.extend(["--max-attempts", str(max_attempts)])
    args.append("--force")  # re-login even if exists (GUI manages dedup)
    if quiet:
        args.append("--quiet")
    if proxy_list and os.path.isfile(proxy_list):
        args.extend(["--proxy-list", proxy_list])

    pl = f", proxy_list={proxy_list}" if proxy_list else ""
    log(f"Running batch login: {len(accounts)} accounts, "
        f"{'headless' if headless else 'visible'}, concurrent={concurrent}, "
        f"max_attempts={max_attempts}{pl}")

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=AUTOCLAW_DIR,
        encoding="utf-8",
        errors="replace",
    )

    # Stream output, detect new tokens
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        line = line.rstrip()
        print(line, flush=True)

        # Detect successful login
        if "Token saved" in line or "Login success" in line or "login_done" in line:
            # Sync from tokens.json periodically
            sync_from_tokens()

    proc.wait()
    rc = proc.returncode
    log(f"Batch login finished (exit={rc})")

    # Final sync
    sync_from_tokens()
    return load_results()


# ── Main ───────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AutoClaw wrapper for farm GUI")
    parser.add_argument("--accounts-file", help="File with email:password per line")
    parser.add_argument("--email", help="Single email")
    parser.add_argument("--pass", dest="password", help="Single password")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--concurrent", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=None,
                        help="Alias for --concurrent (GUI compatibility)")
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Max login attempts per account on 630014/stale-state (default 3)")
    parser.add_argument("--count", type=int, default=None,
                        help="Max accounts to process (GUI compatibility)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Quiet mode: suppress per-account logs, show progress counter")
    parser.add_argument("--show", action="store_true", help="Show browser (visible)")
    parser.add_argument("--proxy-only", action="store_true", help="Only start proxy")
    parser.add_argument("--stop", action="store_true", help="Stop proxy and exit")
    parser.add_argument("--sync", action="store_true", help="Only sync tokens→results")
    parser.add_argument("--proxy-list", default=None, metavar="FILE",
                        help="File with proxy URLs (one per line) for browser IP rotation")
    args = parser.parse_args()

    # ── Stop mode ──
    if args.stop:
        stop_proxy()
        return

    # ── Sync-only mode ──
    if args.sync:
        n = sync_from_tokens()
        results = load_results()
        has = sum(1 for r in results if r.get("access_token", "").strip())
        emit_stats(queued=0, processing=0, created=n, done=len(results),
                   failed=0, apikey=has)
        return

    # ── Proxy-only mode ──
    if args.proxy_only:
        log("Proxy-only mode. Starting proxy...", "OK")
        if start_proxy():
            log("Proxy running. Press Ctrl+C to stop.", "OK")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                stop_proxy()
        return

    # ── Normal mode: start proxy + run login ──
    headless = not args.show

    # Resolve concurrency alias: --concurrency takes priority if set
    concurrent = args.concurrent
    if args.concurrency is not None:
        concurrent = args.concurrency

    # 1. Start proxy
    if not start_proxy():
        log("Cannot start proxy. Aborting.", "ERR")
        emit_stats(failed=1)
        return

    # 2. Load accounts
    if args.email and args.password:
        accounts = [f"{args.email}:{args.password}"]
    elif args.accounts_file:
        accounts = load_accounts_file(args.accounts_file)
    else:
        log("No accounts specified. Use --accounts-file or --email/--pass", "ERR")
        emit_stats(failed=1)
        return

    if not accounts:
        log("No valid accounts found", "ERR")
        emit_stats(failed=1)
        return

    # Apply --count limit (GUI sends max accounts to process)
    if args.count is not None and args.count > 0:
        accounts = accounts[:args.count]
        log(f"Limited to {len(accounts)} accounts (--count)")

    # 3. Emit initial stats
    # Sync tokens.json -> results.json FIRST so dedup uses latest data
    sync_from_tokens()
    from auth import normalize_email, load_tokens
    results_before = load_results()
    # Dedup from BOTH tokens.json AND results.json (tokens.json is source of truth)
    tokens_data = load_tokens()
    token_emails = {normalize_email(a.get("email", ""))
                    for a in tokens_data.get("accounts", [])
                    if a.get("access_token", "").strip()}
    result_emails = {normalize_email(r.get("email", ""))
                     for r in results_before if r.get("access_token", "").strip()}
    emails_before = token_emails | result_emails
    pending = [a for a in accounts
               if normalize_email(a.split(":", 1)[0]) not in emails_before]

    emit_stats(queued=len(pending), processing=0, created=len(emails_before),
               done=len(results_before), failed=0, apikey=len(emails_before))

    log(f"Total: {len(accounts)} | Already have token: {len(accounts)-len(pending)} | "
        f"To process: {len(pending)}")

    if not pending:
        log("All accounts already have tokens. Use --force or clear tokens.json to re-login.", "OK")
        emit_stats(queued=0, done=len(results_before), apikey=len(emails_before))
        return

    # 4. Run batch login
    emit_stats(queued=len(pending), processing=len(pending),
               created=len(emails_before), done=len(results_before))

    results = run_batch_login(pending, headless=headless, concurrent=concurrent,
                              proxy_list=args.proxy_list,
                              max_attempts=args.max_attempts,
                              quiet=args.quiet)

    # 5. Final stats
    results_after = load_results()
    has_token = sum(1 for r in results_after if r.get("access_token", "").strip())
    no_token = len(results_after) - has_token

    emit_stats(queued=0, processing=0, created=has_token,
               done=len(results_after), failed=no_token, apikey=has_token)

    log(f"Done! Total accounts: {len(results_after)} | With token: {has_token} | "
        f"Without: {no_token}", "OK")

    # 6. Stop proxy (clean shutdown)
    stop_proxy()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Interrupted by user", "WAIT")
        stop_proxy()
    except Exception as e:
        log(f"Fatal: {e}", "ERR")
        stop_proxy()
        sys.exit(1)
