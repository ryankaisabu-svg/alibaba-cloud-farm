#!/usr/bin/env python3
"""
Alibaba Cloud Farm — Desktop GUI
=================================
Tkinter GUI dengan tab system:
  Tab 1: Xiaomi MiMo Farm (registrasi + API key)
  Tab 2: Email Farm (bulk email creation)
  Tab 3: Alibaba Cloud Farm (registrasi Alibaba)

Usage:
  python farm_gui.py
"""

import sys
import os
import threading
import time
import json

# Load .env if python-dotenv available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

# ─ Config ──────────────────────────────────────────
FARM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, FARM_DIR)


# ─ Colors ──────────────────────────────────────────
BG_DARK = "#1e1e2e"
BG_PANEL = "#2a2a3c"
BG_INPUT = "#363649"
FG_MAIN = "#cdd6f4"
FG_DIM = "#7f7f9f"
ACCENT = "#89b4fa"
ACCENT_GREEN = "#a6e3a1"
ACCENT_RED = "#f38ba8"
ACCENT_YELLOW = "#f9e2af"


class RedirectText:
    """Redirect stdout to tkinter Text widget."""
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, string):
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        self.text_widget.config(state=tk.DISABLED)

    def flush(self):
        pass


class XiaomiTab(ttk.Frame):
    """Tab 1: Xiaomi MiMo Farm."""

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        # ─ Header ─
        hdr = tk.Label(self, text="Xiaomi MiMo Farm", font=("Segoe UI", 16, "bold"),
                       bg=BG_DARK, fg=FG_MAIN)
        hdr.pack(pady=(10, 5))

        # ─ Settings frame ─
        settings = tk.Frame(self, bg=BG_PANEL, padx=15, pady=15)
        settings.pack(fill=tk.X, padx=20, pady=5)

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
                           font=("Segoe UI", 9)).grid(row=0, column=i+1, sticky="w", padx=5)

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
                       font=("Segoe UI", 9)).grid(row=2, column=0, columnspan=2, sticky="w", pady=5)
        tk.Checkbutton(settings, text="Debug Screenshots", variable=self.debug_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9)).grid(row=2, column=2, columnspan=2, sticky="w", pady=5)
        tk.Checkbutton(settings, text="Auto CAPTCHA (CapSolver)", variable=self.auto_captcha_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9)).grid(row=2, column=4, columnspan=2, sticky="w", pady=5)

        # ─ Buttons ─
        btn_frame = tk.Frame(self, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, padx=20, pady=10)

        self.start_btn = tk.Button(btn_frame, text="▶ START REGISTRATION",
                                   bg=ACCENT_GREEN, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                   relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
                                   command=self.start_registration)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = tk.Button(btn_frame, text="■ STOP",
                                  bg=ACCENT_RED, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                  relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
                                  state=tk.DISABLED, command=self.stop_registration)
        self.stop_btn.pack(side=tk.LEFT)

        # ─ Log output ─
        log_frame = tk.Frame(self, bg=BG_DARK)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(5, 10))

        tk.Label(log_frame, text="Output Log:", bg=BG_DARK, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(anchor="w")

        self.log_text = scrolledtext.ScrolledText(log_frame, bg=BG_INPUT, fg=ACCENT,
                                                   font=("Consolas", 9), height=12,
                                                   insertbackground=FG_MAIN, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ─ Results ─
        res_frame = tk.Frame(self, bg=BG_PANEL, padx=15, pady=10)
        res_frame.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Label(res_frame, text="Accounts Created:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")

        cols = ("email", "password", "api_key", "status", "timestamp")
        self.tree = ttk.Treeview(res_frame, columns=cols, show="headings", height=5)
        for col in cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=150 if col != "api_key" else 250)
        self.tree.pack(fill=tk.X, pady=5)

        self.load_results()

        self.running = False

    def load_results(self):
        """Load existing results into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        results_file = os.path.join(FARM_DIR, "xiaomi_results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                for row in data[-20:]:  # last 20
                    self.tree.insert("", tk.END, values=(
                        row.get("email", ""),
                        row.get("password", ""),
                        row.get("api_key", ""),
                        row.get("status", ""),
                        row.get("timestamp", ""),
                    ))
            except:
                pass

    def start_registration(self):
        if self.running:
            return
        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        threading.Thread(target=self._run_registration, daemon=True).start()

    def stop_registration(self):
        self.running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def _run_registration(self):
        redirector = RedirectText(self.log_text)
        old_stdout = sys.stdout
        sys.stdout = redirector
        try:
            # Build args
            args = [sys.executable, os.path.join(FARM_DIR, "xiaomi_farm.py")]
            args.append("--provider")
            args.append(self.provider_var.get())
            if self.show_var.get():
                args.append("--show")
            if self.debug_var.get():
                args.append("--debug")
            if self.auto_captcha_var.get():
                args.append("--auto-captcha")

            print(f"[GUI] Running: {' '.join(args)}\n")
            import subprocess
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, cwd=FARM_DIR)
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
            proc.wait()
            print("\n[GUI] Done.")
            self.load_results()
        except Exception as e:
            print(f"\n[GUI] Error: {e}")
        finally:
            sys.stdout = old_stdout
            self.running = False
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)


class EmailFarmTab(ttk.Frame):
    """Tab 2: Email Farm — bulk email creation."""

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Label(self, text="Email Farm — Bulk Email Creation", font=("Segoe UI", 16, "bold"),
                       bg=BG_DARK, fg=FG_MAIN)
        hdr.pack(pady=(10, 5))

        # ─ Settings ─
        settings = tk.Frame(self, bg=BG_PANEL, padx=15, pady=15)
        settings.pack(fill=tk.X, padx=20, pady=5)

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
                           font=("Segoe UI", 9)).grid(row=i+1, column=0, columnspan=4, sticky="w", padx=10)

        # Count
        tk.Label(settings, text="Jumlah Akun:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=6, column=0, sticky="w", pady=5)
        self.count_var = tk.StringVar(value="10")
        tk.Entry(settings, textvariable=self.count_var, bg=BG_INPUT, fg=FG_MAIN, width=10,
                 insertbackground=FG_MAIN, font=("Segoe UI", 10)).grid(row=6, column=1, sticky="w", pady=5)

        # Password
        tk.Label(settings, text="Password (sama untuk semua):", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=7, column=0, sticky="w", pady=5)
        self.password_var = tk.StringVar()
        tk.Entry(settings, textvariable=self.password_var, bg=BG_INPUT, fg=FG_MAIN, width=25,
                 insertbackground=FG_MAIN, font=("Segoe UI", 10)).grid(row=7, column=1, sticky="w", pady=5)
        tk.Label(settings, text="(kosongkan = auto-generate)", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8)).grid(row=7, column=2, sticky="w", pady=5)

        # ─ Buttons ─
        btn_frame = tk.Frame(self, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, padx=20, pady=10)

        self.start_btn = tk.Button(btn_frame, text="▶ CREATE EMAILS",
                                   bg=ACCENT_GREEN, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                   relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
                                   command=self.start_creation)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.open_csv_btn = tk.Button(btn_frame, text="📂 Open CSV",
                                      bg=ACCENT_YELLOW, fg="#1e1e2e", font=("Segoe UI", 10, "bold"),
                                      relief=tk.FLAT, padx=15, pady=8, cursor="hand2",
                                      command=self.open_csv)
        self.open_csv_btn.pack(side=tk.LEFT)

        # ─ Log ─
        log_frame = tk.Frame(self, bg=BG_DARK)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(5, 10))

        tk.Label(log_frame, text="Output Log:", bg=BG_DARK, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(anchor="w")

        self.log_text = scrolledtext.ScrolledText(log_frame, bg=BG_INPUT, fg=ACCENT,
                                                   font=("Consolas", 9), height=8,
                                                   insertbackground=FG_MAIN, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ─ Results table ─
        res_frame = tk.Frame(self, bg=BG_PANEL, padx=15, pady=10)
        res_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))

        tk.Label(res_frame, text="Emails Created:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")

        cols = ("email", "password", "provider", "timestamp")
        self.tree = ttk.Treeview(res_frame, columns=cols, show="headings", height=6)
        for col in cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=200)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=5)

        # Right-click context menu for copy
        self.ctx_menu = tk.Menu(self.tree, tearoff=0, bg=BG_INPUT, fg=FG_MAIN,
                                activebackground=ACCENT, activeforeground="#1e1e2e",
                                font=("Segoe UI", 9))
        self.ctx_menu.add_command(label="📋 Copy Selected Row", command=self._copy_selected)
        self.ctx_menu.add_command(label="📋 Copy All Rows", command=self._copy_all)
        self.ctx_menu.add_command(label="📋 Copy Email Only", command=self._copy_emails)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="🗑 Delete Selected Row", command=self._delete_selected)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Control-c>", lambda e: self._copy_selected())

        # Copy buttons
        copy_frame = tk.Frame(res_frame, bg=BG_PANEL)
        copy_frame.pack(fill=tk.X, pady=(5, 0))

        tk.Button(copy_frame, text="📋 Copy Selected",
                  bg=ACCENT, fg="#1e1e2e", font=("Segoe UI", 9, "bold"),
                  relief=tk.FLAT, padx=12, pady=5, cursor="hand2",
                  command=self._copy_selected).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(copy_frame, text="📋 Copy All",
                  bg=ACCENT_GREEN, fg="#1e1e2e", font=("Segoe UI", 9, "bold"),
                  relief=tk.FLAT, padx=12, pady=5, cursor="hand2",
                  command=self._copy_all).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(copy_frame, text="📋 Copy Emails Only",
                  bg=ACCENT_YELLOW, fg="#1e1e2e", font=("Segoe UI", 9, "bold"),
                  relief=tk.FLAT, padx=12, pady=5, cursor="hand2",
                  command=self._copy_emails).pack(side=tk.LEFT)

        self.load_results()

    def load_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        results_file = os.path.join(FARM_DIR, "email_farm_results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                for row in data[-30:]:
                    self.tree.insert("", tk.END, values=(
                        row.get("email", ""),
                        row.get("password", ""),
                        row.get("provider", ""),
                        row.get("timestamp", ""),
                    ))
            except:
                pass

    def _on_right_click(self, event):
        """Show context menu on right-click."""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
        self.ctx_menu.tk_popup(event.x_root, event.y_root)

    def _copy_selected(self):
        """Copy selected row(s) to clipboard as TSV."""
        items = self.tree.selection()
        if not items:
            messagebox.showinfo("Info", "Pilih baris dulu (klik di tabel).")
            return
        lines = []
        # Header
        cols = ["email", "password", "provider", "timestamp"]
        lines.append("\t".join(c.upper() for c in cols))
        for item in items:
            vals = self.tree.item(item, "values")
            lines.append("\t".join(str(v) for v in vals))
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", f"{len(items)} baris di-copy ke clipboard!\n\nPaste ke Excel: Ctrl+V")

    def _copy_all(self):
        """Copy all rows to clipboard as TSV."""
        items = self.tree.get_children()
        if not items:
            messagebox.showinfo("Info", "Tabel kosong, belum ada data.")
            return
        lines = []
        cols = ["email", "password", "provider", "timestamp"]
        lines.append("\t".join(c.upper() for c in cols))
        for item in items:
            vals = self.tree.item(item, "values")
            lines.append("\t".join(str(v) for v in vals))
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", f"{len(items)} baris di-copy ke clipboard!\n\nPaste ke Excel: Ctrl+V")

    def _copy_emails(self):
        """Copy email column only (one per line)."""
        items = self.tree.get_children()
        if not items:
            messagebox.showinfo("Info", "Tabel kosong, belum ada data.")
            return
        emails = []
        for item in items:
            vals = self.tree.item(item, "values")
            if vals and vals[0]:
                emails.append(vals[0])
        text = "\n".join(emails)
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", f"{len(emails)} email di-copy ke clipboard!")

    def _delete_selected(self):
        """Delete selected row from treeview + JSON file."""
        items = self.tree.selection()
        if not items:
            return
        if not messagebox.askyesno("Confirm", f"Hapus {len(items)} baris dari tabel?"):
            return
        # Get emails to delete
        emails_to_delete = set()
        for item in items:
            vals = self.tree.item(item, "values")
            if vals:
                emails_to_delete.add(vals[0])
            self.tree.delete(item)
        # Update JSON file
        results_file = os.path.join(FARM_DIR, "email_farm_results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                data = [r for r in data if r.get("email") not in emails_to_delete]
                with open(results_file, "w") as f:
                    json.dump(data, f, indent=2)
            except:
                pass

    def open_csv(self):
        csv_path = os.path.join(FARM_DIR, "email_farm_accounts.csv")
        if os.path.exists(csv_path):
            os.startfile(csv_path)
        else:
            messagebox.showinfo("Info", "CSV file belum ada. Buat email dulu.")

    def start_creation(self):
        threading.Thread(target=self._run_creation, daemon=True).start()

    def _run_creation(self):
        self.start_btn.config(state=tk.DISABLED)
        redirector = RedirectText(self.log_text)
        old_stdout = sys.stdout
        sys.stdout = redirector
        try:
            from email_farm import run_bulk
            provider = self.provider_var.get()
            count = int(self.count_var.get() or "10")
            password = self.password_var.get().strip() or None

            accounts = run_bulk(provider, count, password)
            self.load_results()
        except Exception as e:
            print(f"\n[GUI] Error: {e}")
        finally:
            sys.stdout = old_stdout
            self.start_btn.config(state=tk.NORMAL)


class QwenCloudTab(ttk.Frame):
    """Tab 4: Qwen Cloud Farm — Gmail dot trick registration + API key."""

    def __init__(self, parent):
        super().__init__(parent)
        self.running = False
        self._build_ui()

    def _detect_specs(self):
        """Detect PC specs and recommend max browsers."""
        try:
            import psutil
            ram_total = psutil.virtual_memory().total // (1024**3)
            cpu_cores = psutil.cpu_count(logical=True)
            cpu_physical = psutil.cpu_count(logical=False)
        except ImportError:
            ram_total, cpu_cores, cpu_physical = 0, 0, 0

        # Each Chromium browser ~300-500MB RAM. Reserve 2GB for OS.
        # Concurrency limited by RAM (not CPU — mostly I/O wait on OTP)
        if ram_total > 0:
            usable_ram = max(1, ram_total - 2)
            ram_based = max(1, usable_ram // 1)  # 1GB per browser (generous)
        else:
            ram_based = 3

        # Also cap at physical cores * 2 (don't over-subscribe)
        if cpu_physical > 0:
            cpu_based = max(1, cpu_physical * 2)
        else:
            cpu_based = 4

        recommended = min(ram_based, cpu_based, 8)  # hard cap at 8

        return {
            "ram_gb": ram_total,
            "cpu_cores": cpu_cores,
            "cpu_physical": cpu_physical,
            "recommended": recommended,
        }

    def _build_ui(self):
        # ─ Header ─
        hdr = tk.Label(self, text="Qwen Cloud Farm", font=("Segoe UI", 16, "bold"),
                       bg=BG_DARK, fg=FG_MAIN)
        hdr.pack(pady=(10, 5))

        info = tk.Label(self, text="Register Qwen Cloud (qwencloud.com) accounts via Gmail dot trick\n"
                                   "Email → OTP (Gmail IMAP) → Validate → API Key extraction",
                        bg=BG_DARK, fg=FG_DIM, font=("Segoe UI", 9), justify=tk.CENTER)
        info.pack(pady=(0, 5))

        # ─ PC Specs + Browser settings ─
        specs = self._detect_specs()

        specs_frame = tk.Frame(self, bg=BG_PANEL, padx=15, pady=10)
        specs_frame.pack(fill=tk.X, padx=20, pady=5)

        # Specs display
        specs_text = (f"PC Specs: RAM {specs['ram_gb']}GB | "
                      f"CPU {specs['cpu_physical']}c/{specs['cpu_cores']}t | "
                      f"Rekomendasi: {specs['recommended']} browser")
        tk.Label(specs_frame, text=specs_text, bg=BG_PANEL, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 5))

        # ─ Settings frame ─
        settings = tk.Frame(self, bg=BG_PANEL, padx=15, pady=15)
        settings.pack(fill=tk.X, padx=20, pady=5)

        # Gmail user (masked)
        tk.Label(settings, text="Gmail User:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", pady=5)
        self.gmail_user = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=30,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 10), show="*")
        self.gmail_user.insert(0, os.environ.get("QWEN_GMAIL_USER", ""))
        self.gmail_user.grid(row=0, column=1, columnspan=2, sticky="w", pady=5)
        self.gmail_user.bind("<KeyRelease>", self._on_gmail_changed)

        # App password (masked)
        tk.Label(settings, text="App Password:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=0, column=3, sticky="w", pady=5)
        self.gmail_pass = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=25,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 10), show="*")
        self.gmail_pass.insert(0, os.environ.get("QWEN_GMAIL_APP_PASS", ""))
        self.gmail_pass.grid(row=0, column=4, columnspan=2, sticky="w", pady=5)

        # ─ Gmail alias info bar ─
        alias_info_frame = tk.Frame(settings, bg=BG_PANEL)
        alias_info_frame.grid(row=1, column=0, columnspan=6, sticky="w", pady=(2, 5))

        self.max_aliases_var = tk.StringVar(value="Max Aliases: -")
        tk.Label(alias_info_frame, textvariable=self.max_aliases_var, bg=BG_PANEL, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 15))

        self.used_aliases_var = tk.StringVar(value="Used: -")
        tk.Label(alias_info_frame, textvariable=self.used_aliases_var, bg=BG_PANEL, fg=ACCENT_RED,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 15))

        self.remaining_aliases_var = tk.StringVar(value="Remaining: -")
        tk.Label(alias_info_frame, textvariable=self.remaining_aliases_var, bg=BG_PANEL, fg=ACCENT_GREEN,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

        # Account Count
        tk.Label(settings, text="Account Count:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w", pady=5)
        self.count_var = tk.StringVar(value="5")
        self.count_spinbox = tk.Spinbox(settings, from_=1, to=512, textvariable=self.count_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 10))
        self.count_spinbox.grid(row=2, column=1, sticky="w", pady=5)

        # Browser Concurrency
        tk.Label(settings, text="Browser Concurrency:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=2, column=2, sticky="w", pady=5, padx=(20, 0))
        self.concurrency_var = tk.IntVar(value=specs["recommended"])
        tk.Spinbox(settings, from_=1, to=8, textvariable=self.concurrency_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 10)).grid(row=2, column=3, sticky="w", pady=5)

        # Recommended button (quick set)
        tk.Button(settings, text=f"\u2699 Auto ({specs['recommended']})",
                  bg=ACCENT, fg="#1e1e2e", font=("Segoe UI", 8, "bold"),
                  relief=tk.FLAT, padx=8, pady=2, cursor="hand2",
                  command=lambda: self.concurrency_var.set(specs["recommended"])
                  ).grid(row=2, column=4, sticky="w", pady=5)

        # Helper text: explain relationship
        tk.Label(settings, text="(Account Count = total akun target | Concurrency = browser yang jalan bersamaan)",
                 bg=BG_PANEL, fg=FG_DIM, font=("Segoe UI", 8)).grid(row=3, column=0, columnspan=6, sticky="w", pady=(2, 0))

        # ─ Browser mode checkboxes ─
        mode_frame = tk.Frame(self, bg=BG_PANEL, padx=15, pady=8)
        mode_frame.pack(fill=tk.X, padx=20, pady=2)

        tk.Label(mode_frame, text="Browser Mode:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")

        self.headless_var = tk.BooleanVar(value=True)
        self.show_browser_var = tk.BooleanVar(value=False)

        tk.Checkbutton(mode_frame, text="Headless (background, recommended)",
                       variable=self.headless_var, bg=BG_PANEL, fg=FG_MAIN,
                       selectcolor=BG_INPUT, activebackground=BG_PANEL,
                       activeforeground=FG_MAIN, font=("Segoe UI", 9),
                       command=self._on_headless_toggle).pack(anchor="w", padx=10)

        tk.Checkbutton(mode_frame, text="Show Browser (visible window)",
                       variable=self.show_browser_var, bg=BG_PANEL, fg=FG_MAIN,
                       selectcolor=BG_INPUT, activebackground=BG_PANEL,
                       activeforeground=FG_MAIN, font=("Segoe UI", 9),
                       command=self._on_show_toggle).pack(anchor="w", padx=10)

        # ─ Buttons ─
        btn_frame = tk.Frame(self, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, padx=20, pady=10)

        self.start_btn = tk.Button(btn_frame, text="▶ START QWEN FARM",
                                   bg=ACCENT_GREEN, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                   relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
                                   command=self.start_registration)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = tk.Button(btn_frame, text="■ STOP",
                                  bg=ACCENT_RED, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                  relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
                                  state=tk.DISABLED, command=self.stop_registration)
        self.stop_btn.pack(side=tk.LEFT)

        # ─ Log output ─
        log_frame = tk.Frame(self, bg=BG_DARK)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(5, 10))

        tk.Label(log_frame, text="Output Log:", bg=BG_DARK, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(anchor="w")

        self.log_text = scrolledtext.ScrolledText(log_frame, bg=BG_INPUT, fg=ACCENT,
                                                   font=("Consolas", 9), height=12,
                                                   insertbackground=FG_MAIN, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ─ Results ─
        res_frame = tk.Frame(self, bg=BG_PANEL, padx=15, pady=10)
        res_frame.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Label(res_frame, text="Qwen Cloud Accounts:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")

        cols = ("email", "api_key", "status", "timestamp")
        self.tree = ttk.Treeview(res_frame, columns=cols, show="headings", height=5)
        for col in cols:
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=200 if col == "api_key" else 150)
        self.tree.pack(fill=tk.X, pady=5)

        self.load_results()

        # ─ Realtime Stats Bar ─
        stats_frame = tk.Frame(self, bg=BG_PANEL, padx=15, pady=10)
        stats_frame.pack(fill=tk.X, padx=20, pady=(5, 10))

        tk.Label(stats_frame, text="📊 Realtime Stats:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")

        stats = [
            ("Queued", "stats_queued", ACCENT),
            ("Processing", "stats_processing", ACCENT_YELLOW),
            ("Created", "stats_created", ACCENT_GREEN),
            ("Done", "stats_done", FG_MAIN),
            ("Failed", "stats_failed", ACCENT_RED),
            ("API Key", "stats_apikey", ACCENT_GREEN),
        ]
        for i, (label, attr, color) in enumerate(stats):
            col = i + 1
            tk.Label(stats_frame, text=label, bg=BG_PANEL, fg=FG_DIM,
                     font=("Segoe UI", 8)).grid(row=0, column=col*2, padx=(10, 0), pady=2)
            lbl = tk.Label(stats_frame, text="0", bg=BG_PANEL, fg=color,
                          font=("Segoe UI", 14, "bold"), width=4)
            lbl.grid(row=0, column=col*2+1, padx=(2, 5), pady=2)
            setattr(self, attr, lbl)

        # Initialize alias info on load
        self._update_alias_info()

    def _on_headless_toggle(self):
        """When headless checked, uncheck show."""
        if self.headless_var.get():
            self.show_browser_var.set(False)

    def _on_show_toggle(self):
        """When show checked, uncheck headless."""
        if self.show_browser_var.get():
            self.headless_var.set(False)

    def _on_gmail_changed(self, event=None):
        """Recalculate alias info when Gmail address changes."""
        self._update_alias_info()

    def _update_alias_info(self):
        """Calculate and display max Gmail dot-trick aliases, used, remaining."""
        gmail = self.gmail_user.get().strip().lower()
        if not gmail or "@" not in gmail:
            self.max_aliases_var.set("Max Aliases: -")
            self.used_aliases_var.set("Used: -")
            self.remaining_aliases_var.set("Remaining: -")
            return

        username = gmail.split("@")[0]
        # Remove existing dots for calculation
        clean = username.replace(".", "")
        if len(clean) < 2:
            max_aliases = 1
        else:
            positions = len(clean) - 1
            max_aliases = 2 ** positions

        # Load used aliases from JSON
        used_count = 0
        aliases_file = os.path.join(FARM_DIR, "used_aliases.json")
        if os.path.exists(aliases_file):
            try:
                import json
                with open(aliases_file, "r") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    used_count = len(data)
                elif isinstance(data, dict):
                    used_count = len(data.get("used_aliases", data))
            except Exception:
                pass

        remaining = max(0, max_aliases - used_count)

        self.max_aliases_var.set(f"Max Aliases: {max_aliases}")
        self.used_aliases_var.set(f"Used: {used_count}")
        self.remaining_aliases_var.set(f"Remaining: {remaining}")

        # Update Account Count spinbox max to remaining
        self.count_spinbox.config(to=max(1, remaining))

    def _update_stats(self, queued=0, processing=0, created=0, done=0, failed=0, apikey=0):
        """Update realtime stats display."""
        self.stats_queued.config(text=str(queued))
        self.stats_processing.config(text=str(processing))
        self.stats_created.config(text=str(created))
        self.stats_done.config(text=str(done))
        self.stats_failed.config(text=str(failed))
        self.stats_apikey.config(text=str(apikey))

    def load_results(self):
        """Load existing results into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        results_file = os.path.join(FARM_DIR, "qwen_results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                for row in data[-20:]:
                    self.tree.insert("", tk.END, values=(
                        row.get("email", ""),
                        row.get("api_key", ""),
                        row.get("status", ""),
                        row.get("timestamp", ""),
                    ))
            except:
                pass

    def start_registration(self):
        if self.running:
            return
        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        threading.Thread(target=self._run_registration, daemon=True).start()

    def stop_registration(self):
        self.running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def _run_registration(self):
        redirector = RedirectText(self.log_text)
        old_stdout = sys.stdout
        sys.stdout = redirector
        try:
            args = [sys.executable, os.path.join(FARM_DIR, "alibaba_farm.py")]
            args.append("--gmail")
            args.append(self.gmail_user.get())
            args.append("--apppass")
            args.append(self.gmail_pass.get())
            args.append("--count")
            args.append(self.count_var.get())
            args.append("--concurrency")
            args.append(str(self.concurrency_var.get()))

            # Browser mode
            if self.show_browser_var.get():
                args.append("--show")

            # Log config
            print(f"[GUI] ═══════════════════════════════════════════")
            print(f"[GUI] Qwen Cloud Farm Starting")
            print(f"[GUI] Gmail: {self.gmail_user.get()}")
            print(f"[GUI] Target accounts: {self.count_var.get()}")
            print(f"[GUI] Browser concurrency: {self.concurrency_var.get()}")
            print(f"[GUI] Browser mode: {'visible' if self.show_browser_var.get() else 'headless'}")
            print(f"[GUI] ═══════════════════════════════════════════\n")

            import subprocess
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, cwd=FARM_DIR)
            import re as _re
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
                    # Parse [STATS] lines for realtime update
                    if "[STATS]" in line:
                        try:
                            vals = dict(_re.findall(r'(\w+)=(\d+)', line))
                            self.after(0, lambda v=vals: self._update_stats(
                                queued=int(v.get('queued', 0)),
                                processing=int(v.get('processing', 0)),
                                created=int(v.get('created', 0)),
                                done=int(v.get('done', 0)),
                                failed=int(v.get('failed', 0)),
                                apikey=int(v.get('apikey', 0)),
                            ))
                        except Exception:
                            pass
            proc.wait()
            print("\n[GUI] ═══════════════════════════════════════════")
            print("[GUI] Done.")
            print("[GUI] ═══════════════════════════════════════════")
            self.load_results()
        except Exception as e:
            print(f"\n[GUI] Error: {e}")
        finally:
            sys.stdout = old_stdout
            self.running = False
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)


class AlibabaTab(ttk.Frame):
    """Tab 3: Alibaba Cloud Farm (placeholder — launches farm_headless.py)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        hdr = tk.Label(self, text="Alibaba Cloud Farm", font=("Segoe UI", 16, "bold"),
                       bg=BG_DARK, fg=FG_MAIN)
        hdr.pack(pady=(10, 5))

        info = tk.Label(self, text="Klik tombol di bawah untuk launch farm_headless.py\n"
                                  "(menu interaktif CLI akan muncul di terminal)",
                        bg=BG_DARK, fg=FG_DIM, font=("Segoe UI", 10), justify=tk.CENTER)
        info.pack(pady=20)

        btn = tk.Button(self, text="▶ LAUNCH ALIBABA FARM",
                        bg=ACCENT, fg="#1e1e2e", font=("Segoe UI", 12, "bold"),
                        relief=tk.FLAT, padx=30, pady=10, cursor="hand2",
                        command=self.launch)
        btn.pack(pady=10)

    def launch(self):
        import subprocess
        subprocess.Popen([sys.executable, os.path.join(FARM_DIR, "farm_headless.py")],
                         cwd=FARM_DIR)


class FarmGUI(tk.Tk):
    """Main GUI window dengan tab system."""

    def __init__(self):
        super().__init__()
        self.title("Alibaba Cloud Farm — Desktop")
        self.configure(bg=BG_DARK)

        # ─ Fullscreen launch ─
        self.state("zoomed")  # Windows: maximized fullscreen
        self.minsize(1024, 700)

        # ─ Style ─
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG_DARK, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_PANEL, foreground=FG_DIM,
                        padding=[20, 10], font=("Segoe UI", 11))
        style.map("TNotebook.Tab",
                  background=[("selected", BG_INPUT)],
                  foreground=[("selected", ACCENT)])
        style.configure("TFrame", background=BG_DARK)
        style.configure("Treeview", background=BG_INPUT, foreground=FG_MAIN,
                        fieldbackground=BG_INPUT, font=("Segoe UI", 9), rowheight=24)
        style.configure("Treeview.Heading", background=BG_PANEL, foreground=ACCENT,
                        font=("Segoe UI", 10, "bold"))

        # ─ Header ─
        header = tk.Frame(self, bg=BG_DARK, height=60)
        header.pack(fill=tk.X)
        tk.Label(header, text="🖥  ALIBABA CLOUD FARM", font=("Segoe UI", 20, "bold"),
                 bg=BG_DARK, fg=ACCENT).pack(side=tk.LEFT, padx=25, pady=12)

        # ─ Tabs ─
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        self.xiaomi_tab = XiaomiTab(self.notebook)
        self.email_tab = EmailFarmTab(self.notebook)
        self.alibaba_tab = AlibabaTab(self.notebook)
        self.qwen_tab = QwenCloudTab(self.notebook)

        self.notebook.add(self.xiaomi_tab, text="  📱 Xiaomi MiMo Farm  ")
        self.notebook.add(self.email_tab, text="  📧 Email Farm  ")
        self.notebook.add(self.alibaba_tab, text="  ☁  Alibaba Cloud Farm  ")
        self.notebook.add(self.qwen_tab, text="  🌐 Qwen Cloud Farm  ")

        # ─ Footer ─
        tk.Label(self, text="© 2026 Alibaba Cloud Farm | E:\\WEB\\alibaba-cloud-farm",
                 bg=BG_DARK, fg=FG_DIM, font=("Segoe UI", 9)).pack(side=tk.BOTTOM, pady=5)


if __name__ == "__main__":
    app = FarmGUI()
    app.mainloop()
