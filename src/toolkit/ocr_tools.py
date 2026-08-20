# -*- coding: utf-8 -*-
"""OCR 工具：识别图片中的文字（麒麟 SDK libkyocr）。

⚠️ libkyocr 的 C 库调用在主进程内可能 SIGSEGV（与 libkyedid/libkyrealtime 同类问题），
因此识别全部放到子进程执行，主进程永不因 OCR 崩溃。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from .base import BaseTool, RiskLevel, ToolResult


class OcrTool(BaseTool):
    """OCR 文字识别（官方 SDK libkyocr，子进程隔离）。"""
    name = "ocr"
    description = ("OCR文字识别：识别图片中的文字。"
                   "action=recognize + path=图片路径（如 ~/图片/截图.png）")
    risk = RiskLevel.LOW
    timeout_s = 90.0

    def execute(self, **kwargs) -> ToolResult:
        action = (kwargs.get("action") or "recognize").strip().lower()
        path = (kwargs.get("path") or "").strip()
        if action != "recognize":
            return self._fail(f"未知操作: '{action}'。可用: recognize")
        if not path:
            return self._fail("请提供图片路径：path=~/图片/xxx.png")
        full = os.path.expanduser(path)
        if not os.path.isfile(full):
            return self._fail(f"图片不存在: {full}")

        # ---- 子进程隔离执行 OCR（防 C 库 SIGSEGV 杀死主进程）----
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        code = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from src.sdk.ai_vision import recognize_text\n"
            "try:\n"
            "    text = recognize_text(sys.argv[1])\n"
            "    print(json.dumps({'ok': True, 'text': text}, ensure_ascii=False))\n"
            "except Exception as e:\n"
            "    print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))\n"
        ) % project_root
        try:
            r = subprocess.run(
                [sys.executable, "-c", code, full],
                capture_output=True, text=True, timeout=self.timeout_s,
                cwd=project_root,
            )
            out = (r.stdout or "").strip().splitlines()
            if out:
                data = json.loads(out[-1])
                if data.get("ok"):
                    text = (data.get("text") or "").strip()
                    if not text:
                        return self._ok("未识别到文字（图片中可能没有文本，或文字不清晰）")
                    return self._ok(f"OCR 识别结果（官方 SDK）:\n{text}")
                return self._fail(f"OCR 识别失败: {data.get('error')}")
            return self._fail(f"OCR 子进程无输出 (stderr: {(r.stderr or '')[:120]})")
        except subprocess.TimeoutExpired:
            return self._fail(f"OCR 识别超时（>{self.timeout_s}s）")
        except Exception as e:
            return self._fail(f"OCR 调用异常: {e}")


def register_ocr_tools(registry=None):
    """注册 OCR 工具。"""
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    registry.register(OcrTool())
    return registry
