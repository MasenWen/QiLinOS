"""
文件/文件夹操作工具 — 创建文件夹或空文件。

安全护栏：仅允许在用户主目录（~/）内创建，禁止写入系统目录，
避免 LLM 误用导致任意路径写文件。
"""

from __future__ import annotations

import os

from .base import BaseTool, RiskLevel


class FileTool(BaseTool):
    """创建文件或文件夹。"""

    name = "file"
    description = (
        "创建文件或文件夹（仅限用户主目录内）。"
        "action: 'mkdir'=创建文件夹, 'touch'=创建空文件；"
        "path 为目标完整路径，支持 ~ 开头，例如在桌面新建文件夹填 "
        "'~/桌面/测试文档'。若用户说「在桌面新建一个文件夹」，"
        "action 填 mkdir，path 填 ~/桌面/<文件夹名>"
    )
    risk = RiskLevel.MEDIUM
    timeout_s = 10.0

    @staticmethod
    def _resolve(path: str) -> str:
        full = os.path.expanduser(path.strip())
        if not os.path.isabs(full):
            full = os.path.join(os.path.expanduser("~"), full)
        return os.path.abspath(full)

    def execute(self, **kwargs):
        action = (kwargs.get("action") or "mkdir").strip().lower()
        raw_path = (kwargs.get("path") or "").strip()
        if not raw_path:
            return self._fail("缺少参数: path（目标路径，例如 ~/桌面/测试文档）")

        full = self._resolve(raw_path)
        home = os.path.abspath(os.path.expanduser("~"))
        if full != home and not full.startswith(home + os.sep):
            return self._fail(f"安全限制：仅允许在用户主目录内创建（收到 {full}）")

        try:
            if action == "mkdir":
                os.makedirs(full, exist_ok=True)
                return self._ok(f"文件夹已创建: {full}", path=full)
            if action == "touch":
                parent = os.path.dirname(full) or "."
                os.makedirs(parent, exist_ok=True)
                with open(full, "a", encoding="utf-8"):
                    pass
                return self._ok(f"文件已创建: {full}", path=full)
            return self._fail(f"未知操作: '{action}'。可用: mkdir, touch")
        except OSError as e:
            return self._fail(f"创建失败: {e}")

    def verify(self, **kwargs) -> bool:
        action = (kwargs.get("action") or "mkdir").strip().lower()
        raw_path = (kwargs.get("path") or "").strip()
        if not raw_path:
            return False
        full = self._resolve(raw_path)
        if action == "mkdir":
            return os.path.isdir(full)
        if action == "touch":
            return os.path.isfile(full)
        return False


def register_file_tools(registry=None):
    """注册文件/文件夹创建工具。"""
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    registry.register(FileTool())
    return registry
