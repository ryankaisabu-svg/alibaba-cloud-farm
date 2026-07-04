"""
gui/tabs.py — Concrete tab implementations inheriting BaseFarmTab.

Each tab overrides only what's unique:
  - class attributes (TAB_TITLE, FARM_SCRIPT, RESULTS_KEY, RESULT_COLS)
  - _build_settings() for farm-specific input fields
  - _build_args() for farm-specific CLI args
  - _post_init() for extra setup

Layout: BaseFarmTab uses vertical (top-down) layout by default.
Tabs needing horizontal (left-right) layout override _build_ui().

This file is the modular replacement for the 5 tab classes in farm_gui.py.
 farm_gui.py stays intact until Phase 9 validation.
"""

import os
import sys
import json
import subprocess
import csv as _csv
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

from gui.base_tab import (
    BaseFarmTab, RedirectText,
    BG_DARK, BG_PANEL, BG_INPUT, FG_MAIN, FG_DIM,
    ACCENT, ACCENT_GREEN, ACCENT_RED, ACCENT_YELLOW,
)

FARM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ════════════════════════════════════════════════════════════════
# Mixin: Gmail Alias Info
# ════════════════════════════════════════════════════════════════

class GmailAliasMixin:
    """Mixin for tabs that use Gmail dot-trick aliases.

    Provides _build_alias_widgets(), _update_alias_info(), _on_gmail_changed().
    Subclass must set ALIAS_CSV_KEY (e.g. "alibaba", "mistral") for the CSV path.
    """

    ALIAS_CSV_KEY = None  # override in subclass

    def _build_alias_widgets(self, settings, start_row=0):
        """Build Gmail user/pass entries + alias info bar. Returns next free row."""
        # Gmail user
        tk.Label(settings, text="Gmail:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=start_row, column=0, sticky="w", pady=3)
        self.gmail_user = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=28,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 9), show="*")
        self.gmail_user.insert(0, os.environ.get("QWEN_GMAIL_USER", ""))
        self.gmail_user.grid(row=start_row, column=1, columnspan=3, sticky="we", pady=3, padx=(5, 0))
        self.gmail_user.bind("<KeyRelease>", self._on_gmail_changed)

        # App password
        tk.Label(settings, text="App Pass:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=start_row + 1, column=0, sticky="w", pady=3)
        self.gmail_pass = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=28,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 9), show="*")
        self.gmail_pass.insert(0, os.environ.get("QWEN_GMAIL_APP_PASS", ""))
        self.gmail_pass.grid(row=start_row + 1, column=1, columnspan=3, sticky="we", pady=3, padx=(5, 0))

        # Alias info bar
        self.max_aliases_var = tk.StringVar(value="Max: -")
        self.used_aliases_var = tk.StringVar(value="Used: -")
        self.remaining_aliases_var = tk.StringVar(value="Remaining: -")
        self.complete_var = tk.StringVar(value="Complete: -")
        self.recoverable_var = tk.StringVar(value="Recoverable: -")

        alias_row = tk.Frame(settings, bg=BG_PANEL)
        alias_row.grid(row=start_row + 2, column=0, columnspan=4, sticky="we", pady=(3, 2))
        tk.Label(alias_row, textvariable=self.max_aliases_var, bg=BG_PANEL, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(alias_row, textvariable=self.used_aliases_var, bg=BG_PANEL, fg=ACCENT_RED,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(alias_row, textvariable=self.remaining_aliases_var, bg=BG_PANEL, fg=ACCENT_GREEN,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))

        alias_row2 = tk.Frame(settings, bg=BG_PANEL)
        alias_row2.grid(row=start_row + 3, column=0, columnspan=4, sticky="we", pady=(0, 5))
        tk.Label(alias_row2, textvariable=self.complete_var, bg=BG_PANEL, fg=ACCENT_GREEN,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(alias_row2, textvariable=self.recoverable_var, bg=BG_PANEL, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)

        return start_row + 4

    def _on_gmail_changed(self, event=None):
        self._update_alias_info()

    def _update_alias_info(self):
        """Calculate and display Gmail dot-trick alias stats from CSV."""
        gmail = self.gmail_user.get().strip().lower()
        if not gmail or "@" not in gmail:
            self.max_aliases_var.set("Max: -")
            self.used_aliases_var.set("Used: -")
            self.remaining_aliases_var.set("Remaining: -")
            self.complete_var.set("Complete: -")
            self.recoverable_var.set("Recoverable: -")
            return

        username = gmail.split("@")[0]
        clean = username.replace(".", "")
        if len(clean) < 2:
            max_aliases = 1
        else:
            max_aliases = 2 ** (len(clean) - 1)

        used_count = 0
        complete_count = 0
        recoverable_count = 0

        from data_paths import get_path
        results_file = get_path(self.ALIAS_CSV_KEY, "accounts.csv")
        if os.path.exists(results_file):
            try:
                with open(results_file, newline="") as f:
                    for row in _csv.DictReader(f):
                        used_count += 1
                        status = row.get("status", "").strip().lower()
                        apikey = row.get("api_key", "").strip()
                        if (status == "complete" and apikey
                                and apikey != "REGISTRATION_FAILED"
                                and not apikey.startswith("EXCEPTION")):
                            complete_count += 1
                        elif status == "failed" or not apikey:
                            recoverable_count += 1
            except Exception:
                pass

        remaining = max(0, max_aliases - used_count)

        self.max_aliases_var.set(f"Max: {max_aliases}")
        self.used_aliases_var.set(f"Used: {used_count}")
        self.remaining_aliases_var.set(f"Remaining: {remaining}")
        self.complete_var.set(f"Complete: {complete_count}")
        self.recoverable_var.set(f"Recoverable: {recoverable_count}")


# ════════════════════════════════════════════════════════════════
# Mixin: Horizontal (Left-Right) Layout
# ════════════════════════════════════════════════════════════════

class HorizontalLayoutMixin:
    """Mixin for tabs that use horizontal left-right layout (AlibabaTab, MistralTab).

    Provides _build_horizontal_ui() — a complete alternative to BaseFarmTab._build_ui().
    Subclass must override _build_ui() to call _build_horizontal_ui().
    Subclass overrides _build_settings(settings) to populate the left panel.
    """

    def _build_horizontal_ui(self):
        """Horizontal layout: scrollable left settings + right log."""
        # ─ Main horizontal layout ─
        main_frame = tk.Frame(self, bg=BG_DARK)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left panel: scrollable
        left_outer = tk.Frame(main_frame, bg=BG_DARK, width=420)
        left_outer.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        left_outer.pack_propagate(False)

        left_canvas = tk.Canvas(left_outer, bg=BG_DARK, highlightthickness=0)
        left_scroll = tk.Scrollbar(left_outer, orient=tk.VERTICAL, command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        left = tk.Frame(left_canvas, bg=BG_DARK)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_left_configure(event):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
            if left.winfo_reqwidth() != left_canvas.winfo_width():
                left_canvas.itemconfig(left_window, width=left_canvas.winfo_width())

        left.bind("<Configure>", _on_left_configure)
        left_canvas.bind("<Configure>", lambda e: left_canvas.itemconfig(left_window, width=e.width))

        # Mouse wheel scroll
        def _on_wheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        left_canvas.bind_all("<MouseWheel>", _on_wheel)
        left_canvas.bind_all("<Enter>", lambda e: left_canvas.bind_all("<MouseWheel>", _on_wheel))
        left_canvas.bind_all("<Leave>", lambda e: left_canvas.unbind_all("<MouseWheel>"))

        # Right panel: log
        right = tk.Frame(main_frame, bg=BG_DARK)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ─ Header (left) ─
        tk.Label(left, text=self.TAB_TITLE, font=("Segoe UI", 14, "bold"),
                 bg=BG_DARK, fg=FG_MAIN).pack(pady=(5, 2))

        # ─ PC Specs (left) ─
        specs = self._detect_specs()
        self._specs = specs
        specs_text = (f"RAM {specs['ram_gb']}GB | CPU {specs['cpu_physical']}c/{specs['cpu_cores']}t | "
                      f"Max {specs['recommended']} browser")
        tk.Label(left, text=specs_text, bg=BG_DARK, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8, "bold")).pack(pady=(0, 5))

        # ─ Settings frame (left) — subclass populates ─
        settings = tk.Frame(left, bg=BG_PANEL, padx=10, pady=10)
        settings.pack(fill=tk.X, pady=2)
        self._settings_frame = settings

        # Account Count + Concurrency (common)
        tk.Label(settings, text="Count:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=3)
        self.count_var = tk.StringVar(value="1")
        tk.Spinbox(settings, from_=1, to=100, textvariable=self.count_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9)).grid(row=0, column=1, sticky="w", pady=3, padx=(5, 0))

        tk.Label(settings, text="Browsers:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=0, column=2, sticky="w", pady=3, padx=(10, 0))
        self.concurrency_var = tk.IntVar(value=1)
        tk.Spinbox(settings, from_=1, to=8, textvariable=self.concurrency_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9)).grid(row=0, column=3, sticky="w", pady=3, padx=(5, 0))

        tk.Button(settings, text=f"Auto ({specs['recommended']})",
                  bg=ACCENT, fg="#1e1e2e", font=("Segoe UI", 7, "bold"),
                  relief=tk.FLAT, padx=5, pady=1, cursor="hand2",
                  command=lambda: self.concurrency_var.set(min(specs["recommended"], 3))
                  ).grid(row=1, column=3, sticky="e", pady=2)

        # Subclass adds its own fields
        self._build_settings(settings)

        # ─ Browser mode (left) ─
        mode_frame = tk.Frame(left, bg=BG_PANEL, padx=10, pady=5)
        mode_frame.pack(fill=tk.X, pady=2)

        self.headless_var = tk.BooleanVar(value=True)
        self.show_browser_var = tk.BooleanVar(value=False)

        tk.Checkbutton(mode_frame, text="Headless", variable=self.headless_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9), command=self._on_headless_toggle).pack(side=tk.LEFT, padx=(0, 10))
        tk.Checkbutton(mode_frame, text="Show Browser", variable=self.show_browser_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9), command=self._on_show_toggle).pack(side=tk.LEFT, padx=(0, 10))

        # ─ Buttons (left) ─
        btn_frame = tk.Frame(left, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, pady=5)

        self.start_btn = tk.Button(btn_frame, text=f"\u25b6 START {self.TAB_TITLE.upper()}",
                                   bg=ACCENT_GREEN, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                   relief=tk.FLAT, padx=25, pady=8, cursor="hand2",
                                   command=self.start_registration)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = tk.Button(btn_frame, text="\u25a0 STOP",
                                  bg=ACCENT_RED, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                  relief=tk.FLAT, padx=25, pady=8, cursor="hand2",
                                  state=tk.DISABLED, command=self.stop_registration)
        self.stop_btn.pack(side=tk.LEFT)

        # ─ Realtime Stats (left) ─
        stats_frame = tk.Frame(left, bg=BG_PANEL, padx=10, pady=8)
        stats_frame.pack(fill=tk.X, pady=2)

        tk.Label(stats_frame, text="\U0001f4ca Realtime Stats", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 3))

        stats = [
            ("Queued", "stats_queued", ACCENT),
            ("Proc", "stats_processing", ACCENT_YELLOW),
            ("Done", "stats_done", FG_MAIN),
            ("Fail", "stats_failed", ACCENT_RED),
            ("Key", "stats_apikey", ACCENT_GREEN),
        ]
        for i, (label, attr, color) in enumerate(stats):
            col = i
            tk.Label(stats_frame, text=label, bg=BG_PANEL, fg=FG_DIM,
                     font=("Segoe UI", 7)).grid(row=1, column=col, padx=2)
            lbl = tk.Label(stats_frame, text="0", bg=BG_PANEL, fg=color,
                          font=("Segoe UI", 13, "bold"), width=3)
            lbl.grid(row=2, column=col, padx=2)
            setattr(self, attr, lbl)

        # ─ Results (left, bottom) ─
        res_frame = tk.Frame(left, bg=BG_PANEL, padx=8, pady=5)
        res_frame.pack(fill=tk.BOTH, expand=True, pady=2)

        tk.Label(res_frame, text="Accounts:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")

        cols = self.RESULT_COLS
        # Use larger height for tabs with many accounts (SF, WaveSpeed)
        tv_height = 8 if getattr(self, 'RESULTS_KEY', '') in ('siliconflow', 'wavespeed') else 6
        self.tree = ttk.Treeview(res_frame, columns=cols, show="headings", height=tv_height)
        for col in cols:
            self.tree.heading(col, text=col.upper())
            if self.RESULT_COL_WIDTHS and col in self.RESULT_COL_WIDTHS:
                w = self.RESULT_COL_WIDTHS[col]
            else:
                w = 140 if col == "email" else (120 if col == "api_key" else 60)
            self.tree.column(col, width=w)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=3)

        self.load_results()

        # ─ Log output (right, large) ─
        tk.Label(right, text="Output Log:", bg=BG_DARK, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 2))

        self.log_text = scrolledtext.ScrolledText(right, bg=BG_INPUT, fg=ACCENT,
                                                   font=("Consolas", 9),
                                                   insertbackground=FG_MAIN, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Subclass post-init hook
        self._post_init()

    def _build_settings(self, settings):
        """Override in subclass to add farm-specific fields to left panel."""
        pass


# ════════════════════════════════════════════════════════════════
# Tab 1: XiaomiTab
# ════════════════════════════════════════════════════════════════

class XiaomiTab(BaseFarmTab):
    """Xiaomi MiMo Farm — email provider selection + debug + auto-captcha."""

    TAB_TITLE = "Xiaomi MiMo Farm"
    TAB_DESCRIPTION = "Xiaomi MiMo account registration"
    FARM_SCRIPT = "xiaomi_farm.py"
    RESULTS_KEY = "xiaomi"
    RESULT_COLS = ("email", "password", "api_key", "status", "timestamp")
    RESULT_COL_WIDTHS = {"email": 150, "password": 150, "api_key": 250, "status": 150, "timestamp": 150}
    SUPPORTS_COUNT_CONCURRENCY = False  # xiaomi_farm.py doesn't accept --count/--concurrency

    def _build_settings(self, settings):
        """Add provider radio buttons + gmail fields + debug/auto-captcha checkboxes."""
        # Provider
        tk.Label(settings, text="Email Provider:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", pady=5)
        self.provider_var = tk.StringVar(value="gmail")
        providers = [
            ("Gmail (dot trick, 512 alias)", "gmail"),
            ("tempmail.plus (9 domains)", "tempmail"),
            ("mail.tm (free API)", "mailtm"),
            ("Manual", "manual"),
        ]
        for i, (label, val) in enumerate(providers):
            tk.Radiobutton(settings, text=label, variable=self.provider_var, value=val,
                           bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                           activebackground=BG_PANEL, activeforeground=FG_MAIN,
                           font=("Segoe UI", 9)).grid(row=0, column=i + 1, sticky="w", padx=5)

        # Gmail config
        tk.Label(settings, text="Gmail User:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=5)
        self.gmail_user = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=30,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 10))
        self.gmail_user.insert(0, os.environ.get("QWEN_GMAIL_USER", ""))
        self.gmail_user.grid(row=1, column=1, columnspan=2, sticky="w", pady=5)

        tk.Label(settings, text="App Password:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=1, column=3, sticky="w", pady=5)
        self.gmail_pass = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=25,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 10))
        self.gmail_pass.insert(0, os.environ.get("QWEN_GMAIL_APP_PASS", ""))
        self.gmail_pass.grid(row=1, column=4, columnspan=2, sticky="w", pady=5)

        # Options
        self.show_var = tk.BooleanVar(value=True)
        self.debug_var = tk.BooleanVar(value=True)
        self.auto_captcha_var = tk.BooleanVar(value=False)

        tk.Checkbutton(settings, text="Show Browser", variable=self.show_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9)).grid(row=4, column=0, columnspan=2, sticky="w", pady=5)
        tk.Checkbutton(settings, text="Debug Screenshots", variable=self.debug_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9)).grid(row=4, column=2, columnspan=2, sticky="w", pady=5)
        tk.Checkbutton(settings, text="Auto CAPTCHA (CapSolver)", variable=self.auto_captcha_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9)).grid(row=4, column=4, columnspan=2, sticky="w", pady=5)

    def _build_args(self):
        args = ["--provider", self.provider_var.get()]
        if self.show_var.get():
            args.append("--show")
        if self.debug_var.get():
            args.append("--debug")
        if self.auto_captcha_var.get():
            args.append("--auto-captcha")
        return args

    def load_results(self):
        """Load existing results into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        from data_paths import get_path
        results_file = get_path(self.RESULTS_KEY, "results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                for row in data[-20:]:
                    self.tree.insert("", tk.END, values=tuple(
                        row.get(col, "") for col in self.RESULT_COLS
                    ))
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════
# Tab 2: EmailFarmTab (does not use subprocess — imports email_farm directly)
# ════════════════════════════════════════════════════════════════

class EmailFarmTab(BaseFarmTab):
    """Email Farm — bulk email creation via direct import (no subprocess)."""

    TAB_TITLE = "Email Farm"
    TAB_DESCRIPTION = "Bulk email creation — mail.tm, 1secmail, guerrillamail, gmail, tempmail.plus"
    FARM_SCRIPT = None  # uses direct import, not subprocess
    RESULTS_KEY = "email"
    RESULT_COLS = ("email", "password", "provider", "timestamp")
    RESULT_COL_WIDTHS = {"email": 200, "password": 200, "provider": 200, "timestamp": 200}

    def _post_init(self):
        """Override default count to 10 (farm_gui.py uses 10 for email farm)."""
        self.count_var.set("10")

    def _build_settings(self, settings):
        """Provider radio buttons + count + password."""
        # Provider selection
        tk.Label(settings, text="Situs Email:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", pady=5)
        self.provider_var = tk.StringVar(value="1")
        providers = [
            ("mail.tm (RECOMMENDED, password custom)", "1"),
            ("1secmail (no password, public inbox)", "2"),
            ("guerrillamail (60 min session)", "3"),
            ("gmail dot trick (512 alias)", "4"),
            ("tempmail.plus (9 domains)", "5"),
        ]
        for i, (label, val) in enumerate(providers):
            tk.Radiobutton(settings, text=label, variable=self.provider_var, value=val,
                           bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                           activebackground=BG_PANEL, activeforeground=FG_MAIN,
                           font=("Segoe UI", 9)).grid(row=i + 1, column=0, columnspan=4, sticky="w", padx=10)

        # Password
        tk.Label(settings, text="Password (sama untuk semua):", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=7, column=0, sticky="w", pady=5)
        self.password_var = tk.StringVar()
        tk.Entry(settings, textvariable=self.password_var, bg=BG_INPUT, fg=FG_MAIN, width=25,
                 insertbackground=FG_MAIN, font=("Segoe UI", 10)).grid(row=7, column=1, sticky="w", pady=5)
        tk.Label(settings, text="(kosongkan = auto-generate)", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8)).grid(row=7, column=2, sticky="w", pady=5)

    def _build_args(self):
        return []  # EmailFarmTab doesn't use subprocess

    def _run_registration(self):
        """Override: uses direct import instead of subprocess."""
        redirector = RedirectText(self.log_text)
        old_stdout = sys.stdout
        sys.stdout = redirector
        try:
            from email_farm import run_bulk
            provider = self.provider_var.get()
            count = int(self.count_var.get() or "10")
            password = self.password_var.get().strip() or None
            print(f"[GUI] Email Farm Starting")
            print(f"[GUI] Provider: {provider}, Count: {count}")
            accounts = run_bulk(provider, count, password)
            print(f"\n[GUI] Done. Created {len(accounts) if accounts else 0} emails.")
            self.load_results()
        except Exception as e:
            print(f"\n[GUI] Error: {e}")
        finally:
            sys.stdout = old_stdout
            self.running = False
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def load_results(self):
        """Load existing results into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        from data_paths import get_path
        results_file = get_path(self.RESULTS_KEY, "results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                for row in data[-30:]:
                    self.tree.insert("", tk.END, values=tuple(
                        row.get(col, "") for col in self.RESULT_COLS
                    ))
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════
# Tab 3: QwenCloudTab
# ════════════════════════════════════════════════════════════════

class QwenCloudTab(BaseFarmTab, GmailAliasMixin):
    """Qwen Cloud Farm — Gmail dot trick registration + API key extraction."""

    TAB_TITLE = "Qwen Cloud Farm"
    TAB_DESCRIPTION = "Qwen Cloud account registration with Gmail dot-trick aliases"
    FARM_SCRIPT = "alibaba_farm.py"  # farm_gui.py L861 uses alibaba_farm.py, NOT qwen_cloud_farm.py
    RESULTS_KEY = "qwen"
    RESULT_COLS = ("email", "api_key", "status", "timestamp")
    RESULT_COL_WIDTHS = {"email": 200, "api_key": 250, "status": 150, "timestamp": 150}
    ALIAS_CSV_KEY = "qwen"

    def _build_settings(self, settings):
        """Gmail user/pass + alias info bar."""
        next_row = self._build_alias_widgets(settings, start_row=4)
        return next_row

    def _build_args(self):
        args = []
        gmail_user = self.gmail_user.get().strip()
        gmail_pass = self.gmail_pass.get().strip()
        if gmail_user and gmail_pass:
            args.extend(["--gmail", gmail_user, "--apppass", gmail_pass])
        return args

    def _post_init(self):
        self._update_alias_info()

    def _on_stats_received(self):
        self._update_alias_info()

    def load_results(self):
        """Load existing results into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        from data_paths import get_path
        results_file = get_path(self.RESULTS_KEY, "results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                for row in data[-20:]:
                    self.tree.insert("", tk.END, values=tuple(
                        row.get(col, "") for col in self.RESULT_COLS
                    ))
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════
# Tab 4: AlibabaTab (horizontal layout + provider dropdown + browser engine)
# ════════════════════════════════════════════════════════════════

class AlibabaTab(BaseFarmTab, HorizontalLayoutMixin, GmailAliasMixin):
    """Alibaba Cloud Farm — Multi-provider registration + API key.

    Uses horizontal layout (scrollable left + right log).
    Entry point: farm_headless.py (supports --browser flag).
    """

    TAB_TITLE = "Alibaba Cloud Farm"
    TAB_DESCRIPTION = "Multi-provider Alibaba Cloud account registration + API key"
    FARM_SCRIPT = "farm_headless.py"
    RESULTS_KEY = "alibaba"
    RESULT_COLS = ("email", "api_key", "status")
    RESULT_COL_WIDTHS = {"email": 140, "api_key": 120, "status": 60}
    ALIAS_CSV_KEY = "alibaba"

    def _build_ui(self):
        """Use horizontal layout instead of BaseFarmTab's vertical layout."""
        self._build_horizontal_ui()

    def _build_settings(self, settings):
        """Provider dropdown + gmail fields + alias info + debug checkbox."""
        # Email Provider Selection
        tk.Label(settings, text="Provider:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=3)

        self.provider_var = tk.StringVar(value="gmail")
        provider_options = ["tempmail", "gmail", "outlook", "manual"]
        self.provider_combo = tk.OptionMenu(settings, self.provider_var, *provider_options,
                                            command=self._on_provider_changed)
        self.provider_combo.config(bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9),
                                   activebackground=BG_INPUT, activeforeground=FG_MAIN,
                                   highlightthickness=0, relief=tk.FLAT, width=12)
        self.provider_combo.grid(row=2, column=1, columnspan=3, sticky="we", pady=3, padx=(5, 0))

        # Gmail fields + alias info
        next_row = self._build_alias_widgets(settings, start_row=3)

        # Debug checkbox
        self.debug_var = tk.BooleanVar(value=False)
        tk.Checkbutton(settings, text="Debug", variable=self.debug_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9)).grid(row=next_row, column=0, sticky="w", pady=3)

        # ─ Browser engine selector ──
        browser_frame = tk.Frame(self._settings_frame.master, bg=BG_PANEL, padx=10, pady=5)
        browser_frame.pack(fill=tk.X, pady=2)

        tk.Label(browser_frame, text="Browser:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))

        self.browser_var = tk.StringVar(value="chrome")
        browser_options = [
            "chrome", "firefox", "webkit",
            "camoufox", "undetected-chromedriver", "rebrowser",
        ]
        self.browser_combo = tk.OptionMenu(browser_frame, self.browser_var, *browser_options)
        self.browser_combo.config(bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9),
                                  activebackground=BG_INPUT, activeforeground=FG_MAIN,
                                  highlightthickness=0, relief=tk.FLAT, width=18)
        self.browser_combo["menu"].config(bg=BG_INPUT, fg=FG_MAIN,
                                          activebackground=ACCENT, activeforeground="#1e1e2e")
        self.browser_combo.pack(side=tk.LEFT, padx=(0, 5))

        tk.Label(browser_frame, text="(anti-detect test)", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 7)).pack(side=tk.LEFT)

    def _on_provider_changed(self, event=None):
        """Update alias info when provider changes to Gmail."""
        if self.provider_var.get() == "gmail":
            self._update_alias_info()

    def _build_args(self):
        args = []
        provider = self.provider_var.get()
        if provider != "tempmail":
            args.extend(["--provider", provider])

        if provider == "gmail":
            gmail_user = self.gmail_user.get().strip()
            gmail_pass = self.gmail_pass.get().strip()
            if gmail_user and gmail_pass:
                args.extend(["--gmail", gmail_user, "--apppass", gmail_pass])
        elif provider == "outlook":
            outlook_email = self.gmail_user.get().strip()
            outlook_pass = self.gmail_pass.get().strip()
            if outlook_email and outlook_pass:
                args.extend(["--gmail", outlook_email, "--apppass", outlook_pass])

        if self.debug_var.get():
            args.append("--debug")

        # Browser engine
        args.extend(["--browser", self.browser_var.get()])
        return args

    def _post_init(self):
        """Set concurrency to min(recommended, 3) — matches farm_gui.py L1092 Auto button."""
        if hasattr(self, '_specs'):
            self.concurrency_var.set(min(self._specs["recommended"], 3))
        self._update_alias_info()

    def _on_stats_received(self):
        self._update_alias_info()

    def load_results(self):
        """Load existing results into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        from data_paths import get_path
        results_file = get_path(self.RESULTS_KEY, "results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                for row in data[-20:]:
                    self.tree.insert("", tk.END, values=tuple(
                        row.get(col, "") for col in self.RESULT_COLS
                    ))
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════
# Tab 5: MistralTab (horizontal layout + gmail alias)
# ════════════════════════════════════════════════════════════════

class MistralTab(BaseFarmTab, HorizontalLayoutMixin, GmailAliasMixin):
    """Mistral AI Farm — Gmail dot trick registration + API key.

    Uses horizontal layout (scrollable left + right log).
    Entry point: mistral_farm.py.
    """

    TAB_TITLE = "Mistral AI Farm"
    TAB_DESCRIPTION = "Mistral AI account registration with Gmail dot-trick aliases"
    FARM_SCRIPT = "mistral_farm.py"
    RESULTS_KEY = "mistral"
    RESULT_COLS = ("email", "api_key", "status")
    RESULT_COL_WIDTHS = {"email": 140, "api_key": 120, "status": 60}
    ALIAS_CSV_KEY = "mistral"

    def _build_ui(self):
        """Use horizontal layout instead of BaseFarmTab's vertical layout."""
        self._build_horizontal_ui()

    def _build_settings(self, settings):
        """Gmail fields + alias info bar."""
        next_row = self._build_alias_widgets(settings, start_row=2)
        return next_row

    def _build_args(self):
        args = []
        gmail_user = self.gmail_user.get().strip()
        gmail_pass = self.gmail_pass.get().strip()
        if gmail_user and gmail_pass:
            args.extend(["--gmail", gmail_user, "--apppass", gmail_pass])
        return args

    def _post_init(self):
        """Set concurrency to min(recommended, 3) — matches farm_gui.py L1574."""
        if hasattr(self, '_specs'):
            self.concurrency_var.set(min(self._specs["recommended"], 3))
        self._update_alias_info()

    def _on_stats_received(self):
        self._update_alias_info()

    def load_results(self):
        """Load existing results from CSV into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        from data_paths import get_path
        results_file = get_path(self.RESULTS_KEY, "accounts.csv")
        if os.path.exists(results_file):
            try:
                with open(results_file, newline="") as f:
                    rows = list(_csv.DictReader(f))
                for row in rows[-20:]:
                    apikey = row.get("api_key", "")
                    apikey_display = (apikey[:20] + "...") if len(apikey) > 20 else apikey
                    self.tree.insert("", tk.END, values=(
                        row.get("email", ""),
                        apikey_display,
                        row.get("status", ""),
                    ))
            except Exception:
                pass


# ════════════════════════════════════════════════════
# Tab 6: SiliconFlowTab (horizontal layout + GSuite accounts)
# ════════════════════════════════════════════════════

class SiliconFlowTab(BaseFarmTab, HorizontalLayoutMixin):
    """SiliconFlow Farm — Bulk GSuite account login + API key extraction.

    Uses horizontal layout with REALTIME DASHBOARD:
      - Summary bar: total / has_key / no_key / pending counts
      - Colored treeview: green=has key, red=failed, gray=pending
      - Filter toggle: all | has_key | no_key
      - Auto-refresh every 3s while farm running
    """

    TAB_TITLE = "SiliconFlow Farm"
    TAB_DESCRIPTION = "Bulk SiliconFlow API key farm via GSuite email+OTP login"
    FARM_SCRIPT = "siliconflow_farm.py"
    RESULTS_KEY = "siliconflow"
    RESULT_COLS = ("email", "api_key", "status")
    RESULT_COL_WIDTHS = {"email": 150, "api_key": 160, "status": 70}

    def _build_ui(self):
        """Use horizontal layout."""
        self._build_horizontal_ui()

    def _build_settings(self, settings):
        """GSuite accounts file path input + single account override.

        Compact horizontal layout — everything fits within 400px left panel:
          - All entries use tight widths
          - LabelFrame sections with minimal padding
          - Email/Pass on same line, compact
        """
        # ═══ Section 1: Account Source ═══
        sec1 = tk.LabelFrame(settings, text=" \U0001f4c1 ACCOUNTS ", bg=BG_PANEL,
                              fg=ACCENT, font=("Segoe UI", 8, "bold"),
                              labelanchor="w", padx=6, pady=3)
        sec1.grid(row=10, column=0, columnspan=5, sticky="we", pady=(5, 2))

        # File path row — compact
        f_row = tk.Frame(sec1, bg=BG_PANEL)
        f_row.pack(fill=tk.X, pady=(0, 1))

        tk.Label(f_row, text="File:", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)

        from data_paths import get_path as gp
        default_accounts = os.path.join(FARM_DIR, "data", "siliconflow",
                                        "sf_pending.txt")

        self.accounts_file_var = tk.StringVar(value=default_accounts)
        # width=18 ≈ 144px — leaves room for Browse button within 400px
        tk.Entry(f_row, textvariable=self.accounts_file_var, bg=BG_INPUT,
                 fg=FG_MAIN, width=18, insertbackground=FG_MAIN,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(3, 3), fill=tk.X, expand=True)

        # Bind: auto-detect count when file path changes (type or paste)
        self.accounts_file_var.trace_add("write", self._on_file_path_changed)

        tk.Button(f_row, text="Browse...", bg=ACCENT, fg="#1e1e2e",
                  font=("Segoe UI", 7), relief=tk.FLAT, padx=4, cursor="hand2",
                  command=self._browse_accounts).pack(side=tk.LEFT)

        # Account count label — compact
        self.account_count_var = tk.StringVar(value="\u23f3 Loading...")
        tk.Label(sec1, textvariable=self.account_count_var, bg=BG_PANEL,
                 fg=ACCENT_YELLOW, font=("Segoe UI", 7)).pack(anchor="w", pady=(1, 0))

        # ═══ Section 2: Single Account Mode — compact ═══
        single_frame = tk.LabelFrame(settings, text=" \u2705 SINGLE ",
                                     bg=BG_PANEL, fg=ACCENT,
                                     font=("Segoe UI", 8, "bold"),
                                     labelanchor="w", padx=6, pady=3)
        single_frame.grid(row=12, column=0, columnspan=5, sticky="we", pady=(2, 0))

        # Define vars FIRST (before using in widgets)
        self.use_single_var = tk.BooleanVar(value=False)
        self.single_email_var = tk.StringVar()
        self.single_pass_var = tk.StringVar()

        # Checkbox + fields on SAME row for compactness
        cb = tk.Checkbutton(single_frame, text="Single account:",
                       variable=self.use_single_var, bg=BG_PANEL, fg=FG_MAIN,
                       selectcolor=BG_INPUT, activebackground=BG_PANEL,
                       activeforeground=FG_MAIN, font=("Segoe UI", 8),
                       command=self._on_single_toggle)
        cb.pack(side=tk.LEFT)

        tk.Entry(single_frame, textvariable=self.single_email_var, bg=BG_INPUT,
                 fg=FG_MAIN, width=18, insertbackground=FG_MAIN,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 3))

        tk.Label(single_frame, text="Pass:", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        tk.Entry(single_frame, textvariable=self.single_pass_var, bg=BG_INPUT,
                 fg=FG_MAIN, width=12, insertbackground=FG_MAIN,
                 font=("Segoe UI", 8), show="\u2022").pack(side=tk.LEFT, padx=(2, 0))

        # ═══ Section 3: Proxy (Global Widget) ═══
        from gui.proxy import build_proxy_widget
        self.proxy_vars = build_proxy_widget(settings, row_offset=14)

    def _browse_accounts(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Select GSuite Accounts File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=FARM_DIR,
        )
        if path:
            self.accounts_file_var.set(path)
            self._auto_detect_count()

    def _on_single_toggle(self):
        pass

    def _build_args(self):
        """Build CLI args including proxy if enabled."""
        args = []
        if self.use_single_var.get():
            email = self.single_email_var.get().strip()
            pw = self.single_pass_var.get().strip()
            if email and pw:
                args.extend(["--email", email, "--pass", pw])
            else:
                args.extend(["--accounts-file", self.accounts_file_var.get().strip()])
        else:
            args.extend(["--accounts-file", self.accounts_file_var.get().strip()])

        # ── Append proxy args from global widget ──
        from gui.proxy import get_proxy_args
        proxy_args = get_proxy_args(self.proxy_vars)
        if proxy_args:
            args.extend(proxy_args)

        return args

    def _auto_detect_count(self):
        """Count non-empty lines in accounts file → auto-fill Count spinbox.

        Only overwrites Count if user hasn't manually changed it.
        User can still edit Count to any lower number.
        """
        path = self.accounts_file_var.get().strip()
        count_label = getattr(self, 'account_count_var', None)

        if not path or not os.path.isfile(path):
            if count_label:
                count_label.set("⚠ File not found")
            return

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [l.strip() for l in f if l.strip() and "|" in l]

            total = len(lines)

            # Update info label
            if count_label:
                count_label.set(f"📄 {total} accounts")

            # Auto-fill Count spinbox with total lines
            if total > 0:
                self.count_var.set(str(total))

        except Exception as e:
            if count_label:
                count_label.set("⚠ Error reading file")

    def _on_file_path_changed(self, *args):
        """Trace callback when accounts file path Entry is edited (debounce 500ms)."""
        if hasattr(self, '_count_debounce_id'):
            self.after_cancel(self._count_debounce_id)
        self._count_debounce_id = self.after(500, self._auto_detect_count)

    def _build_args(self):
        args = []
        if self.use_single_var.get():
            email = self.single_email_var.get().strip()
            pw = self.single_pass_var.get().strip()
            if email and pw:
                args.extend(["--email", email, "--pass", pw])
            else:
                args.extend(["--accounts-file", self.accounts_file_var.get().strip()])
        else:
            args.extend(["--accounts-file", self.accounts_file_var.get().strip()])

        # ── Append proxy args from global widget ──
        from gui.proxy import get_proxy_args
        proxy_args = get_proxy_args(self.proxy_vars)
        if proxy_args:
            args.extend(proxy_args)

        return args

    # ── Next method (varies by tab) ──

    def _post_init(self):
        if hasattr(self, '_specs'):
            self.concurrency_var.set(min(self._specs["recommended"], 3))
        self.count_var.set("5")
        # Filter state: 'all' | 'has_key' | 'no_key'
        self._filter_var = tk.StringVar(value="all")
        self._refresh_job_id = None  # auto-refresh timer handle

        # ── Inject SF Summary Dashboard above the treeview ──
        # Find the results frame (parent of self.tree) and add our dashboard
        if hasattr(self, 'tree') and self.tree.winfo_exists():
            tree_parent = self.tree.master  # res_frame from HorizontalLayoutMixin
            # Build summary bar + filter above tree
            dash = tk.Frame(tree_parent, bg=BG_PANEL)
            dash.pack(fill=tk.X, pady=(0, 5), before=self.tree)

            row1 = tk.Frame(dash, bg=BG_PANEL)
            row1.pack(fill=tk.X, pady=(2, 3))
            tk.Label(row1, text="📊 SF Dashboard:", bg=BG_PANEL, fg=ACCENT,
                     font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

            # Summary counters
            for lbl_text, attr_name, color in [
                ("TOTAL:", "sf_total_lbl", FG_MAIN),
                ("✅ KEY:", "sf_haskey_lbl", ACCENT_GREEN),
                ("❌ FAIL:", "sf_nokey_lbl", ACCENT_RED),
                ("", "sf_pct_lbl", ACCENT_YELLOW),
            ]:
                if lbl_text:
                    tk.Label(row1, text=lbl_text, bg=BG_PANEL, fg=FG_DIM,
                             font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(8, 2))
                l = tk.Label(row1, text="-", bg=BG_PANEL, fg=color,
                             font=("Segoe UI", 10, "bold"), width=(6 if attr_name == "sf_pct_lbl" else 4))
                l.pack(side=tk.LEFT)
                setattr(self, attr_name, l)

            # ── Farm Queue row (file vs dedup) ──
            rowq = tk.Frame(dash, bg=BG_PANEL)
            rowq.pack(fill=tk.X, pady=(3, 0))
            tk.Label(rowq, text="📋 Queue:", bg=BG_PANEL, fg=ACCENT,
                     font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)

            for lbl_text, attr_name, color in [
                ("📄 File:", "sf_file_lbl", FG_DIM),
                ("🔄 Farm:", "sf_queue_lbl", ACCENT_YELLOW),
                ("✅ Done:", "sf_dup_lbl", ACCENT_GREEN),
            ]:
                tk.Label(rowq, text=lbl_text, bg=BG_PANEL, fg=FG_DIM,
                         font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(8, 2))
                ql = tk.Label(rowq, text="-", bg=BG_PANEL, fg=color,
                              font=("Segoe UI", 9, "bold"), width=4)
                ql.pack(side=tk.LEFT)
                setattr(self, attr_name, ql)

            # Filter buttons row
            row2 = tk.Frame(dash, bg=BG_PANEL)
            row2.pack(fill=tk.X, pady=(2, 0))
            tk.Label(row2, text="Filter:", bg=BG_PANEL, fg=FG_DIM,
                     font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(0, 4))

            for fval, ftext in [("all", "All (∞)"), ("has_key", "Has Key"),
                                 ("no_key", "No Key / Failed")]:
                rb = tk.Radiobutton(
                    row2, text=ftext, variable=self._filter_var, value=fval,
                    bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                    activebackground=BG_PANEL, activeforeground=FG_MAIN,
                    font=("Segoe UI", 8),
                    command=lambda: self._refresh_summary())
                rb.pack(side=tk.LEFT, padx=(0, 8))

        # Load data immediately
        self.after(100, self._refresh_summary)
        # Auto-detect count from default accounts file
        self.after(200, self._auto_detect_count)

    def _on_stats_received(self):
        """Called by BaseFarmTab when [STATS] line received — refresh dashboard."""
        self._refresh_summary()

    def _load_results_data(self):
        """Load results.json + accounts file → return categorized lists.

        Returns:
            all_data: all records from results.json
            has_key: records with valid sk- key
            no_key: records without valid key (failed/pending)
            file_accounts: emails from the accounts .txt file (for dedup display)
        """
        from data_paths import get_path

        # ── Load results.json ──
        rf = get_path(self.RESULTS_KEY, "results.json")
        raw_data = []
        if os.path.exists(rf):
            try:
                with open(rf, encoding="utf-8") as f:
                    raw_data = json.load(f)
            except Exception:
                pass

        has_key = []
        no_key = []
        # Deduplicate results by email: keep latest result per email
        seen = {}
        for r in reversed(raw_data):
            email = r.get("email", "").strip()
            if email and email not in seen:
                seen[email] = r

        for r in seen.values():
            email = r.get("email", "").strip()
            key = r.get("api_key", "").strip()
            status = r.get("status", "").strip()
            if status == "complete" and key.startswith("sk-") and len(key) > 10:
                has_key.append(r)
            else:
                no_key.append(r)

        all_data = has_key + no_key  # deduped, no duplicates

        # ── Load accounts .txt file for farm queue preview ──
        file_accounts = []
        file_path = getattr(self, 'accounts_file_var', None)
        if file_path:
            fp = file_path.get().strip()
            if fp and os.path.isfile(fp):
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line = line.strip()
                            if line and "|" in line:
                                em = line.split("|")[0].strip()
                                if em:
                                    file_accounts.append(em)
                except Exception:
                    pass

        return all_data, has_key, no_key, file_accounts

    def _refresh_summary(self):
        """Reload results.json, update summary bar + treeview. Thread-safe via after()."""
        try:
            result = self._load_results_data()
            if len(result) == 3:
                # Fallback: old format (before update) — shouldn't happen but safe
                data, has_key, no_key = result
                file_accounts = []
            else:
                data, has_key, no_key, file_accounts = result

            total = len(data)
            n_key = len(has_key)
            n_nkey = len(no_key)

            # ── Farm queue analysis (file vs results) ──
            has_key_emails = {r.get("email", "").strip() for r in has_key}
            if file_accounts:
                n_file = len(file_accounts)
                n_already = sum(1 for em in file_accounts if em in has_key_emails)
                n_queue = n_file - n_already
            else:
                n_file = n_already = n_queue = 0

            # ── Update summary labels on dashboard ──
            if hasattr(self, 'sf_total_lbl'):
                self.sf_total_lbl.config(text=str(total))
                self.sf_haskey_lbl.config(text=str(n_key))
                self.sf_nokey_lbl.config(text=str(n_nkey))
                pct = f"{(n_key/total*100):.0f}%" if total else "0%"
                self.sf_pct_lbl.config(text=pct)

            # ── Update farm queue labels (if exist) ──
            if hasattr(self, 'sf_file_lbl'):
                self.sf_file_lbl.config(text=str(n_file))
            if hasattr(self, 'sf_queue_lbl'):
                self.sf_queue_lbl.config(text=str(n_queue))
                # Color: green if 0 (all done), yellow if some, red if error
                color = ACCENT_GREEN if n_queue == 0 else (ACCENT_YELLOW if n_queue > 0 else ACCENT_RED)
                self.sf_queue_lbl.config(fg=color)
            if hasattr(self, 'sf_dup_lbl'):
                self.sf_dup_lbl.config(text=str(n_already))

            # Update treeview based on current filter
            self._populate_tree(data, has_key, no_key)
        except Exception as e:
            pass

    def _populate_tree(self, all_data, has_key_list, no_key_list):
        """Fill treeview according to current filter, with color tags."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        filt = getattr(self, '_filter_var', None)
        filt_val = filt.get() if filt else "all"

        if filt_val == "has_key":
            rows = has_key_list
        elif filt_val == "no_key":
            rows = no_key_list
        else:
            rows = all_data

        # Configure tag colors (must use tree.tag_configure)
        self.tree.tag_configure("has_key", foreground=ACCENT_GREEN)
        self.tree.tag_configure("no_key", foreground=ACCENT_RED)
        self.tree.tag_configure("pending", foreground=FG_DIM)

        for r in rows:
            email = r.get("email", "")
            key = r.get("api_key", "")
            status = r.get("status", "")
            key_display = (key[:35] + "...") if len(key) > 35 else key

            # Determine tag
            if status == "complete" and key.startswith("sk-") and len(key) > 10:
                tag = ("has_key",)
            elif status in ("failed", "error") or "EXCEPTION" in str(status) or "NO_API_KEY" in str(status):
                tag = ("no_key",)
            else:
                tag = ("pending",)

            self.tree.insert("", tk.END, values=(email, key_display, status), tags=tag)

    # Override load_results to also refresh summary
    def load_results(self):
        """Called by BaseFarmTab at startup and after farm completes."""
        self._refresh_summary()

    # Override start/stop to manage auto-refresh timer
    def start_registration(self):
        super(SiliconFlowTab, self).start_registration()  # skip to BaseFarmTab
        self._start_auto_refresh()

    def stop_registration(self):
        super(SiliconFlowTab, self).stop_registration()
        self._stop_auto_refresh()

    def _run_registration(self):
        redirector = RedirectText(self.log_text)
        old_stdout = sys.stdout
        sys.stdout = redirector
        try:
            args = [sys.executable, os.path.join(FARM_DIR, self.FARM_SCRIPT)]
            args.extend(self._build_args())
            if self.SUPPORTS_COUNT_CONCURRENCY:
                args.extend(["--count", self.count_var.get()])
                args.extend(["--concurrency", str(self.concurrency_var.get())])
            if self.show_browser_var.get():
                args.append("--show")

            print(f"[GUI] {'━'*60}")
            print(f"[GUI] {self.TAB_TITLE} Starting")
            print(f"[GUI] Target accounts: {self.count_var.get()}")
            print(f"[GUI] Browser concurrency: {self.concurrency_var.get()}")
            print(f"[GUI] Browser mode: {'visible' if self.show_browser_var.get() else 'headless'}")
            print(f"[GUI] {'━'*60}\n")

            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, cwd=FARM_DIR)
            while True:
                if not self.running:
                    proc.terminate()
                    print("\n[GUI] Stopped by user.")
                    break
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    print(line, end="")
                    if "[STATS]" in line:
                        try:
                            stats = self._parse_stats_line(line)
                            if stats:
                                self.after(0, lambda v=stats: self._update_stats(**v))
                                self.after(0, lambda: self._on_stats_received())
                        except Exception:
                            pass
            proc.wait()
            print(f"\n[GUI] {'━'*60}")
            print("[GUI] Done.")
            print(f"[GUI] {'━'*60}")
            self.load_results()
        except Exception as e:
            print(f"\n[GUI] Error: {e}")
        finally:
            sys.stdout = old_stdout
            self.running = False
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self._stop_auto_refresh()
            # Final full refresh
            self._refresh_summary()

    def _start_auto_refresh(self):
        """Schedule periodic summary refresh while farm runs."""
        self._stop_auto_refresh()
        def tick():
            if self.running:
                self._refresh_summary()
                self._refresh_job_id = self.after(3000, tick)
        self._refresh_job_id = self.after(3000, tick)

    def _stop_auto_refresh(self):
        """Cancel the auto-refresh timer."""
        jid = getattr(self, '_refresh_job_id', None)
        if jid is not None:
            try:
                self.after_cancel(jid)
            except Exception:
                pass
            self._refresh_job_id = None


def load_done_emails_siliconflow():
    """Helper for tab to load done emails count."""
    track_file = os.path.join(FARM_DIR, "data", "siliconflow", "done_emails.txt")
    if os.path.exists(track_file):
        with open(track_file, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def load_done_emails_wavespeed():
    """Helper for tab to load done emails count."""
    track_file = os.path.join(FARM_DIR, "data", "wavespeed", "done_emails.txt")
    if os.path.exists(track_file):
        with open(track_file, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


# ════════════════════════════════════════════════════
# Tab 7: WaveSpeedTab (horizontal layout + GSuite accounts + CF Turnstile bypass)
# ════════════════════════════════════════════════════

class WaveSpeedTab(BaseFarmTab, HorizontalLayoutMixin):
    """WaveSpeed Farm — Bulk GSuite account login + API key extraction.

    Uses horizontal layout with REALTIME DASHBOARD:
      - Summary bar: total / has_key / no_key / pending counts
      - Colored treeview: green=has key, red=failed, gray=pending
      - Filter toggle: all | has_key | no_key
      - Auto-refresh every 3s while farm running
    """

    TAB_TITLE = "WaveSpeed Farm"
    TAB_DESCRIPTION = "Bulk WaveSpeed API key farm via GSuite email+OAuth login"
    FARM_SCRIPT = "wavespeed_farm.py"
    RESULTS_KEY = "wavespeed"
    RESULT_COLS = ("email", "api_key", "status")
    # Wider columns for better readability
    RESULT_COL_WIDTHS = {"email": 240, "api_key": 280, "status": 120}

    def _build_ui(self):
        """Use horizontal layout."""
        self._build_horizontal_ui()

    def _build_settings(self, settings):
        """GSuite accounts file path input + single account override.

        Layout:
          ┌─ 📁 ACCOUNTS SOURCE ─────────────────────┐
          │  Accounts File: [________] [Browse...]    │
          │  Accounts: 0                             │
          │                                          │
          │  ☐ Single account mode                  │
          │      Email: [________] Pass: [_____]     │
          ├─ ⚙ CONFIGURATION ──────────────────────┤
          │  (Count/Browsers — from HorizontalLayout)│
          ├─ 🖥 BROWSER MODE ───────────────────────┤
          │  Headless / Show Browser checkboxes      │
          └──────────────────────────────────────────┘
        """
        # ── Section: Account Source ──
        sec1 = tk.LabelFrame(settings, text="  \U0001f4c1  ACCOUNTS SOURCE  ", bg=BG_PANEL,
                              fg=ACCENT, font=("Segoe UI", 8, "bold"),
                              labelanchor="w", padx=8, pady=5)
        sec1.grid(row=10, column=0, columnspan=5, sticky="we", pady=(8, 3))

        # Accounts file
        f_row = tk.Frame(sec1, bg=BG_PANEL)
        f_row.pack(fill=tk.X, pady=(0, 2))

        tk.Label(f_row, text="File:", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)

        from data_paths import get_path as gp
        default_accounts = os.path.join(FARM_DIR, "data", "wavespeed",
                                        "available_for_wavespeed.txt")

        self.accounts_file_var = tk.StringVar(value=default_accounts)
        tk.Entry(f_row, textvariable=self.accounts_file_var, bg=BG_INPUT,
                 fg=FG_MAIN, width=30, insertbackground=FG_MAIN,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 4), fill=tk.X, expand=True)

        tk.Button(f_row, text="Browse...", bg=ACCENT, fg="#1e1e2e",
                  font=("Segoe UI", 7), relief=tk.FLAT, padx=6, cursor="hand2",
                  command=self._browse_accounts).pack(side=tk.LEFT)

        # Account count label
        self.account_count_var = tk.StringVar(value="\u23f3 Loading...")
        tk.Label(sec1, textvariable=self.account_count_var, bg=BG_PANEL,
                 fg=ACCENT_YELLOW, font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))

        # ═══ Section: Proxy (Global Widget) — replaces old WebShare-only code ═══
        from gui.proxy import build_proxy_widget
        self.proxy_vars = build_proxy_widget(settings, row_offset=20)

    def _browse_accounts(self):
        self.single_email_var = tk.StringVar()
        self.single_pass_var = tk.StringVar()

        single_frame = tk.Frame(settings, bg=BG_PANEL)
        single_frame.grid(row=12, column=0, columnspan=5, sticky="we")

        cb = tk.Checkbutton(single_frame, text="\u2705  Single Account Mode (overrides file)",
                           variable=self.use_single_var, bg=BG_PANEL, fg=FG_MAIN,
                           selectcolor=BG_INPUT, activebackground=BG_PANEL,
                           activeforeground=FG_MAIN, font=("Segoe UI", 9),
                           command=self._on_single_toggle)
        cb.pack(anchor="w", pady=(0, 4))

        # Email + Pass row (indented under checkbox)
        ep_frame = tk.Frame(single_frame, bg=BG_PANEL)
        ep_frame.pack(fill=tk.X, padx=(20, 0))

        tk.Label(ep_frame, text="Email:", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8), width=6, anchor="e").pack(side=tk.LEFT)
        tk.Entry(ep_frame, textvariable=self.single_email_var, bg=BG_INPUT,
                 fg=FG_MAIN, width=26, insertbackground=FG_MAIN,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(3, 6))

        tk.Label(ep_frame, text="Pass:", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8), width=5, anchor="e").pack(side=tk.LEFT)
        tk.Entry(ep_frame, textvariable=self.single_pass_var, bg=BG_INPUT,
                 fg=FG_MAIN, width=14, insertbackground=FG_MAIN,
                 font=("Segoe UI", 8), show="\u2022").pack(side=tk.LEFT, padx=(3, 0))

    def _browse_accounts(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Select GSuite Accounts File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=FARM_DIR,
        )
        if path:
            self.accounts_file_var.set(path)
            self._refresh_summary()

    def _on_single_toggle(self):
        pass

    # NOTE: _on_proxy_mode_toggle removed — now handled by gui/proxy.py global widget

    def _build_args(self):
        args = []
        if self.use_single_var.get():
            email = self.single_email_var.get().strip()
            pw = self.single_pass_var.get().strip()
            if email and pw:
                args.extend(["--email", email, "--pass", pw])
            else:
                args.extend(["--accounts-file", self.accounts_file_var.get().strip()])
        else:
            args.extend(["--accounts-file", self.accounts_file_var.get().strip()])

        # ── Append proxy args from global widget ──
        from gui.proxy import get_proxy_args
        proxy_args = get_proxy_args(self.proxy_vars)
        if proxy_args:
            args.extend(proxy_args)

        return args

    # ── Next method (varies by tab) ──

    def _post_init(self):
        if hasattr(self, '_specs'):
            self.concurrency_var.set(min(self._specs["recommended"], 3))
        self.count_var.set("5")
        # Filter state: 'all' | 'has_key' | 'no_key'
        self._filter_var = tk.StringVar(value="all")
        self._refresh_job_id = None

        # ── Inject WS Summary Dashboard above the treeview ──
        if hasattr(self, 'tree') and self.tree.winfo_exists():
            tree_parent = self.tree.master

            # ── Dashboard Container ──
            dash = tk.Frame(tree_parent, bg=BG_PANEL, relief=tk.FLAT)
            dash.pack(fill=tk.X, pady=(0, 6), before=self.tree)

            # ── Row 1: Title + Stats ──
            row1 = tk.Frame(dash, bg=BG_PANEL)
            row1.pack(fill=tk.X, pady=(6, 4), padx=8)

            tk.Label(row1, text="\U0001f30a  WAVE SPEED DASHBOARD",
                     bg=BG_PANEL, fg=ACCENT,
                     font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)

            # Separator
            tk.Frame(row1, bg=FG_DIM, width=2).pack(side=tk.LEFT, padx=(10, 10))

            # Stat boxes
            stat_items = [
                ("TOTAL:", "ws_total_lbl", FG_MAIN),
                ("\u2705 KEY:", "ws_haskey_lbl", ACCENT_GREEN),
                ("\u274c NO KEY:", "ws_nokey_lbl", ACCENT_RED),
            ]
            for lbl_text, attr_name, color in stat_items:
                box = tk.Frame(row1, bg=color, padx=8, pady=2)
                box.pack(side=tk.LEFT, padx=(0, 5))

                tk.Label(box, text=lbl_text, bg=color,
                         fg="#1e1e2e" if color != FG_MAIN else BG_PANEL,
                         font=("Segoe UI", 7, "bold")).pack(side=tk.LEFT)

                l = tk.Label(box, text="-", bg=color,
                             fg="#1e1e2e" if color != FG_MAIN else FG_MAIN,
                             font=("Segoe UI", 11, "bold"), width=3)
                l.pack(side=tk.LEFT, padx=(3, 0))
                setattr(self, attr_name, l)

            # Percentage badge
            pct_box = tk.Frame(row1, bg=ACCENT_YELLOW, padx=8, pady=2)
            pct_box.pack(side=tk.LEFT)
            l = tk.Label(pct_box, text="-%", bg=ACCENT_YELLOW, fg="#1e1e2e",
                         font=("Segoe UI", 11, "bold"), width=4)
            l.pack()
            setattr(self, 'ws_pct_lbl', l)

            # ── Row 2: Filter Bar ──
            row2 = tk.Frame(dash, bg="#2a2a3a")  # slightly darker sub-bar
            row2.pack(fill=tk.X, pady=(0, 6), padx=8)

            tk.Label(row2, text="\U0001f50d  Filter:",
                     bg=row2.cget("bg"), fg=FG_DIM,
                     font=("Segoe UI", 7, "bold")).pack(side=tk.LEFT, padx=(4, 8))

            for fval, ftext in [("all", "\U0001f3af All"), ("has_key", "\u2705 Has Key"),
                                 ("no_key", "\u274c No Key / Failed")]:
                rb = tk.Radiobutton(
                    row2, text=ftext, variable=self._filter_var, value=fval,
                    bg=row2.cget("bg"), fg=FG_MAIN, selectcolor=BG_INPUT,
                    activebackground=row2.cget("bg"),
                    activeforeground=FG_MAIN, font=("Segoe UI", 8, "bold"),
                    command=lambda: self._refresh_summary())
                rb.pack(side=tk.LEFT, padx=(0, 12))

        # Load data immediately
        self.after(100, self._refresh_summary)

    def _on_stats_received(self):
        self._refresh_summary()

    def _load_results_data(self):
        from data_paths import get_path
        rf = get_path(self.RESULTS_KEY, "results.json")
        if not os.path.exists(rf):
            return [], [], []
        try:
            with open(rf, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return [], [], []

        has_key = []
        no_key = []
        for r in data:
            key = r.get("api_key", "").strip()
            status = r.get("status", "").strip()
            if status == "complete" and key.startswith("sk-") and len(key) > 10:
                has_key.append(r)
            else:
                no_key.append(r)
        return data, has_key, no_key

    def _refresh_summary(self):
        try:
            data, has_key, no_key = self._load_results_data()
            total = len(data)
            n_key = len(has_key)
            n_nkey = len(no_key)

            if hasattr(self, 'ws_total_lbl'):
                self.ws_total_lbl.config(text=str(total))
                self.ws_haskey_lbl.config(text=str(n_key))
                self.ws_nokey_lbl.config(text=str(n_nkey))
                pct = f"{(n_key/total*100):.0f}%" if total else "0%"
                self.ws_pct_lbl.config(text=pct)

            self._populate_tree(data, has_key, no_key)
        except Exception:
            pass

    def _populate_tree(self, all_data, has_key_list, no_key_list):
        for item in self.tree.get_children():
            self.tree.delete(item)

        filt = getattr(self, '_filter_var', None)
        filt_val = filt.get() if filt else "all"

        if filt_val == "has_key":
            rows = has_key_list
        elif filt_val == "no_key":
            rows = no_key_list
        else:
            rows = all_data

        self.tree.tag_configure("has_key", foreground=ACCENT_GREEN)
        self.tree.tag_configure("no_key", foreground=ACCENT_RED)
        self.tree.tag_configure("pending", foreground=FG_DIM)

        for r in rows:
            email = r.get("email", "")
            key = r.get("api_key", "")
            status = r.get("status", "")
            key_display = (key[:35] + "...") if len(key) > 35 else key

            if status == "complete" and key.startswith("sk-") and len(key) > 10:
                tag = ("has_key",)
            elif status in ("failed", "error") or "EXCEPTION" in str(status) or "NO_API_KEY" in str(status):
                tag = ("no_key",)
            else:
                tag = ("pending",)

            self.tree.insert("", tk.END, values=(email, key_display, status), tags=tag)

    def load_results(self):
        self._refresh_summary()

    def start_registration(self):
        super(WaveSpeedTab, self).start_registration()
        self._start_auto_refresh()

    def stop_registration(self):
        super(WaveSpeedTab, self).stop_registration()
        self._stop_auto_refresh()

    def _run_registration(self):
        redirector = RedirectText(self.log_text)
        old_stdout = sys.stdout
        sys.stdout = redirector
        try:
            args = [sys.executable, os.path.join(FARM_DIR, self.FARM_SCRIPT)]
            args.extend(self._build_args())
            if self.SUPPORTS_COUNT_CONCURRENCY:
                args.extend(["--count", self.count_var.get()])
                args.extend(["--concurrency", str(self.concurrency_var.get())])
            if self.show_browser_var.get():
                args.append("--show")

            print(f"[GUI] {'━'*60}")
            print(f"[GUI] {self.TAB_TITLE} Starting")
            print(f"[GUI] Target accounts: {self.count_var.get()}")
            print(f"[GUI] Browser concurrency: {self.concurrency_var.get()}")
            print(f"[GUI] Browser mode: {'visible' if self.show_browser_var.get() else 'headless'}")
            print(f"[GUI] {'━'*60}\n")

            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, cwd=FARM_DIR)
            while True:
                if not self.running:
                    proc.terminate()
                    print("\n[GUI] Stopped by user.")
                    break
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    print(line, end="")
                    if "[STATS]" in line:
                        try:
                            stats = self._parse_stats_line(line)
                            if stats:
                                self.after(0, lambda v=stats: self._update_stats(**v))
                                self.after(0, lambda: self._on_stats_received())
                        except Exception:
                            pass
            proc.wait()
            print(f"\n[GUI] {'━'*60}")
            print("[GUI] Done.")
            print(f"[GUI] {'━'*60}")
            self.load_results()
        except Exception as e:
            print(f"\n[GUI] Error: {e}")
        finally:
            sys.stdout = old_stdout
            self.running = False
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self._stop_auto_refresh()
            self._refresh_summary()

    def _start_auto_refresh(self):
        self._stop_auto_refresh()
        def tick():
            if self.running:
                self._refresh_summary()
                self._refresh_job_id = self.after(3000, tick)
        self._refresh_job_id = self.after(3000, tick)

    def _stop_auto_refresh(self):
        jid = getattr(self, '_refresh_job_id', None)
        if jid is not None:
            try:
                self.after_cancel(jid)
            except Exception:
                pass
            self._refresh_job_id = None
