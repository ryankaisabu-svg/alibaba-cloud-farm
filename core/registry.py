"""
core/registry.py — Farm tab registry and configuration system.

Provides a declarative registry for farm tabs. Each tab registers its
class, display label, icon, and order. The main GUI then iterates the
registry to build the Notebook dynamically.

Usage in farm_gui.py (or new entry point):

    from core.registry import FarmRegistry

    registry = FarmRegistry()
    registry.register(XiaomiTab, label="Xiaomi MiMo Farm", icon="📱")
    registry.register(EmailFarmTab, label="Email Farm", icon="📧")
    ...

    # Or auto-discover from gui.tabs:
    registry = FarmRegistry.auto_discover()

    # In FarmGUI.__init__:
    for entry in registry.entries:
        tab = entry.cls(self.notebook)
        self.notebook.add(tab, text=f"  {entry.icon}  {entry.label}  ")

Adding a new farm tab requires only:
  1. Create tab class inheriting BaseFarmTab in gui/tabs.py
  2. Register it here in TAB_REGISTRY (or via auto_discover)
No changes needed in FarmGUI.
"""

import importlib
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Type

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TabEntry:
    """Registry entry for a single farm tab.

    Attributes:
        cls:      Tab class (subclass of BaseFarmTab).
        label:    Display label in the Notebook tab bar.
        icon:     Emoji icon for the tab bar.
        order:    Sort priority (lower = appears first). Default 100.
        enabled:  If False, tab is registered but skipped during build.
    """

    cls: Type
    label: str
    icon: str = "🔧"
    order: int = 100
    enabled: bool = True


class FarmRegistry:
    """Declarative registry for farm tabs.

    Tabs can be registered programmatically or auto-discovered from gui.tabs.
    The registry is iterable and sorted by order.
    """

    def __init__(self):
        self._entries: List[TabEntry] = []

    def register(
        self,
        cls: Type,
        label: str,
        icon: str = "🔧",
        order: int = 100,
        enabled: bool = True,
    ):
        """Register a tab class.

        Args:
            cls:     Tab class (must inherit BaseFarmTab).
            label:   Display label in Notebook tab bar.
            icon:    Emoji icon prefix.
            order:   Sort priority (lower appears first).
            enabled: If False, tab is skipped during build.
        """
        entry = TabEntry(cls=cls, label=label, icon=icon, order=order, enabled=enabled)
        self._entries.append(entry)
        logger.debug("Registered tab: %s (order=%d)", label, order)

    def entries(self) -> List[TabEntry]:
        """Return all enabled entries sorted by order."""
        return sorted(
            [e for e in self._entries if e.enabled],
            key=lambda e: e.order,
        )

    def all_entries(self) -> List[TabEntry]:
        """Return all entries (including disabled), sorted by order."""
        return sorted(self._entries, key=lambda e: e.order)

    def __len__(self):
        return len(self.entries())

    def __iter__(self):
        return iter(self.entries())

    @classmethod
    def auto_discover(cls) -> "FarmRegistry":
        registry = cls()

        try:
            tabs_mod = importlib.import_module("gui.tabs")
        except ImportError as e:
            logger.error("Cannot import gui.tabs for auto-discovery: %s", e)
            return registry

        # Tab class name -> (icon, order) mapping
        _TAB_META = {
            "XiaomiTab":      ("📱", 10),
            "EmailFarmTab":   ("📧", 20),
            "AlibabaTab":     ("☁", 30),
            "QwenCloudTab":   ("🌐", 40),
            "MistralTab":     ("🎯", 50),
            "SiliconFlowTab": ("🤖", 55),
            "WaveSpeedTab":   ("🌊", 56),
            "GensparkTab":    ("✨", 57),
            "KiroHarvesterTab":("🔑", 60),
        }

        for class_name, (icon, order) in _TAB_META.items():
            tab_cls = getattr(tabs_mod, class_name, None)
            if tab_cls is None:
                logger.warning("Tab class %s not found in gui.tabs", class_name)
                continue

            # Use TAB_TITLE as label, strip " Farm" suffix for tab bar
            label = getattr(tab_cls, "TAB_TITLE", class_name)
            if label.endswith(" Farm"):
                label = label[: -len(" Farm")]

            registry.register(
                cls=tab_cls,
                label=label,
                icon=icon,
                order=order,
                enabled=True,
            )

        return registry

        # Tab class name -> (icon, order) mapping
        _TAB_META = {
            "XiaomiTab":      ("\U0001f4f1", 10),
            "EmailFarmTab":   ("\U0001f4e7", 20),
            "AlibabaTab":     ("\u2601", 30),
            "QwenCloudTab":   ("\U0001f310", 40),
            "MistralTab":     ("\U0001f3af", 50),
            "SiliconFlowTab": ("\U0001f916", 55),
            "WaveSpeedTab":   ("\U0001f30a", 56),
            "GensparkTab":    ("\u2728", 57),
        }

        for class_name, (icon, order) in _TAB_META.items():
            tab_cls = getattr(tabs_mod, class_name, None)
            if tab_cls is None:
                logger.warning("Tab class %s not found in gui.tabs", class_name)
                continue

            # Use TAB_TITLE as label, strip " Farm" suffix for tab bar
            label = getattr(tab_cls, "TAB_TITLE", class_name)
            # Remove trailing " Farm" for cleaner tab bar text
            if label.endswith(" Farm"):
                label = label[: -len(" Farm")]

            registry.register(
                cls=tab_cls,
                label=label,
                icon=icon,
                order=order,
                enabled=True,
            )


        # --- KIRO HARVESTER INJECT ---
        try:
            tab_kiro_cls = getattr(tabs_mod, "KiroHarvesterTab", None)
            if tab_kiro_cls:
                registry.register(
                    cls=tab_kiro_cls,
                    label="Kiro Harvester Desktop",
                    icon="🔑",
                    order=60,
                    enabled=True,
                )
        except Exception:
            pass
        # -----------------------------
        return registry

    @classmethod
    def default(cls) -> "FarmRegistry":
        """Return the default registry with all 5 farm tabs.

        This is the standard configuration used by FarmGUI.
        Equivalent to auto_discover() but explicit.
        """
        return cls.auto_discover()
