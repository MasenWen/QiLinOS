"""受控 Python 代码执行工具（PythonExec）— 沙箱安全设计。

安全机制:
  1. 子进程隔离执行（超时 kill，不阻塞主服务）
  2. 受限内建：禁用 open/exec/eval/compile/input/__import__ 等危险内建
  3. import 白名单：禁止 os/sys/subprocess/socket/shutil/pathlib/ctypes/pickle 等
  4. 预置常用库：pandas/numpy/math/json/re/datetime
  5. 输出截断（4000 字符）、无网络（不提供网络库）
  6. 只读环境：无文件写入能力（open 已禁用）
"""
from __future__ import annotations

import os
import subprocess
import textwrap

from .base import BaseTool, ToolResult, ToolStatus, RiskLevel

# 禁止导入的模块（第一层：代码内 import 检查）
_DENY_IMPORTS = (
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "importlib",
    "ctypes", "pickle", "pty", "fcntl", "pwd", "grp", "signal", "multiprocessing",
    "threading", "asyncio", "requests", "urllib", "http", "ftplib", "telnetlib",
    "smtplib", "poplib", "imaplib", "ssl", "crypt", "getpass", "keyring",
)

# 预置的安全内建别名（exec 前注入）
_SAFE_PREAMBLE = r'''
import math, json, re, datetime, statistics
import pandas as pd
import numpy as np
import builtins as _b
_deny = {DENY!r}
_orig_import = _b.__import__
def _safe_import(name, *a, **k):
    root = name.split(".")[0]
    if root in _deny or (root.startswith("_") and root != "_pandas" and root != "_numpy"):
        raise ImportError("禁止导入模块: " + name)
    return _orig_import(name, *a, **k)
_b.__import__ = _safe_import
for _n in ("open", "exec", "eval", "compile", "input", "exit", "quit", "help", "breakpoint", "memoryview"):
    if hasattr(_b, _n):
        setattr(_b, _n, None)
del _b, _n
'''.format(DENY=_DENY_IMPORTS)

_MAX_OUTPUT = 4000


class PythonExecTool(BaseTool):
    """受控 Python 代码执行。适合数据分析/计算（pandas/numpy/math 可用）。"""
    name = "python_exec"
    description = ("受控Python代码执行。参数 code=要执行的Python代码（必填）。"
                   "预置 pandas/numpy/math/json/re/datetime；结果需用 print() 输出。"
                   "⚠️ 沙箱限制：禁止文件读写、网络、系统命令、导入危险模块，超时30秒。"
                   "适合数据分析、计算、格式转换等任务。")
    risk = RiskLevel.MEDIUM
    requires_approval = True   # 网页端执行需确认（代码执行属于敏感操作）
    timeout_s = 40.0

    def execute(self, **kwargs) -> ToolResult:
        code = str(kwargs.get("code") or "").strip()
        if not code:
            return self._fail("缺少 code 参数")
        if len(code) > 4000:
            return self._fail("代码过长（上限 4000 字符）")
        # 静态检查：禁止明显危险调用
        low = code.lower()
        for bad in ("__import__", "open(", "eval(", "exec(", "compile(", "subprocess", "os.system"):
            if bad in low:
                return self._fail(f"代码包含被禁止的调用: {bad}")

        full_code = _SAFE_PREAMBLE + "\n" + textwrap.dedent(code)
        try:
            python = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), ".venv", "bin", "python")
            if not os.path.exists(python):
                python = "python3"
            proc = subprocess.run(
                [python, "-"], input=full_code.encode("utf-8"),
                capture_output=True, timeout=30,
            )
            stdout = proc.stdout.decode("utf-8", errors="replace").strip()
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            if proc.returncode == 0:
                out = stdout or "(无输出，代码执行成功)"
                if len(out) > _MAX_OUTPUT:
                    out = out[:_MAX_OUTPUT] + f"\n...(输出截断，共 {len(out)} 字符)"
                return self._ok(f"✅ 执行成功:\n```\n{out}\n```")
            detail = stderr[-800:] or f"exit code {proc.returncode}"
            return self._fail(f"执行失败:\n{detail}")
        except subprocess.TimeoutExpired:
            return self._fail("执行超时（30 秒）已终止")
        except Exception as e:
            return self._fail(f"执行器异常: {e}")

    def verify(self, **kwargs) -> bool:
        return True


def register_python_tools(registry=None):
    from .base import get_registry
    reg = registry or get_registry()
    reg.register(PythonExecTool())
    return reg
