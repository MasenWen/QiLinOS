"""
Process toolkit tools - process list, info, kill.
"""
from .base import BaseTool, ToolResult, RiskLevel

class ProcessListTool(BaseTool):
    """Process listing."""
    name = "process_list"
    description = "列出运行中的进程"
    risk = RiskLevel.LOW
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        from src.sdk import process
        procs = process.get_process_list()
        return self._ok(f"共 {len(procs)} 个进程")


class ProcessKillTool(BaseTool):
    """Process termination."""
    name = "process_kill"
    description = "终止进程。pid=进程ID, signal=信号(默认15)"
    risk = RiskLevel.CONSEQUENTIAL
    requires_approval = True
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        pid = kwargs.get("pid")
        signal = int(kwargs.get("signal", 15))
        if not pid: return self._fail("缺少pid参数")
        from src.sdk import process
        ok, msg = process.kill_process(int(pid), signal)
        return self._ok(msg) if ok else self._fail(msg)

    def verify(self, **kwargs) -> bool:
        pid = kwargs.get("pid")
        if not pid: return False
        from src.sdk import process
        info = process.get_process_info(int(pid))
        return not info or "name" not in info


def register_process_tools(registry=None):
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    registry.register_many([ProcessListTool(), ProcessKillTool()])
    return registry
