"""
gui/app.py — Main FarmGUI application (modular version).

Replaces farm_gui.py's FarmGUI class. Uses core.registry to build
the Notebook tab system dynamically from registered farm tabs.

Usage:
    python -m gui.app
    # or
    python gui/app.py
"""

import sys
import os
import tkinter as tk
from tkinter import ttk

# ─ Path setup ─────────────────────────────────────
FARM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if FARM_DIR not in sys.path:
    sys.path.insert(0, FARM_DIR)

# ─ Colors (shared) ─────────────────────────────────
BG_DARK = "#1e1e2e"
BG_PANEL = "#2a2a3c"
BG_INPUT = "#363649"
FG_MAIN = "#cdd6f4"
FG_DIM = "#7f7f9f"
ACCENT = "#89b4fa"
ACCENT_GREEN = "#a6e3a1"
ACCENT_RED = "#f38ba8"
ACCENT_YELLOW = "#f9e2af"

# ─ Load .env if available ─────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─ Import registry ────────────────────────────────
from core.registry import FarmRegistry


class FarmGUI(tk.Tk):
    """Main GUI window with tab system built from registry.

    Tabs are registered in core/registry.py via FarmRegistry.
    To add a new tab:
      1. Create tab class inheriting BaseFarmTab in gui/tabs.py
      2. Register it in FarmRegistry.auto_discover() or manually
      3. No changes needed here.
    """

    def __init__(self, registry: FarmRegistry = None):
        super().__init__()
        self.title("Alibaba Cloud Farm — Desktop")
        self.configure(bg=BG_DARK)

        # ─ Fullscreen launch ─
        self.state("zoomed")  # Windows: maximized fullscreen
        self.minsize(1024, 700)

        # ─ Registry ─
        self.registry = registry or FarmRegistry.default()

        # ─ Style ─
        self._setup_style()

        # ─ Header ─
        header = tk.Frame(self, bg=BG_DARK, height=60)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="\U0001f5a5  ALIBABA CLOUD FARM",
            font=("Segoe UI", 20, "bold"),
            bg=BG_DARK,
            fg=ACCENT,
        ).pack(side=tk.LEFT, padx=25, pady=12)

        # ─ Notebook ─
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        # ─ Build tabs from registry ─
        self.tabs = {}
        for entry in self.registry.entries():
            try:
                tab = entry.cls(self.notebook)
                self.notebook.add(
                    tab,
                    text=f"  {entry.icon}  {entry.label}  ",
                )
                self.tabs[entry.label] = tab
            except Exception as e:
                print(f"[GUI] Failed to build tab {entry.label}: {e}")

        # ─ Footer ─
        tk.Label(
            self,
            text=f"\u00a9 2026 Alibaba Cloud Farm | {FARM_DIR}",
            bg=BG_DARK,
            fg=FG_DIM,
            font=("Segoe UI", 9),
        ).pack(side=tk.BOTTOM, pady=5)

    def _setup_style(self):
        """Configure ttk styles for dark theme."""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG_DARK, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=BG_PANEL,
            foreground=FG_DIM,
            padding=[20, 10],
            font=("Segoe UI", 11),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", BG_INPUT)],
            foreground=[("selected", ACCENT)],
        )
        style.configure("TFrame", background=BG_DARK)
        style.configure(
            "Treeview",
            background=BG_INPUT,
            foreground=FG_MAIN,
            fieldbackground=BG_INPUT,
            font=("Segoe UI", 9),
            rowheight=24,
        )
        style.configure(
            "Treeview.Heading",
            background=BG_PANEL,
            foreground=ACCENT,
            font=("Segoe UI", 10, "bold"),
        )


def main():
    """Entry point for the GUI application."""
    registry = FarmRegistry.default()
    app = FarmGUI(registry=registry)
    app.mainloop()


if __name__ == "__main__":
    main()
