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
import re
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
        "支持受限管道（如 'du -sh ~/* | sort -rn | head -5'，每段必须在白名单内）。"
        "写类命令(mkdir/touch/cp/mv/rmdir)的路径必须在主目录 ~/ 内。"
        "参数: cmd（完整命令字符串，例如 'mkdir -p ~/桌面/测试文档'）"
    )
    risk = RiskLevel.MEDIUM
    timeout_s = 20.0

    # 只读命令：可读任意路径（读取是低风险操作，不限主目录）
    READONLY_CMDS = {
        "ls", "pwd", "tree", "cat", "head", "tail", "wc", "grep",
        "file", "stat", "sort", "uniq", "df", "du", "date",
        "whoami", "hostname", "uname", "uptime", "top", "find",
    }
    # find 只读参数白名单：命令名级校验拦不住 -exec/-delete，需参数级特判
    FIND_BLOCKED_OPTS = {
        "-exec", "-execdir", "-ok", "-okdir", "-delete",
        "-fprint", "-fprintf", "-fls", "-fprint0", "-quit",
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
    def _validate_find_args(argv) -> str | None:
        """find 参数级白名单：只允许只读选项，拦截 -exec/-delete 等。"""
        if os.path.basename(argv[0]) != "find":
            return None
        for a in argv[1:]:
            if a.startswith("-"):
                opt = a.split("=")[0]
                if opt in ShellTool.FIND_BLOCKED_OPTS:
                    return f"find 参数不在只读白名单: {opt!r}"
        return None

    @staticmethod
    def _expand_tilde(arg: str) -> str:
        """手动展开 ~ 前缀（shell=False 时 subprocess 不做 tilde 展开）。"""
        if arg == "~":
            return os.path.expanduser("~")
        if arg.startswith("~/"):
            return os.path.join(os.path.expanduser("~"), arg[2:])
        return arg

    def _run_pipeline(self, cmd: str) -> "ToolResult":
        """受限管道执行：| 分隔的每段独立解析与白名单校验，手动 Popen 串联。

        安全设计：不用 shell 解析（无注入面）；每段首命令必须在白名单；
        每段参数禁止元字符；管道段数 ≤ 4。
        """
        parts = [p.strip() for p in cmd.split("|") if p.strip()]
        if len(parts) > 4:
            return self._fail("管道段数超过限制（最多 4 段）")
        try:
            parsed = [shlex.split(p) for p in parts]
        except ValueError as e:
            return self._fail(f"命令解析失败: {e}")
        if not parsed or any(not p for p in parsed):
            return self._fail("空命令")
        # 逐段校验
        for argv in parsed:
            base = os.path.basename(argv[0])
            if base not in self.ALLOWED:
                return self._fail(f"管道段命令不在白名单: {base!r}")
            for ch in (";", "&", ">", "<", "`", "$(", "${", "\n", "\r"):
                if any(ch in a for a in argv if not self._REDIR_NULL.fullmatch(a or "")):
                    return self._fail(f"管道段含禁止字符: {ch!r}")
            # find 参数级白名单：只允许只读选项
            find_err = self._validate_find_args(argv)
            if find_err:
                return self._fail(find_err)
            # 写类命令禁止入管道
            if base in self.WRITE_CMDS:
                return self._fail(f"写类命令不允许用于管道: {base!r}")
        # 展开 ~
        parsed = [[self._expand_tilde(a) if i > 0 else a for i, a in enumerate(argv)]
                  for argv in parsed]
        home = os.path.abspath(os.path.expanduser("~"))
        procs = []
        try:
            for i, argv in enumerate(parsed):
                stdin = procs[-1].stdout if procs else None
                argv, _out_n, _err_n = self._extract_redir(argv)
                _last = (i == len(parsed) - 1)
                procs.append(subprocess.Popen(
                    argv, stdin=stdin,
                    stdout=subprocess.DEVNULL if (_out_n and _last) else subprocess.PIPE,
                    stderr=subprocess.DEVNULL if _err_n else subprocess.PIPE,
                    text=True, cwd=home,
                ))
                if stdin is not None:
                    stdin.close()
            out, err = procs[-1].communicate(timeout=self.timeout_s)
            for p in procs[:-1]:
                try:
                    p.wait(timeout=5)
                except Exception:
                    pass
            if procs[-1].returncode == 0:
                out = (out or "").rstrip()
                if not out.strip():
                    return self._ok("（管道命令执行成功，但没有输出内容——请检查路径/命令是否有效）")
                return self._ok(out[:2000])
            return self._fail(f"管道执行失败: {err.strip()[:200]}")
        except subprocess.TimeoutExpired:
            for p in procs:
                try:
                    p.kill()
                except Exception:
                    pass
            return self._fail("管道执行超时")
        except Exception as e:
            return self._fail(f"管道执行异常: {e}")

    _REDIR_NULL = re.compile(r"[12]?[<>]\s*/dev/null")

    @classmethod
    def _extract_redir(cls, argv: list) -> tuple:
        """把 argv 中的 2>/dev/null / >/dev/null / 1>/dev/null 参数拆出。
        返回 (clean_argv, stdout_to_null, stderr_to_null)。只读丢弃输出，无注入面。"""
        clean, out_null, err_null = [], False, False
        for a in argv or []:
            if cls._REDIR_NULL.fullmatch(a or ""):
                if a.lstrip("0123456789").startswith("<"):
                    continue  # 输入重定向一律不放开
                if a.startswith("2"):
                    err_null = True
                else:
                    out_null = True
            else:
                clean.append(a)
        return clean, out_null, err_null

    def execute(self, **kwargs):
        cmd = (kwargs.get("cmd") or kwargs.get("command") or "").strip()
        if not cmd:
            return self._fail("缺少参数: cmd（白名单命令，例如 'mkdir -p ~/桌面/测试文档'）")

        # 1. 受限管道支持：| 分隔的每段单独校验（手动 Popen 串联，无 shell 解析）
        if "|" in cmd:
            return self._run_pipeline(cmd)

        # 1b. 拒绝其余 shell 元字符（命令注入防护）
        # 2>/dev/null 等只读输出丢弃特例先行剥离（无注入面）
        _chk = self._REDIR_NULL.sub("", cmd)
        for ch in (";", "&", ">", "<", "`", "$(", "${", "\n", "\r"):
            if ch in _chk:
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
        # find 参数级校验（P0：无管道单命令同样拦截 -exec/-delete）
        find_err = self._validate_find_args(argv)
        if find_err:
            return self._fail(find_err)

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
        argv, _out_n, _err_n = self._extract_redir(argv)
        try:
            r = subprocess.run(
                argv,
                stdout=subprocess.DEVNULL if _out_n else subprocess.PIPE,
                stderr=subprocess.DEVNULL if _err_n else subprocess.PIPE,
                text=True, timeout=self.timeout_s, cwd=home,
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
