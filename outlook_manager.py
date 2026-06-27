#!/usr/bin/env python3
"""
Outlook Account Manager — Automate Outlook account registration + alias creation + OTP reading.

Features:
- Register new Outlook personal accounts (with manual CAPTCHA solve in --show mode)
- Create aliases (max 10/year, max 2/week per Outlook account)
- Read OTP from Outlook inbox via Playwright (no IMAP/OAuth needed)
- Track alias usage in outlook_accounts.json (prevent over-limit)
- Log every action for audit

Usage:
  python outlook_manager.py --action register --show
  python outlook_manager.py --action add-alias --email user@outlook.com --password PASS --show
  python outlook_manager.py --action read-otp --email user@outlook.com --password PASS --timeout 120
  python outlook_manager.py --action list
  python outlook_manager.py --action auto --show  (register + add 2 aliases in one run)
"""

import argparse
import json
import os
import random
import re
import string
import sys
import time
from datetime import datetime, timedelta

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


# ─ Config ─────────────────────────────────────────
ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), "outlook_accounts.json")
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# Outlook limits
MAX_ALIASES_TOTAL = 10       # per account, lifetime
MAX_ALIASES_PER_YEAR = 10    # per account, per year
MAX_ALIASES_PER_WEEK = 2     # per account, per week

OUTLOOK_SIGNUP_URL = "https://signup.live.com/signup"
OUTLOOK_LOGIN_URL = "https://login.live.com/"
OUTLOOK_INBOX_URL = "https://outlook.live.com/mail/0/inbox"
OUTLOOK_ALIAS_URL = "https://account.live.com/names/manage"


def log(step, msg):
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] [{step}] {msg}")


def screenshot(page, name):
    path = os.path.join(SCREENSHOT_DIR, name)
    try:
        page.screenshot(path=path)
        log("SHOT", f"Saved {name}")
    except:
        pass


def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_accounts(accounts):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)
    log("SAVE", f"Saved {len(accounts)} accounts to {ACCOUNTS_FILE}")


def find_account(accounts, email):
    for acc in accounts:
        if acc["email"].lower() == email.lower():
            return acc
    return None


# ─ Alias limit checker ────────────────────────────
def check_alias_limits(account):
    """Returns (can_create, reason, remaining_total, remaining_week, remaining_year)."""
    aliases = account.get("aliases", [])
    now = datetime.now()

    # Total limit
    if len(aliases) >= MAX_ALIASES_TOTAL:
        return False, f"MAX_ALIASES_TOTAL ({MAX_ALIASES_TOTAL}) reached", 0, 0, 0

    # Yearly limit
    year_ago = now - timedelta(days=365)
    aliases_this_year = [a for a in aliases if datetime.fromisoformat(a["created_at"]) > year_ago]
    if len(aliases_this_year) >= MAX_ALIASES_PER_YEAR:
        return False, f"MAX_ALIASES_PER_YEAR ({MAX_ALIASES_PER_YEAR}) reached", \
               MAX_ALIASES_TOTAL - len(aliases), 0, 0

    # Weekly limit
    week_ago = now - timedelta(days=7)
    aliases_this_week = [a for a in aliases if datetime.fromisoformat(a["created_at"]) > week_ago]
    if len(aliases_this_week) >= MAX_ALIASES_PER_WEEK:
        next_available = week_ago + timedelta(days=7)
        # Find the earliest alias this week + 7 days
        if aliases_this_week:
            earliest = min(datetime.fromisoformat(a["created_at"]) for a in aliases_this_week)
            next_available = earliest + timedelta(days=7)
        days_wait = (next_available - now).days
        hours_wait = ((next_available - now).seconds // 3600)
        return False, f"MAX_ALIASES_PER_WEEK ({MAX_ALIASES_PER_WEEK}) reached. Wait ~{days_wait}d {hours_wait}h", \
               MAX_ALIASES_TOTAL - len(aliases), \
               0, \
               MAX_ALIASES_PER_YEAR - len(aliases_this_year)

    remaining_total = MAX_ALIASES_TOTAL - len(aliases)
    remaining_week = MAX_ALIASES_PER_WEEK - len(aliases_this_week)
    remaining_year = MAX_ALIASES_PER_YEAR - len(aliases_this_year)

    return True, "OK", remaining_total, remaining_week, remaining_year


# ─ Name generator ─────────────────────────────────
def generate_name():
    """Generate a realistic-looking name for Outlook account."""
    first_names = ["john", "mary", "david", "sarah", "michael", "emma", "james", "lisa",
                   "robert", "anna", "daniel", "sophie", "mark", "jenny", "paul", "kate",
                   "steven", "laura", "chris", "nancy", "thomas", "julia", "kevin", "amy"]
    last_names = ["smith", "jones", "brown", "wilson", "taylor", "davis", "white", "clark",
                  "hall", "lewis", "walker", "young", "king", "wright", "hill", "green",
                  "adams", "baker", "nelson", "carter", "cooper", "morris", "ross", "powell"]
    f = random.choice(first_names)
    l = random.choice(last_names)
    num = random.randint(10, 9999)
    style = random.randint(0, 3)
    if style == 0:
        return f"{f}{l}{num}"
    elif style == 1:
        return f"{f}.{l}{num}"
    elif style == 2:
        return f"{f}_{l}{num}"
    else:
        return f"{f}{num}{l}"


def generate_password():
    """Outlook password: 12+ chars, upper+lower+digits."""
    chars = string.ascii_letters + string.digits
    pw = "Aa1" + ''.join(random.choices(chars, k=13)) + "_"
    return pw


# ─ Outlook Account Registration ───────────────────
def register_outlook(headless=True):
    """Register a new Outlook personal account. Returns (email, password) or (None, None)."""
    log("OUTLOOK-REG", "Starting Outlook registration...")
    name = generate_name()
    email = f"{name}@hotmail.com"
    password = generate_password()

    log("OUTLOOK-REG", f"Email: {email}")
    log("OUTLOOK-REG", f"Password: {password}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # Step 1: Navigate to signup
            log("OUTLOOK-REG", "Navigating to signup.live.com...")
            page.goto(OUTLOOK_SIGNUP_URL, timeout=60000, wait_until="domcontentloaded")
            time.sleep(3)
            screenshot(page, "outlook_reg_00_start.png")

            # Step 2: Enter full email address
            log("OUTLOOK-REG", f"Entering email: {email}")
            try:
                email_input = page.wait_for_selector("#MemberName, input[type='email'], input[name='email'], #usernameInput, input[type='text']", timeout=15000)
                email_input.fill(email)
            except:
                log("OUTLOOK-REG", "Email input not found!")
                screenshot(page, "outlook_reg_error_no_input.png")
                return None, None

            time.sleep(1)
            screenshot(page, "outlook_reg_01_email.png")

            # Click Next
            try:
                page.click("#iSignupAction")
            except:
                page.click("button[type='submit']")
            time.sleep(3)
            screenshot(page, "outlook_reg_02_after_email.png")

            # Step 3: Enter password
            log("OUTLOOK-REG", "Entering password...")
            try:
                pw_input = page.wait_for_selector("#Password", timeout=15000)
                pw_input.fill(password)
            except:
                pw_input = page.wait_for_selector("input[type='password']", timeout=10000)
                pw_input.fill(password)

            time.sleep(1)
            screenshot(page, "outlook_reg_03_password.png")

            # Click Next
            try:
                page.click("#iSignupAction")
            except:
                page.click("button[type='submit']")
            time.sleep(3)
            screenshot(page, "outlook_reg_04_after_password.png")

            # Step 3: Birthday (Fluent UI dropdowns — comes BEFORE name)
            log("OUTLOOK-REG", "Entering birthday (first form after password)...")
            try:
                # Country/region — click dropdown button, select US
                try:
                    country_btn = page.wait_for_selector("#countryDropdownId", timeout=5000)
                    if country_btn:
                        country_btn.click()
                        time.sleep(1)
                        # Click "United States" option in listbox
                        us_option = page.wait_for_selector("[role='option']:has-text('United States'), li:has-text('United States')", timeout=5000)
                        if us_option:
                            us_option.click()
                        log("OUTLOOK-REG", "Country set to United States")
                except Exception as e:
                    log("OUTLOOK-REG", f"Country set failed (using default): {e}")

                time.sleep(1)

                # Birth month — click dropdown with force (label intercepts normal click)
                try:
                    month_btn = page.wait_for_selector("#BirthMonthDropdown", timeout=5000)
                    if month_btn:
                        month_btn.click(force=True)
                        time.sleep(1)
                        # Get all month options
                        month_options = page.query_selector_all("[role='option']")
                        if len(month_options) > 1:
                            # Skip first (placeholder "Month"), pick random
                            pick = random.randint(1, len(month_options) - 1)
                            month_options[pick].click()
                            log("OUTLOOK-REG", f"Month set (option {pick})")
                        else:
                            log("OUTLOOK-REG", f"Month options found: {len(month_options)} — trying JS click")
                    else:
                        log("OUTLOOK-REG", "Month button not found")
                except Exception as e:
                    log("OUTLOOK-REG", f"Month set failed: {e}")
                    # Fallback: try JS click
                    try:
                        page.evaluate("document.getElementById('BirthMonthDropdown').click()")
                        time.sleep(1)
                        month_options = page.query_selector_all("[role='option']")
                        if len(month_options) > 1:
                            pick = random.randint(1, len(month_options) - 1)
                            month_options[pick].click()
                            log("OUTLOOK-REG", f"Month set via JS (option {pick})")
                    except Exception as e2:
                        log("OUTLOOK-REG", f"Month JS fallback also failed: {e2}")

                time.sleep(1)

                # Birth day — click dropdown, select random day
                try:
                    day_btn = page.wait_for_selector("#BirthDayDropdown", timeout=5000)
                    if day_btn:
                        day_btn.click(force=True)
                        time.sleep(1)
                        day_options = page.query_selector_all("[role='option']")
                        if len(day_options) > 1:
                            pick = random.randint(1, min(28, len(day_options) - 1))
                            day_options[pick].click()
                            log("OUTLOOK-REG", f"Day set (option {pick})")
                except Exception as e:
                    log("OUTLOOK-REG", f"Day set failed: {e}")

                time.sleep(1)

                # Birth year — input[type=number]
                try:
                    year_input = page.wait_for_selector("input[name='BirthYear'], #floatingLabelInput24", timeout=5000)
                    if year_input:
                        year_input.fill(str(random.randint(1985, 2000)))
                        log("OUTLOOK-REG", "Year set")
                except Exception as e:
                    log("OUTLOOK-REG", f"Year set failed: {e}")

            except Exception as e:
                log("OUTLOOK-REG", f"Birthday form error: {e}")

            time.sleep(1)
            screenshot(page, "outlook_reg_05_birthday.png")

            # Click Next
            try:
                page.click("#iSignupAction, button:has-text('Next'), button[type='submit']", timeout=5000)
            except:
                page.keyboard.press("Enter")
            time.sleep(5)
            screenshot(page, "outlook_reg_06_after_birthday.png")

            # Step 4: Name (comes AFTER birthday)
            log("OUTLOOK-REG", "Entering name...")
            try:
                first_input = page.wait_for_selector("#FirstName", timeout=15000)
                first_input.fill(name[:4].capitalize())
                last_input = page.wait_for_selector("#LastName")
                last_input.fill(name[4:].capitalize())
            except:
                # Try alternate
                inputs = page.query_selector_all("input[type='text']")
                if len(inputs) >= 2:
                    inputs[0].fill(name[:4].capitalize())
                    inputs[1].fill(name[4:].capitalize())

            time.sleep(1)
            screenshot(page, "outlook_reg_07_name.png")

            # Click Next
            try:
                page.click("#iSignupAction")
            except:
                page.click("button:has-text('Next'), button[type='submit']")
            time.sleep(5)
            screenshot(page, "outlook_reg_08_after_name.png")
            # Step 6: CAPTCHA — "Press and Hold" button in hsprotect iframe
            log("OUTLOOK-REG", "Checking for CAPTCHA / Press and Hold...")
            log("OUTLOOK-REG", ">>> SOLVE CAPTCHA IN BROWSER IF APPEARS! <<<")

            # Check for birthday error first
            try:
                body_text = page.inner_text("body")[:2000]
                if "Enter your birthdate" in body_text:
                    log("OUTLOOK-REG", "Birthday still not accepted — Month may not have been set")
                    screenshot(page, "outlook_reg_06b_birthday_error.png")
                if "blocked" in body_text.lower() and "account" in body_text.lower():
                    log("OUTLOOK-REG", "ACCOUNT BLOCKED — too many attempts. Try again later.")
                    screenshot(page, "outlook_reg_06c_blocked.png")
                    return None, None
            except:
                pass

            # Wait up to 180s for CAPTCHA (Press and Hold in iframe)
            captcha_solved = False
            for wait in range(90):
                url = page.url.lower()
                # Check if we've moved past CAPTCHA
                if "outlook.live.com" in url or "account.live.com" in url or "profile" in url:
                    log("OUTLOOK-REG", f"CAPTCHA passed! URL: {page.url[:80]}")
                    captcha_solved = True
                    break

                # Check for "Account blocked" message
                try:
                    body_text = page.inner_text("body")[:500]
                    if "blocked" in body_text.lower() and "account" in body_text.lower():
                        log("OUTLOOK-REG", "ACCOUNT BLOCKED — stopping")
                        screenshot(page, "outlook_reg_blocked.png")
                        return None, None
                except:
                    pass

                # Look for Press and Hold button in main page AND all frames
                if wait == 0:
                    log("OUTLOOK-REG", "Scanning for Press and Hold button (main page + frames)...")
                    screenshot(page, "outlook_reg_08_captcha.png")

                # Check main page first
                try:
                    hold_btn = page.query_selector("button:has-text('Press'), [role='button']:has-text('Press'), button:has-text('hold'), [role='button']:has-text('hold')")
                    if hold_btn:
                        log("OUTLOOK-REG", "Found 'Press and Hold' button on MAIN PAGE")
                        box = hold_btn.bounding_box()
                        if box:
                            log("OUTLOOK-REG", f"Button at ({box['x']:.0f}, {box['y']:.0f}) size {box['width']:.0f}x{box['height']:.0f}")
                            page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                            page.mouse.down()
                            log("OUTLOOK-REG", "Mouse DOWN — holding...")
                            time.sleep(5)
                            page.mouse.up()
                            log("OUTLOOK-REG", "Mouse UP — released!")
                            time.sleep(3)
                            screenshot(page, "outlook_reg_08b_hold_solved.png")
                except:
                    pass

                # Check all frames
                try:
                    for frame in page.frames:
                        frame_url = frame.url.lower()
                        if "hsprotect" in frame_url or "fpt.live" in frame_url or "cfp.microsoft" in frame_url:
                            try:
                                hold_btn = frame.query_selector("button:has-text('Press'), [role='button']:has-text('Press'), button:has-text('hold'), [role='button']:has-text('hold')")
                                if not hold_btn:
                                    els = frame.query_selector_all("button, [role='button'], div[class*='button'], span[class*='button']")
                                    for el in els:
                                        try:
                                            text = el.inner_text()[:50].lower()
                                            if "press" in text or "hold" in text:
                                                hold_btn = el
                                                break
                                        except:
                                            pass

                                if hold_btn and wait == 0:
                                    log("OUTLOOK-REG", f"Found 'Press and Hold' button in frame: {frame_url[:60]}")
                                    box = hold_btn.bounding_box()
                                    if box and box["width"] > 0:
                                        log("OUTLOOK-REG", f"Button at ({box['x']:.0f}, {box['y']:.0f}) size {box['width']:.0f}x{box['height']:.0f}")
                                        page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                                        page.mouse.down()
                                        log("OUTLOOK-REG", "Mouse DOWN — holding...")
                                        time.sleep(5)
                                        page.mouse.up()
                                        log("OUTLOOK-REG", "Mouse UP — released!")
                                        time.sleep(3)
                                        screenshot(page, "outlook_reg_08b_hold_solved.png")
                            except:
                                pass
                except:
                    pass

                if wait % 10 == 0 and wait > 0:
                    log("OUTLOOK-REG", f"Waiting for CAPTCHA solve... ({wait*2}s)")
                    screenshot(page, f"outlook_reg_08_captcha_{wait}.png")

                time.sleep(2)

            screenshot(page, "outlook_reg_09_after_captcha.png")

            # Step 7: Stay signed in prompt
            try:
                stay_btn = page.wait_for_selector("#acceptButton, #idSIButton9", timeout=10000)
                if stay_btn:
                    stay_btn.click()
                    time.sleep(3)
            except:
                pass

            # Step 8: Check if we're in Outlook
            url = page.url.lower()
            if "outlook.live.com" in url or "account.live.com" in url:
                log("OUTLOOK-REG", f"SUCCESS! Account created: {email}")
                screenshot(page, "outlook_reg_10_success.png")

                # Save account
                accounts = load_accounts()
                accounts.append({
                    "email": email,
                    "password": password,
                    "created_at": datetime.now().isoformat(),
                    "aliases": [],
                    "status": "active"
                })
                save_accounts(accounts)

                return email, password
            else:
                log("OUTLOOK-REG", f"UNCERTAIN — final URL: {page.url}")
                screenshot(page, "outlook_reg_10_uncertain.png")

                # Still save it
                accounts = load_accounts()
                accounts.append({
                    "email": email,
                    "password": password,
                    "created_at": datetime.now().isoformat(),
                    "aliases": [],
                    "status": "uncertain"
                })
                save_accounts(accounts)

                return email, password

        except Exception as e:
            log("OUTLOOK-REG", f"ERROR: {e}")
            screenshot(page, "outlook_reg_error.png")
            return None, None
        finally:
            # Keep browser open for 10s if --show
            if not headless:
                time.sleep(10)
            browser.close()


# ─ Outlook Login ──────────────────────────────────
def outlook_login(page, email, password, headless=True):
    """Login to Outlook web. Returns True on success."""
    log("OUTLOOK-LOGIN", f"Logging in as {email}...")

    page.goto(OUTLOOK_LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(3)

    # Step 1: Enter email
    try:
        email_input = page.wait_for_selector("input[type='email'], #i0116", timeout=15000)
        email_input.fill(email)
    except:
        log("OUTLOOK-LOGIN", "Email field not found!")
        return False

    try:
        page.click("#idSIButton9, button[type='submit']")
    except:
        page.keyboard.press("Enter")
    time.sleep(3)
    screenshot(page, "outlook_login_01_email.png")

    # Step 2: Enter password
    try:
        pw_input = page.wait_for_selector("input[type='password'], #i0118", timeout=15000)
        pw_input.fill(password)
    except:
        log("OUTLOOK-LOGIN", "Password field not found!")
        return False

    try:
        page.click("#idSIButton9, button[type='submit']")
    except:
        page.keyboard.press("Enter")
    time.sleep(5)
    screenshot(page, "outlook_login_02_password.png")

    # Step 3: Handle "Stay signed in?" prompt
    try:
        stay_btn = page.wait_for_selector("#acceptButton, #idSIButton9", timeout=5000)
        if stay_btn:
            stay_btn.click()
            time.sleep(3)
    except:
        pass

    # Step 4: Check for CAPTCHA / verification
    log("OUTLOOK-LOGIN", "Checking for CAPTCHA/verification...")
    for wait in range(60):
        url = page.url.lower()
        if "outlook.live.com" in url:
            log("OUTLOOK-LOGIN", f"Login successful! URL: {page.url[:80]}")
            return True

        # Check for verification
        try:
            verify = page.query_selector("#idDiv_SAOTCS_Proofs, # proofsContainer, .proof-container")
            if verify and wait == 0:
                log("OUTLOOK-LOGIN", ">>> VERIFY ACCOUNT MANUALLY IF NEEDED! <<<")
                screenshot(page, "outlook_login_03_verify.png")
        except:
            pass

        if wait % 10 == 0 and wait > 0:
            log("OUTLOOK-LOGIN", f"Waiting... ({wait*2}s)")
        time.sleep(2)

    log("OUTLOOK-LOGIN", "Login timeout!")
    return False


# ─ Alias Creation ─────────────────────────────────
def create_alias(email, password, headless=True):
    """Create a new alias for an Outlook account.
    Returns alias email or None."""
    accounts = load_accounts()
    account = find_account(accounts, email)

    if not account:
        log("ALIAS", f"Account not found: {email}")
        return None

    # Check limits
    can_create, reason, rem_total, rem_week, rem_year = check_alias_limits(account)
    if not can_create:
        log("ALIAS", f"BLOCKED: {reason}")
        log("ALIAS", f"  Remaining: total={rem_total}, week={rem_week}, year={rem_year}")
        return None

    log("ALIAS", f"Limits OK — remaining: total={rem_total}, week={rem_week}, year={rem_year}")

    alias_name = generate_name()
    alias_email = f"{alias_name}@outlook.com"
    log("ALIAS", f"Creating alias: {alias_email}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # Login first
            if not outlook_login(page, email, password, headless=headless):
                log("ALIAS", "Login failed — cannot create alias")
                return None

            # Navigate to alias management page
            log("ALIAS", f"Navigating to alias management...")
            page.goto(OUTLOOK_ALIAS_URL, timeout=30000, wait_until="domcontentloaded")
            time.sleep(5)
            screenshot(page, "outlook_alias_01_manage.png")

            # Click "Add email" link
            log("ALIAS", "Looking for 'Add email' link...")
            add_link = None
            for attempt in range(10):
                try:
                    # Try various selectors
                    add_link = page.query_selector("a#AssociatedIdLive_Link, a:has-text('Add email'), a:has-text('Add an alias'), #addAlias")
                    if add_link:
                        break
                    # Try by text
                    links = page.query_selector_all("a")
                    for link in links:
                        text = link.inner_text().lower()
                        if "add" in text and ("email" in text or "alias" in text):
                            add_link = link
                            break
                    if add_link:
                        break
                except:
                    pass
                time.sleep(2)

            if not add_link:
                log("ALIAS", "'Add email' link not found — maybe limits reached on Microsoft side")
                screenshot(page, "outlook_alias_02_no_add_link.png")
                # Dump page content for debugging
                try:
                    body = page.inner_text("body")[:1000]
                    log("ALIAS", f"Page content: {body[:200]}...")
                except:
                    pass
                return None

            add_link.click()
            time.sleep(3)
            screenshot(page, "outlook_alias_03_add_form.png")

            # Select "Create a new email address"
            log("ALIAS", "Selecting 'Create new email address'...")
            try:
                new_radio = page.query_selector("input[value='AssociatedIdLive'], input#AssociatedIdLive")
                if new_radio:
                    new_radio.click()
                    time.sleep(1)
            except:
                pass

            # Enter alias name
            log("ALIAS", f"Entering alias name: {alias_name}")
            try:
                alias_input = page.wait_for_selector("#MemberName, input[name='MemberName'], input[type='text']", timeout=10000)
                alias_input.fill(alias_name)
            except:
                log("ALIAS", "Alias input not found!")
                screenshot(page, "outlook_alias_04_no_input.png")
                return None

            time.sleep(1)
            screenshot(page, "outlook_alias_05_name_entered.png")

            # Click Save/Next
            try:
                page.click("#iSignupAction, button[type='submit'], #idSIButton9")
            except:
                page.keyboard.press("Enter")

            time.sleep(5)
            screenshot(page, "outlook_alias_06_after_save.png")

            # Check for error
            try:
                body = page.inner_text("body")[:2000].lower()
                if "limit" in body or "too many" in body or "error" in body:
                    log("ALIAS", f"Possible error on page: {body[:200]}")
                    # Don't return None yet — might be a warning
                if "successfully" in body or "added" in body or "manage" in page.url.lower():
                    log("ALIAS", f"Alias created successfully: {alias_email}")
            except:
                pass

            # Save alias to account
            alias_record = {
                "email": alias_email,
                "name": alias_name,
                "created_at": datetime.now().isoformat()
            }
            account["aliases"].append(alias_record)
            save_accounts(accounts)

            log("ALIAS", f"Saved: {alias_email}")
            log("ALIAS", f"Total aliases for {email}: {len(account['aliases'])}/{MAX_ALIASES_TOTAL}")
            log("ALIAS", f"This week: {len([a for a in account['aliases'] if (datetime.now() - datetime.fromisoformat(a['created_at'])).days < 7])}/{MAX_ALIASES_PER_WEEK}")

            return alias_email

        except Exception as e:
            log("ALIAS", f"ERROR: {e}")
            screenshot(page, "outlook_alias_error.png")
            return None
        finally:
            if not headless:
                time.sleep(10)
            browser.close()


# ─ OTP Reader via Outlook Web ──────────────────────
def read_otp_outlook(email, password, timeout=120, headless=True, existing_page=None):
    """Read OTP from Outlook inbox via Playwright.
    Can use existing page (if already logged in) or create new browser.
    Returns OTP code or None."""
    log("OUTLOOK-OTP", f"Reading OTP from {email}...")

    if existing_page:
        page = existing_page
        # Navigate to inbox
        log("OUTLOOK-OTP", "Navigating to inbox...")
        page.goto(OUTLOOK_INBOX_URL, timeout=30000, wait_until="domcontentloaded")
        time.sleep(3)
        return _scan_inbox_for_otp(page, email, timeout)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # Login
            if not outlook_login(page, email, password, headless=headless):
                log("OUTLOOK-OTP", "Login failed!")
                return None

            # Navigate to inbox
            log("OUTLOOK-OTP", "Navigating to inbox...")
            page.goto(OUTLOOK_INBOX_URL, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)

            return _scan_inbox_for_otp(page, email, timeout)

        except Exception as e:
            log("OUTLOOK-OTP", f"ERROR: {e}")
            return None
        finally:
            browser.close()


def _scan_inbox_for_otp(page, email, timeout):
    """Scan Outlook inbox for OTP email. Returns OTP code or None."""
    log("OUTLOOK-OTP", f"Scanning inbox for OTP (timeout={timeout}s)...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            # Wait for inbox to load
            time.sleep(3)

            # Look for Alibaba email in inbox
            # Outlook web uses div elements for email list
            email_items = page.query_selector_all("div[role='option'], div[data-convid], div[class*='mail']")

            for item in email_items[:15]:
                try:
                    text = item.inner_text()[:500]
                except:
                    continue

                # Check if it's from Alibaba
                if "alibaba" not in text.lower() and "verification" not in text.lower() and "code" not in text.lower():
                    continue

                log("OUTLOOK-OTP", f"Found potential Alibaba email: {text[:100]}...")

                # Click to open
                try:
                    item.click()
                    time.sleep(2)
                except:
                    continue

                # Read email body
                try:
                    body = page.inner_text("body")[:5000]
                except:
                    body = text

                # Find 6-digit OTP
                otp_match = re.search(r'>\s*(\d{6})\s*</span>', body)
                if not otp_match:
                    otp_match = re.search(r'(?:code|verification)[^<]*?(\d{6})', body, re.IGNORECASE)
                if not otp_match:
                    for m in re.finditer(r'\b(\d{6})\b', body):
                        num = m.group(1)
                        if num not in ('181818', '999', '666666', '808080'):
                            otp_match = m
                            break

                if otp_match:
                    code = otp_match.group(1)
                    log("OUTLOOK-OTP", f"OTP found: {code}")
                    return code

            # Check junk folder too
            log("OUTLOOK-OTP", "Checking junk folder...")
            try:
                page.goto("https://outlook.live.com/mail/0/junkemail", timeout=15000, wait_until="domcontentloaded")
                time.sleep(3)

                email_items = page.query_selector_all("div[role='option'], div[data-convid], div[class*='mail']")
                for item in email_items[:10]:
                    try:
                        text = item.inner_text()[:500]
                    except:
                        continue

                    if "alibaba" not in text.lower() and "verification" not in text.lower():
                        continue

                    log("OUTLOOK-OTP", f"Found in junk: {text[:100]}...")

                    try:
                        item.click()
                        time.sleep(2)
                    except:
                        continue

                    try:
                        body = page.inner_text("body")[:5000]
                    except:
                        body = text

                    otp_match = re.search(r'>\s*(\d{6})\s*</span>', body)
                    if not otp_match:
                        otp_match = re.search(r'(?:code|verification)[^<]*?(\d{6})', body, re.IGNORECASE)
                    if not otp_match:
                        for m in re.finditer(r'\b(\d{6})\b', body):
                            num = m.group(1)
                            if num not in ('181818', '999', '666666', '808080'):
                                otp_match = m
                                break

                    if otp_match:
                        code = otp_match.group(1)
                        log("OUTLOOK-OTP", f"OTP found in junk: {code}")
                        return code

            except:
                pass

            # Go back to inbox
            try:
                page.goto(OUTLOOK_INBOX_URL, timeout=15000, wait_until="domcontentloaded")
            except:
                pass

        except Exception as e:
            log("OUTLOOK-OTP", f"Scan error: {e}")

        elapsed = int(time.time() - start)
        if elapsed % 15 == 0:
            log("OUTLOOK-OTP", f"Still scanning... ({elapsed}s/{timeout}s)")

        time.sleep(5)

    log("OUTLOOK-OTP", "OTP timeout!")
    return None


# ─ List accounts ──────────────────────────────────
def list_accounts():
    accounts = load_accounts()
    if not accounts:
        print("No Outlook accounts found.")
        return

    print(f"\n{'='*80}")
    print(f"Outlook Accounts ({len(accounts)})")
    print(f"{'='*80}")

    for i, acc in enumerate(accounts):
        print(f"\n  [{i+1}] {acc['email']}")
        print(f"      Status: {acc.get('status', 'unknown')}")
        print(f"      Created: {acc.get('created_at', '?')[:19]}")
        aliases = acc.get("aliases", [])
        print(f"      Aliases: {len(aliases)}/{MAX_ALIASES_TOTAL} total")

        can_create, reason, rem_total, rem_week, rem_year = check_alias_limits(acc)
        if can_create:
            print(f"      Can create: YES (remaining: total={rem_total}, week={rem_week}, year={rem_year})")
        else:
            print(f"      Can create: NO — {reason}")

        if aliases:
            for j, alias in enumerate(aliases):
                print(f"        [{j+1}] {alias['email']} (created: {alias.get('created_at','?')[:19]})")

    print(f"\n{'='*80}")


# ─ Auto mode: register + add aliases ──────────────
def auto_mode(headless=True):
    """Register new Outlook account, then add 2 aliases (weekly limit)."""
    log("AUTO", "=== Auto Mode: Register + Add Aliases ===")

    # Step 1: Register
    email, password = register_outlook(headless=headless)
    if not email:
        log("AUTO", "Registration failed — aborting")
        return

    log("AUTO", f"Account created: {email}")

    # Step 2: Add 2 aliases (weekly limit)
    for i in range(2):
        log("AUTO", f"Adding alias {i+1}/2...")
        alias = create_alias(email, password, headless=headless)
        if alias:
            log("AUTO", f"Alias created: {alias}")
        else:
            log("AUTO", f"Alias {i+1} failed — stopping")
            break
        time.sleep(5)

    log("AUTO", "=== Done ===")
    list_accounts()


# ─ Main ───────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Outlook Account Manager")
    parser.add_argument("--action", required=True,
                        choices=["register", "add-alias", "read-otp", "list", "auto"],
                        help="Action to perform")
    parser.add_argument("--email", help="Outlook email (for add-alias, read-otp)")
    parser.add_argument("--password", help="Outlook password (for add-alias, read-otp)")
    parser.add_argument("--timeout", type=int, default=120, help="OTP read timeout (seconds)")
    parser.add_argument("--show", action="store_true", help="Show browser window (non-headless)")
    parser.add_argument("--debug", action="store_true", help="Take screenshots at each step")

    args = parser.parse_args()
    headless = not args.show

    if args.action == "register":
        email, password = register_outlook(headless=headless)
        if email:
            print(f"\n=== SUCCESS ===")
            print(f"Email: {email}")
            print(f"Password: {password}")
        else:
            print(f"\n=== FAILED ===")

    elif args.action == "add-alias":
        if not args.email or not args.password:
            print("ERROR: --email and --password required for add-alias")
            sys.exit(1)
        alias = create_alias(args.email, args.password, headless=headless)
        if alias:
            print(f"\n=== ALIAS CREATED: {alias} ===")
        else:
            print(f"\n=== FAILED ===")

    elif args.action == "read-otp":
        if not args.email or not args.password:
            print("ERROR: --email and --password required for read-otp")
            sys.exit(1)
        otp = read_otp_outlook(args.email, args.password, timeout=args.timeout, headless=headless)
        if otp:
            print(f"\n=== OTP: {otp} ===")
        else:
            print(f"\n=== NO OTP FOUND ===")

    elif args.action == "list":
        list_accounts()

    elif args.action == "auto":
        auto_mode(headless=headless)


if __name__ == "__main__":
    main()
