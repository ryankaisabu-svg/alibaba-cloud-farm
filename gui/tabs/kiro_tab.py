
import os
import sys
import tkinter as tk
from tkinter import ttk
import subprocess
import json

class KiroTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.harvester_process = None
        self.script_path = r"E:\WEB\alibaba-cloud-farm\kiro_harvester_standalone.py"
        self.db_path = r"E:\WEB\alibaba-cloud-farm\kiro_database_farm.json"
        
        # Build UI layout
        control_frame = ttk.LabelFrame(self, text="Harvester Daemon Control (Entra ID)", padding=10)
        control_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(control_frame, text="Sistem ini membaca kredensial secara pasif saat Anda login ke Kiro IDE.").pack(anchor=tk.W, pady=(0, 5))
        
        self.btn_toggle = ttk.Button(control_frame, text="▶ Start Harvester Daemon", command=self.toggle_daemon, cursor="hand2")
        self.btn_toggle.pack(side=tk.LEFT, padx=5)
        
        self.btn_refresh = ttk.Button(control_frame, text="↻ Refresh DB", command=self._refresh_db_stats, cursor="hand2")
        self.btn_refresh.pack(side=tk.LEFT, padx=5)
        
        self.lbl_status = ttk.Label(control_frame, text="Status: OFF", foreground="red")
        self.lbl_status.pack(side=tk.RIGHT, padx=10)
        
        stats_frame = ttk.LabelFrame(self, text="Kiro Database Farm", padding=10)
        stats_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.lbl_db_info = ttk.Label(stats_frame, text="Membaca JSON...", font=("Courier", 10))
        self.lbl_db_info.pack(anchor=tk.W)
        
        # Bottom Console
        console_frame = ttk.LabelFrame(self, text="Instruksi & Log", padding=10)
        console_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.txt_console = tk.Text(console_frame, height=15, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.txt_console.pack(fill=tk.BOTH, expand=True)
        
        self._log("[*] Harvester Standalone siap menyala di background.\n")
        self._refresh_db_stats()

    def _log(self, msg):
        self.txt_console.insert(tk.END, msg)
        self.txt_console.see(tk.END)

    def _refresh_db_stats(self):
        if not os.path.exists(self.db_path):
            self.lbl_db_info.config(text=f"Database kosong (File belum terbentuk)")
            return
            
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.lbl_db_info.config(text=f"Total: {len(data)} Akun Tercatat secara aman.\n-> File: {self.db_path}")
            self._log("[+] Database Stats di-refresh.\n")
        except Exception as e:
            self.lbl_db_info.config(text=f"Error membaca DB: {e}")

    def toggle_daemon(self):
        if self.harvester_process is None:
            # START
            self._log("\n[+] Menyalakan process di background (Polling 50msec)...\n")
            self._log("[*] STATUS DAEMON: ONLINE\n")
            self._log("[*] SEKARANG, Anda cukup log out lalu log in kembali berulang-ulang di software Kiro IDE.\n")
            self._log("[*] Program ini akan mendeteksinya secara ajaib di layar belakang.\n")
             
            try:
                self.harvester_process = subprocess.Popen(
                    [sys.executable, self.script_path],
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                self.btn_toggle.config(text="■ Stop Harvester Daemon")
                self.lbl_status.config(text="Status: ONLINE (Monitoring)", foreground="green")
            except Exception as e:
                self._log(f"[-] Gagal Start: {e}\n")
        else:
            # STOP
            try:
                self.harvester_process.terminate()
            except:
                pass
            self.harvester_process = None
            self.btn_toggle.config(text="▶ Start Harvester Daemon")
            self.lbl_status.config(text="Status: OFF", foreground="red")
            self._log("\n[-] Proses Harvester telah dimatikan secara paksa.\n")
