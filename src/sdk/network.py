"""
Kylin Network SDK - ctypes Python bindings.
Wraps: libkynetinfo.so, DBus com.kylin.kysdk.NetworkServer
Replaces: ifconfig, iwconfig, nmcli, ip addr
"""
import ctypes, subprocess, json
from typing import Optional, Dict, Any, List, Tuple
from .base import load_library, _decode_cstring, declare, IS_LINUX, IS_KYLIN

_LIB = None
def _get_lib():
    global _LIB
    if _LIB is None:
        _LIB = load_library("libkynetinfo", mock=not IS_KYLIN)
    return _LIB

def get_network_interfaces():
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_net_get_interfaces", restype=ctypes.c_char_p)
            raw = lib.kdk_net_get_interfaces()
            if raw:
                text = _decode_cstring(raw)
                return json.loads(text) if text else []
        except Exception: pass
    return _fallback_network_interfaces()

def _fallback_network_interfaces():
    import os as _os
    interfaces = []
    net_path = "/sys/class/net"
    if not _os.path.exists(net_path): return interfaces
    for iface in _os.listdir(net_path):
        iface_path = _os.path.join(net_path, iface)
        if not _os.path.isdir(iface_path): continue
        info = {"name": iface}
        try:
            with open(_os.path.join(iface_path, "address")) as f: info["mac"] = f.read().strip()
        except: pass
        try:
            with open(_os.path.join(iface_path, "operstate")) as f: info["state"] = f.read().strip()
        except: pass
        interfaces.append(info)
    return interfaces

def get_ip_address(interface=None):
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_net_get_ip", restype=ctypes.c_char_p, argtypes=[ctypes.c_char_p])
            raw = lib.kdk_net_get_ip((interface or "").encode())
            if raw: return json.loads(_decode_cstring(raw))
        except: pass
    return _fallback_ip(interface)

def _fallback_ip(interface=None):
    try:
        cmd = ["ip", "-j", "addr", "show"]
        if interface: cmd.append(interface)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if r.returncode == 0: return {"interfaces": json.loads(r.stdout)}
    except: pass
    return {}

def get_mac_address(interface):
    info = get_ip_address(interface)
    for iface in info.get("interfaces", []):
        if iface.get("ifname") == interface: return iface.get("address", "")
    return ""

def get_network_status():
    status = {"online": False, "interfaces": [], "default_gateway": "", "dns_servers": []}
    status["interfaces"] = get_network_interfaces()
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", "8.8.8.8"], capture_output=True, timeout=5)
        status["online"] = r.returncode == 0
    except: pass
    try:
        r = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0: status["default_gateway"] = r.stdout.strip()
    except: pass
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"): status["dns_servers"].append(line.split()[1])
    except: pass
    return status

def get_wifi_list():
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_net_wifi_scan", restype=ctypes.c_char_p)
            raw = lib.kdk_net_wifi_scan()
            if raw: return json.loads(_decode_cstring(raw))
        except: pass
    return _fallback_wifi_list()

def _fallback_wifi_list():
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
                          capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            nets = []
            for line in r.stdout.strip().split("\n"):
                if not line: continue
                parts = line.split(":")
                if len(parts) >= 2:
                    nets.append({"ssid": parts[0], "signal": parts[1] if len(parts)>1 else "",
                                 "security": parts[2] if len(parts)>2 else ""})
            return nets
    except: pass
    return []

def connect_wifi(ssid, password):
    try:
        r = subprocess.run(["nmcli", "device", "wifi", "connect", ssid, "password", password],
                          capture_output=True, text=True, timeout=30)
        if r.returncode == 0: return True, f"Connected to WiFi: {ssid}"
        return False, r.stderr.strip()
    except Exception as e: return False, str(e)

def disconnect_wifi():
    try:
        r = subprocess.run(["nmcli", "device", "disconnect"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0: return True, "WiFi disconnected"
        return False, r.stderr.strip()
    except Exception as e: return False, str(e)

def get_proxy_config():
    config = {"mode": "none", "http_host": "", "http_port": ""}
    try:
        r = subprocess.run(["gsettings", "get", "org.gnome.system.proxy", "mode"],
                          capture_output=True, text=True, timeout=3)
        config["mode"] = r.stdout.strip().strip("'")
    except: pass
    return config

def set_proxy(mode, host="", port=0):
    try:
        subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", mode],
                       capture_output=True, timeout=3)
        if mode != "none" and host and port:
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.http", "host", host],
                          capture_output=True, timeout=3)
            subprocess.run(["gsettings", "set", "org.gnome.system.proxy.http", "port", str(port)],
                          capture_output=True, timeout=3)
        return True, f"Proxy {mode}"
    except Exception as e: return False, str(e)

def get_dns_config():
    servers = []
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"): servers.append(line.split()[1])
    except: pass
    return {"servers": servers}
