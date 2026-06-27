#!/usr/bin/env python3
"""
VPN/Proxy Auto-Detector
Deteksi VPN/proxy aktif di sistem untuk dipakai oleh farm_headless.py

Cek:
  1. Network interface (TUN/TAP, OpenVPN, WireGuard, NordVPN, dll)
  2. Default route (apakah traffic melalui VPN gateway)
  3. Public IP geolocation (apakah beda dari ISP lokal)
  4. Common VPN process running
  5. System proxy settings (Windows registry)
  6. Environment variables (HTTP_PROXY, HTTPS_PROXY)

Output: proxy URL atau None
"""

import os
import sys
import json
import socket
import subprocess
import urllib.request
import urllib.error
import re

# ─ Default ISP info (ganti dengan ISP kamu) ──────────
# Kalau IP publik beda dari ini, kemungkinan pakai VPN
DEFAULT_ISP_KEYWORDS = ["indonesia", "telkom", "indihome", "biznet", "first media", 
                         "myrepublic", "xl", "tri", "indosat", "smartfren", "linknet"]
DEFAULT_COUNTRY = "ID"


def log(msg):
    print(f"  [VPN] {msg}")


# ════════════════════════════════════════════════════
# 1. Network Interface Detection
# ════════════════════════════════════════════════════

def check_network_interfaces():
    """Cek adapter VPN (TUN/TAP, WireGuard, NordVPN, dll) via ipconfig."""
    vpn_adapters = []
    try:
        result = subprocess.run(
            ["ipconfig"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        lines = result.stdout.split("\n")
        current_adapter = None
        for line in lines:
            # Adapter name line
            if line.strip() and not line.startswith(" ") and ":" in line and "." not in line.split(":")[0]:
                current_adapter = line.strip().rstrip(":")
            # Check for VPN-related adapter names
            if current_adapter:
                name_lower = current_adapter.lower()
                vpn_keywords = [
                    "tun", "tap", "openvpn", "wireguard", "nordvpn", "nord",
                    "expressvpn", "protonvpn", "surfshark", "cyberghost",
                    "vpn", "warp", "cloudflare", "tunnel", "ppp", "l2tp",
                    "cisco", "anyconnect", "fortissl", "sophos", "zerotier",
                    "tailscale", "hamachi",
                ]
                if any(kw in name_lower for kw in vpn_keywords):
                    # Check if adapter has IP (is active)
                    has_ip = False
                    for nl in lines[lines.index(line):lines.index(line)+10]:
                        if "IPv4" in nl and ":" in nl:
                            has_ip = True
                            break
                    if has_ip and current_adapter not in vpn_adapters:
                        vpn_adapters.append(current_adapter)
    except:
        pass
    return vpn_adapters


# ════════════════════════════════════════════════════
# 2. Default Route Check
# ════════════════════════════════════════════════════

def check_default_route():
    """Cek apakah default route melalui VPN gateway."""
    vpn_routes = []
    try:
        result = subprocess.run(
            ["route", "print", "0.0.0.0"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        # Look for 0.0.0.0 routes with VPN-like gateways
        for line in result.stdout.split("\n"):
            if "0.0.0.0" in line and "0.0.0.0" in line:
                parts = line.split()
                if len(parts) >= 3:
                    gateway = parts[2]
                    # VPN gateways are usually 10.x.x.x, 172.16-31.x.x, 192.168.x.x
                    # or specific VPN subnets
                    if gateway not in ("0.0.0.0", "On-link"):
                        vpn_routes.append(gateway)
    except:
        pass
    return vpn_routes


# ════════════════════════════════════════════════════
# 3. Public IP Geolocation
# ════════════════════════════════════════════════════

def get_public_ip_info(timeout=8):
    """Dapatkan info IP publik: IP, country, ISP."""
    apis = [
        ("http://ip-api.com/json/?fields=query,country,countryCode,isp,org,as", "ip-api"),
        ("https://ipinfo.io/json", "ipinfo"),
        ("https://api.ipify.org?format=json", "ipify"),
    ]
    for url, name in apis:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(resp.read().decode())
            
            if name == "ip-api":
                return {
                    "ip": data.get("query", "?"),
                    "country": data.get("country", "?"),
                    "country_code": data.get("countryCode", "?"),
                    "isp": data.get("isp", "?"),
                    "org": data.get("org", "?"),
                }
            elif name == "ipinfo":
                return {
                    "ip": data.get("ip", "?"),
                    "country": data.get("country", "?"),
                    "country_code": data.get("country", "?"),
                    "isp": data.get("org", "?"),
                    "org": data.get("org", "?"),
                }
            elif name == "ipify":
                ip = data.get("ip", "?")
                # ipify only gives IP, try to get geo from ip-api
                try:
                    req2 = urllib.request.Request(
                        f"http://ip-api.com/json/{ip}?fields=query,country,countryCode,isp,org,as",
                        headers={"User-Agent": "Mozilla/5.0"}
                    )
                    resp2 = urllib.request.urlopen(req2, timeout=timeout)
                    data2 = json.loads(resp2.read().decode())
                    return {
                        "ip": ip,
                        "country": data2.get("country", "?"),
                        "country_code": data2.get("countryCode", "?"),
                        "isp": data2.get("isp", "?"),
                        "org": data2.get("org", "?"),
                    }
                except:
                    return {"ip": ip, "country": "?", "country_code": "?", "isp": "?", "org": "?"}
        except Exception as e:
            continue
    return None


def is_vpn_ip(ip_info):
    """Cek apakah IP publik menunjukkan VPN (bukan ISP lokal)."""
    if not ip_info:
        return False, "Tidak bisa cek IP publik"
    
    country = ip_info.get("country_code", "?").upper()
    isp = (ip_info.get("isp", "") + " " + ip_info.get("org", "")).lower()
    
    # Check country
    if country != DEFAULT_COUNTRY and country != "?":
        return True, f"Country: {country} (bukan {DEFAULT_COUNTRY}) — kemungkinan VPN"
    
    # Check ISP keywords
    is_local_isp = any(kw in isp for kw in DEFAULT_ISP_KEYWORDS)
    vpn_isp_keywords = [
        "vpn", "proxy", "nordvpn", "expressvpn", "protonvpn", "surfshark",
        "cyberghost", "private internet", "tunnelbear", "mullvad", "windscribe",
        "digitalocean", "amazon", "aws", "google cloud", "linode", "vultr",
        "ovh", "hetzner", "leaseweb", "datacamp", "m247", "choopa", "global secure",
        "warp", "cloudflare",
    ]
    is_vpn_isp = any(kw in isp for kw in vpn_isp_keywords)
    
    if is_vpn_isp:
        return True, f"ISP: {isp[:50]} — terdeteksi VPN/proxy"
    
    if not is_local_isp and country == DEFAULT_COUNTRY:
        return None, f"ISP tidak dikenali: {isp[:50]} — mungkin VPN"
    
    return False, f"ISP lokal: {isp[:50]}"


# ════════════════════════════════════════════════════
# 4. Running Process Check
# ════════════════════════════════════════════════════

def check_vpn_processes():
    """Cek process VPN yang sedang running."""
    vpn_processes = []
    vpn_exe_names = [
        "openvpn", "wireguard", "nordvpn", "expressvpn", "protonvpn",
        "surfshark", "cyberghost", "tunnelbear", "mullvad", "windscribe",
        "vpn", "anyconnect", "cisco", "fortissl", "sophos", "zerotier",
        "tailscale", "hamachi", "warp", "cloudflare", "psiphon", "outline",
        "torguard", "pia", "private internet access", "vyprvpn",
        "purevpn", "ipvanish", "norton secure", "avg secure", "kaspersky vpn",
        "bitdefender vpn", "avast secureline", "mcAfee safe connect",
    ]
    try:
        result = subprocess.run(
            ["tasklist"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        for line in result.stdout.split("\n"):
            line_lower = line.lower()
            for vpn_name in vpn_exe_names:
                if vpn_name in line_lower:
                    # Extract process name
                    parts = line.split()
                    if parts:
                        proc = parts[0]
                        if proc not in vpn_processes:
                            vpn_processes.append(proc)
                    break
    except:
        pass
    return vpn_processes


# ════════════════════════════════════════════════════
# 5. System Proxy Settings (Windows Registry)
# ════════════════════════════════════════════════════

def check_system_proxy():
    """Cek proxy settings dari Windows registry."""
    proxies = []
    try:
        result = subprocess.run(
            ["reg", "query",
             "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings",
             "/v", "ProxyServer"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "ProxyServer" in line and "REG_SZ" in line:
                    val = line.split("REG_SZ")[-1].strip()
                    if val:
                        # Format bisa: "host:port" atau "http=host:port;https=host:port"
                        if "=" in val:
                            for part in val.split(";"):
                                if "=" in part:
                                    proto, addr = part.split("=", 1)
                                    proxies.append(f"{proto}://{addr}")
                        else:
                            proxies.append(f"http://{val}")
    except:
        pass
    
    # Also check env vars
    for var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                 "ALL_PROXY", "all_proxy"]:
        val = os.environ.get(var)
        if val:
            proxies.append(val)
    
    return proxies


# ════════════════════════════════════════════════════
# 6. SOCKS Proxy Detection (Common Ports)
# ════════════════════════════════════════════════════

def check_local_socks():
    """Cek SOCKS/HTTP proxy lokal (port umum VPN clients)."""
    local_proxies = []
    common_ports = [
        # SOCKS5
        (1080, "socks5://127.0.0.1:1080"),
        (1081, "socks5://127.0.0.1:1081"),
        # HTTP proxy
        (8080, "http://127.0.0.1:8080"),
        (8118, "http://127.0.0.1:8118"),  # Privoxy
        # NordVPN
        (1086, "socks5://127.0.0.1:1086"),
        # ExpressVPN
        (443, "http://127.0.0.1:443"),
        # Cloudflare WARP
        (40000, "socks5://127.0.0.1:40000"),
        # WireGuard (usually no local proxy)
        # ProtonVPN
        (1083, "socks5://127.0.0.1:1083"),
        # Surfshark
        (1443, "socks5://127.0.0.1:1443"),
        # Psiphon
        (7777, "http://127.0.0.1:7777"),
        # Outline
        (45670, "socks5://127.0.0.1:45670"),
    ]
    for port, proxy_url in common_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.3)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            if result == 0:
                local_proxies.append(proxy_url)
        except:
            pass
    return local_proxies


# ════════════════════════════════════════════════════
# Main Detection
# ════════════════════════════════════════════════════

def detect_vpn():
    """Deteksi VPN/proxy aktif. Return dict dengan semua info."""
    result = {
        "active": False,
        "type": None,
        "proxy_url": None,
        "details": [],
    }

    # 1. Check network interfaces
    adapters = check_network_interfaces()
    if adapters:
        result["active"] = True
        result["type"] = "adapter"
        result["details"].append(f"VPN adapter: {', '.join(adapters)}")
        log(f"VPN adapter terdeteksi: {adapters}")

    # 2. Check VPN processes
    processes = check_vpn_processes()
    if processes:
        result["active"] = True
        if not result["type"]:
            result["type"] = "process"
        result["details"].append(f"VPN process: {', '.join(processes)}")
        log(f"VPN process running: {processes}")

    # 3. Check local SOCKS/HTTP proxies
    local_proxies = check_local_socks()
    if local_proxies:
        result["active"] = True
        result["type"] = "local_proxy"
        result["proxy_url"] = local_proxies[0]
        result["details"].append(f"Local proxy: {local_proxies[0]}")
        log(f"Local proxy port terbuka: {local_proxies}")
    else:
        log("Tidak ada local proxy di port umum VPN")

    # 4. Check system proxy settings
    sys_proxies = check_system_proxy()
    if sys_proxies:
        result["active"] = True
        if not result["proxy_url"]:
            result["proxy_url"] = sys_proxies[0]
        result["type"] = result["type"] or "system_proxy"
        result["details"].append(f"System proxy: {sys_proxies[0]}")
        log(f"System proxy: {sys_proxies}")

    # 5. Check public IP geolocation
    log("Cek IP publik...")
    ip_info = get_public_ip_info()
    if ip_info:
        log(f"IP: {ip_info['ip']} | Country: {ip_info['country']} | ISP: {ip_info['isp'][:40]}")
        is_vpn, reason = is_vpn_ip(ip_info)
        if is_vpn:
            result["active"] = True
            result["type"] = result["type"] or "ip_geolocation"
            result["details"].append(f"IP VPN: {reason}")
            log(f"IP menunjukkan VPN: {reason}")
        elif is_vpn is None:
            result["details"].append(f"IP tidak jelas: {reason}")
            log(f"IP tidak jelas: {reason}")
        else:
            result["details"].append(f"IP lokal: {reason}")
            log(f"IP lokal: {reason}")
    else:
        log("Tidak bisa cek IP publik (network error)")
        result["details"].append("Tidak bisa cek IP publik")

    return result


def get_proxy_for_farm():
    """Return proxy URL yang bisa dipakai farm_headless.py, atau None."""
    vpn = detect_vpn()
    if vpn["proxy_url"]:
        return vpn["proxy_url"]
    
    # Kalau VPN aktif tapi tidak ada local proxy, coba HTTP proxy umum
    if vpn["active"] and vpn["type"] in ("adapter", "process", "ip_geolocation"):
        # VPN system-level (full tunnel) — tidak perlu proxy di Playwright
        # Browser akan otomatis pakai VPN
        return "SYSTEM_VPN"
    
    return None


def print_report():
    """Print laporan deteksi VPN yang readable."""
    print()
    print("  ═══════════════════════════════════════════")
    print("  ║     VPN / PROXY DETECTOR              ║")
    print("  ═══════════════════════════════════════════")
    print()

    vpn = detect_vpn()

    status = "🟢 AKTIF" if vpn["active"] else "🔴 TIDAK AKTIF"
    print(f"  Status: {status}")
    print(f"  Type:   {vpn['type'] or 'none'}")
    if vpn["proxy_url"]:
        print(f"  Proxy:  {vpn['proxy_url']}")
    print()

    if vpn["details"]:
        print("  Details:")
        for d in vpn["details"]:
            print(f"    • {d}")
    print()

    # Recommendation
    if vpn["proxy_url"] and vpn["proxy_url"] != "SYSTEM_VPN":
        print(f"  → Gunakan proxy: --proxy {vpn['proxy_url']}")
    elif vpn["active"]:
        print("  → VPN sistem aktif — browser akan otomatis pakai VPN")
        print("    Tidak perlu --proxy flag")
    else:
        print("  → Tidak ada VPN terdeteksi")
        print("    Aktifkan VPN dulu untuk bypass IP block")
    print()
    print("  ═══════════════════════════════════════════")


if __name__ == "__main__":
    print_report()
