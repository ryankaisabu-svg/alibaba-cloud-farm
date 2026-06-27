"""
CapSolver reCAPTCHA Enterprise solver.
Integrates with CapSolver API to solve reCAPTCHA v2 Enterprise automatically.

Usage:
    from capsolver_enterprise import solve_recaptcha_enterprise
    token = solve_recaptcha_enterprise(page, api_key="CAP-...")
    # token is injected into page automatically

Cost: ~$0.80/1000 solves
"""
import requests
import time
import logging
import os

logger = logging.getLogger("capsolver")

# CapSolver API endpoints
CAPSOLVER_CREATE = "https://api.capsolver.com/createTask"
CAPSOLVER_RESULT = "https://api.capsolver.com/getTaskResult"

# Default API key — can be overridden via env var or function param
DEFAULT_API_KEY = os.environ.get(
    "CAPSOLVER_API_KEY",
    "",  # Set via CAPSOLVER_API_KEY env var
)


def solve_recaptcha_enterprise(page, api_key=None, site_key=None, site_url=None, timeout=120):
    """
    Solve reCAPTCHA v2 Enterprise using CapSolver API.

    Flow:
    1. Find reCAPTCHA site key on page (if not provided)
    2. Send task to CapSolver
    3. Poll for result (token)
    4. Inject token into page DOM
    5. Trigger callback

    Args:
        page: Playwright Page instance
        api_key: CapSolver API key (default: from env or hardcoded)
        site_key: reCAPTCHA site key (auto-detect if None)
        site_url: page URL (auto-detect if None)
        timeout: max seconds to wait for solution

    Returns:
        True if solved, False if failed
    """
    api_key = api_key or DEFAULT_API_KEY
    site_url = site_url or page.url

    # Auto-detect site key if not provided
    if not site_key:
        site_key = _detect_site_key(page)
        if not site_key:
            logger.error("Could not detect reCAPTCHA site key on page")
            return False

    logger.info(f"CapSolver: site_key={site_key[:20]}... url={site_url[:50]}...")

    # Step 1: Create task
    task_payload = {
        "clientKey": api_key,
        "task": {
            "type": "ReCaptchaV2EnterpriseTaskProxyLess",
            "websiteKey": site_key,
            "websiteURL": site_url,
        },
    }

    try:
        resp = requests.post(CAPSOLVER_CREATE, json=task_payload, timeout=30)
        data = resp.json()
    except Exception as e:
        logger.error(f"CapSolver createTask error: {e}")
        return False

    if data.get("errorId"):
        error = data.get("errorDescription", "Unknown error")
        logger.error(f"CapSolver error: {error}")
        if "balance" in error.lower() or "insufficient" in error.lower():
            logger.error(">>> Insufficient balance — top up at https://capsolver.com <<<")
        return False

    task_id = data.get("taskId")
    if not task_id:
        logger.error(f"CapSolver: no taskId in response: {data}")
        return False

    logger.info(f"CapSolver task created: {task_id}")
    logger.info("Waiting for solution (usually 10-30s)...")

    # Step 2: Poll for result
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        try:
            result_resp = requests.post(
                CAPSOLVER_RESULT,
                json={"clientKey": api_key, "taskId": task_id},
                timeout=30,
            )
            result = result_resp.json()
        except Exception as e:
            logger.warning(f"CapSolver poll error: {e}")
            continue

        status = result.get("status")
        if status == "ready":
            token = result.get("solution", {}).get("gRecaptchaResponse")
            if token:
                logger.info(f"CapSolver: token received ({len(token)} chars)")
                # Step 3: Inject token into page
                injected = _inject_token(page, token)
                if injected:
                    logger.info("CapSolver: token injected — reCAPTCHA solved!")
                    return True
                else:
                    logger.error("CapSolver: token received but injection failed")
                    return False
            else:
                logger.error("CapSolver: ready but no token in solution")
                return False

        elif status == "failed" or result.get("errorId"):
            error = result.get("errorDescription", "Unknown")
            logger.error(f"CapSolver task failed: {error}")
            return False

        # Still processing...
        logger.debug(f"CapSolver: status={status}, waiting...")

    logger.error(f"CapSolver: timeout after {timeout}s")
    return False


def _detect_site_key(page):
    """Auto-detect reCAPTCHA Enterprise site key from page."""
    try:
        # Check for data-sitekey attribute
        site_key = page.evaluate("""() => {
            // Method 1: data-sitekey attribute
            const el = document.querySelector('[data-sitekey]');
            if (el) return el.getAttribute('data-sitekey');

            // Method 2: grecaptcha render call
            const scripts = document.querySelectorAll('script');
            for (const s of scripts) {
                const match = s.textContent.match(/render['"\\s,]+['"]([0-9A-Za-z_-]{40})['"]/);
                if (match) return match[1];
            }

            // Method 3: iframe src with k= parameter
            const iframes = document.querySelectorAll('iframe[src*="recaptcha"]');
            for (const iframe of iframes) {
                const match = iframe.src.match(/[?&]k=([0-9A-Za-z_-]{40})/);
                if (match) return match[1];
            }

            // Method 4: search all frames
            for (const frame of document.querySelectorAll('iframe')) {
                const match = (frame.src || '').match(/[?&]k=([0-9A-Za-z_-]{40})/);
                if (match) return match[1];
            }

            return null;
        }""")

        if site_key:
            logger.info(f"Auto-detected site key: {site_key}")
            return site_key

        # Fallback: known Xiaomi site key
        return "6LeBM0ocAAAAAEwYcFUjtxpVbs-0rnbSVXBBXmh4"

    except Exception as e:
        logger.warning(f"Site key detection error: {e}, using fallback")
        return "6LeBM0ocAAAAAEwYcFUjtxpVbs-0rnbSVXBBXmh4"


def _inject_token(page, token):
    """
    Inject reCAPTCHA token into page DOM.

    Sets the g-recaptcha-response textarea and triggers the callback
    so the page thinks reCAPTCHA was solved.
    """
    try:
        result = page.evaluate("""(token) => {
            let success = false;

            // Method 1: Set textarea value + trigger callback
            const textarea = document.getElementById('g-recaptcha-response');
            if (textarea) {
                textarea.value = token;
                success = true;
            }

            // Method 2: Try to trigger reCAPTCHA callback
            try {
                if (typeof ___grecaptcha_cfg !== 'undefined') {
                    const clients = ___grecaptcha_cfg.clients;
                    for (const key of Object.keys(clients)) {
                        const client = clients[key];
                        // Look for callback function
                        const callbackPath = _findCallback(client);
                        if (callbackPath) {
                            callbackPath(token);
                            success = true;
                            break;
                        }
                    }
                }
            } catch(e) {}

            // Method 3: Dispatch event
            if (textarea) {
                textarea.dispatchEvent(new Event('input', {bubbles: true}));
                textarea.dispatchEvent(new Event('change', {bubbles: true}));
            }

            // Method 4: Try miverify callback (Xiaomi-specific)
            try {
                if (typeof window.onRecaptchaVerify === 'function') {
                    window.onRecaptchaVerify(token);
                    success = true;
                }
            } catch(e) {}

            // Method 5: Try generic callback
            try {
                if (typeof window.captchaCallback === 'function') {
                    window.captchaCallback(token);
                    success = true;
                }
            } catch(e) {}

            return success;

            function _findCallback(obj, depth) {
                depth = depth || 0;
                if (depth > 5) return null;
                for (const k of Object.keys(obj)) {
                    const v = obj[k];
                    if (typeof v === 'function' && k.length > 10) {
                        // Likely a callback function
                        return v;
                    }
                    if (typeof v === 'object' && v !== null && !Array.isArray(v)) {
                        const found = _findCallback(v, depth + 1);
                        if (found) return found;
                    }
                }
                return null;
            }
        }""", token)

        return result

    except Exception as e:
        logger.error(f"Token injection error: {e}")
        return False


def check_balance(api_key=None):
    """Check CapSolver account balance."""
    api_key = api_key or DEFAULT_API_KEY
    try:
        resp = requests.post(
            "https://api.capsolver.com/getBalance",
            json={"clientKey": api_key},
            timeout=10,
        )
        data = resp.json()
        if data.get("errorId"):
            return f"Error: {data.get('errorDescription', 'Unknown')}"
        balance = data.get("balance", 0)
        return f"${balance:.2f}"
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    print("CapSolver reCAPTCHA Enterprise Solver")
    print("=" * 50)
    print(f"API Key: {DEFAULT_API_KEY[:20]}...")
    print()
    print("Checking balance...")
    bal = check_balance()
    print(f"Balance: {bal}")
    print()
    if "Error" in bal or "$0.00" in bal:
        print(">>> Insufficient balance — top up at https://capsolver.com <<<")
        print(">>> Minimum deposit: ~$5 (enough for ~6250 solves) <<<")
    else:
        print("Ready to use!")
