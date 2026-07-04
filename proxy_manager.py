"""Proxy Manager for WebShare.io residential proxies.

Format: host:port:username:password (one per line)
Usage:
    from proxy_manager import get_proxy, ProxyManager
    proxy = get_proxy(0)          # get first proxy dict
    pm = ProxyManager("path/to/proxies.txt")
    proxy = pm.get(index=5)       # get 6th proxy
    proxy = pm.random()           # random proxy
    url = pm.url(index=0)         # -> "http://user:pass@host:port"
"""

import os
import random
from pathlib import Path

# Default proxy list path
DEFAULT_PROXY_FILE = Path(__file__).parent / "data" / "wavespeed" / "webshare_proxies.txt"


class ProxyManager:
    """Manages rotating residential proxies from a text file.

    File format (one per line):
        p.webshare.io:80:pckxkdbx-1:8ediniy4aouv

    Each line: host:port:username:password
    """

    def __init__(self, filepath=None):
        self.filepath = Path(filepath) if filepath else DEFAULT_PROXY_FILE
        self.proxies = []
        self._load()

    def _load(self):
        """Load proxies from file."""
        self.proxies = []
        if not self.filepath.exists():
            return
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "|" in line:
                    # Handle format: 1|p.webshare.io:80:user:pass
                    parts = line.split("|")
                    if len(parts) >= 2:
                        line = parts[1]
                if ":" in line:
                    parts = line.split(":")
                    if len(parts) >= 4:
                        self.proxies.append({
                            "host": parts[0],
                            "port": int(parts[1]),
                            "username": parts[2],
                            "password": parts[3],
                        })

    def reload(self):
        """Reload proxy list from file."""
        self._load()

    def get(self, index=0):
        """Get proxy by index. Returns None if out of range."""
        if not self.proxies:
            return None
        index = index % len(self.proxies)  # wrap around
        return self.proxies[index]

    def random(self):
        """Get a random proxy."""
        if not self.proxies:
            return None
        return random.choice(self.proxies)

    def url(self, index=0, protocol="http"):
        """Get proxy URL for patchright/playwright.

        Args:
            index: Proxy index (0-based)
            protocol: 'http' or 'socks5'

        Returns:
            URL like 'http://user:pass@host:port' or None
        """
        proxy = self.get(index)
        if not proxy:
            return None
        return (
            f"{protocol}://{proxy['username']}:{proxy['password']}"
            f"@{proxy['host']}:{proxy['port']}"
        )

    def server(self, index=0):
        """Get server dict for patchright's `proxy` kwarg.

        Returns:
            {'server': host:port, 'username': ..., 'password': ...}
        """
        proxy = self.get(index)
        if not proxy:
            return None
        return {
            "server": f"{proxy['host']}:{proxy['port']}",
            "username": proxy["username"],
            "password": proxy["password"],
        }

    @property
    def count(self):
        return len(self.proxies)

    @property
    def is_loaded(self):
        return len(self.proxies) > 0


def get_proxy(index=0):
    """Quick helper: get proxy dict by index."""
    pm = ProxyManager()
    return pm.get(index)


def get_proxy_url(index=0, protocol="http"):
    """Quick helper: get proxy URL string."""
    pm = ProxyManager()
    return pm.url(index=index, protocol=protocol)


if __name__ == "__main__":
    # Test
    pm = ProxyManager()
    print(f"Loaded {pm.count} proxies")
    if pm.is_loaded:
        p = pm.get(0)
        print(f"First: {p['host']}:{p['port']} ({p['username']})")
        print(f"URL: {pm.url(0)}")
        print(f"Server: {pm.server(0)}")
        r = pm.random()
        print(f"Random: {r['host']}:{r['port']} ({r['username']})")
