"""
Disk toolkit tools - disk info, usage, mounts.
"""
from .base import BaseTool, ToolResult, RiskLevel

class DiskInfoTool(BaseTool):
    """Disk and partition information."""
    name = "diskinfo"
    description = "查询磁盘信息。action: list=磁盘列表, usage=使用率(path), mounts=挂载点"
    risk = RiskLevel.LOW
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "list").strip().lower()
        from src.sdk import disk
        if action == "list":
            disks = disk.get_disk_list()
            return self._ok(str(disks))
        elif action == "usage":
            path = kwargs.get("path", "/")
            usage = disk.get_disk_usage(path)
            return self._ok(str(usage))
        elif action == "mounts":
            mounts = disk.get_mount_points()
            return self._ok(f"挂载点: {len(mounts)}个")
        return self._fail(f"未知操作: {action}")


def register_disk_tools(registry=None):
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    registry.register_many([DiskInfoTool()])
    return registry
