"""
ToolKit 初始化 — 在应用启动时注册所有工具。

Usage::

    from src.toolkit.init_tools import init_all_tools
    registry = init_all_tools()
"""

import logging
from .base import RiskLevel, ToolRegistry, get_registry

logger = logging.getLogger("toolkit.init")

# 幂等护栏: bash_tool / kylin_actions / runtime 三处都可能触发初始化
_initialized = False


def init_all_tools(registry: ToolRegistry = None) -> ToolRegistry:
    """
    Register all tools (system + desktop) into the global registry.

    Idempotent — safe to call from multiple entry points (FastAPI lifespan,
    bash_tool, kylin_actions).  Subsequent calls just return the registry.
    """
    global _initialized

    if registry is None:
        registry = get_registry()

    if _initialized:
        return registry

    # System tools (timezone, sleep, power, datetime)
    from .system_tools import register_system_tools
    register_system_tools(registry)

    # Desktop tools (volume, screenshot, wallpaper, etc.)
    from .desktop_tools import register_desktop_tools
    register_desktop_tools(registry)

    # Network tools (wifi, proxy, dns, network status)
    from .network_tools import register_network_tools
    register_network_tools(registry)

    # Disk tools (disk info, usage, mounts)
    from .disk_tools import register_disk_tools
    register_disk_tools(registry)

    # Process tools (list, kill, find)
    from .process_tools import register_process_tools
    register_process_tools(registry)

    # Battery tools (battery info, power plans)
    from .battery_tools import register_battery_tools
    register_battery_tools(registry)

    # File tools (create folder/file within home dir)
    from .file_tools import register_file_tools
    register_file_tools(registry)

    # Shell fallback tools (whitelisted OS commands)
    from .shell_tools import register_shell_tools
    register_shell_tools(registry)

    _initialized = True

    logger.info(
        "ToolKit initialized: %d tools (%d low, %d medium, %d consequential)",
        len(registry.list_all()),
        len(registry.list_by_risk(RiskLevel.LOW)),
        len(registry.list_by_risk(RiskLevel.MEDIUM)),
        len(registry.list_by_risk(RiskLevel.CONSEQUENTIAL)),
    )
    return registry


def get_agent_tool_list(registry: ToolRegistry = None) -> str:
    """Return a markdown-formatted list of all agent-callable tools."""
    if registry is None:
        registry = get_registry()
    return registry.describe_for_agent(max_risk=RiskLevel.MEDIUM)


def get_all_tools_summary(registry: ToolRegistry = None) -> str:
    """Return a summary of all registered tools by risk level."""
    if registry is None:
        registry = get_registry()

    lines = ["## ToolKit 工具清单", ""]
    for risk in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.CONSEQUENTIAL]:
        tools = registry.list_by_risk(risk)
        if not tools:
            continue
        icon = {"low": "📖", "medium": "🔧", "consequential": "⚠️"}[risk.value]
        lines.append(f"### {icon} {risk.value.upper()}")
        for name in tools:
            tool = registry.get(name)
            if tool:
                lines.append(f"- **{name}**: {tool.description}")
        lines.append("")
    return "\n".join(lines)
