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
from data_paths import get_path, get_alias_index_path, get_used_count, load_alias_index, migrate_legacy_files


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
    """Redirect stdout to tkinter Text widget with colored formatting."""
    def __init__(self, text_widget):
        self.text_widget = text_widget
        # Configure tags
        self.text_widget.tag_config("success", foreground="#22c55e", font=("Consolas", 10, "bold"))
        self.text_widget.tag_config("fail", foreground="#ef4444", font=("Consolas", 10, "bold"))
        self.text_widget.tag_config("warn", foreground="#eab308", font=("Consolas", 10, "bold"))
        self.text_widget.tag_config("stats", foreground="#38bdf8", font=("Consolas", 10, "bold"))

    def write(self, string):
        self.text_widget.config(state=tk.NORMAL)
        # Determine tag based on content
        tag = None
        lower = string.lower()
        if "✓" in string or "api key extracted" in lower or "api key:" in lower and "failed" not in lower:
            tag = "success"
        elif "failed" in lower or "error" in lower or "exception" in lower:
            tag = "fail"
        elif "[stats]" in lower:
            tag = "stats"
        elif "warning" in lower or "skip" in lower:
            tag = "warn"

        if tag:
            # Insert with prefix emoji for success
            if tag == "success" and "✓" not in string:
                string = string.replace("[MIST]", "[MIST] ✓", 1) if "[MIST]" in string else "✓ " + string
            self.text_widget.insert(tk.END, string, tag)
        else:
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
        results_file = get_path("xiaomi", "results.json")
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
        results_file = get_path("email", "results.json")
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
        results_file = get_path("email", "results.json")
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
        csv_path = get_path("email", "accounts.csv")
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
        aliases_file = get_alias_index_path("email")
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
        try:
            self.stats_created.config(text=str(created))
        except AttributeError:
            pass
        self.stats_done.config(text=str(done))
        self.stats_failed.config(text=str(failed))
        self.stats_apikey.config(text=str(apikey))

    def load_results(self):
        """Load existing results into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        results_file = get_path("qwen", "results.json")
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
                                    text=True, bufsize=1, cwd=FARM_DIR)
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
                            # Update alias info realtime
                            self.after(0, lambda: self._update_alias_info())
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
    """Tab 3: Alibaba Cloud Farm — Multi-provider registration + API key.
    Layout: compact left-right panel (same as MistralTab)."""

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

        if ram_total > 0:
            usable_ram = max(1, ram_total - 2)
            ram_based = max(1, usable_ram // 1)
        else:
            ram_based = 3

        if cpu_physical > 0:
            cpu_based = max(1, cpu_physical * 2)
        else:
            cpu_based = 4

        recommended = min(ram_based, cpu_based, 8)

        return {
            "ram_gb": ram_total,
            "cpu_cores": cpu_cores,
            "cpu_physical": cpu_physical,
            "recommended": recommended,
        }

    def _build_ui(self):
        # ─ Main horizontal layout: left panel (settings) + right panel (log) ─
        main_frame = tk.Frame(self, bg=BG_DARK)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left panel: scrollable settings + buttons + stats
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
        tk.Label(left, text="Alibaba Cloud Farm", font=("Segoe UI", 14, "bold"),
                 bg=BG_DARK, fg=FG_MAIN).pack(pady=(5, 2))

        # ─ PC Specs (left) ─
        specs = self._detect_specs()
        specs_text = (f"RAM {specs['ram_gb']}GB | CPU {specs['cpu_physical']}c/{specs['cpu_cores']}t | "
                      f"Max {specs['recommended']} browser")
        tk.Label(left, text=specs_text, bg=BG_DARK, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8, "bold")).pack(pady=(0, 5))

        # ─ Settings frame (left) ─
        settings = tk.Frame(left, bg=BG_PANEL, padx=10, pady=10)
        settings.pack(fill=tk.X, pady=2)

        # Email Provider Selection
        tk.Label(settings, text="Provider:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=3)

        self.provider_var = tk.StringVar(value="gmail")
        provider_options = ["tempmail", "gmail", "outlook", "manual"]
        self.provider_combo = tk.OptionMenu(settings, self.provider_var, *provider_options,
                                            command=self._on_provider_changed)
        self.provider_combo.config(bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9),
                                   activebackground=BG_INPUT, activeforeground=FG_MAIN,
                                   highlightthickness=0, relief=tk.FLAT, width=12)
        self.provider_combo.grid(row=0, column=1, columnspan=2, sticky="we", pady=3, padx=(5, 0))

        # ─ Gmail fields (always visible — filled from env, hidden until provider==gmail) ─
        # Gmail user
        tk.Label(settings, text="Gmail:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=3)
        self.gmail_user = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=28,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 9), show="*")
        self.gmail_user.insert(0, os.environ.get("QWEN_GMAIL_USER", ""))
        self.gmail_user.grid(row=1, column=1, columnspan=3, sticky="we", pady=3, padx=(5, 0))
        self.gmail_user.bind("<KeyRelease>", self._on_gmail_changed)

        # App password
        tk.Label(settings, text="App Pass:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=3)
        self.gmail_pass = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=28,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 9), show="*")
        self.gmail_pass.insert(0, os.environ.get("QWEN_GMAIL_APP_PASS", ""))
        self.gmail_pass.grid(row=2, column=1, columnspan=3, sticky="we", pady=3, padx=(5, 0))

        # Alias info bar
        self.max_aliases_var = tk.StringVar(value="Max: -")
        self.used_aliases_var = tk.StringVar(value="Used: -")
        self.remaining_aliases_var = tk.StringVar(value="Remaining: -")
        self.complete_var = tk.StringVar(value="Complete: -")
        self.recoverable_var = tk.StringVar(value="Recoverable: -")

        alias_row = tk.Frame(settings, bg=BG_PANEL)
        alias_row.grid(row=3, column=0, columnspan=4, sticky="we", pady=(3, 2))
        tk.Label(alias_row, textvariable=self.max_aliases_var, bg=BG_PANEL, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(alias_row, textvariable=self.used_aliases_var, bg=BG_PANEL, fg=ACCENT_RED,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(alias_row, textvariable=self.remaining_aliases_var, bg=BG_PANEL, fg=ACCENT_GREEN,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))

        alias_row2 = tk.Frame(settings, bg=BG_PANEL)
        alias_row2.grid(row=4, column=0, columnspan=4, sticky="we", pady=(0, 5))
        tk.Label(alias_row2, textvariable=self.complete_var, bg=BG_PANEL, fg=ACCENT_GREEN,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(alias_row2, textvariable=self.recoverable_var, bg=BG_PANEL, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)

        # Account Count
        tk.Label(settings, text="Count:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=5, column=0, sticky="w", pady=3)
        self.count_var = tk.StringVar(value="1")
        tk.Spinbox(settings, from_=1, to=100, textvariable=self.count_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9)).grid(row=5, column=1, sticky="w", pady=3, padx=(5, 0))

        # Browser Concurrency
        tk.Label(settings, text="Browsers:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=5, column=2, sticky="w", pady=3, padx=(10, 0))
        self.concurrency_var = tk.IntVar(value=1)
        tk.Spinbox(settings, from_=1, to=8, textvariable=self.concurrency_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9)).grid(row=5, column=3, sticky="w", pady=3, padx=(5, 0))

        # Auto button
        tk.Button(settings, text=f"Auto ({specs['recommended']})",
                  bg=ACCENT, fg="#1e1e2e", font=("Segoe UI", 7, "bold"),
                  relief=tk.FLAT, padx=5, pady=1, cursor="hand2",
                  command=lambda: self.concurrency_var.set(min(specs["recommended"], 3))
                  ).grid(row=6, column=3, sticky="e", pady=2)

        # ─ Browser mode (left) ─
        mode_frame = tk.Frame(left, bg=BG_PANEL, padx=10, pady=5)
        mode_frame.pack(fill=tk.X, pady=2)

        self.headless_var = tk.BooleanVar(value=True)
        self.show_browser_var = tk.BooleanVar(value=False)
        self.debug_var = tk.BooleanVar(value=False)

        tk.Checkbutton(mode_frame, text="Headless", variable=self.headless_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9), command=self._on_headless_toggle).pack(side=tk.LEFT, padx=(0, 10))
        tk.Checkbutton(mode_frame, text="Show Browser", variable=self.show_browser_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9), command=self._on_show_toggle).pack(side=tk.LEFT, padx=(0, 10))
        tk.Checkbutton(mode_frame, text="Debug", variable=self.debug_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9)).pack(side=tk.LEFT)

        # ─ Browser engine selector ──
        browser_frame = tk.Frame(left, bg=BG_PANEL, padx=10, pady=5)
        browser_frame.pack(fill=tk.X, pady=2)

        tk.Label(browser_frame, text="Browser:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 5))

        self.browser_var = tk.StringVar(value="chrome")
        browser_options = [
            "chrome",
            "firefox",
            "webkit",
            "camoufox",
            "undetected-chromedriver",
            "rebrowser",
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

        # ─ Buttons (left) ─
        btn_frame = tk.Frame(left, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, pady=5)

        self.start_btn = tk.Button(btn_frame, text="▶ START",
                                   bg=ACCENT_GREEN, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                   relief=tk.FLAT, padx=25, pady=8, cursor="hand2",
                                   command=self.start_registration)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = tk.Button(btn_frame, text="■ STOP",
                                  bg=ACCENT_RED, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                  relief=tk.FLAT, padx=25, pady=8, cursor="hand2",
                                  state=tk.DISABLED, command=self.stop_registration)
        self.stop_btn.pack(side=tk.LEFT)

        # ─ Realtime Stats (left) ─
        stats_frame = tk.Frame(left, bg=BG_PANEL, padx=10, pady=8)
        stats_frame.pack(fill=tk.X, pady=2)

        tk.Label(stats_frame, text="📊 Realtime Stats", bg=BG_PANEL, fg=FG_MAIN,
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

        tk.Label(res_frame, text="Recent Accounts:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")

        cols = ("email", "api_key", "status")
        self.tree = ttk.Treeview(res_frame, columns=cols, show="headings", height=6)
        self.tree.heading("email", text="EMAIL")
        self.tree.heading("api_key", text="API KEY")
        self.tree.heading("status", text="STATUS")
        self.tree.column("email", width=140)
        self.tree.column("api_key", width=120)
        self.tree.column("status", width=60)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=3)

        self.load_results()

        # ─ Log output (right, large) ─
        tk.Label(right, text="Output Log:", bg=BG_DARK, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 2))

        self.log_text = scrolledtext.ScrolledText(right, bg=BG_INPUT, fg=ACCENT,
                                                   font=("Consolas", 9),
                                                   insertbackground=FG_MAIN, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Initialize alias info on load
        self._update_alias_info()

    def _on_headless_toggle(self):
        if self.headless_var.get():
            self.show_browser_var.set(False)

    def _on_show_toggle(self):
        if self.show_browser_var.get():
            self.headless_var.set(False)

    def _on_gmail_changed(self, event=None):
        self._update_alias_info()

    def _on_provider_changed(self, event=None):
        """Update alias info when provider changes to Gmail."""
        if self.provider_var.get() == "gmail":
            self._update_alias_info()

    def _update_alias_info(self):
        """Calculate and display max Gmail dot-trick aliases, used, remaining, complete, recoverable."""
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
            positions = len(clean) - 1
            max_aliases = 2 ** positions

        # Count from alibaba_accounts.csv
        used_count = 0
        complete_count = 0
        recoverable_count = 0
        results_file = get_path("alibaba", "accounts.csv")
        if os.path.exists(results_file):
            try:
                import csv as _csv
                with open(results_file, newline="") as f:
                    for row in _csv.DictReader(f):
                        used_count += 1
                        status = row.get("status", "").strip().lower()
                        apikey = row.get("api_key", "").strip()
                        if status == "complete" and apikey and apikey != "REGISTRATION_FAILED" and not apikey.startswith("EXCEPTION"):
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

    def _update_stats(self, queued=0, processing=0, created=0, done=0, failed=0, apikey=0):
        """Update realtime stats display."""
        self.stats_queued.config(text=str(queued))
        self.stats_processing.config(text=str(processing))
        try:
            self.stats_created.config(text=str(created))
        except AttributeError:
            pass
        self.stats_done.config(text=str(done))
        self.stats_failed.config(text=str(failed))
        self.stats_apikey.config(text=str(apikey))

    def load_results(self):
        """Load existing results into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        results_file = get_path("alibaba", "results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                for row in data[-20:]:
                    self.tree.insert("", tk.END, values=(
                        row.get("email", ""),
                        row.get("api_key", ""),
                        row.get("status", ""),
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
            args = [sys.executable, os.path.join(FARM_DIR, "farm_headless.py")]

            # Provider
            provider = self.provider_var.get()
            if provider != "tempmail":  # tempmail is default
                args.append("--provider")
                args.append(provider)

            # Gmail credentials (dot trick)
            if provider == "gmail":
                gmail_user = self.gmail_user.get().strip()
                gmail_pass = self.gmail_pass.get().strip()
                if gmail_user and gmail_pass:
                    args.append("--gmail")
                    args.append(gmail_user)
                    args.append("--apppass")
                    args.append(gmail_pass)
                else:
                    print("[GUI] ERROR: Gmail credentials required for Gmail Dot Trick provider!")
                    return

            # Outlook credentials
            if provider == "outlook":
                # For now, Outlook still uses direct creds from env or manual entry
                outlook_email = self.gmail_user.get().strip()
                outlook_pass = self.gmail_pass.get().strip()
                if outlook_email and outlook_pass:
                    args.append("--gmail")
                    args.append(outlook_email)
                    args.append("--apppass")
                    args.append(outlook_pass)

            # Count & concurrency
            args.append("--count")
            args.append(self.count_var.get())
            args.append("--concurrency")
            args.append(str(self.concurrency_var.get()))

            # Browser mode
            if self.show_browser_var.get():
                args.append("--show")

            if self.debug_var.get():
                args.append("--debug")

            # Browser engine
            args.append("--browser")
            args.append(self.browser_var.get())

            # Log config
            print(f"[GUI] ═══════════════════════════════════════════")
            print(f"[GUI] Alibaba Cloud Farm Starting")
            print(f"[GUI] Provider: {provider}")
            print(f"[GUI] Target accounts: {self.count_var.get()}")
            print(f"[GUI] Browser concurrency: {self.concurrency_var.get()}")
            print(f"[GUI] Browser engine: {self.browser_var.get()}")
            print(f"[GUI] Browser mode: {'visible' if self.show_browser_var.get() else 'headless'}")
            print(f"[GUI] Debug mode: {'ON' if self.debug_var.get() else 'OFF'}")
            if provider == "gmail":
                print(f"[GUI] Gmail: {self.gmail_user.get()}")
            print(f"[GUI] ═══════════════════════════════════════════\n")

            import subprocess
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, cwd=FARM_DIR)
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
                            # Update alias info realtime
                            self.after(0, lambda: self._update_alias_info())
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


class MistralTab(ttk.Frame):
    """Tab 5: Mistral AI Farm — Gmail dot trick registration + API key."""

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

        if ram_total > 0:
            usable_ram = max(1, ram_total - 2)
            ram_based = max(1, usable_ram // 1)
        else:
            ram_based = 3

        if cpu_physical > 0:
            cpu_based = max(1, cpu_physical * 2)
        else:
            cpu_based = 4

        recommended = min(ram_based, cpu_based, 8)

        return {
            "ram_gb": ram_total,
            "cpu_cores": cpu_cores,
            "cpu_physical": cpu_physical,
            "recommended": recommended,
        }

    def _build_ui(self):
        # ─ Main horizontal layout: left panel (settings) + right panel (log) ─
        main_frame = tk.Frame(self, bg=BG_DARK)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left panel: scrollable settings + buttons + stats
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
        tk.Label(left, text="Mistral AI Farm", font=("Segoe UI", 14, "bold"),
                 bg=BG_DARK, fg=FG_MAIN).pack(pady=(5, 2))

        # ─ PC Specs (left) ─
        specs = self._detect_specs()
        specs_text = (f"RAM {specs['ram_gb']}GB | CPU {specs['cpu_physical']}c/{specs['cpu_cores']}t | "
                      f"Max {specs['recommended']} browser")
        tk.Label(left, text=specs_text, bg=BG_DARK, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8, "bold")).pack(pady=(0, 5))

        # ─ Settings frame (left) ─
        settings = tk.Frame(left, bg=BG_PANEL, padx=10, pady=10)
        settings.pack(fill=tk.X, pady=2)

        # Gmail user
        tk.Label(settings, text="Gmail:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=3)
        self.gmail_user = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=28,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 9), show="*")
        self.gmail_user.insert(0, os.environ.get("QWEN_GMAIL_USER", ""))
        self.gmail_user.grid(row=0, column=1, columnspan=3, sticky="we", pady=3, padx=(5, 0))
        self.gmail_user.bind("<KeyRelease>", self._on_gmail_changed)

        # App password
        tk.Label(settings, text="App Pass:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=3)
        self.gmail_pass = tk.Entry(settings, bg=BG_INPUT, fg=FG_MAIN, width=28,
                                   insertbackground=FG_MAIN, font=("Segoe UI", 9), show="*")
        self.gmail_pass.insert(0, os.environ.get("QWEN_GMAIL_APP_PASS", ""))
        self.gmail_pass.grid(row=1, column=1, columnspan=3, sticky="we", pady=3, padx=(5, 0))

        # Alias info bar
        self.max_aliases_var = tk.StringVar(value="Max: -")
        self.used_aliases_var = tk.StringVar(value="Used: -")
        self.remaining_aliases_var = tk.StringVar(value="Remaining: -")
        self.complete_var = tk.StringVar(value="Complete: -")
        self.recoverable_var = tk.StringVar(value="Recoverable: -")

        alias_row = tk.Frame(settings, bg=BG_PANEL)
        alias_row.grid(row=2, column=0, columnspan=4, sticky="we", pady=(3, 2))
        tk.Label(alias_row, textvariable=self.max_aliases_var, bg=BG_PANEL, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(alias_row, textvariable=self.used_aliases_var, bg=BG_PANEL, fg=ACCENT_RED,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(alias_row, textvariable=self.remaining_aliases_var, bg=BG_PANEL, fg=ACCENT_GREEN,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))

        alias_row2 = tk.Frame(settings, bg=BG_PANEL)
        alias_row2.grid(row=3, column=0, columnspan=4, sticky="we", pady=(0, 5))
        tk.Label(alias_row2, textvariable=self.complete_var, bg=BG_PANEL, fg=ACCENT_GREEN,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(alias_row2, textvariable=self.recoverable_var, bg=BG_PANEL, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)

        # Account Count
        tk.Label(settings, text="Count:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=4, column=0, sticky="w", pady=3)
        self.count_var = tk.StringVar(value="5")
        tk.Spinbox(settings, from_=1, to=512, textvariable=self.count_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9)).grid(row=4, column=1, sticky="w", pady=3, padx=(5, 0))

        # Browser Concurrency
        tk.Label(settings, text="Browsers:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).grid(row=4, column=2, sticky="w", pady=3, padx=(10, 0))
        self.concurrency_var = tk.IntVar(value=min(specs["recommended"], 3))
        tk.Spinbox(settings, from_=1, to=8, textvariable=self.concurrency_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9)).grid(row=4, column=3, sticky="w", pady=3, padx=(5, 0))

        # Auto button
        tk.Button(settings, text=f"Auto ({specs['recommended']})",
                  bg=ACCENT, fg="#1e1e2e", font=("Segoe UI", 7, "bold"),
                  relief=tk.FLAT, padx=5, pady=1, cursor="hand2",
                  command=lambda: self.concurrency_var.set(min(specs["recommended"], 3))
                  ).grid(row=5, column=3, sticky="e", pady=2)

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
                       font=("Segoe UI", 9), command=self._on_show_toggle).pack(side=tk.LEFT)

        # ─ Buttons (left) ─
        btn_frame = tk.Frame(left, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, pady=5)

        self.start_btn = tk.Button(btn_frame, text="▶ START",
                                   bg=ACCENT_GREEN, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                   relief=tk.FLAT, padx=25, pady=8, cursor="hand2",
                                   command=self.start_registration)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = tk.Button(btn_frame, text="■ STOP",
                                  bg=ACCENT_RED, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                  relief=tk.FLAT, padx=25, pady=8, cursor="hand2",
                                  state=tk.DISABLED, command=self.stop_registration)
        self.stop_btn.pack(side=tk.LEFT)

        # ─ Realtime Stats (left) ─
        stats_frame = tk.Frame(left, bg=BG_PANEL, padx=10, pady=8)
        stats_frame.pack(fill=tk.X, pady=2)

        tk.Label(stats_frame, text="📊 Realtime Stats", bg=BG_PANEL, fg=FG_MAIN,
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

        tk.Label(res_frame, text="Recent Accounts:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")

        cols = ("email", "api_key", "status")
        self.tree = ttk.Treeview(res_frame, columns=cols, show="headings", height=6)
        self.tree.heading("email", text="EMAIL")
        self.tree.heading("api_key", text="API KEY")
        self.tree.heading("status", text="STATUS")
        self.tree.column("email", width=140)
        self.tree.column("api_key", width=120)
        self.tree.column("status", width=60)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=3)

        self.load_results()

        # ─ Log output (right, large) ─
        tk.Label(right, text="Output Log:", bg=BG_DARK, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 2))

        self.log_text = scrolledtext.ScrolledText(right, bg=BG_INPUT, fg=ACCENT,
                                                   font=("Consolas", 9),
                                                   insertbackground=FG_MAIN, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Initialize alias info on load
        self._update_alias_info()

    def _on_headless_toggle(self):
        if self.headless_var.get():
            self.show_browser_var.set(False)

    def _on_show_toggle(self):
        if self.show_browser_var.get():
            self.headless_var.set(False)

    def _on_gmail_changed(self, event=None):
        self._update_alias_info()

    def _update_alias_info(self):
        """Calculate and display max Gmail dot-trick aliases, used, remaining, complete, recoverable."""
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
            positions = len(clean) - 1
            max_aliases = 2 ** positions

        # Count from mistral_accounts.csv
        used_count = 0
        complete_count = 0
        recoverable_count = 0
        results_file = get_path("mistral", "accounts.csv")
        if os.path.exists(results_file):
            try:
                import csv as _csv
                with open(results_file, newline="") as f:
                    for row in _csv.DictReader(f):
                        used_count += 1
                        status = row.get("status", "").strip().lower()
                        apikey = row.get("api_key", "").strip()
                        if status == "complete" and apikey and apikey != "REGISTRATION_FAILED" and not apikey.startswith("EXCEPTION"):
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

    def _update_stats(self, queued=0, processing=0, created=0, done=0, failed=0, apikey=0):
        """Update realtime stats display."""
        self.stats_queued.config(text=str(queued))
        self.stats_processing.config(text=str(processing))
        try:
            self.stats_created.config(text=str(created))
        except AttributeError:
            pass
        self.stats_done.config(text=str(done))
        self.stats_failed.config(text=str(failed))
        self.stats_apikey.config(text=str(apikey))

    def load_results(self):
        """Load existing results into treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        results_file = get_path("mistral", "accounts.csv")
        if os.path.exists(results_file):
            try:
                import csv as _csv
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
            args = [sys.executable, os.path.join(FARM_DIR, "mistral_farm.py")]
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
            print(f"[GUI] Mistral AI Farm Starting")
            print(f"[GUI] Gmail: {self.gmail_user.get()}")
            print(f"[GUI] Target accounts: {self.count_var.get()}")
            print(f"[GUI] Browser concurrency: {self.concurrency_var.get()}")
            print(f"[GUI] Browser mode: {'visible' if self.show_browser_var.get() else 'headless'}")
            print(f"[GUI] ═══════════════════════════════════════════\n")

            import subprocess
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, cwd=FARM_DIR)
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
                            # Update alias info realtime
                            self.after(0, lambda: self._update_alias_info())
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


class SiliconFlowTab(ttk.Frame):
    """Tab 6: SiliconFlow Farm — GSuite Google OAuth + API key extraction."""

    def __init__(self, parent):
        super().__init__(parent)
        self.running = False
        self._build_ui()

    def _detect_specs(self):
        try:
            import psutil
            ram_total = psutil.virtual_memory().total // (1024**3)
            cpu_cores = psutil.cpu_count(logical=True)
            cpu_physical = psutil.cpu_count(logical=False)
        except ImportError:
            ram_total, cpu_cores, cpu_physical = 0, 0, 0

        if ram_total > 0:
            usable_ram = max(1, ram_total - 2)
            ram_based = max(1, usable_ram // 1)
        else:
            ram_based = 3

        if cpu_physical > 0:
            cpu_based = max(1, cpu_physical * 2)
        else:
            cpu_based = 4

        recommended = min(ram_based, cpu_based, 8)

        return {
            "ram_gb": ram_total,
            "cpu_cores": cpu_cores,
            "cpu_physical": cpu_physical,
            "recommended": recommended,
        }

    def _build_ui(self):
        main_frame = tk.Frame(self, bg=BG_DARK)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # ════════════════════════════════════════
        # Left panel: fixed-width scrollable settings
        # Width must fit ALL content without clip
        # ════════════════════════════════════════
        LEFT_WIDTH = 440

        left_outer = tk.Frame(main_frame, bg=BG_DARK, width=LEFT_WIDTH)
        left_outer.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left_outer.pack_propagate(False)

        left_canvas = tk.Canvas(left_outer, bg=BG_DARK, highlightthickness=0,
                                width=LEFT_WIDTH)
        left_scroll = tk.Scrollbar(left_outer, orient=tk.VERTICAL, command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        left = tk.Frame(left_canvas, bg=BG_DARK)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        # Keep inner frame width synced with canvas
        def _sync_width(e=None):
            canvas_w = left_canvas.winfo_width()
            if canvas_w > 1:
                left.canvas_w = canvas_w
                left_canvas.itemconfig(left_window, width=canvas_w)

        left.bind("<Configure>", lambda e: (
            left_canvas.configure(scrollregion=left_canvas.bbox("all")),
            _sync_width(),
        ))
        left_canvas.bind("<Configure>", _sync_width)

        def _on_wheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        left_canvas.bind_all("<MouseWheel>", _on_wheel)
        left_canvas.bind_all("<Enter>", lambda e: left_canvas.bind_all("<MouseWheel>", _on_wheel))
        left_canvas.bind_all("<Leave>", lambda e: left_canvas.unbind_all("<MouseWheel>"))

        # ════════════════════════════════════════
        # Right panel: log + results
        # ════════════════════════════════════════
        right = tk.Frame(main_frame, bg=BG_DARK)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── Header (left) ──
        tk.Label(left, text="SiliconFlow Farm", font=("Segoe UI", 14, "bold"),
                 bg=BG_DARK, fg=FG_MAIN).pack(pady=(6, 1))

        specs = self._detect_specs()
        specs_text = (f"RAM {specs['ram_gb']}GB | CPU {specs['cpu_physical']}c/{specs['cpu_cores']}t | "
                      f"Max {specs['recommended']} browsers")
        tk.Label(left, text=specs_text, bg=BG_DARK, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 8)).pack(pady=(0, 6))

        # ── Settings panel (white card) ──
        settings = tk.Frame(left, bg=BG_PANEL, padx=12, pady=10)
        settings.pack(fill=tk.X, pady=0)

        # Row 0: Accounts File path
        r0 = tk.Frame(settings, bg=BG_PANEL)
        r0.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        r0.grid_columnconfigure(1, weight=1)

        tk.Label(r0, text="Accounts:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)

        default_accounts = os.path.join(FARM_DIR, "data", "siliconflow", "gsuite_accounts.txt")
        self.accounts_file_var = tk.StringVar(value=default_accounts)
        tk.Entry(r0, textvariable=self.accounts_file_var, bg=BG_INPUT,
                 fg=FG_MAIN, width=30, insertbackground=FG_MAIN,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 4))

        tk.Button(r0, text="Browse", bg=ACCENT, fg="#1e1e2e",
                  font=("Segoe UI", 8), relief=tk.FLAT, padx=8, cursor="hand2",
                  command=self._browse_accounts).pack(side=tk.LEFT)

        # Row 1: Account count info
        self.account_count_var = tk.StringVar(value="Accounts: -")
        tk.Label(settings, textvariable=self.account_count_var, bg=BG_PANEL,
                 fg=ACCENT_YELLOW, font=("Segoe UI", 8),
                 anchor="w").grid(row=1, column=0, sticky="ew", pady=(0, 5))
        self._refresh_account_count()

        # Row 2: Single Account mode
        single_frame = tk.Frame(settings, bg=BG_PANEL)
        single_frame.grid(row=2, column=0, sticky="ew", pady=(2, 5))

        self.use_single_var = tk.BooleanVar(value=False)
        tk.Checkbutton(single_frame, text="Single account",
                       variable=self.use_single_var, bg=BG_PANEL, fg=FG_MAIN,
                       selectcolor=BG_INPUT, activebackground=BG_PANEL,
                       activeforeground=FG_MAIN, font=("Segoe UI", 9),
                       command=self._on_single_toggle).pack(side=tk.LEFT)

        self.single_email_var = tk.StringVar()
        self.single_pass_var = tk.StringVar()

        tk.Label(single_frame, text="Email:", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(8, 2))
        tk.Entry(single_frame, textvariable=self.single_email_var, bg=BG_INPUT,
                 fg=FG_MAIN, width=18, insertbackground=FG_MAIN,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 3))

        tk.Label(single_frame, text="Pass:", bg=BG_PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 2))
        tk.Entry(single_frame, textvariable=self.single_pass_var, bg=BG_INPUT,
                 fg=FG_MAIN, width=12, insertbackground=FG_MAIN,
                 font=("Segoe UI", 8), show="*").pack(side=tk.LEFT)

        # Row 3: Count + Concurrency + Options
        opts_frame = tk.Frame(settings, bg=BG_PANEL)
        opts_frame.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        tk.Label(opts_frame, text="Count:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.count_var = tk.StringVar(value="5")
        tk.Spinbox(opts_frame, from_=1, to=999, textvariable=self.count_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(4, 10))

        tk.Label(opts_frame, text="Conc:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.concurrency_var = tk.IntVar(value=1)
        c_spin = tk.Spinbox(opts_frame, from_=1, to=10, textvariable=self.concurrency_var, width=4,
                            bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 9))
        c_spin.pack(side=tk.LEFT, padx=(4, 10))

        self.show_browser_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opts_frame, text="Show browser", variable=self.show_browser_var,
                       bg=BG_PANEL, fg=FG_MAIN, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_MAIN,
                       font=("Segoe UI", 9)).pack(side=tk.LEFT)

        self.debug_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opts_frame, text="Debug", variable=self.debug_var,
                       bg=BG_PANEL, fg=FG_DIM, selectcolor=BG_INPUT,
                       activebackground=BG_PANEL, activeforeground=FG_DIM,
                       font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(8, 0))

        # ── Buttons ──
        btn_frame = tk.Frame(left, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, pady=(10, 6))

        self.start_btn = tk.Button(btn_frame, text="▶ Start", font=("Segoe UI", 11, "bold"),
                                   bg=ACCENT_GREEN, fg="#1e1e2e", relief=tk.FLAT,
                                   padx=28, pady=7, cursor="hand2",
                                   command=self.start_farm)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.stop_btn = tk.Button(btn_frame, text="■ Stop", font=("Segoe UI", 11, "bold"),
                                  bg=ACCENT_RED, fg="#1e1e2e", relief=tk.FLAT,
                                  padx=28, pady=7, cursor="hand2",
                                  command=self.stop_farm, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)

        # ── Stats ──
        stats_frame = tk.Frame(left, bg=BG_DARK)
        stats_frame.pack(fill=tk.X, pady=2)

        self.stats_done = tk.Label(stats_frame, text="Done: 0", bg=BG_DARK,
                                   fg=ACCENT_GREEN, font=("Segoe UI", 9, "bold"))
        self.stats_done.pack(side=tk.LEFT, padx=(0, 16))
        self.stats_failed = tk.Label(stats_frame, text="Failed: 0", bg=BG_DARK,
                                     fg=ACCENT_RED, font=("Segoe UI", 9, "bold"))
        self.stats_failed.pack(side=tk.LEFT)

        # ── Log (right) ──
        tk.Label(right, text="📋 Output Log", font=("Segoe UI", 10, "bold"),
                 bg=BG_DARK, fg=ACCENT).pack(anchor="w", padx=6, pady=(6, 2))

        log_frame = tk.Frame(right, bg=BG_DARK)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 5))

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED,
                                bg="#1e1e2e", fg="#cdd6f4", font=("Consolas", 9),
                                insertbackground="#cdd6f4", height=20)
        log_scroll = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── Results table (right bottom) ──
        tk.Label(right, text="📊 Recent Results", font=("Segoe UI", 10, "bold"),
                 bg=BG_DARK, fg=ACCENT).pack(anchor="w", padx=6, pady=(6, 2))

        cols = ("email", "api_key", "status")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=7)
        self.tree.heading("email", text="Email")
        self.tree.heading("api_key", text="API Key")
        self.tree.heading("status", text="Status")
        self.tree.column("email", width=210, anchor="w")
        self.tree.column("api_key", width=230, anchor="w")
        self.tree.column("status", width=100, anchor="center")
        self.tree.pack(fill=tk.X, padx=6, pady=(0, 10))

    def _browse_accounts(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Select GSuite Accounts File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=FARM_DIR,
        )
        if path:
            self.accounts_file_var.set(path)
            self._refresh_account_count()

    def _refresh_account_count(self):
        fpath = self.accounts_file_var.get().strip()
        if os.path.isfile(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                done = len(self._load_done_emails())
                self.account_count_var.set(f"Accounts: {len(lines)} ({done} done)")
            except Exception:
                self.account_count_var.set("Accounts: (error reading)")
        else:
            self.account_count_var.set("Accounts: (file not found)")

    def _load_done_emails(self):
        track_file = os.path.join(FARM_DIR, "data", "siliconflow", "done_emails.txt")
        if os.path.exists(track_file):
            with open(track_file, "r", encoding="utf-8") as f:
                return set(line.strip() for line in f if line.strip())
        return set()

    def _on_single_toggle(self):
        pass

    def start_farm(self):
        if self.running:
            return
        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        threading.Thread(target=_run_siliconflow_farm, args=(self,), daemon=True).start()

    def stop_farm(self):
        self.running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def load_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        results_file = os.path.join(FARM_DIR, "data", "siliconflow", "siliconflow_results.json")
        if os.path.exists(results_file):
            try:
                with open(results_file) as f:
                    data = json.load(f)
                for row in data[-20:]:
                    apikey = row.get("api_key", "")
                    apikey_display = (apikey[:35] + "...") if len(apikey) > 35 else apikey
                    self.tree.insert("", tk.END, values=(
                        row.get("email", ""),
                        apikey_display,
                        row.get("status", ""),
                    ))
            except Exception:
                pass


def _run_siliconflow_farm(tab):
    """Run siliconflow_farm.py in subprocess, redirect stdout to tab's log widget."""
    redirector = RedirectText(tab.log_text)
    old_stdout = sys.stdout
    sys.stdout = redirector
    try:
        args = [sys.executable, os.path.join(FARM_DIR, "siliconflow_farm.py")]

        if tab.use_single_var.get():
            email = tab.single_email_var.get().strip()
            pw = tab.single_pass_var.get().strip()
            if email and pw:
                args.extend(["--email", email, "--pass", pw])
            else:
                args.extend(["--accounts-file", tab.accounts_file_var.get().strip()])
        else:
            args.extend(["--accounts-file", tab.accounts_file_var.get().strip()])

        args.extend(["--count", tab.count_var.get()])
        args.extend(["--concurrency", str(tab.concurrency_var.get())])

        if tab.show_browser_var.get():
            args.append("--show")

        if tab.debug_var.get():
            args.append("--debug")

        print(f"[GUI] ════════════════════════════════════")
        print(f"[GUI] SiliconFlow Farm Starting")
        print(f"[GUI] Accounts file: {tab.accounts_file_var.get()}")
        print(f"[GUI] Target count: {tab.count_var.get()}")
        print(f"[GUI] Concurrency: {tab.concurrency_var.get()}")
        print(f"[GUI] Browser: {'visible' if tab.show_browser_var.get() else 'headless'}")
        print(f"[GUI] ════════════════════════════════════\n")

        import subprocess as _sp
        proc = _sp.Popen(args, stdout=_sp.PIPE, stderr=_sp.STDOUT,
                         text=True, bufsize=1, cwd=FARM_DIR)
        import re as _re
        while True:
            if not tab.running:
                proc.terminate()
                print("\n[GUI] Stopped by user.")
                break
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if line:
                # Safe print for Windows console (strip non-ASCII)
                safe_line = line.encode("ascii", "replace").decode("ascii")
                print(safe_line, end="")
                # Parse result lines for stats update
                decoded = line  # keep original for matching
                if (("+ [" in decoded or "SUCCESS" in decoded.upper() or "Reused" in decoded) and "API Key" in decoded):
                    tab.after(0, lambda: tab.stats_done.configure(
                        text=f"Done: {int(tab.stats_done.cget('text').split(': ')[1]) + 1}"))
                elif ("X [" in decoded or ("Failed:" in decoded and "SUCCESS" not in decoded.upper())):
                    tab.after(0, lambda: tab.stats_failed.configure(
                        text=f"Failed: {int(tab.stats_failed.cget('text').split(': ')[1]) + 1}"))
        proc.wait()
        print("\n[GUI] ════════════════════════════════════")
        print("[GUI] Done.")
        print("[GUI] ════════════════════════════════════")
        tab.after(0, lambda: (tab.load_results(), tab._refresh_account_count()))
    except Exception as e:
        print(f"\n[GUI] Error: {e}")
    finally:
        sys.stdout = old_stdout
        tab.running = False
        tab.after(0, lambda: (
            tab.start_btn.config(state=tk.NORMAL),
            tab.stop_btn.config(state=tk.DISABLED)
        ))


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
        self.mistral_tab = MistralTab(self.notebook)
        self.siliconflow_tab = SiliconFlowTab(self.notebook)

        self.notebook.add(self.xiaomi_tab, text="  📱 Xiaomi MiMo Farm  ")
        self.notebook.add(self.email_tab, text="  📧 Email Farm  ")
        self.notebook.add(self.alibaba_tab, text="  ☁  Alibaba Cloud Farm  ")
        self.notebook.add(self.qwen_tab, text="  🌐 Qwen Cloud Farm  ")
        self.notebook.add(self.mistral_tab, text="  🎯 Mistral AI Farm  ")
        self.notebook.add(self.siliconflow_tab, text="  🤖 SiliconFlow Farm  ")

        # ─ Footer ─
        tk.Label(self, text="© 2026 Alibaba Cloud Farm | E:\\WEB\\alibaba-cloud-farm",
                 bg=BG_DARK, fg=FG_DIM, font=("Segoe UI", 9)).pack(side=tk.BOTTOM, pady=5)


if __name__ == "__main__":
    app = FarmGUI()
    app.mainloop()
