"""
Shell 兜底工具 — 当没有专门工具时，用白名单内的操作系统命令执行。

安全护栏：
- 仅允许白名单命令（无 rm/sudo/关机/网络修改等危险操作）
- 禁止 shell 元字符（管道/重定向/命令替换/分号/换行等），杜绝命令注入
- 写类命令（mkdir/touch/cp/mv/rmdir）的路径限定在用户主目录 ~/ 内
- 用 shell=False（shlex 拆分）执行，不经过 /bin/sh
"""

from __future__ import annotations

import os
import shlex
import subprocess

from .base import BaseTool, RiskLevel


class ShellTool(BaseTool):
    """用白名单系统命令兜底完成请求。"""

    name = "shell"
    description = (
        "当其它工具无法完成请求时，用白名单系统命令兜底执行。"
        "可用命令: mkdir, touch, rmdir, ls, pwd, tree, cat, head, tail, wc, grep, "
        "file, stat, sort, uniq, cp, mv, df, du, date, whoami, hostname, uname, uptime, top。"
        "写类命令(mkdir/touch/cp/mv/rmdir)的路径必须在主目录 ~/ 内。"
        "参数: cmd（完整命令字符串，例如 'mkdir -p ~/桌面/测试文档'）"
    )
    risk = RiskLevel.MEDIUM
    timeout_s = 20.0

    # 只读命令：可读任意路径（读取是低风险操作，不限主目录）
    READONLY_CMDS = {
        "ls", "pwd", "tree", "cat", "head", "tail", "wc", "grep",
        "file", "stat", "sort", "uniq", "df", "du", "date",
        "whoami", "hostname", "uname", "uptime", "top",
    }
    # 写类命令：路径必须限定在主目录内
    WRITE_CMDS = {"mkdir", "touch", "rmdir", "cp", "mv"}
    ALLOWED = READONLY_CMDS | WRITE_CMDS

    @staticmethod
    def _resolve(path: str) -> str:
        full = os.path.expanduser(path)
        if not os.path.isabs(full):
            full = os.path.join(os.path.expanduser("~"), full)
        return os.path.abspath(full)

    def _within_home(self, path: str) -> bool:
        home = os.path.abspath(os.path.expanduser("~"))
        full = self._resolve(path)
        return full == home or full.startswith(home + os.sep)

    @staticmethod
    def _expand_tilde(arg: str) -> str:
        """手动展开 ~ 前缀（shell=False 时 subprocess 不做 tilde 展开）。"""
        if arg == "~":
            return os.path.expanduser("~")
        if arg.startswith("~/"):
            return os.path.join(os.path.expanduser("~"), arg[2:])
        return arg

    def execute(self, **kwargs):
        cmd = (kwargs.get("cmd") or kwargs.get("command") or "").strip()
        if not cmd:
            return self._fail("缺少参数: cmd（白名单命令，例如 'mkdir -p ~/桌面/测试文档'）")

        # 1. 拒绝 shell 元字符（命令注入防护）
        for ch in ("|", ";", "&", ">", "<", "`", "$(", "${", "\n", "\r"):
            if ch in cmd:
                return self._fail(f"命令包含禁止的字符: {ch!r}")

        # 2. 拆分命令
        try:
            argv = shlex.split(cmd)
        except ValueError as e:
            return self._fail(f"命令解析失败: {e}")
        if not argv:
            return self._fail("空命令")

        base = os.path.basename(argv[0])
        if base not in self.ALLOWED:
            return self._fail(f"命令不在白名单: {base!r}")

        # 2.5 展开参数里的 ~（shell=False 不会自动展开）
        argv[1:] = [self._expand_tilde(a) for a in argv[1:]]

        # 3. 写类命令的路径护栏
        if base in self.WRITE_CMDS:
            path_args = [a for a in argv[1:] if not a.startswith("-")]
            if base == "cp":
                # cp SRC... DEST — 只约束目标(最后一个路径参数)
                if path_args and not self._within_home(path_args[-1]):
                    return self._fail(f"目标路径超出主目录: {path_args[-1]}")
            else:
                # mv / mkdir / touch / rmdir — 所有路径参数都约束在主目录内
                for a in path_args:
                    if ("/" in a) or a.startswith("~") or a.startswith("."):
                        if not self._within_home(a):
                            return self._fail(f"路径超出主目录: {a}")

        # 4. 执行（shell=False，cwd 固定在主目录）
        home = os.path.abspath(os.path.expanduser("~"))
        try:
            r = subprocess.run(
                argv, capture_output=True, text=True,
                timeout=self.timeout_s, cwd=home,
            )
        except subprocess.TimeoutExpired:
            return self._fail(f"命令执行超时({self.timeout_s:.0f}s)")
        except FileNotFoundError:
            return self._fail(f"命令不存在: {base}")
        except Exception as e:
            return self._fail(f"执行失败: {e}")

        stdout = (r.stdout or "").strip()
        stderr = (r.stderr or "").strip()
        if r.returncode == 0:
            return self._ok(stdout or f"命令执行成功: {cmd}", stdout=stdout, stderr=stderr)
        return self._fail(stderr or stdout or f"命令退出码 {r.returncode}", output=stdout)

    def verify(self, **kwargs) -> bool:
        return True  # execute() 已用退出码确认成功


def register_shell_tools(registry=None):
    """注册 shell 兜底工具。"""
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    registry.register(ShellTool())
    return registry
