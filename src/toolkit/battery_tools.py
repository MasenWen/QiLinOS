"""
Battery toolkit tools.
"""
from .base import BaseTool, ToolResult, RiskLevel

class BatteryInfoTool(BaseTool):
    """Battery status query."""
    name = "battery"
    description = "查询电池状态：百分比、是否充电、电源计划"
    risk = RiskLevel.LOW
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        from src.sdk import battery
        info = battery.get_battery_info()
        pct = battery.get_battery_percentage()
        charging = battery.is_charging()
        plan = battery.get_power_plan()
        status = "充电中" if charging else ("放电中" if charging is False else "未知")
        return self._ok(f"电池: {pct}% ({status}), 电源计划: {plan}")


class PowerPlanTool(BaseTool):
    """Power plan management."""
    name = "power_plan"
    description = "电源计划管理。plan: power-saver/balanced/performance"
    risk = RiskLevel.MEDIUM
    requires_approval = True
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        plan = kwargs.get("plan", "")
        if not plan: return self._fail("缺少plan参数")
        from src.sdk import battery
        ok, msg = battery.set_power_plan(plan)
        return self._ok(msg) if ok else self._fail(msg)

    def verify(self, **kwargs) -> bool:
        plan = kwargs.get("plan", "")
        from src.sdk import battery
        return battery.get_power_plan() == plan


def register_battery_tools(registry=None):
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    registry.register_many([BatteryInfoTool(), PowerPlanTool()])
    return registry
