"""
Central data path definitions for all farm tabs.

Each tab has its own subdirectory under data/ with isolated JSON + CSV files.
Gmail dot-trick tabs also get an alias index for dedup.

Structure:
  data/
    xiaomi/        — Xiaomi MiMo Farm
      xiaomi_results.json
      xiaomi_accounts.csv
    email/         — Email Farm
      email_farm_results.json
      email_farm_accounts.csv
      alias_index.json          (dedup for gmail dot trick)
    alibaba/       — Alibaba Cloud Farm
      alibaba_results.json
      alibaba_accounts.csv
      alias_index.json          (dedup for gmail dot trick)
    qwen/          — Qwen Cloud Farm
      qwen_results.json
      qwen_accounts.csv
      alias_index.json          (dedup for gmail dot trick)
    mistral/       — Mistral AI Farm
      mistral_results.json
      mistral_accounts.csv
      alias_index.json          (dedup for gmail dot trick)

Usage:
  from data_paths import DATA_DIR, get_path, get_alias_index_path
  results_file = get_path("alibaba", "results.json")
  csv_file = get_path("alibaba", "accounts.csv")
  alias_index = get_alias_index_path("alibaba")
"""

import os
import json
import threading

FARM_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(FARM_DIR, "data")

# ─ Tab subdirectories ──────────────────────────────
TAB_DIRS = {
    "xiaomi":      os.path.join(DATA_DIR, "xiaomi"),
    "email":       os.path.join(DATA_DIR, "email"),
    "alibaba":     os.path.join(DATA_DIR, "alibaba"),
    "qwen":        os.path.join(DATA_DIR, "qwen"),
    "mistral":     os.path.join(DATA_DIR, "mistral"),
    "siliconflow": os.path.join(DATA_DIR, "siliconflow"),
    "wavespeed":   os.path.join(DATA_DIR, "wavespeed"),
}

# ─ File definitions per tab ────────────────────────
TAB_FILES = {
    "xiaomi": {
        "results.json":  "xiaomi_results.json",
        "accounts.csv":  "xiaomi_accounts.csv",
    },
    "email": {
        "results.json":  "email_farm_results.json",
        "accounts.csv":  "email_farm_accounts.csv",
    },
    "alibaba": {
        "results.json":  "alibaba_results.json",
        "accounts.csv":  "alibaba_accounts.csv",
    },
    "qwen": {
        "results.json":  "qwen_results.json",
        "accounts.csv":  "qwen_accounts.csv",
    },
    "mistral": {
        "results.json":  "mistral_results.json",
        "accounts.csv":  "mistral_accounts.csv",
    },
    "siliconflow": {
        "results.json":  "siliconflow_results.json",
        "accounts.csv":  "siliconflow_accounts.csv",
    },
    "wavespeed": {
        "results.json":  "wavespeed_results.json",
        "accounts.csv":  "wavespeed_accounts.csv",
    },
}

# ─ Tabs that use Gmail dot trick (need alias dedup) ──
GMAIL_DOT_TRICK_TABS = {"email", "alibaba", "qwen", "mistral", "siliconflow"}


def get_path(tab, file_key):
    """Get absolute path for a tab's file.
    
    Args:
        tab: one of "xiaomi", "email", "alibaba", "qwen", "mistral"
        file_key: "results.json" or "accounts.csv"
    
    Returns:
        Absolute path string.
    """
    tab_dir = TAB_DIRS[tab]
    os.makedirs(tab_dir, exist_ok=True)
    filename = TAB_FILES[tab][file_key]
    return os.path.join(tab_dir, filename)


def get_alias_index_path(tab):
    """Get path to alias index file for a tab (gmail dot trick dedup).
    
    Returns None if tab doesn't use gmail dot trick.
    """
    if tab not in GMAIL_DOT_TRICK_TABS:
        return None
    tab_dir = TAB_DIRS[tab]
    os.makedirs(tab_dir, exist_ok=True)
    return os.path.join(tab_dir, "alias_index.json")


# ─ Alias index manager (thread-safe dedup) ─────────
_alias_locks = {}


def _get_lock(tab):
    """Get or create a threading.RLock for a tab's alias index.
    
    Uses RLock (reentrant) so mark_alias_used can call save_alias_index
    without deadlocking.
    """
    if tab not in _alias_locks:
        _alias_locks[tab] = threading.RLock()
    return _alias_locks[tab]


def load_alias_index(tab):
    """Load alias index for a tab.
    
    Returns:
        dict with keys:
            "aliases": {email: True} — set-like dict for O(1) lookup
            "base_gmail": str — the base gmail address
    """
    path = get_alias_index_path(tab)
    if not path or not os.path.exists(path):
        return {"aliases": {}, "base_gmail": ""}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"aliases": {}, "base_gmail": ""}


def save_alias_index(tab, index):
    """Save alias index for a tab (thread-safe)."""
    path = get_alias_index_path(tab)
    if not path:
        return
    lock = _get_lock(tab)
    with lock:
        with open(path, "w") as f:
            json.dump(index, f, indent=2)


def is_alias_used(tab, email):
    """Check if a gmail dot-trick alias is already used (O(1) lookup).
    
    Args:
        tab: tab name
        email: alias email to check
    
    Returns:
        True if alias already used, False otherwise.
    """
    index = load_alias_index(tab)
    return email.lower() in index.get("aliases", {})


def mark_alias_used(tab, email, base_gmail=None):
    """Mark a gmail dot-trick alias as used (thread-safe, dedup).
    
    Args:
        tab: tab name
        email: alias email to mark
        base_gmail: optional base gmail address to store
    
    Returns:
        True if alias was newly added, False if already existed.
    """
    lock = _get_lock(tab)
    with lock:
        index = load_alias_index(tab)
        email_lower = email.lower()
        if email_lower in index.get("aliases", {}):
            return False  # already used
        if "aliases" not in index:
            index["aliases"] = {}
        index["aliases"][email_lower] = True
        if base_gmail and not index.get("base_gmail"):
            index["base_gmail"] = base_gmail.lower()
        save_alias_index(tab, index)
        return True


def get_used_count(tab):
    """Get count of used aliases for a tab (O(1))."""
    index = load_alias_index(tab)
    return len(index.get("aliases", {}))


def migrate_legacy_files():
    """One-time migration: move legacy root-level data files to data/<tab>/.
    
    Moves:
      xiaomi_results.json, xiaomi_accounts.csv → data/xiaomi/
      email_farm_results.json, email_farm_accounts.csv → data/email/
      qwen_results.json, qwen_accounts.csv → data/qwen/
      alibaba_accounts.csv → data/alibaba/
      mistral_accounts.csv → data/mistral/
      results.json → data/alibaba/ (legacy farm_headless output)
      results_gmail.json → data/alibaba/ (legacy gmail provider)
      used_aliases.json → data/email/alias_index.json (converted)
    """
    import shutil
    import csv as _csv

    # Legacy → (tab, file_key) mapping
    legacy_map = {
        "xiaomi_results.json":      ("xiaomi",   "results.json"),
        "xiaomi_accounts.csv":      ("xiaomi",   "accounts.csv"),
        "email_farm_results.json":  ("email",    "results.json"),
        "email_farm_accounts.csv":  ("email",    "accounts.csv"),
        "qwen_results.json":        ("qwen",     "results.json"),
        "qwen_accounts.csv":        ("qwen",     "accounts.csv"),
        "alibaba_accounts.csv":     ("alibaba",  "accounts.csv"),
        "mistral_accounts.csv":     ("mistral",  "accounts.csv"),
        "results.json":             ("alibaba",  "results.json"),
        "results_gmail.json":       ("alibaba",  "results.json"),
    }

    migrated = []
    for legacy_name, (tab, file_key) in legacy_map.items():
        legacy_path = os.path.join(FARM_DIR, legacy_name)
        new_path = get_path(tab, file_key)
        if os.path.exists(legacy_path):
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            # Don't overwrite if new file already has data
            if os.path.exists(new_path):
                # Merge: append legacy data to new file
                _merge_files(legacy_path, new_path, file_key)
                os.remove(legacy_path)
            else:
                shutil.move(legacy_path, new_path)
            migrated.append(f"{legacy_name} → data/{tab}/{TAB_FILES[tab][file_key]}")

    # Convert used_aliases.json → data/email/alias_index.json
    old_aliases = os.path.join(FARM_DIR, "used_aliases.json")
    if os.path.exists(old_aliases):
        try:
            with open(old_aliases, "r") as f:
                data = json.load(f)
            aliases = data if isinstance(data, list) else data.get("used_aliases", list(data.values()) if isinstance(data, dict) else [])
            index = {"aliases": {a.lower(): True for a in aliases}, "base_gmail": ""}
            save_alias_index("email", index)
            os.remove(old_aliases)
            migrated.append("used_aliases.json → data/email/alias_index.json")
        except Exception:
            pass

    return migrated


def _merge_files(old_path, new_path, file_key):
    """Merge old file into new file (JSON append or CSV append)."""
    if file_key == "results.json":
        try:
            old_data = []
            new_data = []
            with open(old_path) as f:
                old_data = json.load(f)
            with open(new_path) as f:
                new_data = json.load(f)
            # Avoid duplicates by email
            existing_emails = {r.get("email", "").lower() for r in new_data if isinstance(r, dict)}
            for r in old_data:
                if isinstance(r, dict) and r.get("email", "").lower() not in existing_emails:
                    new_data.append(r)
            with open(new_path, "w") as f:
                json.dump(new_data, f, indent=2)
        except (json.JSONDecodeError, IOError):
            pass
    elif file_key == "accounts.csv":
        try:
            with open(new_path, "a", newline="") as f_out:
                with open(old_path, newline="") as f_in:
                    # Skip header line of old file
                    lines = f_in.readlines()
                    if lines:
                        f_out.writelines(lines[1:])
        except IOError:
            pass


# ─ Ensure directories exist on import ──────────────
for tab_dir in TAB_DIRS.values():
    os.makedirs(tab_dir, exist_ok=True)
