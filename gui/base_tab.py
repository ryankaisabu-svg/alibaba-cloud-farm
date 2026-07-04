"""
gui/base_tab.py — Base class for all farm tab widgets.

Extracted from QwenCloudTab pattern in farm_gui.py (L532-926).
Provides reusable Tkinter UI scaffolding: header, specs detection,
settings frame, browser mode toggles, start/stop buttons, log output,
results treeview, realtime stats bar, and subprocess management.

Subclasses override:
  - TAB_TITLE       (str)  — header text
  - TAB_DESCRIPTION (str)  — subtitle text
  - FARM_SCRIPT     (str)  — script path to run (e.g. "alibaba_farm.py")
  - RESULTS_KEY     (str)  — data_paths key (e.g. "qwen", "alibaba", "mistral")
  - RESULT_COLS     (tuple) — treeview column names
  - _build_settings (method) — add farm-specific input fields to settings frame
  - _build_args     (method) — return list of extra CLI args for subprocess
  - _parse_stats_line (method) — parse [STATS] lines, return dict or None
"""

import sys
import os
import json
import threading
import subprocess
import re as _re
import tkinter as tk
from tkinter import ttk, scrolledtext

# ─ Colors (shared from farm_gui.py) ─────────────────
BG_DARK = "#1e1e2e"
BG_PANEL = "#2a2a3c"
BG_INPUT = "#363649"
FG_MAIN = "#cdd6f4"
FG_DIM = "#7f7f9f"
ACCENT = "#89b4fa"
ACCENT_GREEN = "#a6e3a1"
ACCENT_RED = "#f38ba8"
ACCENT_YELLOW = "#f9e2af"

FARM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RedirectText:
    """Redirect stdout to tkinter Text widget with colored formatting."""

    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.text_widget.tag_config("success", foreground="#22c55e", font=("Consolas", 10, "bold"))
        self.text_widget.tag_config("fail", foreground="#ef4444", font=("Consolas", 10, "bold"))
        self.text_widget.tag_config("warn", foreground="#eab308", font=("Consolas", 10, "bold"))
        self.text_widget.tag_config("stats", foreground="#38bdf8", font=("Consolas", 10, "bold"))

    def write(self, string):
        self.text_widget.config(state=tk.NORMAL)
        tag = None
        lower = string.lower()
        if "\u2713" in string or "api key extracted" in lower or "api key:" in lower and "failed" not in lower:
            tag = "success"
        elif "failed" in lower or "error" in lower or "exception" in lower:
            tag = "fail"
        elif "[stats]" in lower:
            tag = "stats"
        elif "warning" in lower or "skip" in lower:
            tag = "warn"

        if tag:
            if tag == "success" and "\u2713" not in string:
                string = "\u2713 " + string
            self.text_widget.insert(tk.END, string, tag)
        else:
            self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        self.text_widget.config(state=tk.DISABLED)

    def flush(self):
        pass


class BaseFarmTab(ttk.Frame):
    """Base class for all farm tab widgets.

    Subclasses must set class attributes and override hook methods.
    See module docstring for details.
    """

    # ─ Subclass overrides ───────────────────────────
    TAB_TITLE = "Farm"
    TAB_DESCRIPTION = ""
    FARM_SCRIPT = None          # e.g. "alibaba_farm.py"
    RESULTS_KEY = "alibaba"    # data_paths key
    RESULT_COLS = ("email", "api_key", "status", "timestamp")
    RESULT_COL_WIDTHS = None   # dict col->width, or None for default 150 (api_key=200)
    SUPPORTS_COUNT_CONCURRENCY = True  # False = don't pass --count/--concurrency (xiaomi_farm.py)

    # ─ Init ──────────────────────────────────────────

    def __init__(self, parent):
        super().__init__(parent)
        self.running = False
        self._build_ui()

    # ─ PC Specs detection ────────────────────────────

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

    # ─ UI Construction ───────────────────────────────

    def _build_ui(self):
        """Build the standard tab layout. Override _build_settings for custom fields."""
        # ─ Header ─
        hdr = tk.Label(self, text=self.TAB_TITLE, font=("Segoe UI", 16, "bold"),
                       bg=BG_DARK, fg=FG_MAIN)
        hdr.pack(pady=(10, 5))

        info = tk.Label(self, text=self.TAB_DESCRIPTION,
                        bg=BG_DARK, fg=FG_DIM, font=("Segoe UI", 9), justify=tk.CENTER)
        info.pack(pady=(0, 5))

        # ─ PC Specs ─
        specs = self._detect_specs()

        specs_frame = tk.Frame(self, bg=BG_PANEL, padx=15, pady=10)
        specs_frame.pack(fill=tk.X, padx=20, pady=5)

        specs_text = (f"PC Specs: RAM {specs['ram_gb']}GB | "
                      f"CPU {specs['cpu_physical']}c/{specs['cpu_cores']}t | "
                      f"Rekomendasi: {specs['recommended']} browser")
        tk.Label(specs_frame, text=specs_text, bg=BG_PANEL, fg=ACCENT_YELLOW,
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 5))

        self._specs = specs

        # ─ Settings frame (subclass adds fields here) ─
        settings = tk.Frame(self, bg=BG_PANEL, padx=15, pady=15)
        settings.pack(fill=tk.X, padx=20, pady=5)
        self._settings_frame = settings

        # Account Count (common to all tabs)
        tk.Label(settings, text="Account Count:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w", pady=5)
        self.count_var = tk.StringVar(value="5")
        self.count_spinbox = tk.Spinbox(settings, from_=1, to=512, textvariable=self.count_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 10))
        self.count_spinbox.grid(row=2, column=1, sticky="w", pady=5)

        # Browser Concurrency (common to all tabs)
        tk.Label(settings, text="Browser Concurrency:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10)).grid(row=2, column=2, sticky="w", pady=5, padx=(20, 0))
        self.concurrency_var = tk.IntVar(value=specs["recommended"])
        tk.Spinbox(settings, from_=1, to=8, textvariable=self.concurrency_var, width=5,
                   bg=BG_INPUT, fg=FG_MAIN, font=("Segoe UI", 10)).grid(row=2, column=3, sticky="w", pady=5)

        tk.Button(settings, text=f"\u2699 Auto ({specs['recommended']})",
                  bg=ACCENT, fg="#1e1e2e", font=("Segoe UI", 8, "bold"),
                  relief=tk.FLAT, padx=8, pady=2, cursor="hand2",
                  command=lambda: self.concurrency_var.set(specs["recommended"])
                  ).grid(row=2, column=4, sticky="w", pady=5)

        tk.Label(settings, text="(Account Count = total akun target | Concurrency = browser yang jalan bersamaan)",
                 bg=BG_PANEL, fg=FG_DIM, font=("Segoe UI", 8)).grid(row=3, column=0, columnspan=6, sticky="w", pady=(2, 0))

        # Let subclass add its own fields
        self._build_settings(settings)

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

        self.start_btn = tk.Button(btn_frame, text=f"\u25b6 START {self.TAB_TITLE.upper()}",
                                   bg=ACCENT_GREEN, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                   relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
                                   command=self.start_registration)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = tk.Button(btn_frame, text="\u25a0 STOP",
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

        # ─ Results treeview ─
        res_frame = tk.Frame(self, bg=BG_PANEL, padx=15, pady=10)
        res_frame.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Label(res_frame, text=f"{self.TAB_TITLE} Accounts:", bg=BG_PANEL, fg=FG_MAIN,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")

        cols = self.RESULT_COLS
        self.tree = ttk.Treeview(res_frame, columns=cols, show="headings", height=5)
        for col in cols:
            self.tree.heading(col, text=col.upper())
            if self.RESULT_COL_WIDTHS and col in self.RESULT_COL_WIDTHS:
                w = self.RESULT_COL_WIDTHS[col]
            else:
                w = 200 if col == "api_key" else 150
            self.tree.column(col, width=w)
        self.tree.pack(fill=tk.X, pady=5)

        self.load_results()

        # ─ Realtime Stats Bar ─
        stats_frame = tk.Frame(self, bg=BG_PANEL, padx=15, pady=10)
        stats_frame.pack(fill=tk.X, padx=20, pady=(5, 10))

        tk.Label(stats_frame, text="\U0001f4ca Realtime Stats:", bg=BG_PANEL, fg=FG_MAIN,
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

        # Subclass post-init hook
        self._post_init()

    # ─ Hooks for subclasses ──────────────────────────

    def _build_settings(self, settings_frame):
        """Override to add farm-specific input fields. settings_frame is a tk.Frame."""
        pass

    def _build_args(self):
        """Override to return extra CLI args list for the subprocess."""
        return []

    def _parse_stats_line(self, line):
        """Override to parse [STATS] lines. Return dict with keys:
        queued, processing, created, done, failed, apikey — or None."""
        vals = dict(_re.findall(r'(\w+)=(\d+)', line))
        if not vals:
            return None
        return {
            "queued": int(vals.get('queued', 0)),
            "processing": int(vals.get('processing', 0)),
            "created": int(vals.get('created', 0)),
            "done": int(vals.get('done', 0)),
            "failed": int(vals.get('failed', 0)),
            "apikey": int(vals.get('apikey', 0)),
        }

    def _post_init(self):
        """Override for additional initialization after UI is built."""
        pass

    # ─ Browser mode toggles ─────────────────────────

    def _on_headless_toggle(self):
        if self.headless_var.get():
            self.show_browser_var.set(False)

    def _on_show_toggle(self):
        if self.show_browser_var.get():
            self.headless_var.set(False)

    # ─ Stats ─────────────────────────────────────────

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

    # ─ Results ───────────────────────────────────────

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
            except:
                pass

    # ─ Start / Stop ─────────────────────────────────

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
            args = [sys.executable, os.path.join(FARM_DIR, self.FARM_SCRIPT)]
            args.extend(self._build_args())
            if self.SUPPORTS_COUNT_CONCURRENCY:
                args.extend(["--count", self.count_var.get()])
                args.extend(["--concurrency", str(self.concurrency_var.get())])

            if self.show_browser_var.get():
                args.append("--show")

            print(f"[GUI] \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550")
            print(f"[GUI] {self.TAB_TITLE} Starting")
            print(f"[GUI] Target accounts: {self.count_var.get()}")
            print(f"[GUI] Browser concurrency: {self.concurrency_var.get()}")
            print(f"[GUI] Browser mode: {'visible' if self.show_browser_var.get() else 'headless'}")
            print(f"[GUI] \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n")

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
            print(f"\n[GUI] \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550")
            print("[GUI] Done.")
            print(f"[GUI] \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550")
            self.load_results()
        except Exception as e:
            print(f"\n[GUI] Error: {e}")
        finally:
            sys.stdout = old_stdout
            self.running = False
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def _on_stats_received(self):
        """Hook called when a [STATS] line is received. Override in subclass."""
        pass
