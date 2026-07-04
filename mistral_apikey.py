#!/usr/bin/env python3
"""
Mistral AI API Key Extraction Module.
=====================================
After registration, extract API key from Mistral AI admin console.

Flow (steps 10-18 from alur automation):
  10. Navigate to https://admin.mistral.ai/organization
  11. Navigate to https://admin.mistral.ai/organization/api-keys
  12. Click "Create new key" button
  13. Enter random name for the key
  14. Open workspace dropdown
  15. Type "Default Workspace" + Enter
  16. Click "Default Workspace" from menu
  17. Click "Create new key" (submit)
  18. Extract API key from readonly input

API key format: 32-char alphanumeric (e.g. 33YuSpM2TwaTnMYtEYaN9y6xGXNA6N3G)

Separated from mistral_register.py for clean module boundaries.
"""

import sys
import os
import time
import json
import re
import string
import random

from farm_headless import log
from mistral_register import _save_lock, save_result, RESULTS_FILE as MISTRAL_CSV
from data_paths import get_path

# ─ Config ──────────────────────────────────────────

MISTRAL_ORG_URL = "https://admin.mistral.ai/organization"
MISTRAL_APIKEYS_URL = "https://admin.mistral.ai/organization/api-keys"

RESULTS_FILE = get_path("mistral", "accounts.csv")
CSV_FILE = RESULTS_FILE  # Same as mistral_register.py


def load_results():
    """Load all results from CSV. Returns list of dicts."""
    import csv as _csv
    if not os.path.exists(CSV_FILE):
        return []
    try:
        with open(CSV_FILE, newline="") as f:
            return list(_csv.DictReader(f))
    except:
        return []


# ─ API Key Extraction ──────────────────────────────

def _random_key_name():
    """Generate a random name for the API key."""
    return "key_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))


def create_api_key(page, timeout=60):
    """Create and extract an API key from Mistral AI console.

    Steps 10-18 from the automation flow.
    Returns API key string or None.
    """
    log("KEY", "Starting API key extraction...")

    # ─ Step 10: Navigate to organization page ─
    log("KEY", "Step 10: Navigating to admin.mistral.ai/organization...")
    try:
        page.goto(MISTRAL_ORG_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
    except Exception as e:
        log("KEY", f"Navigate to org page failed: {e}")
        return None

    # ─ Step 11: Navigate to API keys page ─
    log("KEY", "Step 11: Navigating to API keys page...")
    try:
        page.goto(MISTRAL_APIKEYS_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
    except Exception as e:
        log("KEY", f"Navigate to API keys page failed: {e}")
        return None

    # Check if we got redirected to login (session not established)
    current_url = page.url.lower()
    if "auth.mistral.ai" in current_url or "login" in current_url:
        log("KEY", f"ERROR: Redirected to login page — session not established!")
        log("KEY", f"URL: {current_url[:100]}")
        return None
    log("KEY", f"API keys page URL: {current_url[:80]}")

    # ─ Step 12: Click "Create new key" button ─
    log("KEY", "Step 12: Looking for 'Create new key' button...")
    create_clicked = False
    for sel in [
        'button:has-text("Create new key")',
        'button:has-text("Create New Key")',
        'button:has-text("Create key")',
    ]:
        try:
            page.wait_for_selector(sel, timeout=15000, state="visible")
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("KEY", f"Clicked 'Create new key' via: {sel}")
                create_clicked = True
                break
        except:
            continue

    if not create_clicked:
        # Try evaluating buttons by text
        try:
            found = page.evaluate("""
                () => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        const txt = (b.innerText || '').trim().toLowerCase();
                        if (txt.includes('create') && txt.includes('key')) {
                            b.click();
                            return txt;
                        }
                    }
                    return null;
                }
            """)
            if found:
                log("KEY", f"Clicked 'Create new key' via JS eval: {found}")
                create_clicked = True
        except:
            pass

    if not create_clicked:
        log("KEY", "ERROR: 'Create new key' button not found!")
        return None

    time.sleep(3)

    # ─ Step 13: Enter random name for key ─
    log("KEY", "Step 13: Entering random key name...")
    key_name = _random_key_name()
    name_filled = False
    name_selectors = [
        'input[name="name"]',
        'input[placeholder="My API Key"]',
        'input[placeholder*="API Key"]',
        'input[placeholder*="api key"]',
    ]

    for sel in name_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.3)
                el.fill(key_name)
                name_filled = True
                log("KEY", f"Key name '{key_name}' filled via: {sel}")
                break
        except:
            continue

    if not name_filled:
        log("KEY", "WARNING: Key name input not found — continuing anyway")

    time.sleep(1)

    # ─ Step 14: Open workspace dropdown ─
    log("KEY", "Step 14: Opening workspace dropdown...")
    dropdown_clicked = False
    dropdown_selectors = [
        'button[role="combobox"]',
        'button:has-text("Select workspace")',
        'button:has-text("Select Workspace")',
    ]

    for sel in dropdown_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("KEY", f"Clicked workspace dropdown via: {sel}")
                dropdown_clicked = True
                break
        except:
            continue

    if not dropdown_clicked:
        log("KEY", "WARNING: Workspace dropdown not found — trying to proceed")
    time.sleep(1)

    # ─ Step 15: Type "Default Workspace" + Enter ─
    log("KEY", "Step 15: Typing 'Default Workspace'...")
    search_selectors = [
        'input[placeholder="Search workspace"]',
        'input[placeholder*="Search"]',
        'input[type="text"]',
    ]

    search_filled = False
    for sel in search_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.2)
                el.fill("Default Workspace")
                search_filled = True
                log("KEY", f"Search filled via: {sel}")
                break
        except:
            continue

    if search_filled:
        page.keyboard.press("Enter")
    time.sleep(1)

    # ─ Step 16: Click "Default Workspace" from menu ─
    log("KEY", "Step 16: Clicking 'Default Workspace' from menu...")
    ws_clicked = False
    ws_selectors = [
        '[role="menuitem"]:has-text("Default Workspace")',
        'div[role="menuitem"]:has-text("Default Workspace")',
        'text=Default Workspace',
    ]

    for sel in ws_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("KEY", f"Selected Default Workspace via: {sel}")
                ws_clicked = True
                break
        except:
            continue

    if not ws_clicked:
        log("KEY", "WARNING: Default Workspace menu item not found — trying Enter")
        page.keyboard.press("Enter")

    time.sleep(1)

    # ─ Step 17: Click "Create new key" (submit) ─
    log("KEY", "Step 17: Clicking submit 'Create new key'...")
    submit_clicked = False
    submit_selectors = [
        'button[type="submit"]:has-text("Create new key")',
        'button[type="submit"]:has-text("Create New Key")',
        'button:has-text("Create new key")',
    ]

    for sel in submit_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log("KEY", f"Clicked submit via: {sel}")
                submit_clicked = True
                break
        except:
            continue

    if not submit_clicked:
        log("KEY", "WARNING: Submit button not found — trying Enter")
        page.keyboard.press("Enter")

    time.sleep(3)

    # ─ Step 18: Extract API key from readonly input ─
    log("KEY", "Step 18: Extracting API key...")

    api_key = None
    for wait in range(timeout // 2):
        try:
            # Method 1: readonly input with value
            found = page.evaluate("""
                () => {
                    // Look for readonly inputs (the key is displayed in a readonly field)
                    const inputs = document.querySelectorAll('input[readonly], input');
                    for (const inp of inputs) {
                        const val = inp.value || inp.getAttribute('value') || '';
                        // Mistral API keys are 32-char alphanumeric
                        if (val.length >= 20 && /^[A-Za-z0-9]+$/.test(val) && !val.includes('@')) {
                            return val;
                        }
                    }
                    // Look in any element text
                    const els = document.querySelectorAll('span, div, p, code, td, [class*="key"]');
                    for (const el of els) {
                        const txt = (el.innerText || el.textContent || '').trim();
                        // Match 32-char alphanumeric strings
                        const m = txt.match(/\\b([A-Za-z0-9]{32})\\b/);
                        if (m) return m[1];
                    }
                    return null;
                }
            """)
            if found:
                api_key = found
                log("KEY", f"API key found: {api_key[:16]}...")
                break
        except Exception as e:
            log("KEY", f"Extraction error: {e}")
            break

        time.sleep(2)

    if not api_key:
        log("KEY", "ERROR: API key not found after waiting")
        try:
            body_text = page.inner_text("body")[:500]
            log("KEY", f"Page content: {body_text}")
        except:
            pass
        return None

    return api_key
