class AlibabaTab(ttk.Frame):
    """Tab 3: Alibaba Cloud Farm — full GUI with monitoring."""

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
        return {"ram_gb": ram_total, "cpu_cores": cpu_cores,
                "cpu_physical": cpu_physical, "recommended": recommended}
