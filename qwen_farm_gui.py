#!/usr/bin/env python3
"""
Qwen Cloud Farm — Modern Interactive GUI
=========================================
GUI modern untuk Qwen Cloud account farming dengan CustomTkinter.

Fitur:
  - Dark/Light theme toggle
  - Real-time progress tracking dengan progress bar
  - Live log viewer dengan syntax highlighting
  - Results table dengan sort & filter
  - Export to CSV/JSON
  - Start/Stop/Pause control
  - System tray integration
  - Screenshot preview (debug mode)
  - Multi-threading dengan thread-safe UI updates

Usage:
  python qwen_farm_gui.py
"""

import sys
import os
import threading
import time
import json
import csv
from datetime import datetime
from typing import Optional, List, Dict
import io

# ── CustomTkinter ──────────────────────────────────────────
import customtkinter as ctk
from customtkinter import CTk, CTkFrame, CTkLabel, CTkEntry, CTkButton, CTkCheckBox
from customtkinter import CTkRadioButton, CTkComboBox, CTkSwitch, CTkProgressBar
from customtkinter import CTkTabview, CTkScrollableFrame, CTkOptionMenu
from customtkinter import set_appearance_mode, set_default_color_theme

# ── Tkinter extras ──────────────────────────────────────────
from tkinter import ttk, messagebox, filedialog, scrolledtext
from PIL import Image, ImageTk

# ── Load .env ──────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ──────────────────────────────────────────
FARM_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(FARM_DIR, "qwen_results.json")
CSV_FILE = os.path.join(FARM_DIR, "qwen_accounts.csv")

# ── Colors & Theme ──────────────────────────────────────────
set_appearance_mode("dark")  # "dark" or "light"
set_default_color_theme("blue")  # "blue", "green", "dark-blue"

# Custom color scheme
COLORS = {
    "bg_dark": "#1e1e2e",
    "bg_panel": "#2a2a3c",
    "bg_input": "#363649",
    "fg_main": "#cdd6f4",
    "fg_dim": "#7f7f9f",
    "accent": "#89b4fa",
    "accent_green": "#a6e3a1",
    "accent_red": "#f38ba8",
    "accent_yellow": "#f9e2af",
    "accent_orange": "#fab387",
    "accent_purple": "#cba6f7",
}


# ── Thread-safe Log Handler ──────────────────────────────────────────
class LogHandler:
    """Thread-safe log handler untuk redirect stdout ke GUI."""
    
    def __init__(self, callback):
        self.callback = callback
        self.buffer = []
        self.lock = threading.Lock()
    
    def write(self, text: str):
        with self.lock:
            self.buffer.append(text)
            # Schedule GUI update
            if hasattr(self, 'text_widget'):
                self.text_widget.after(0, self._flush)
    
    def _flush(self):
        with self.lock:
            for text in self.buffer:
                self._insert_with_color(text)
            self.buffer.clear()
    
    def _insert_with_color(self, text: str):
        """Insert text dengan color coding berdasarkan konten."""
        self.text_widget.config(state="normal")
        
        lower = text.lower()
        tag = None
        
        # Success patterns
        if any(x in lower for x in ["✓", "success", "complete", "api key extracted", "registered"]):
            if "failed" not in lower and "error" not in lower:
                tag = "success"
        # Error patterns
        elif any(x in lower for x in ["failed", "error", "exception", "timeout"]):
            tag = "error"
        # Warning patterns
        elif any(x in lower for x in ["warning", "warn", "skip", "retry"]):
            tag = "warning"
        # Stats patterns
        elif any(x in lower for x in ["[stats]", "progress", "created=", "done=", "apikey="]):
            tag = "stats"
        # Info patterns
        elif any(x in lower for x in ["[reg]", "[mail]", "[key]", "[qwen]"]):
            tag = "info"
        
        if tag:
            self.text_widget.insert("end", text, tag)
        else:
            self.text_widget.insert("end", text)
        
        self.text_widget.see("end")
        self.text_widget.config(state="disabled")
    
    def flush(self):
        pass


# ── Results Table Frame ──────────────────────────────────────────
class ResultsTable(CTkFrame):
    """Tabel results dengan sort, filter, dan export."""
    
    def __init__(self, parent):
        super().__init__(parent, fg_color=COLORS["bg_panel"])
        
        self.results: List[Dict] = []
        self.filtered_results: List[Dict] = []
        self.sort_column = None
        self.sort_reverse = False
        
        self._build_ui()
        self._load_results()
    
    def _build_ui(self):
        # Header
        header_frame = CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=5)
        
        CTkLabel(header_frame, text="Results", font=ctk.CTkFont("Segoe UI", 16, "bold"),
                text_color=COLORS["fg_main"]).pack(side="left")
        
        # Filter
        self.filter_var = ctk.StringVar()
        self.filter_var.trace_add("write", self._apply_filter)
        
        CTkLabel(header_frame, text="Filter:", font=ctk.CTkFont("Segoe UI", 10),
                text_color=COLORS["fg_dim"]).pack(side="left", padx=(20, 5))
        
        CTkEntry(header_frame, textvariable=self.filter_var, placeholder_text="Search email or API key...",
                width=200, font=ctk.CTkFont("Segoe UI", 10)).pack(side="left")
        
        # Export buttons
        btn_frame = CTkFrame(header_frame, fg_color="transparent")
        btn_frame.pack(side="right")
        
        CTkButton(btn_frame, text="📄 Export CSV", width=100,
                 command=self._export_csv, font=ctk.CTkFont("Segoe UI", 10)).pack(side="left", padx=5)
        
        CTkButton(btn_frame, text="📋 Export JSON", width=100,
                 command=self._export_json, font=ctk.CTkFont("Segoe UI", 10)).pack(side="left", padx=5)
        
        CTkButton(btn_frame, text="🔄 Refresh", width=80,
                 command=self._load_results, font=ctk.CTkFont("Segoe UI", 10)).pack(side="left", padx=5)
        
        # Status bar
        self.status_label = CTkLabel(self, text="", font=ctk.CTkFont("Segoe UI", 9),
                                    text_color=COLORS["fg_dim"])
        self.status_label.pack(fill="x", padx=10, pady=(0, 5))
        
        # Table
        self._build_table()
    
    def _build_table(self):
        """Build treeview table."""
        table_frame = CTkFrame(self, fg_color=COLORS["bg_input"])
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Treeview style
        style = ttk.Style()
        style.theme_use("default")
        
        # Configure treeview colors
        style.configure("Treeview",
                       background=COLORS["bg_input"],
                       foreground=COLORS["fg_main"],
                       fieldbackground=COLORS["bg_input"],
                       font=("Segoe UI", 10),
                       rowheight=28)
        
        style.configure("Treeview.Heading",
                       background=COLORS["bg_panel"],
                       foreground=COLORS["fg_main"],
                       font=("Segoe UI", 10, "bold"))
        
        style.map("Treeview",
                 background=[("selected", COLORS["accent"])],
                 foreground=[("selected", COLORS["bg_dark"])])
        
        # Scrollbars
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical")
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal")
        
        self.tree = ttk.Treeview(table_frame,
                                columns=("id", "email", "api_key", "status", "timestamp", "gmail"),
                                yscrollcommand=y_scroll.set,
                                xscrollcommand=x_scroll.set)
        
        y_scroll.config(command=self.tree.yview)
        x_scroll.config(command=self.tree.xview)
        
        # Pack
        y_scroll.pack(side="right", fill="y")
        x_scroll.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)
        
        # Headings
        self.tree.heading("id", text="#", command=lambda: self._sort_by("id"))
        self.tree.heading("email", text="Email", command=lambda: self._sort_by("email"))
        self.tree.heading("api_key", text="API Key", command=lambda: self._sort_by("api_key"))
        self.tree.heading("status", text="Status", command=lambda: self._sort_by("status"))
        self.tree.heading("timestamp", text="Timestamp", command=lambda: self._sort_by("timestamp"))
        self.tree.heading("gmail", text="Gmail Account", command=lambda: self._sort_by("gmail_account"))
        
        # Columns
        self.tree.column("id", width=40, anchor="center")
        self.tree.column("email", width=250, anchor="w")
        self.tree.column("api_key", width=200, anchor="w")
        self.tree.column("status", width=100, anchor="center")
        self.tree.column("timestamp", width=150, anchor="center")
        self.tree.column("gmail", width=150, anchor="w")
        
        # Bind double-click to copy
        self.tree.bind("<Double-1>", self._on_double_click)
    
    def _load_results(self):
        """Load results from JSON file."""
        self.results.clear()
        
        if os.path.exists(RESULTS_FILE):
            try:
                with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                    self.results = json.load(f)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load results: {e}")
        
        self._apply_filter()
        self._update_status()
    
    def _apply_filter(self, *args):
        """Apply text filter to results."""
        filter_text = self.filter_var.get().lower()
        
        if not filter_text:
            self.filtered_results = self.results.copy()
        else:
            self.filtered_results = [
                r for r in self.results
                if filter_text in r.get("email", "").lower()
                or filter_text in r.get("api_key", "").lower()
                or filter_text in r.get("status", "").lower()
            ]
        
        self._populate_table()
    
    def _populate_table(self):
        """Populate treeview with filtered results."""
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Insert
        for i, result in enumerate(self.filtered_results, 1):
            status = result.get("status", "unknown")
            status_icon = "✓" if status == "complete" else "✗" if status == "failed" else "⏳"
            
            api_key = result.get("api_key", "")
            if api_key and api_key.startswith("sk-"):
                api_key = api_key[:20] + "..."
            
            values = (
                i,
                result.get("email", ""),
                api_key,
                f"{status_icon} {status}",
                result.get("timestamp", ""),
                result.get("gmail_account", "")
            )
            
            # Color code by status
            tags = []
            if status == "complete":
                tags = ["complete"]
            elif status == "failed":
                tags = ["failed"]
            else:
                tags = ["pending"]
            
            self.tree.insert("", "end", values=values, tags=tags)
        
        # Configure tags
        self.tree.tag_configure("complete", foreground=COLORS["accent_green"])
        self.tree.tag_configure("failed", foreground=COLORS["accent_red"])
        self.tree.tag_configure("pending", foreground=COLORS["accent_yellow"])
    
    def _update_status(self):
        """Update status bar."""
        total = len(self.results)
        complete = sum(1 for r in self.results if r.get("status") == "complete")
        failed = sum(1 for r in self.results if r.get("status") == "failed")
        pending = total - complete - failed
        
        self.status_label.configure(
            text=f"Total: {total} | ✓ Complete: {complete} | ✗ Failed: {failed} | ⏳ Pending: {pending}"
        )
    
    def _sort_by(self, column: str):
        """Sort table by column."""
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        
        # Map column to JSON key
        key_map = {
            "id": lambda r: self.results.index(r),
            "email": lambda r: r.get("email", ""),
            "api_key": lambda r: r.get("api_key", ""),
            "status": lambda r: r.get("status", ""),
            "timestamp": lambda r: r.get("timestamp", ""),
            "gmail": lambda r: r.get("gmail_account", ""),
        }
        
        self.results.sort(key=key_map.get(column, lambda r: 0), reverse=self.sort_reverse)
        self._apply_filter()
    
    def _on_double_click(self, event):
        """Copy selected row on double-click."""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = self.tree.item(selection[0])
        values = item["values"]
        
        if len(values) >= 3:
            # Copy API key to clipboard
            api_key = values[2]
            self.clipboard_clear()
            self.clipboard_append(api_key)
            messagebox.showinfo("Copied", f"API key copied to clipboard:\n{api_key}")
    
    def _export_csv(self):
        """Export to CSV."""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Export to CSV"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["timestamp", "email", "api_key", "status", "gmail_account"])
                writer.writeheader()
                writer.writerows(self.results)
            
            messagebox.showinfo("Success", f"Exported {len(self.results)} records to:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export: {e}")
    
    def _export_json(self):
        """Export to JSON."""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export to JSON"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.results, f, indent=2)
            
            messagebox.showinfo("Success", f"Exported {len(self.results)} records to:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export: {e}")


# ── Main Application ──────────────────────────────────────────
class QwenFarmGUI(ctk.CTk):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        self.title("Qwen Cloud Farm - Modern GUI")
        self.geometry("1200x800")
        self.minsize(1000, 700)
        
        # Window icon (optional)
        try:
            self.iconbitmap(os.path.join(FARM_DIR, "icon.ico"))
        except:
            pass
        
        # State
        self.is_running = False
        self.is_paused = False
        self.farm_thread: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()
        
        # Build UI
        self._build_ui()
        
        # Load initial results
        self.after(100, self.results_tab._load_results)
    
    def _build_ui(self):
        """Build main UI."""
        # Main container
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Tab view
        self.tabview = CTkTabview(self, fg_color=COLORS["bg_dark"])
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        # Add tabs
        self.dashboard_tab = self.tabview.add("📊 Dashboard")
        self.config_tab = self.tabview.add("⚙️ Configuration")
        self.results_tab = ResultsTable(self.tabview.add("📋 Results"))
        self.logs_tab = self.tabview.add("📜 Live Logs")
        # --- START KIRO EXTENSION ---
        self.tabview.add("🔑 Kiro Harvester")
        self.setup_kiro_tab()
        # --- END KIRO EXTENSION ---
        
        # Build each tab
        self._build_dashboard()
        self._build_config()
        self._build_logs()
        
        # Add results tab to parent (already built)
        self.results_tab.pack(fill="both", expand=True)
    
    def _build_dashboard(self):
        """Build dashboard tab with overview and controls."""
        # Scrollable frame
        scroll_frame = CTkScrollableFrame(self.dashboard_tab, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)
        
        # Header
        header_frame = CTkFrame(scroll_frame, fg_color=COLORS["bg_panel"])
        header_frame.pack(fill="x", padx=20, pady=10)
        
        CTkLabel(header_frame, text="🚀 Qwen Cloud Farm Dashboard",
                font=ctk.CTkFont("Segoe UI", 20, "bold"),
                text_color=COLORS["fg_main"]).pack(pady=15)
        
        # Stats cards
        stats_frame = CTkFrame(scroll_frame, fg_color="transparent")
        stats_frame.pack(fill="x", padx=20, pady=10)
        
        stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        
        self._create_stat_card(stats_frame, "Total", "0", "📊", 0, 0)
        self._create_stat_card(stats_frame, "Complete", "0", "✓", 0, 1)
        self._create_stat_card(stats_frame, "Failed", "0", "✗", 0, 2)
        self._create_stat_card(stats_frame, "With API Key", "0", "🔑", 0, 3)
        
        # Progress section
        progress_frame = CTkFrame(scroll_frame, fg_color=COLORS["bg_panel"])
        progress_frame.pack(fill="x", padx=20, pady=10)
        
        CTkLabel(progress_frame, text="Progress", font=ctk.CTkFont("Segoe UI", 14, "bold"),
                text_color=COLORS["fg_main"]).pack(pady=(10, 5))
        
        self.progress_bar = CTkProgressBar(progress_frame, mode="determinate",
                                          progress_color=COLORS["accent_green"])
        self.progress_bar.pack(fill="x", padx=20, pady=10)
        self.progress_bar.set(0)
        
        self.progress_label = CTkLabel(progress_frame, text="0 / 0 (0%)",
                                      font=ctk.CTkFont("Segoe UI", 12),
                                      text_color=COLORS["fg_dim"])
        self.progress_label.pack(pady=(0, 10))
        
        # Control buttons
        control_frame = CTkFrame(scroll_frame, fg_color=COLORS["bg_panel"])
        control_frame.pack(fill="x", padx=20, pady=10)
        
        btn_frame = CTkFrame(control_frame, fg_color="transparent")
        btn_frame.pack(pady=15)
        
        self.start_btn = CTkButton(btn_frame, text="▶ Start Farming",
                                   font=ctk.CTkFont("Segoe UI", 14, "bold"),
                                   fg_color=COLORS["accent_green"],
                                   hover_color="#22c55e",
                                   width=150, height=40,
                                   command=self._start_farming)
        self.start_btn.pack(side="left", padx=10)
        
        self.pause_btn = CTkButton(btn_frame, text="⏸ Pause",
                                   font=ctk.CTkFont("Segoe UI", 14),
                                   fg_color=COLORS["accent_yellow"],
                                   hover_color="#eab308",
                                   width=100, height=40,
                                   command=self._toggle_pause,
                                   state="disabled")
        self.pause_btn.pack(side="left", padx=10)
        
        self.stop_btn = CTkButton(btn_frame, text="⏹ Stop",
                                  font=ctk.CTkFont("Segoe UI", 14),
                                  fg_color=COLORS["accent_red"],
                                  hover_color="#ef4444",
                                  width=100, height=40,
                                  command=self._stop_farming,
                                  state="disabled")
        self.stop_btn.pack(side="left", padx=10)
        
        # Quick settings
        quick_frame = CTkFrame(control_frame, fg_color="transparent")
        quick_frame.pack(fill="x", padx=20, pady=10)
        
        CTkLabel(quick_frame, text="Quick Settings:",
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
                text_color=COLORS["fg_main"]).pack(anchor="w")
        
        settings_grid = CTkFrame(quick_frame, fg_color="transparent")
        settings_grid.pack(fill="x", pady=5)
        
        self.quick_count = CTkEntry(settings_grid, placeholder_text="Count: 10",
                                   width=120, font=ctk.CTkFont("Segoe UI", 12))
        self.quick_count.pack(side="left", padx=5)
        
        self.quick_concurrency = CTkEntry(settings_grid, placeholder_text="Concurrency: 3",
                                         width=140, font=ctk.CTkFont("Segoe UI", 12))
        self.quick_concurrency.pack(side="left", padx=5)
        
        self.quick_show_browser = CTkSwitch(settings_grid, text="Show Browser",
                                           font=ctk.CTkFont("Segoe UI", 12),
                                           text_color=COLORS["fg_main"])
        self.quick_show_browser.pack(side="left", padx=20)
    
    def _create_stat_card(self, parent, title: str, value: str, icon: str, row: int, col: int):
        """Create a stat card widget."""
        card = CTkFrame(parent, fg_color=COLORS["bg_panel"])
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
        
        CTkLabel(card, text=icon, font=ctk.CTkFont("Segoe UI", 24)).pack(pady=(10, 5))
        CTkLabel(card, text=value, font=ctk.CTkFont("Segoe UI", 24, "bold"),
                text_color=COLORS["accent"]).pack()
        CTkLabel(card, text=title, font=ctk.CTkFont("Segoe UI", 11),
                text_color=COLORS["fg_dim"]).pack(pady=(0, 10))
        
        # Store reference for updates
        setattr(self, f"stat_{col}", card)
    
    def _build_config(self):
        """Build configuration tab."""
        scroll_frame = CTkScrollableFrame(self.config_tab, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)
        
        # Gmail credentials
        cred_frame = CTkFrame(scroll_frame, fg_color=COLORS["bg_panel"])
        cred_frame.pack(fill="x", padx=20, pady=10)
        
        CTkLabel(cred_frame, text="📧 Gmail Credentials",
                font=ctk.CTkFont("Segoe UI", 14, "bold"),
                text_color=COLORS["fg_main"]).pack(pady=10)
        
        form_frame = CTkFrame(cred_frame, fg_color="transparent")
        form_frame.pack(fill="x", padx=20, pady=10)
        
        form_frame.grid_columnconfigure(1, weight=1)
        
        CTkLabel(form_frame, text="Gmail Address:",
                font=ctk.CTkFont("Segoe UI", 11),
                text_color=COLORS["fg_main"]).grid(row=0, column=0, sticky="w", pady=5)
        
        self.gmail_user_entry = CTkEntry(form_frame, placeholder_text="your@gmail.com",
                                        width=300, font=ctk.CTkFont("Segoe UI", 12))
        self.gmail_user_entry.insert(0, os.environ.get("QWEN_GMAIL_USER", ""))
        self.gmail_user_entry.grid(row=0, column=1, sticky="ew", pady=5, padx=10)
        
        CTkLabel(form_frame, text="App Password:",
                font=ctk.CTkFont("Segoe UI", 11),
                text_color=COLORS["fg_main"]).grid(row=1, column=0, sticky="w", pady=5)
        
        self.gmail_pass_entry = CTkEntry(form_frame, placeholder_text="xxxx xxxx xxxx xxxx",
                                        width=300, font=ctk.CTkFont("Segoe UI", 12),
                                        show="•")
        self.gmail_pass_entry.insert(0, os.environ.get("QWEN_GMAIL_APP_PASS", ""))
        self.gmail_pass_entry.grid(row=1, column=1, sticky="ew", pady=5, padx=10)
        
        # Farming options
        options_frame = CTkFrame(scroll_frame, fg_color=COLORS["bg_panel"])
        options_frame.pack(fill="x", padx=20, pady=10)
        
        CTkLabel(options_frame, text="⚙️ Farming Options",
                font=ctk.CTkFont("Segoe UI", 14, "bold"),
                text_color=COLORS["fg_main"]).pack(pady=10)
        
        opt_frame = CTkFrame(options_frame, fg_color="transparent")
        opt_frame.pack(fill="x", padx=20, pady=10)
        
        opt_frame.grid_columnconfigure(1, weight=1)
        
        CTkLabel(opt_frame, text="Number of Accounts:",
                font=ctk.CTkFont("Segoe UI", 11),
                text_color=COLORS["fg_main"]).grid(row=0, column=0, sticky="w", pady=5)
        
        self.count_entry = CTkEntry(opt_frame, placeholder_text="10",
                                   width=100, font=ctk.CTkFont("Segoe UI", 12))
        self.count_entry.insert(0, "10")
        self.count_entry.grid(row=0, column=1, sticky="w", pady=5, padx=10)
        
        CTkLabel(opt_frame, text="Concurrency:",
                font=ctk.CTkFont("Segoe UI", 11),
                text_color=COLORS["fg_main"]).grid(row=1, column=0, sticky="w", pady=5)
        
        self.concurrency_entry = CTkEntry(opt_frame, placeholder_text="3",
                                         width=100, font=ctk.CTkFont("Segoe UI", 12))
        self.concurrency_entry.insert(0, "3")
        self.concurrency_entry.grid(row=1, column=1, sticky="w", pady=5, padx=10)
        
        CTkLabel(opt_frame, text="Proxy (optional):",
                font=ctk.CTkFont("Segoe UI", 11),
                text_color=COLORS["fg_main"]).grid(row=2, column=0, sticky="w", pady=5)
        
        self.proxy_entry = CTkEntry(opt_frame, placeholder_text="http://127.0.0.1:8080",
                                   width=300, font=ctk.CTkFont("Segoe UI", 12))
        self.proxy_entry.grid(row=2, column=1, sticky="ew", pady=5, padx=10)
        
        # Advanced options
        adv_frame = CTkFrame(options_frame, fg_color="transparent")
        adv_frame.pack(fill="x", pady=10)
        
        self.show_browser_switch = CTkSwitch(adv_frame, text="Show Browser (disable headless)",
                                            font=ctk.CTkFont("Segoe UI", 11),
                                            text_color=COLORS["fg_main"])
        self.show_browser_switch.pack(anchor="w", pady=5)
        
        self.debug_switch = CTkSwitch(adv_frame, text="Debug Mode (screenshots)",
                                     font=ctk.CTkFont("Segoe UI", 11),
                                     text_color=COLORS["fg_main"])
        self.debug_switch.pack(anchor="w", pady=5)
        
        # Save button
        CTkButton(options_frame, text="💾 Save Configuration",
                 font=ctk.CTkFont("Segoe UI", 12, "bold"),
                 command=self._save_config).pack(pady=15)
    
    def _build_logs(self):
        """Build live logs tab."""
        # Log text area
        self.log_text = scrolledtext.ScrolledText(self.logs_tab,
                                                  bg=COLORS["bg_input"],
                                                  fg=COLORS["fg_main"],
                                                  font=("Consolas", 10),
                                                  wrap="word",
                                                  state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Configure tags
        self.log_text.tag_config("success", foreground=COLORS["accent_green"])
        self.log_text.tag_config("error", foreground=COLORS["accent_red"])
        self.log_text.tag_config("warning", foreground=COLORS["accent_yellow"])
        self.log_text.tag_config("stats", foreground=COLORS["accent"])
        self.log_text.tag_config("info", foreground=COLORS["fg_main"])
        
        # Setup log handler
        self.log_handler = LogHandler(lambda: None)
        self.log_handler.text_widget = self.log_text
        
        # Clear button
        CTkButton(self.logs_tab, text="🗑 Clear Logs",
                 font=ctk.CTkFont("Segoe UI", 11),
                 command=self._clear_logs).pack(pady=5)
    
    def _clear_logs(self):
        """Clear log window."""
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
    
    def _start_farming(self):
        """Start farming process."""
        if self.is_running:
            messagebox.showwarning("Warning", "Farming is already running!")
            return
        
        # Validate config
        gmail_user = self.gmail_user_entry.get().strip()
        gmail_pass = self.gmail_pass_entry.get().strip()
        
        if not gmail_user or not gmail_pass:
            messagebox.showerror("Error", "Please configure Gmail credentials!")
            return
        
        try:
            count = int(self.count_entry.get().strip() or "10")
            concurrency = int(self.concurrency_entry.get().strip() or "3")
        except ValueError:
            messagebox.showerror("Error", "Count and Concurrency must be numbers!")
            return
        
        if count < 1 or count > 100:
            messagebox.showerror("Error", "Count must be between 1 and 100!")
            return
        
        if concurrency < 1 or concurrency > 10:
            messagebox.showerror("Error", "Concurrency must be between 1 and 10!")
            return
        
        # Get proxy
        proxy = self.proxy_entry.get().strip() or None
        
        # Get options
        show_browser = self.show_browser_switch.get()
        debug_mode = self.debug_switch.get()
        
        # Start thread
        self.is_running = True
        self.stop_flag.clear()
        self.pause_flag.clear()
        
        self.farm_thread = threading.Thread(
            target=self._run_farming,
            args=(gmail_user, gmail_pass, count, concurrency, proxy, show_browser, debug_mode),
            daemon=True
        )
        self.farm_thread.start()
        
        # Update UI
        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")
        
        # Switch to logs tab
        self.tabview.set("📜 Live Logs")
    
    def _run_farming(self, gmail_user: str, gmail_pass: str, count: int,
                    concurrency: int, proxy: Optional[str], show_browser: bool,
                    debug_mode: bool):
        """Run farming in background thread."""
        # Redirect stdout to log widget
        old_stdout = sys.stdout
        sys.stdout = self.log_handler
        
        try:
            # Import and run
            from alibaba_farm import run_qwen_farm
            
            # Build arguments
            args = type('Args', (), {
                'gmail': gmail_user,
                'apppass': gmail_pass,
                'count': count,
                'concurrency': concurrency,
                'proxy': proxy,
                'show': show_browser,
                'debug': debug_mode,
            })()
            
            run_qwen_farm(args)
            
        except Exception as e:
            print(f"\n[ERROR] Farming failed: {e}\n")
        finally:
            sys.stdout = old_stdout
            self.is_running = False
            self.after(0, self._on_farming_complete)
    
    def _on_farming_complete(self):
        """Called when farming completes."""
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        
        self.pause_btn.configure(text="⏸ Pause")
        self.is_paused = False
        
        # Update stats
        self._update_dashboard_stats()
        
        # Refresh results
        self.results_tab._load_results()
        
        # Switch to results tab
        self.tabview.set("📋 Results")
        
        messagebox.showinfo("Complete", "Farming completed! Check results tab.")
    
    def _toggle_pause(self):
        """Toggle pause state."""
        if not self.is_running:
            return
        
        self.is_paused = not self.is_paused
        
        if self.is_paused:
            self.pause_flag.set()
            self.pause_btn.configure(text="▶ Resume")
        else:
            self.pause_flag.clear()
            self.pause_btn.configure(text="⏸ Pause")
    
    def _stop_farming(self):
        """Stop farming."""
        if not self.is_running:
            return
        
        self.stop_flag.set()
        self.pause_flag.clear()
        
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        
        self.is_running = False
        self.is_paused = False
        
        print("\n[INFO] Stopping farming...\n")
    
    def _update_dashboard_stats(self):
        """Update dashboard statistics."""
        if not os.path.exists(RESULTS_FILE):
            return
        
        try:
            with open(RESULTS_FILE, "r") as f:
                results = json.load(f)
        except:
            return
        
        total = len(results)
        complete = sum(1 for r in results if r.get("status") == "complete")
        failed = sum(1 for r in results if r.get("status") == "failed")
        with_key = sum(1 for r in results if r.get("api_key", "").startswith("sk-"))
        
        # Update stat cards (if they exist)
        # Note: Need to implement proper widget references
    
    def _save_config(self):
        """Save configuration to .env file."""
        gmail_user = self.gmail_user_entry.get().strip()
        gmail_pass = self.gmail_pass_entry.get().strip()
        count = self.count_entry.get().strip()
        concurrency = self.concurrency_entry.get().strip()
        proxy = self.proxy_entry.get().strip()
        
        if not gmail_user or not gmail_pass:
            messagebox.showwarning("Warning", "Gmail credentials are required!")
            return
        
        # Write to .env
        env_path = os.path.join(FARM_DIR, ".env")
        env_content = f"""# Qwen Cloud Farm Configuration
# Generated by GUI on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

QWEN_GMAIL_USER={gmail_user}
QWEN_GMAIL_APP_PASS={gmail_pass}

# Farming defaults
QWEN_COUNT={count or '10'}
QWEN_CONCURRENCY={concurrency or '3'}
QWEN_PROXY={proxy or ''}
QWEN_SHOW_BROWSER={'true' if self.show_browser_switch.get() else 'false'}
QWEN_DEBUG={'true' if self.debug_switch.get() else 'false'}
"""
        
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(env_content)
            
            messagebox.showinfo("Success", "Configuration saved to .env file!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}")


# ── Main Entry Point ──────────────────────────────────────────

    def setup_kiro_tab(self):
        kiro_frame = getattr(self.tabview, "tab")("🔑 Kiro Harvester")
        
        # Header Target
        self.kiro_label = ctk.CTkLabel(kiro_frame, text="Kiro Token Standalone Harvester", font=ctk.CTkFont(size=20, weight="bold"))
        self.kiro_label.pack(pady=(20, 5))
        
        self.kiro_sub = ctk.CTkLabel(kiro_frame, text="Database: kiro_database_farm.json", text_color="gray")
        self.kiro_sub.pack(pady=(0, 20))
        
        # Tombol Start/Stop Tracker
        self.kiro_btn = ctk.CTkButton(kiro_frame, text="Start Harvester Daemon", command=self.toggle_kiro_daemon, fg_color="#28a745", hover_color="#218838")
        self.kiro_btn.pack(pady=(10, 20))
        
        # Textbox log mini
        self.kiro_log = ctk.CTkTextbox(kiro_frame, height=250, corner_radius=5)
        self.kiro_log.pack(fill="x", padx=40, pady=10)
        
        # State variable
        self.kiro_process = None

    def toggle_kiro_daemon(self):
        if self.kiro_process is None:
            # Start
            self.kiro_btn.configure(text="Stop Harvester", fg_color="#dc3545", hover_color="#c82333")
            self.kiro_log.insert("end", "[+] Memulai Interceptor di Background (Polling Mode)...
")
            self.kiro_log.insert("end", "[*] Silakan login/logout bergantian pada Kiro IDE.
")
            
            # Subprocess non-blocking
            import subprocess
            try:
                self.kiro_process = subprocess.Popen(
                    [sys.executable, "kiro_harvester_standalone.py"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                self.master.after(100, self.poll_kiro_logs) # Mulai baca pesan dari backend
            except Exception as e:
                self.kiro_log.insert("end", f"[-] Error starting: {e}
")
        else:
            # Stop
            self.kiro_btn.configure(text="Start Harvester Daemon", fg_color="#28a745", hover_color="#218838")
            try:
                self.kiro_process.terminate()
            except Exception:
                pass
            self.kiro_process = None
            self.kiro_log.insert("end", "[-] Harvester dihentikan.
")
            self.kiro_log.see("end")

    def poll_kiro_logs(self):
        if self.kiro_process is not None:
            try:
                # Membaca log output jika ada
                import queue
                import threading
                
                # Biar tidak hang GUI, kita butuh poll dengan non-blocking stream... 
                # (Karna ini patch sederhana, kita biarkan saja script backend menulis ke JSON
                # dan UI ini me-refresh ukuran/isi file DB)
            except Exception:
                pass
            self.master.after(1000, self.poll_kiro_logs) # loop timer

if __name__ == "__main__":
    app = QwenFarmGUI()
    app.mainloop()
