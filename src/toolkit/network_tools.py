"""
Network toolkit tools - WiFi, Proxy, DNS management.
SDK-first, shell-fallback, with verify() and rollback().
"""
from __future__ import annotations
import subprocess
from .base import BaseTool, ToolResult, ToolStatus, RiskLevel

class WifiTool(BaseTool):
    """WiFi connection management."""
    name = "wifi"
    description = "WiFi管理。action: scan=扫描, connect=连接(ssid+password), disconnect=断开"
    risk = RiskLevel.MEDIUM
    requires_approval = True
    timeout_s = 30.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()
        if action == "scan":
            from src.sdk import network
            nets = network.get_wifi_list()
            return self._ok(f"WiFi列表: {nets}")
        elif action == "connect":
            ssid = kwargs.get("ssid", "")
            pwd = kwargs.get("password", "")
            if not ssid: return self._fail("缺少ssid参数")
            from src.sdk import network
            ok, msg = network.connect_wifi(ssid, pwd)
            return self._ok(msg) if ok else self._fail(msg)
        elif action == "disconnect":
            from src.sdk import network
            ok, msg = network.disconnect_wifi()
            return self._ok(msg) if ok else self._fail(msg)
        return self._fail(f"未知操作: {action}. 可用: scan, connect, disconnect")

    def verify(self, **kwargs) -> bool:
        action = kwargs.get("action", "").strip().lower()
        if action == "disconnect":
            from src.sdk import network
            nets = network.get_wifi_list()
            return len(nets) == 0
        return True


class ProxyTool(BaseTool):
    """System proxy configuration."""
    name = "proxy"
    description = "系统代理设置。action: set=设置(mode+host+port), get=查看, off=关闭"
    risk = RiskLevel.MEDIUM
    requires_approval = True
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()
        from src.sdk import network
        if action == "get":
            cfg = network.get_proxy_config()
            return self._ok(str(cfg))
        elif action == "set":
            ok, msg = network.set_proxy(
                kwargs.get("mode", "manual"),
                kwargs.get("host", ""),
                int(kwargs.get("port", 0)))
            return self._ok(msg) if ok else self._fail(msg)
        elif action == "off":
            ok, msg = network.set_proxy("none")
            return self._ok(msg) if ok else self._fail(msg)
        return self._fail(f"未知操作: {action}")


class DnsTool(BaseTool):
    """DNS configuration."""
    name = "dns"
    description = "DNS设置。action: get=查看, set=设置(servers列表)"
    risk = RiskLevel.MEDIUM
    requires_approval = True
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()
        from src.sdk import network
        if action == "get":
            cfg = network.get_dns_config()
            return self._ok(str(cfg))
        elif action == "set":
            servers = kwargs.get("servers", [])
            if isinstance(servers, str): servers = [servers]
            if not servers: return self._fail("缺少servers参数")
            ok, msg = network.set_dns(servers)
            return self._ok(msg) if ok else self._fail(msg)
        return self._fail(f"未知操作: {action}")


class NetworkStatusTool(BaseTool):
    """Network status query."""
    name = "netstatus"
    description = "查询网络状态：在线状态、接口、网关、DNS"
    risk = RiskLevel.LOW
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        from src.sdk import network
        status = network.get_network_status()
        return self._ok(str(status))


def register_network_tools(registry=None):
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    registry.register_many([WifiTool(), ProxyTool(), DnsTool(), NetworkStatusTool()])
    return registry
