"""
Xiaomi CAPTCHA Solver Module
============================
Handles reCAPTCHA Enterprise solving for Xiaomi registration & login.

Priority chain (when auto_solve=True):
  1. CapSolver API (paid, ~$0.80/1000, works for Enterprise)
  2. NopeCHA extension (free, unreliable for Enterprise)
  3. Audio solver (free, doesn't work for Enterprise)
  4. Manual (user clicks checkbox in browser)

Usage:
    from xiaomi_captcha import wait_for_captcha
    solved = wait_for_captcha(page, timeout=300, auto_solve=True)
"""
import os
import time
import logging

# Import shared helpers from farm_headless
from farm_headless import log

# Optional: CapSolver (paid, works for Enterprise)
try:
    from capsolver_enterprise import solve_recaptcha_enterprise, check_balance as capsolver_balance
    CAPSOLVER_AVAILABLE = True
except ImportError:
    CAPSOLVER_AVAILABLE = False

# Optional: Audio solver (free, doesn't work for Enterprise)
try:
    from recaptcha_solver import solve_recaptcha_playwright
    AUDIO_SOLVER_AVAILABLE = True
except ImportError:
    AUDIO_SOLVER_AVAILABLE = False


def wait_for_captcha(page, timeout=300, auto_solve=False, show=True):
    """Wait for Google reCAPTCHA Enterprise to be solved.

    Xiaomi uses reCAPTCHA Enterprise (checkbox "I'm not a robot") wrapped in
    a miverify_wind overlay. We poll for the reCAPTCHA token to appear.

    Args:
        page: Playwright Page instance
        timeout: max seconds to wait for manual solve
        auto_solve: if True, try automated solvers first
        show: if True, browser is visible (user can solve manually)

    Returns:
        True if solved, False if failed/timeout
    """
    log("CAPTCHA", "Google reCAPTCHA Enterprise detected — waiting for solve...")

    # Try auto-solve first if requested
    if auto_solve:
        if _try_capsolver(page):
            return True
        if _try_nopecha():
            pass  # NopeCHA waits in background, fall through to manual poll
        elif _try_audio_solver(page):
            return True

    if not show:
        log("CAPTCHA", "Use --show flag to solve reCAPTCHA manually")
        return False

    log("CAPTCHA", ">>> CLICK 'I'm not a robot' CHECKBOX IN BROWSER! <<<")
    log("CAPTCHA", f"Waiting up to {timeout}s for reCAPTCHA to be solved...")

    # Poll for solved state
    deadline = time.time() + timeout
    while time.time() < deadline:
        token = page.evaluate("""() => {
            // Check for reCAPTCHA response token
            const ta = document.getElementById('g-recaptcha-response');
            if (ta && ta.value && ta.value.length > 10) return ta.value;

            // Check miverify state — if panel is gone, CAPTCHA was solved
            const wind = document.querySelector('.miverify_wind');
            if (wind) {
                const style = window.getComputedStyle(wind);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                    return 'solved';
                }
            }

            // Check if Next button is no longer loading (reCAPTCHA passed)
            const nextBtn = document.querySelector('button[type="submit"]');
            if (nextBtn && !nextBtn.disabled && !nextBtn.textContent.toLowerCase().includes('loading')) {
                return 'solved';
            }

            return null;
        }""")

        if token:
            log("CAPTCHA", "reCAPTCHA solved!")
            return True

        time.sleep(2)

    log("CAPTCHA", "reCAPTCHA timeout — not solved in time")
    return False


def _try_capsolver(page):
    """Priority 1: CapSolver API (paid, works for Enterprise)."""
    if not CAPSOLVER_AVAILABLE:
        return False

    log("CAPTCHA", "CapSolver detected — solving reCAPTCHA Enterprise via API...")
    bal = capsolver_balance()
    log("CAPTCHA", f"CapSolver balance: {bal}")

    if "Error" in bal or "$0.00" in bal:
        log("CAPTCHA", ">>> Insufficient balance — top up at https://capsolver.com <<<")
        log("CAPTCHA", ">>> Falling back to manual solve <<<")
        return False

    try:
        solved = solve_recaptcha_enterprise(page, timeout=120)
        if solved:
            log("CAPTCHA", "reCAPTCHA Enterprise solved by CapSolver!")
            return True
        log("CAPTCHA", "CapSolver failed — falling back")
    except Exception as e:
        log("CAPTCHA", f"CapSolver error: {e} — falling back")

    return False


def _try_nopecha():
    """Priority 2: NopeCHA extension (free, unreliable for Enterprise).

    Returns True if NopeCHA is active (waits in background).
    Does NOT solve — just lets the extension try while we poll.
    """
    nopecha_path = os.path.join(os.path.dirname(__file__), "nopecha-ext")
    if os.path.exists(os.path.join(nopecha_path, "manifest.json")):
        log("CAPTCHA", "NopeCHA extension active — waiting for auto-solve...")
        log("CAPTCHA", "Extension will detect & solve reCAPTCHA automatically")
        return True
    return False


def _try_audio_solver(page):
    """Priority 3: Audio challenge solver (free, doesn't work for Enterprise)."""
    if not AUDIO_SOLVER_AVAILABLE:
        log("CAPTCHA", "No auto-solver available — manual mode")
        return False

    log("CAPTCHA", "Attempting auto-solve via audio challenge...")
    try:
        solved = solve_recaptcha_playwright(page, timeout=60)
        if solved:
            log("CAPTCHA", "reCAPTCHA auto-solved!")
            return True
        log("CAPTCHA", "Auto-solve failed — falling back to manual")
    except Exception as e:
        log("CAPTCHA", f"Auto-solve error: {e} — falling back to manual")

    return False
