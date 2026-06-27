"""
Xiaomi Login & API Key Extraction Module

Handles Xiaomi account login and API key extraction from the Xiaomi MiMo platform.
Extracted from xiaomi_farm.py as part of modular refactoring.

Functions:
    login_xiaomi(page, email, password) - Login to Xiaomi account
    get_api_key(page, email, password)  - Login + navigate to API key page + create + extract key
"""

import os
import sys
import time
import re

from farm_headless import log, screenshot
from xiaomi_captcha import wait_for_captcha

XIAOMI_APIKEY_URL = "https://platform.xiaomimimo.com/console/plan-manage"
XIAOMI_BALANCE_URL = "https://platform.xiaomimimo.com/console/balance"

DEBUG = "--debug" in sys.argv


def login_xiaomi(page, email, password):
    """Login to Xiaomi account after registration."""
    log("LOGIN", f"Logging in as {email}...")

    # We should already be on login page after OTP verification redirect
    # If not, navigate to login
    current_url = page.url
    if "login" not in current_url.lower() and "account.xiaomi.com" not in current_url:
        login_url = (
            "https://account.xiaomi.com/fe/service/login?_group=DEFAULT"
            "&sid=api-platform"
            "&callback=https%3A%2F%2Fplatform.xiaomimimo.com%2Fsts"
            "&followup=https%3A%2F%252F%252Fplatform.xiaomimimo.com%252Fconsole%252Fbalance"
            "&_locale=en_US"
        )
        page.goto(login_url, wait_until="networkidle", timeout=60000)
        time.sleep(2)

    if DEBUG:
        screenshot(page, "xiaomi_06_login_page.png")

    # Fill email
    email_selectors = [
        'input[placeholder*="Email"]',
        'input[placeholder*="Phone"]',
        'input[placeholder*="Account"]',
        'input[name="user"]',
        'input[type="text"]',
    ]
    for sel in email_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.fill(email)
                log("LOGIN", f"Email filled via: {sel}")
                break
        except:
            continue

    # Fill password
    pw_selectors = [
        'input[type="password"]',
        'input[name="password"]',
        'input[placeholder*="Password"]',
    ]
    for sel in pw_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.fill(password)
                log("LOGIN", f"Password filled via: {sel}")
                break
        except:
            continue

    # Check agreement
    try:
        checkbox = page.query_selector('input[type="checkbox"]')
        if checkbox and not checkbox.is_checked():
            checkbox.click()
            log("LOGIN", "Checked agreement checkbox")
    except:
        pass

    time.sleep(0.5)

    # Click Sign in
    signin_selectors = [
        'button:has-text("Sign in")',
        'button[type="submit"]',
        'button.mi-button--primary:not(:disabled)',
    ]
    for sel in signin_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                log("LOGIN", f"Clicked sign in: {sel}")
                break
        except:
            continue

    # Wait for login to complete (redirect to platform)
    log("LOGIN", "Waiting for login redirect...")
    for i in range(30):  # 30 seconds
        time.sleep(1)
        url = page.url
        if "platform.xiaomimimo.com" in url or "console" in url:
            log("LOGIN", f"Login successful! Redirected to: {url[:80]}")
            time.sleep(2)
            return True
        if "captcha" in page.content().lower() or "miverify" in page.content().lower():
            log("LOGIN", "CAPTCHA detected during login — waiting for solve...")
            wait_for_captcha(page, timeout=120)

    log("LOGIN", f"Login may have failed. Current URL: {page.url[:80]}")
    if DEBUG:
        screenshot(page, "xiaomi_06_login_result.png")
    return False


def get_api_key(page, email, password):
    """Login + navigate to API key page + create + extract key."""
    # Step 1: Login
    logged_in = login_xiaomi(page, email, password)

    if not logged_in:
        log("LOGIN", "Login failed — cannot get API key")
        return None

    # Step 2: Navigate to API key management page
    log("API", "Navigating to API key page...")
    page.goto(XIAOMI_APIKEY_URL, wait_until="networkidle", timeout=60000)
    time.sleep(3)

    if DEBUG:
        screenshot(page, "xiaomi_07_apikey_page.png")

    # Step 3: Look for existing API key
    page_content = page.content()
    api_key_patterns = [
        r'(sk-[a-zA-Z0-9]{20,})',
        r'(API[_\s]*Key[:\s]+[a-zA-Z0-9\-]{20,})',
        r'([a-f0-9]{32,64})',
    ]

    for pattern in api_key_patterns:
        match = re.search(pattern, page_content)
        if match:
            key = match.group(1)
            log("API", f"Existing API key found: {key[:20]}...")
            return key

    # Step 4: Try to create new API key
    log("API", "No existing key found — creating new one...")
    create_selectors = [
        'button:has-text("Create")',
        'button:has-text("Generate")',
        'button:has-text("New")',
        'button:has-text("Add")',
        'a:has-text("Create")',
        'a:has-text("Generate")',
        'button:has-text("API")',
    ]

    for sel in create_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                log("API", f"Clicked: {sel}")
                time.sleep(3)
                break
        except:
            continue

    if DEBUG:
        screenshot(page, "xiaomi_08_apikey_create.png")

    # Step 5: Check for API key after creation
    page_content = page.content()
    for pattern in api_key_patterns:
        match = re.search(pattern, page_content)
        if match:
            key = match.group(1)
            log("API", f"New API key created: {key[:20]}...")
            return key

    # Step 6: Try looking for key in input/copy fields
    key_input_selectors = [
        'input[readonly]',
        'input[value*="sk-"]',
        'input[class*="key"]',
        'input[class*="token"]',
        'span[class*="key"]',
        'code',
        'pre',
    ]
    for sel in key_input_selectors:
        try:
            el = page.query_selector(sel)
            if el:
                val = el.get_attribute("value") or el.text_content() or ""
                for pattern in api_key_patterns:
                    match = re.search(pattern, val)
                    if match:
                        key = match.group(1)
                        log("API", f"API key found in {sel}: {key[:20]}...")
                        return key
        except:
            continue

    log("API", "API key not found — may need manual creation")
    if DEBUG:
        screenshot(page, "xiaomi_09_apikey_final.png")
    return None
