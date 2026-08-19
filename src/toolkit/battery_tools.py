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
        plan = (kwargs.get("plan") or "").strip().lower()
        if not plan or plan in ("get", "query", "查看", "查询", "status"):
            # 查询模式：返回当前电源计划（支持 plan=get 等显式查询）
            from src.sdk import battery
            try:
                return self._ok(f"当前电源计划: {battery.get_power_plan()}")
            except Exception as e:
                return self._fail(f"查询电源计划失败: {e}")
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
