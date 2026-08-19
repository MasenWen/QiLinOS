# -*- coding: utf-8 -*-
"""日志驱动更新记忆：扫描 conversation.log 增量，提取动作类事件供记忆入库。

设计：
- webchat 每次对话把 {用户消息, 工具结果摘要} 追加写入 ~/.nex-agent/conversation.log（JSONL）。
- 本模块记录读取偏移（state 文件），增量扫描。
- 只提取「动作类」事件（创建/设置/修改/删除等持久事实），跳过查询类快照，避免记忆污染。
"""
import json
import os
import re

_LOG_PATH = os.path.expanduser("~/.nex-agent/conversation.log")
_STATE_PATH = os.path.expanduser("~/.nex-agent/log_reader_state.json")

# 动作类工具：执行结果值得长期记忆
_ACTION_TOOLS = {"file", "timezone", "power_plan", "dns", "bluetooth", "volume",
                 "wallpaper", "touchpad", "screensaver", "power_idle", "proxy",
                 "process_kill", "wifi", "music", "notify", "app", "screenshot"}
# 查询类工具：结果快照不入记忆
_QUERY_TOOLS = {"sysinfo", "netstatus", "battery", "diskinfo", "process_list",
                "datetime", "directory", "shell"}


def _load_state() -> int:
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            return int(json.load(f).get("offset", 0))
    except Exception:
        return 0


def _save_state(offset: int) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"offset": offset}, f)
    except Exception as e:
        print(f"[log_reader] state 保存失败: {e}")


def scan_events(top_n: int = 10):
    """增量扫描 conversation.log，返回 (事件列表, 是否还有新数据)。"""
    if not os.path.exists(_LOG_PATH):
        return [], False
    offset = _load_state()
    events = []
    with open(_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        new_lines = f.readlines()
        new_offset = f.tell()
    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("role") != "tool":
            continue
        tool = rec.get("tool", "")
        if tool in _QUERY_TOOLS:
            continue
        status = rec.get("status", "")
        if status not in ("success", "verified"):
            continue
        summary = (rec.get("summary") or "").strip()
        if not summary or len(summary) < 6:
            continue
        events.append({
            "ts": rec.get("ts", ""),
            "tool": tool,
            "text": f"用户小张于{rec.get('ts', '')[:10]}执行{summary}",
        })
    _save_state(new_offset)
    return events[:top_n], len(new_lines) > 0


def append_record(role: str, content: str, tool: str = "", status: str = "", summary: str = "") -> None:
    """webchat 调用：追加一条对话记录。"""
    import time
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "role": role,
            "content": (content or "")[:300],
        }
        if tool:
            rec["tool"] = tool
            rec["status"] = status
            rec["summary"] = (summary or "")[:200]
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[log_reader] 记录失败: {e}")


if __name__ == "__main__":
    ev, more = scan_events()
    print(f"扫描到 {len(ev)} 条事件, 还有更多: {more}")
    for e in ev:
        print(" -", e["text"][:80])
