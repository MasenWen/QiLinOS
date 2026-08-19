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
        "action: 'mkdir'=创建文件夹, 'touch'=创建空文件；单个用 path。"
        "创建「文件夹内含 N 个空文件」：action=mkdir + path=文件夹路径 + "
        "count=N + ext=后缀（如 count=10, ext=md 生成 10 个 .md 空文件）。"
        "多个不同路径用 paths 数组（action=touch）。"
    )
    risk = RiskLevel.MEDIUM
    timeout_s = 10.0

    @staticmethod
    def _resolve(path: str) -> str:
        full = os.path.expanduser(path.strip())
        if not os.path.isabs(full):
            full = os.path.join(os.path.expanduser("~"), full)
        return os.path.abspath(full)

    def _create_one(self, action: str, full: str, count: int = 0, ext: str = "md"):
        if action == "mkdir":
            os.makedirs(full, exist_ok=True)
            if count > 0:
                created = 0
                for i in range(1, count + 1):
                    fname = os.path.join(full, f"文件{i}.{ext.strip('.')}")
                    try:
                        with open(fname, "a", encoding="utf-8"):
                            pass
                        created += 1
                    except OSError:
                        pass
                return f"文件夹已创建: {full}，内含 {created} 个空 .{ext.strip('.')} 文件"
            return f"文件夹已创建: {full}"
        if action == "touch":
            parent = os.path.dirname(full) or "."
            os.makedirs(parent, exist_ok=True)
            with open(full, "a", encoding="utf-8"):
                pass
            return f"文件已创建: {full}"
        return None

    def execute(self, **kwargs):
        action = (kwargs.get("action") or "mkdir").strip().lower()
        raw_path = (kwargs.get("path") or "").strip()
        raw_paths = kwargs.get("paths") or []
        home = os.path.abspath(os.path.expanduser("~"))

        # batch：一步创建文件夹 + 内部多文件（解决"建文件夹含N个文件"场景）
        if action == "batch":
            folder = (kwargs.get("folder") or "").strip()
            files = kwargs.get("files") or []
            if not folder:
                return self._fail("batch 模式缺少 folder 参数")
            full_folder = self._resolve(folder)
            if full_folder != home and not full_folder.startswith(home + os.sep):
                return self._fail(f"安全限制：仅允许在主目录内创建（收到 {full_folder}）")
            try:
                os.makedirs(full_folder, exist_ok=True)
            except OSError as e:
                return self._fail(f"创建文件夹失败: {e}")
            created = []
            for f in files:
                f = (f or "").strip()
                if not f or "/" in f:
                    continue  # 只允许文件夹内的简单文件名（防路径穿越）
                full = os.path.join(full_folder, f)
                try:
                    with open(full, "a", encoding="utf-8"):
                        pass
                    created.append(f)
                except OSError:
                    pass
            return self._ok(
                f"已创建文件夹 {full_folder} 及 {len(created)} 个空文件: {', '.join(created[:15])}",
                folder=full_folder, created=created,
            )

        # 批量：paths 数组（一次创建多个，解决 AI 用 ; 批量被拒的问题）
        if raw_paths:
            if isinstance(raw_paths, str):
                raw_paths = [raw_paths]
            created, failed = [], []
            for p in raw_paths:
                p = (p or "").strip()
                if not p:
                    continue
                full = self._resolve(p)
                if full != home and not full.startswith(home + os.sep):
                    failed.append(f"{p}（超出主目录）")
                    continue
                try:
                    msg = self._create_one(action, full)
                    if msg:
                        created.append(full)
                    else:
                        failed.append(f"{p}（未知操作）")
                except OSError as e:
                    failed.append(f"{p}（{e}）")
            if created:
                result = f"批量创建 {action} {len(created)} 个: " + "; ".join(created[:10])
                if failed:
                    result += f"；失败 {len(failed)} 个: " + "; ".join(failed[:5])
                return self._ok(result, created=created, failed=failed)
            return self._fail("批量创建全部失败: " + "; ".join(failed[:5]))

        if not raw_path:
            return self._fail("缺少参数: path（目标路径）或 paths（批量路径数组）")

        full = self._resolve(raw_path)
        if full != home and not full.startswith(home + os.sep):
            return self._fail(f"安全限制：仅允许在用户主目录内创建（收到 {full}）")

        count = int(kwargs.get("count") or 0)
        ext = (kwargs.get("ext") or "md").strip() or "md"
        try:
            msg = self._create_one(action, full, count=count, ext=ext)
            if msg:
                return self._ok(msg, path=full)
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
