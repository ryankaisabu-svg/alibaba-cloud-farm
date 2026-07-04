"""
gui/proxy.py — Global Proxy Module for all farm tabs.

Provides:
  - Proxy loading from WebShare-format file (host:port:user:pass per line)
  - Reusable proxy widget (tkinter UI) for any tab
  - CLI arg builder: converts widget state to --proxy args
  - Per-browser rotation for multi-account farming

Usage in tab's _build_settings():
    from gui.proxy import build_proxy_widget
    self.proxy_vars = build_proxy_widget(self._settings_frame)

Usage in tab's _build_args():
    from gui.proxy import get_proxy_args
    return get_proxy_args(self.proxy_vars) + [...other args...]

Usage in farm script:
    # Parse: --proxy http://user:pass@host:port
    # Apply to browser launch kwargs["proxy"] = {"server": proxy_url}

Proxy file format (WebShare):
    p.webshare.io:80:pckxkdbx-1:8ediniy4aouv
    p.webshare.io:80:pckxkdbx-2:8ediniy4aouv
    ...
"""

import os
import random
import tkinter as tk
from tkinter import ttk

FARM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROXY_FILE = os.path.join(FARM_DIR, "data", "wavespeed", "webshare_proxies.txt")

# ── Shared colors (from base_tab.py) ────────────────────
BG_PANEL = "#2a2a3c"
BG_INPUT = "#363649"
FG_MAIN = "#cdd6f4"
FG_DIM = "#7f7f9f"
ACCENT = "#89b4fa"
ACCENT_GREEN = "#a6e3a1"


# ── Proxy Data ─────────────────────────────────────────

_proxies_cache = None
_proxies_cache_file = None


def load_proxies(filepath=None):
    """Load proxies from WebShare format file.

    Args:
        filepath: path to proxy file. Default: data/wavespeed/webshare_proxies.txt

    Returns:
        list of dict: [{"host": str, "port": str, "user": str, "pass": str, "url": str}, ...]
        Returns [] if file missing or empty.
    """
    global _proxies_cache, _proxies_cache_file

    filepath = filepath or DEFAULT_PROXY_FILE

    if (_proxies_cache is not None
            and _proxies_cache_file == filepath
            and os.path.exists(filepath)):
        return _proxies_cache

    proxies = []
    if not os.path.exists(filepath):
        return proxies

    with open(filepath, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) >= 4:
                host = parts[0].strip()
                port = parts[1].strip()
                user = parts[2].strip()
                passwd = ":".join(parts[3:]).strip()
                url = f"http://{user}:{passwd}@{host}:{port}"
                proxies.append({
                    "host": host,
                    "port": port,
                    "user": user,
                    "pass": passwd,
                    "url": url,
                    "_line": line_no,
                })

    _proxies_cache = proxies
    _proxies_cache_file = filepath
    return proxies


def get_proxy(index=0, filepath=None):
    """Get a single proxy URL by index (with cycling).

    Args:
        index: which proxy to get (0-based). Cycles with modulo.
        filepath: optional override for proxy file.

    Returns:
        proxy URL string like "http://user:pass@host:port" or None.
    """
    proxies = load_proxies(filepath)
    if not proxies:
        return None
    return proxies[index % len(proxies)]["url"]


def get_proxy_dict(index=0, filepath=None):
    """Get full proxy dict by index."""
    proxies = load_proxies(filepath)
    if not proxies:
        return None
    return proxies[index % len(proxies)]


def reload_proxies():
    """Force reload proxy cache on next access."""
    global _proxies_cache, _proxies_cache_file
    _proxies_cache = None
    _proxies_cache_file = None


def count_proxies(filepath=None):
    """Return number of available proxies."""
    return len(load_proxies(filepath))


# ── URL Builder ────────────────────────────────────────

def build_proxy_url(host, port, user, password):
    """Build proxy URL from components.

    Returns:
        "http://user:password@host:port"
    """
    host = host or "p.webshare.io"
    port = port or "80"
    if user and password:
        return f"http://{user}:{password}@{host}:{port}"
    return f"http://{host}:{port}"


# ── Widget Factory ─────────────────────────────────────

def build_proxy_widget(parent_frame, row_offset=25):
    """Build a reusable proxy settings widget inside parent frame.

    Inserts a LabelFrame with:
      - Proxy enable checkbox (OFF / ON)
      - Mode: Auto (rotate from file) / Manual (single proxy)
      - Manual fields: Host, Port, User, Pass (shown when Manual mode selected)
      - Proxy file path (shown when Auto mode, read-only label)
      - Status label showing proxy count

    Args:
        parent_frame: the tk.Frame to insert into (usually self._settings_frame)
        row_offset: grid row number to start at (default 25, after other settings)

    Returns:
        dict of StringVar/BooleanVar keys that tab can read:
        {
            "enabled": BooleanVar     — whether proxy is active
            "mode": StringVar         — "off" / "auto" / "manual"
            "host": StringVar          — manual proxy host
            "port": StringVar          — manual proxy port
            "user": StringVar          — manual proxy user
            "pass": StringVar          — manual proxy password
            "file_path": StringVar     — path to proxy list file
            "status": StringVar        — status text (readonly label)
        }
    """

    vars_dict = {
        "enabled": tk.BooleanVar(value=False),
        "mode": tk.StringVar(value="auto"),
        "host": tk.StringVar(value="p.webshare.io"),
        "port": tk.StringVar(value="80"),
        "user": tk.StringVar(value=""),
        "pass": tk.StringVar(value=""),
        "file_path": tk.StringVar(value=DEFAULT_PROXY_FILE),
        "status": tk.StringVar(value=""),
    }

    # ── Section: Proxy Settings ──
    sec = tk.LabelFrame(parent_frame,
                       text="  \U0001f6a7  PROXY (Global)  ",
                       bg=BG_PANEL, fg=ACCENT,
                       font=("Segoe UI", 8, "bold"),
                       labelanchor="w", padx=8, pady=5)
    sec.grid(row=row_offset, column=0, columnspan=5, sticky="we", pady=(8, 3))

    # Enable checkbox + mode selection row
    top_row = tk.Frame(sec, bg=BG_PANEL)
    top_row.pack(fill=tk.X, pady=(0, 3))

    cb = tk.Checkbutton(top_row, text="Enable Proxy",
                        variable=vars_dict["enabled"], bg=BG_PANEL, fg=FG_MAIN,
                        selectcolor=BG_INPUT, activebackground=BG_PANEL,
                        font=("Segoe UI", 9, "bold"),
                        command=lambda: _on_proxy_toggle(vars_dict))
    cb.pack(side=tk.LEFT)

    # Separator
    tk.Frame(top_row, bg=FG_DIM, width=2).pack(side=tk.LEFT, padx=(10, 10))

    # Mode radio buttons
    for mval, mtext in [("auto", "\U0001f504 Auto (rotate)"), ("manual", "\u270f Manual")]:
        rb = tk.Radiobutton(top_row, text=mtext, variable=vars_dict["mode"],
                           value=mval, bg=BG_PANEL, fg=FG_MAIN,
                           selectcolor=BG_INPUT, activebackground=BG_PANEL,
                           font=("Segoe UI", 8),
                           state=tk.DISABLED,  # disabled until enabled
                           command=lambda v=mval, vd=vars_dict: _on_mode_toggle(v, vd))
        rb.pack(side=tk.LEFT, padx=(0, 10))
        setattr(rb, "_proxy_mode_value", mval)  # store for later enable

    # Store radio refs for enable/disable
    vars_dict["_mode_radios"] = [
        w for w in top_row.winfo_children() if isinstance(w, tk.Radiobutton)
    ]

    # ── Manual Proxy Fields Frame ──
    manual_frame = tk.Frame(sec, bg=BG_PANEL)
    vars_dict["_manual_frame"] = manual_frame

    fields = [
        ("Host:", vars_dict["host"], 16),
        ("Port:", vars_dict["port"], 5),
        ("User:", vars_dict["user"], 14),
        ("Pass:", vars_dict["pass"], 12),
    ]
    for label_text, var, width in fields:
        row_f = tk.Frame(manual_frame, bg=BG_PANEL)
        row_f.pack(side=tk.LEFT, padx=(0, 4))
        show_char = "*" if "ass" in label_text else None
        tk.Label(row_f, text=label_text, bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8), width=4, anchor="e").pack(side=tk.LEFT)
        tk.Entry(row_f, textvariable=var, bg=BG_INPUT, fg=FG_MAIN,
                 width=width, insertbackground=FG_MAIN,
                 font=("Segoe UI", 8), show=show_char).pack(side=tk.LEFT)

    # ── Auto mode: file info ──
    auto_frame = tk.Frame(sec, bg=BG_PANEL)
    vars_dict["_auto_frame"] = auto_frame

    tk.Label(auto_frame, text="File:",
             bg=BG_PANEL, fg=FG_DIM, font=("Segoe UI", 8)).pack(side=tk.LEFT)

    tk.Entry(auto_frame, textvariable=vars_dict["file_path"],
             bg=BG_INPUT, fg=ACCENT_YELLOW, width=40,
             insertbackground=FG_MAIN, font=("Segoe UI", 8),
             state="readonly").pack(side=tk.LEFT, padx=(4, 4), fill=tk.X, expand=True)

    btn_reload = tk.Button(auto_frame, text="Reload",
                            bg=ACCENT, fg="#1e1e2e",
                            font=("Segoe UI", 7), relief=tk.FLAT, padx=5,
                            command=lambda: _on_reload_count(vars_dict))
    btn_reload.pack(side=tk.LEFT)
    vars_dict["_reload_btn"] = btn_reload

    # ── Status Label ──
    vars_dict["status"].set("\U0001f3af 20,000 proxies loaded")
    status_lbl = tk.Label(sec, textvariable=vars_dict["status"],
                          bg=BG_PANEL, fg=ACCENT_GREEN,
                          font=("Segoe UI", 7))
    status_lbl.pack(anchor="w", pady=(3, 0))
    vars_dict["_status_lbl"] = status_lbl

    # Initial state: disabled
    manual_frame.pack_forget()

    # Load initial count
    _update_status(vars_dict)

    return vars_dict


# ── Internal Callbacks ─────────────────────────────────

def _on_proxy_toggle(vd):
    """Called when proxy checkbox is toggled."""
    enabled = vd["enabled"].get()

    # Enable/disable mode radios
    for rb in vd.get("_mode_radios", []):
        if enabled:
            rb.config(state=tk.NORMAL)
        else:
            rb.config(state=tk.DISABLED)

    if enabled:
        _on_mode_toggle(vd["mode"].get(), vd)
    else:
        # Hide both frames when disabled
        vd["_manual_frame"].pack_forget()
        vd["_auto_frame"].pack_forget()
        vd["status"].set("Proxy disabled")


def _on_mode_toggle(mode_val, vd):
    """Called when auto/manual radio changes."""
    if not vd["enabled"].get():
        return

    if mode_val == "manual":
        vd["_manual_frame"].pack(fill=tk.X, pady=(4, 0), before=vd["_status_lbl"].master.winfo_children()[-1])
        vd["_auto_frame"].pack_forget()
        vd["status"].set("\U0001f527 Enter proxy details above")
    else:  # auto
        vd["_manual_frame"].pack_forget()
        vd["_auto_frame"].pack(fill=tk.X, pady=(4, 0), before=vd["_status_lbl"].master.winfo_children()[-1])
        _update_status(vd)


def _on_reload_count(vd):
    """Reload proxy file and update count display."""
    reload_proxies()
    _update_status(vd)


def _update_status(vd):
    """Update status label with current proxy count."""
    try:
        n = count_proxies(vd["file_path"].get())
        if n > 0:
            vd["status"].set(f"\U0001f3af {n:,} proxies loaded")
            vd["_status_lbl"].config(fg=ACCENT_GREEN)
        else:
            vd["status"].set("\U0001f533 No proxy file found (running without proxy)")
            vd["_status_lbl"].config(fg=ACCENT_RED)
    except Exception:
        vd["status"].set("\U0001f533 Error reading proxy file")


# ── CLI Arg Builder ────────────────────────────────────

def get_proxy_args(widget_vars, browser_index=0):
    """Convert proxy widget state to CLI arguments list.

    Args:
        widget_vars: dict returned by build_proxy_widget()
        browser_index: which browser this is for (0-based, used for rotation)

    Returns:
        list: CLI args e.g., ["--proxy", "http://user:pass@host:port"]
              or [] if proxy disabled/not configured.
    """
    if not widget_vars.get("enabled") or not widget_vars["enabled"].get():
        return []

    mode = widget_vars["mode"].get()

    if mode == "manual":
        host = widget_vars["host"].get().strip()
        port = widget_vars["port"].get().strip()
        user = widget_vars["user"].get().strip()
        pw = widget_vars["pass"].get().strip()

        if not host:
            return []
        url = build_proxy_url(host, port, user, pw)
        return ["--proxy", url]

    elif mode == "auto":
        filepath = widget_vars["file_path"].get().strip()
        url = get_proxy(browser_index, filepath)
        if url:
            return ["--proxy", url]
        return []

    return []


# ── Convenience: Get proxy for specific browser ─────────

def get_proxy_for_browser(browser_index=0, filepath=None):
    """Get a rotated proxy URL for a specific browser instance.

    In multi-browser farming, each browser should use a different
    proxy IP so Google/SiliconFlow sees different sources.

    Args:
        browser_index: 0-based browser number
        filepath: optional proxy file path

    Returns:
        proxy URL string or None
    """
    return get_proxy(browser_index, filepath)


if __name__ == "__main__":
    # Quick test
    print(f"Proxy file: {DEFAULT_PROXY_FILE}")
    print(f"Proxies loaded: {count_proxies()}")
    print(f"Proxy[0]: {get_proxy(0)}")
    print(f"Proxy[1]: {get_proxy(1)}")
    print(f"Proxy[9999]: {get_proxy(9999)}")
