#!/usr/bin/env python3
"""服务器端 AI 调用助手：从 stdin 读问题，输出 AI 回复。

配合本地 aichat.py 使用（通过 ssh 调用）。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.sdk import ai_text  # noqa: E402

prompt = sys.stdin.read().strip()
if not prompt:
    sys.exit(0)

with ai_text.TextSession() as t:
    reply = t.generate(prompt)

# 去掉 ai_text 末尾常见的引用标记，如 [1][2][3]
reply = re.sub(r"(?:\[\d+\])+\s*$", "", (reply or "").strip()).strip()
print(reply)
