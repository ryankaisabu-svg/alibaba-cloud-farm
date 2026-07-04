"""
core/browser_engine.py — Browser launch dispatch + context setup + anti-detection.

Extracted from farm_headless.py L2650-2804.
Handles: engine selection (chrome/firefox/webkit/camoufox/uc/rebrowser),
         context args per-engine, stealth, WebGL spoof, Firefox hang fallback.

Usage:
    from core.browser_engine import launch_browser_context
    browser, context, page = launch_browser_context(p, headless=True, browser="chrome")
"""

import sys
import os
import threading

# ─ Optional deps (same pattern as farm_headless.py) ──
try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False


# ─ Constants ──
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

LAUNCH_COMMON_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]

# JavaScript anti-detection script (Chromium-only)
ANTI_DETECT_JS = """
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
"""


def _log(step, msg):
    """Minimal log — avoids circular import with core/helpers.py."""
    import time
    ts = time.strftime("%H:%M:%S")
    try:
        print(f"  [{ts}] [{step}] {msg}", flush=True)
    except UnicodeEncodeError:
        safe = msg.encode("ascii", "replace").decode("ascii")
        print(f"  [{ts}] [{step}] {safe}", flush=True)


def _launch_engine(p, browser_name, headless, proxy_arg):
    """Launch browser by engine name. Returns (browser, use_chrome_ua, use_stealth,
    use_webgl_spoof, use_manual_fingerprint)."""
    use_chrome_ua = True
    use_stealth = True
    use_webgl_spoof = True
    use_manual_fingerprint = True

    if browser_name == "firefox":
        browser = p.firefox.launch(headless=headless, proxy=proxy_arg)
        use_chrome_ua = False
        use_stealth = False
        use_webgl_spoof = False
        _log("BROWSER", "Firefox engine (native fingerprint)")

    elif browser_name == "webkit":
        browser = p.webkit.launch(headless=headless, proxy=proxy_arg)
        use_chrome_ua = False
        use_stealth = False
        use_webgl_spoof = False
        _log("BROWSER", "WebKit engine (native fingerprint)")

    elif browser_name == "camoufox":
        try:
            from camoufox.sync_api import NewBrowser
            # Camoufox via NewBrowser — uses existing Playwright instance
            # Camoufox has built-in fingerprint spoofing — don't override anything
            browser = NewBrowser(p, headless=headless, proxy=proxy_arg)
            use_chrome_ua = False
            use_stealth = False
            use_webgl_spoof = False
            use_manual_fingerprint = False  # Camoufox handles all fingerprinting
            _log("BROWSER", "Camoufox launched (Firefox-based, built-in anti-detect)")
        except ImportError:
            _log("BROWSER", "Camoufox not installed — fallback to Chrome")
            browser = p.chromium.launch(headless=headless, channel="chrome",
                                        args=LAUNCH_COMMON_ARGS, proxy=proxy_arg)

    elif browser_name == "undetected-chromedriver":
        try:
            import undetected_chromedriver as uc  # noqa: F401
            _log("BROWSER", "undetected-chromedriver not Playwright-compatible — fallback to Chrome")
            browser = p.chromium.launch(headless=headless, channel="chrome",
                                        args=LAUNCH_COMMON_ARGS, proxy=proxy_arg)
        except ImportError:
            _log("BROWSER", "undetected-chromedriver not installed — fallback to Chrome")
            browser = p.chromium.launch(headless=headless, channel="chrome",
                                        args=LAUNCH_COMMON_ARGS, proxy=proxy_arg)

    elif browser_name == "rebrowser":
        try:
            from rebrowser_playwright import sync_playwright as rb_sync  # noqa: F401
            _log("BROWSER", "rebrowser-patches mode (Chromium with CDP leak patches)")
            browser = p.chromium.launch(headless=headless, channel="chrome",
                                        args=LAUNCH_COMMON_ARGS, proxy=proxy_arg)
        except ImportError:
            _log("BROWSER", "rebrowser-patches not installed — fallback to Chrome")
            browser = p.chromium.launch(headless=headless, channel="chrome",
                                        args=LAUNCH_COMMON_ARGS, proxy=proxy_arg)

    else:  # chrome (default)
        browser = p.chromium.launch(headless=headless, channel="chrome",
                                    args=LAUNCH_COMMON_ARGS, proxy=proxy_arg)
        _log("BROWSER", "Chrome Vanilla + playwright-stealth")

    return browser, use_chrome_ua, use_stealth, use_webgl_spoof, use_manual_fingerprint


def _build_context_args(browser_name, use_manual_fingerprint, use_chrome_ua):
    """Build context_args dict based on engine capabilities."""
    context_args = {}

    if use_manual_fingerprint:
        if use_chrome_ua:
            context_args["user_agent"] = CHROME_UA
        # Camoufox/Firefox rejects viewport with isMobile in Playwright 1.61+
        # Camoufox has built-in fingerprint spoofing — don't override viewport
        if browser_name not in ("camoufox", "firefox"):
            context_args["viewport"] = {"width": 1366, "height": 768}
            context_args["device_scale_factor"] = 1
        context_args["locale"] = "en-US"
        context_args["timezone_id"] = "America/New_York"
        if browser_name not in ("camoufox", "firefox"):
            context_args["permissions"] = ["geolocation", "notifications"]

    # Camoufox/Firefox: Playwright 1.61+ sends viewport.isMobile which Camoufox rejects
    if browser_name in ("camoufox", "firefox"):
        context_args["no_viewport"] = True

    return context_args


def _try_firefox_create(browser, context_args, timeout=15):
    """Try creating context+page for Firefox/Camoufox with hang detection.
    Returns (context, page, hung, error)."""
    result = {"context": None, "page": None, "error": None}

    def _try_create():
        try:
            result["context"] = browser.new_context(**context_args)
            result["page"] = result["context"].new_page()
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_try_create, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        return None, None, True, None
    if result["error"]:
        return None, None, True, result["error"]
    return result["context"], result["page"], False, None


def _chrome_context_args():
    """Full Chrome context args (used after Firefox hang fallback)."""
    return {
        "viewport": {"width": 1366, "height": 768},
        "device_scale_factor": 1,
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "permissions": ["geolocation", "notifications"],
        "user_agent": CHROME_UA,
    }


def launch_browser_context(p, headless=True, browser="chrome", proxy=None):
    """Launch browser, create context+page with anti-detection.

    Args:
        p: Playwright instance (from sync_playwright() context).
        headless: Run without visible window.
        browser: Engine name (chrome/firefox/webkit/camoufox/uc/rebrowser).
        proxy: Proxy URL string or None.

    Returns:
        (browser, context, page, browser_name_used)
        browser_name_used may differ from `browser` if Firefox/Camoufox hung
        and fell back to Chrome.

    Raises:
        Exception if browser launch fails entirely.
    """
    proxy_arg = {"server": proxy} if proxy else None
    if proxy_arg:
        _log("MAIN", f"Using proxy: {proxy}")

    browser_obj, use_chrome_ua, use_stealth, use_webgl_spoof, use_manual_fp = \
        _launch_engine(p, browser, headless, proxy_arg)

    context_args = _build_context_args(browser, use_manual_fp, use_chrome_ua)

    # Firefox/Camoufox: new_page() may hang — use timeout wrapper
    if browser in ("camoufox", "firefox"):
        ctx, pg, hung, err = _try_firefox_create(browser_obj, context_args, timeout=15)
        if hung:
            _log("BROWSER", f"Firefox/Camoufox new_page() hung/failed — fallback to Chrome")
            try:
                browser_obj.close()
            except Exception:
                pass
            # Fallback to Chrome
            browser_obj = p.chromium.launch(headless=headless, channel="chrome",
                                             args=LAUNCH_COMMON_ARGS, proxy=proxy_arg)
            context_args = _chrome_context_args()
            context = browser_obj.new_context(**context_args)
            page = context.new_page()
            use_stealth = True
            use_webgl_spoof = True
            browser = "chrome"
        else:
            context = ctx
            page = pg
    else:
        context = browser_obj.new_context(**context_args)
        page = context.new_page()

    # Apply playwright-stealth (Chromium only)
    if STEALTH_AVAILABLE and use_stealth:
        stealth = Stealth()
        stealth.apply_stealth_sync(context)

    # JavaScript anti-detection (Chromium-only — skip for Firefox/WebKit/Camoufox)
    if use_webgl_spoof:
        page.add_init_script(ANTI_DETECT_JS)

    return browser_obj, context, page, browser


def kill_chrome():
    """Kill all chrome.exe processes (Windows). Use with caution."""
    import subprocess
    subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'],
                   stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    _log("MAIN", "Chrome killed.")
