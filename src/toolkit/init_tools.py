"""
ToolKit 初始化 — 在应用启动时注册所有工具。

Usage::

    from src.toolkit.init_tools import init_all_tools
    registry = init_all_tools()
"""

import logging
from .base import ToolRegistry, get_registry

logger = logging.getLogger("toolkit.init")


def init_all_tools(registry: ToolRegistry = None) -> ToolRegistry:
    """
    Register all tools (system + desktop) into the global registry.

    Call once at application startup.
    """
    if registry is None:
        registry = get_registry()

    # System tools (timezone, sleep, power, datetime)
    from .system_tools import register_system_tools
    register_system_tools(registry)

    # Desktop tools (volume, screenshot, wallpaper, etc.)
    from .desktop_tools import register_desktop_tools
    register_desktop_tools(registry)

    logger.info(
        "ToolKit initialized: %d tools (%d low, %d medium, %d consequential)",
        len(registry.list_all()),
        len(registry.list_by_risk(RiskLevel.LOW) if 'RiskLevel' in dir() else []),
        len(registry.list_by_risk(RiskLevel.MEDIUM) if 'RiskLevel' in dir() else []),
        len(registry.list_by_risk(RiskLevel.CONSEQUENTIAL) if 'RiskLevel' in dir() else []),
    )
    return registry


# Fix: import RiskLevel properly
from .base import RiskLevel


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
