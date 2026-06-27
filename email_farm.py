#!/usr/bin/env python3
"""
Email Farm — Bulk Email Creation Module
========================================
Membuat banyak akun email gratis dengan password yang sama untuk disimpan.

Situs rekomendasi (FREE, API-based, bulk creation):

  [1] mail.tm           — REST API gratis, no API key, unlimited accounts
                          Password bisa custom, akun persisten (60 hari)
                          API: https://api.mail.tm/
                          Domains: rotating (web-library.net, dll)

  [2] 1secmail          — REST API gratis, no signup, unlimited
                          Tidak perlu password (inbox publik)
                          API: https://www.1secmail.com/api/v1/
                          Domains: 1secmail.com, 1secmail.net, dll

  [3] guerrillamail     — REST API gratis, session-based
                          Tidak perlu password, inbox 60 menit
                          API: https://api.guerrillamail.com/ajax.php

  [4] yopmail           — No API, tapi unlimited inbox
                          Akses via web scrape (Playwright)
                          Inbox: [nama]@yopmail.com

  [5] gmail dot trick   — 512 alias dari 1 akun Gmail
                          Password sama (1 akun Gmail)
                          OTP via IMAP (App Password)

  [6] tempmail.plus     — REST API gratis, 9 domains
                          No password needed, inbox publik
                          API: https://tempmail.plus/api/

Usage:
  python email_farm.py
  python email_farm.py --provider mailtm --count 10 --password MyPass123
  python email_farm.py --provider 1secmail --count 50
  python email_farm.py --provider gmail --count 100 --password MyPass123
"""

import sys
import os
import json
import time
import random
import string
import requests

# ─ Config ──────────────────────────────────────────
FARM_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(FARM_DIR, "email_farm_results.json")
CSV_FILE = os.path.join(FARM_DIR, "email_farm_accounts.csv")

# ─ Helpers ─────────────────────────────────────────

def log(step, msg):
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] [{step}] {msg}")


def generate_password():
    """Generate strong password."""
    upper = random.choice(string.ascii_uppercase)
    lower = ''.join(random.choices(string.ascii_lowercase, k=6))
    digit = ''.join(random.choices(string.digits, k=4))
    special = random.choice("!@#$%")
    return f"{upper}{lower}{digit}{special}"


def save_accounts(accounts):
    """Save to JSON + CSV."""
    # JSON
    existing = []
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE) as f:
                existing = json.load(f)
        except:
            pass
    existing.extend(accounts)
    with open(RESULTS_FILE, "w") as f:
        json.dump(existing, f, indent=2)
    log("SAVE", f"Saved {len(accounts)} accounts to {RESULTS_FILE}")

    # CSV
    header = "timestamp,provider,email,password,inbox_url,notes\n"
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w") as f:
            f.write(header)
    with open(CSV_FILE, "a") as f:
        for acc in accounts:
            row = (
                f'"{acc.get("timestamp","")}","{acc.get("provider","")}",'
                f'"{acc.get("email","")}","{acc.get("password","")}",'
                f'"{acc.get("inbox_url","")}","{acc.get("notes","")}"\n'
            )
            f.write(row)
    log("SAVE", f"Saved {len(accounts)} accounts to {CSV_FILE}")


# ─ Providers ───────────────────────────────────────

def create_mailtm_account(password=None):
    """Create mail.tm account via API. Returns dict or None."""
    if not password:
        password = generate_password()

    try:
        # Get available domains
        resp = requests.get("https://api.mail.tm/domains", timeout=10)
        resp.raise_for_status()
        domains = resp.json().get("hydra:member", [])
        if not domains:
            log("MAILTM", "No domains available")
            return None
        domain = domains[0]["domain"]

        # Generate random username
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        email = f"{username}@{domain}"

        # Create account
        resp = requests.post("https://api.mail.tm/accounts", json={
            "address": email,
            "password": password,
        }, timeout=10)

        if resp.status_code == 201:
            log("MAILTM", f"Created: {email}")
            return {
                "email": email,
                "password": password,
                "provider": "mail.tm",
                "inbox_url": f"https://mail.tm/en/",
                "notes": "Login via mail.tm web or API",
            }
        else:
            log("MAILTM", f"Create failed: {resp.status_code} — {resp.text[:100]}")
            return None
    except Exception as e:
        log("MAILTM", f"Error: {e}")
        return None


def create_1secmail_account():
    """Create 1secmail inbox (no password needed, public inbox)."""
    try:
        domains = ["1secmail.com", "1secmail.net", "1secmail.org",
                    "wwjmp.com", "esiix.com", "xojxe.com"]
        domain = random.choice(domains)
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
        email = f"{username}@{domain}"

        # Verify it works
        resp = requests.get(
            f"https://www.1secmail.com/api/v1/?action=getMessages&login={username}&domain={domain}",
            timeout=10
        )
        if resp.status_code == 200:
            log("1SECMAIL", f"Created: {email}")
            return {
                "email": email,
                "password": "(no password — public inbox)",
                "provider": "1secmail",
                "inbox_url": f"https://www.1secmail.com/en/",
                "notes": "Inbox is public, no login required",
            }
        else:
            log("1SECMAIL", f"Verify failed: {resp.status_code}")
            return None
    except Exception as e:
        log("1SECMAIL", f"Error: {e}")
        return None


def create_guerrillamail_account():
    """Create Guerrilla Mail inbox (session-based, 60 min)."""
    try:
        resp = requests.get(
            "https://api.guerrillamail.com/ajax.php?f=get_email_address&lang=en",
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        email = data.get("email_addr", "")
        sid = data.get("sid_token", "")

        if email:
            log("GUERRILLA", f"Created: {email}")
            return {
                "email": email,
                "password": "(session-based, no password)",
                "provider": "guerrillamail",
                "inbox_url": "https://www.guerrillamail.com/",
                "notes": f"Session ID: {sid} (expires in 60 min)",
            }
        else:
            log("GUERRILLA", "No email returned")
            return None
    except Exception as e:
        log("GUERRILLA", f"Error: {e}")
        return None


def create_gmail_alias(count=1):
    """Generate Gmail dot-trick aliases (no creation needed)."""
    GMAIL_USER = os.environ.get("QWEN_GMAIL_USER", "")
    base = GMAIL_USER.split("@")[0]
    domain = GMAIL_USER.split("@")[1]

    aliases = set()
    # Generate unique dot-trick variations
    positions = list(range(1, len(base)))  # positions where dots can go

    attempts = 0
    while len(aliases) < count and attempts < count * 10:
        attempts += 1
        # Random dot placement
        num_dots = random.randint(1, min(len(positions), 5))
        dot_positions = sorted(random.sample(positions, num_dots))

        alias = base[0]
        for i in range(1, len(base)):
            if i in dot_positions:
                alias += "."
            alias += base[i]

        aliases.add(f"{alias}@{domain}")

    log("GMAIL", f"Generated {len(aliases)} aliases from {GMAIL_USER}")
    return list(aliases)


# ─ Menu ────────────────────────────────────────────

def show_menu():
    """Interactive CLI menu."""
    print()
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║         EMAIL FARM — BULK EMAIL CREATION                     ║")
    print("  ╠═══════════════════════════════════════════════════════════════╣")
    print("  ║                                                               ║")
    print("  ║  Pilih situs email gratis:                                    ║")
    print("  ║                                                               ║")
    print("  ║  [1] mail.tm         ★ RECOMMENDED                           ║")
    print("  ║      API gratis, unlimited, password custom, persist 60 hari ║")
    print("  ║      Semua akun password sama, bisa login via web/API        ║")
    print("  ║                                                               ║")
    print("  ║  [2] 1secmail        ★ MUDAH                                 ║")
    print("  ║      API gratis, unlimited, no password (inbox publik)       ║")
    print("  ║      Cepat, langsung pakai, tidak perlu login                ║")
    print("  ║                                                               ║")
    print("  ║  [3] guerrillamail   (60 menit, session-based)               ║")
    print("  ║      API gratis, inbox hilang setelah 60 menit               ║")
    print("  ║                                                               ║")
    print("  ║  [4] gmail dot trick (512 alias dari 1 akun)                 ║")
    print("  ║      Password sama (1 akun Gmail), OTP via IMAP              ║")
    print("  ║      Sudah teruji untuk Xiaomi registration                  ║")
    print("  ║                                                               ║")
    print("  ║  [5] tempmail.plus   (9 domains, API gratis)                 ║")
    print("  ║      Inbox publik, no password, 1 hari expiry                ║")
    print("  ║                                                               ║")
    print("  ╠═══════════════════════════════════════════════════════════════╣")
    print("  ║  Semua akun disimpan di:                                      ║")
    print("  ║    email_farm_results.json (JSON)                             ║")
    print("  ║    email_farm_accounts.csv  (CSV, buka di Excel)              ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print()

    while True:
        try:
            choice = input("  Pilih situs [1-5] (default 1): ").strip()
        except:
            choice = "1"
        if choice in ("", "1", "2", "3", "4", "5"):
            return choice or "1"
        print("  Invalid. Enter 1-5.")


def run_bulk(provider_choice, count, password=None):
    """Run bulk email creation."""
    accounts = []
    provider_names = {
        "1": "mail.tm",
        "2": "1secmail",
        "3": "guerrillamail",
        "4": "gmail dot trick",
        "5": "tempmail.plus",
    }
    log("FARM", f"Provider: {provider_names.get(provider_choice, '?')} | Count: {count}")

    if provider_choice == "1":
        # mail.tm — password sama untuk semua
        if not password:
            password = generate_password()
            log("FARM", f"Generated password: {password}")
        for i in range(count):
            log("FARM", f"Creating account {i+1}/{count}...")
            acc = create_mailtm_account(password)
            if acc:
                acc["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                accounts.append(acc)
            time.sleep(1)  # Rate limit

    elif provider_choice == "2":
        # 1secmail — no password
        for i in range(count):
            log("FARM", f"Creating inbox {i+1}/{count}...")
            acc = create_1secmail_account()
            if acc:
                acc["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                accounts.append(acc)
            time.sleep(0.5)

    elif provider_choice == "3":
        # guerrillamail — session-based
        for i in range(count):
            log("FARM", f"Creating inbox {i+1}/{count}...")
            acc = create_guerrillamail_account()
            if acc:
                acc["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                accounts.append(acc)
            time.sleep(1)

    elif provider_choice == "4":
        # gmail dot trick
        aliases = create_gmail_alias(count)
        for email in aliases:
            accounts.append({
                "email": email,
                "password": password or "(same Gmail password)",
                "provider": "gmail-dot-trick",
                "inbox_url": "https://mail.google.com",
                "notes": "Alias via dot trick, OTP via IMAP",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            })

    elif provider_choice == "5":
        # tempmail.plus — reuse existing provider
        try:
            from farm_headless import TempMailProvider
            for i in range(count):
                log("FARM", f"Creating inbox {i+1}/{count}...")
                provider = TempMailProvider()
                email = provider.generate_email()
                if email:
                    accounts.append({
                        "email": email,
                        "password": "(no password — public inbox)",
                        "provider": "tempmail.plus",
                        "inbox_url": "https://tempmail.plus/",
                        "notes": "Inbox public, 1 day expiry",
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    })
                time.sleep(1)
        except Exception as e:
            log("FARM", f"tempmail.plus error: {e}")

    if accounts:
        save_accounts(accounts)
        log("FARM", f"DONE! {len(accounts)}/{count} accounts created")
        print()
        print("  ── Summary ──")
        for acc in accounts[:5]:
            print(f"    {acc['email']} | {acc['password'][:20]}")
        if len(accounts) > 5:
            print(f"    ... and {len(accounts)-5} more (see CSV)")
    else:
        log("FARM", "No accounts created")

    return accounts


def main():
    print()
    print("  ╔═══════════════════════════════════════════════════════════╗")
    print("  ║           ALIBABA CLOUD FARM — MAIN MENU                 ║")
    print("  ╠═══════════════════════════════════════════════════════════╣")
    print("  ║                                                           ║")
    print("  ║  [1] Xiaomi MiMo Farm     (registrasi + API key)         ║")
    print("  ║  [2] Email Farm           (bulk email creation)  ← NEW   ║")
    print("  ║  [3] Alibaba Cloud Farm   (registrasi akun Alibaba)     ║")
    print("  ║  [4] Exit                                                 ║")
    print("  ║                                                           ║")
    print("  ╚═══════════════════════════════════════════════════════════╝")
    print()

    while True:
        try:
            choice = input("  Pilih menu [1-4]: ").strip()
        except:
            choice = "4"
        if choice == "1":
            # Launch xiaomi_farm
            log("MENU", "Launching Xiaomi MiMo Farm...")
            os.system(f'"{sys.executable}" "{os.path.join(FARM_DIR, "xiaomi_farm.py")}" --show --debug')
            break
        elif choice == "2":
            # Email Farm
            provider = show_menu()
            try:
                count = int(input("  Jumlah akun (default 10): ").strip() or "10")
            except:
                count = 10
            password = None
            if provider in ("1", "4"):
                pwd_input = input("  Password (kosongkan = auto-generate): ").strip()
                if pwd_input:
                    password = pwd_input
            run_bulk(provider, count, password)
            break
        elif choice == "3":
            # Launch farm_headless
            log("MENU", "Launching Alibaba Cloud Farm...")
            os.system(f'"{sys.executable}" "{os.path.join(FARM_DIR, "farm_headless.py")}"')
            break
        elif choice == "4":
            print("  Bye!")
            break
        else:
            print("  Invalid. Enter 1-4.")


if __name__ == "__main__":
    main()
