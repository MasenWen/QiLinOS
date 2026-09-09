"""任务/会议/事件档案记忆通道（strict 引擎版）。

识别用户显式要求长期跟踪的会议/任务/事件消息，以规范化主题为 slot 写入
strict 引擎（memory_family=task_event）；同主题更新时旧记录置 HISTORICAL
（保留可查），新记录为最新版本；对话上下文注入任务档案块，支持跨会话
恢复与版本核对（历史版本含 updated_at 与状态）。
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from src.memory_engine.strict.contracts import LifecycleStatus, StrictMemory  # noqa: E402

FAMILY = "task_event"
_SLOT_PREFIX = "task_event:"
_SKIP_STATUS = {LifecycleStatus.ARCHIVE, LifecycleStatus.BLOCKED, LifecycleStatus.DELETED}

_DOMAIN_WORDS = ("会议", "日程", "安排", "纪要", "演示", "评审会", "例会",
                 "meeting", "schedule", "task", "event")
_PERSIST_MARKERS = ("请记住", "记住这个", "记住该项", "长期跟踪", "以后可查",
                    "存档", "记下来", "后续问我", "稍后我可能问起", "之后我会问",
                    "长期记住", "请长期记住")
_SUBJECT_PREFIX = ("请记住", "请长期记住", "帮我记住", "更新", "修改", "记录", "记住")
_ACTION_PREFIX = ("我来继续准备", "我来继续", "继续准备", "我来准备", "我来处理",
                  "帮我准备", "请告诉我", "告诉我", "我需要", "需要", "准备",
                  "请帮我", "帮我", "帮我查", "请查", "查一下", "我准备")
_CN_NUM = {"十": "10", "两": "2", "一": "1", "二": "2", "三": "3", "四": "4",
           "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(seed: str) -> str:
    return "task-" + str(abs(hash(seed)) % (10 ** 16)).zfill(16)


def _strip_prefix(text: str) -> str:
    for p in _SUBJECT_PREFIX:
        if text.startswith(p):
            return text[len(p):]
    return text


def _strip_action(text: str) -> str:
    """裁剪句首动作/口语前缀，露出事件主体（如『我来继续准备麒麟软件项目会议…』→『麒麟软件项目会议…』）。"""
    t = text or ""
    for _ in range(3):
        hit = False
        for p in _ACTION_PREFIX:
            if t.startswith(p):
                t = t[len(p):].lstrip(" ，,、")
                hit = True
                break
        if not hit:
            break
    return t


def has_task_persist_intent(text: str) -> bool:
    t = (text or "").strip()
    return any(w in t for w in _PERSIST_MARKERS) and any(w in t for w in _DOMAIN_WORDS)


_UPDATE_WORDS = ("改为", "改成", "更新", "修改", "调整为", "已经完成", "已完成",
                 "现在只需要", "不用", "取消", "推迟", "提前", "换到", "移到")
_QUERY_WORDS = ("告诉我", "查一下", "查询", "恢复", "继续准备", "继续处理", "依据",
                "是什么", "在哪里", "几点", "哪些", "帮我看看", "核对")


def is_update_message(text: str) -> bool:
    return any(w in (text or "") for w in _UPDATE_WORDS)


def is_query_message(text: str) -> bool:
    return any(w in (text or "") for w in _QUERY_WORDS)


def extract_subject(text: str) -> Optional[str]:
    t = _strip_action(_strip_prefix(text or ""))
    for pat in (r"([\u4e00-\u9fa5A-Za-z0-9]{2,10}?(?:项目)[\u4e00-\u9fa5A-Za-z0-9]{0,4}会议)",
                r"([\u4e00-\u9fa5A-Za-z0-9]{2,14}?会议)",
                r"([\u4e00-\u9fa5A-Za-z0-9]{2,16}?(?:安排|任务|日程|事件))"):
        m = re.search(pat, t)
        if m:
            g = m.group(1)
            for tail in ("的当前安排", "的会议安排", "当前安排", "的更新", "安排"):
                if g.endswith(tail):
                    g = g[:-len(tail)]
                    break
            g = g.strip(" ，,、")
            if g:
                return g
    return None


def parse_task_event(text: str) -> dict:
    subject = extract_subject(text)
    parsed = {"subject": subject or "未命名安排", "when": "", "where": "", "items": [], "raw": text[:400]}
    t2 = _strip_prefix(text)
    m = re.search(r"((?:本周|下周|周[一二三四五六日天]|[0-9]{1,2}月[0-9]{1,2}日?|今天|明天|后天)(?:上午|下午|晚上)?(?:[0-9]{1,2}(?::[0-9]{2})?|[一二两三四五六七八九十]{1,3})(?:点|时)(?:半)?)", t2)
    if not m:
        m = re.search(r"(本周|下周|周[一二三四五六日天]|[0-9]{1,2}月[0-9]{1,2}日?|今天|明天|后天)", t2)
    if m:
        w = m.group(1).strip()
        for cn, ar in _CN_NUM.items():
            w = w.replace(cn, ar)
        parsed["when"] = w
    m = re.search(r"(会议室\s*[A-Za-z0-9一二三四五六七八九十]*|线上|线下)", t2)
    if m:
        parsed["where"] = m.group(1).strip()
    items = []
    pm = re.search(r"(?:需要)?准备(.{1,20}?)(?:和|与)(.{1,20}?)(?:[，,。；;]|目前|现在|都)", t2)
    if pm:
        for g in (pm.group(1), pm.group(2)):
            lab = g.strip(" ，,、")
            if lab and not any(x in lab for x in ("目前", "现在", "都")):
                items.append({"label": lab, "status": "todo"})
    for m in re.finditer(r"([^，。,；;]{1,20}?)(?:已(?:经)?完成|已完成|还没?有完成|未完成)", t2):
        lab = m.group(1).strip(" ，,、")
        if any(x in lab for x in ("目前", "现在", "都", "已经")):
            continue
        done = ("完成" in m.group(0)) and not m.group(0).startswith(("未", "没"))
        if lab and not any(i["label"] == lab for i in items):
            items.append({"label": lab, "status": "done" if done else "todo"})
    # 单条待办："(现在)只需要准备 X" / "准备 X"（句尾或后续是句号）
    for m in re.finditer(r"(?:只需要|还要|需)准备([^，。,；;。]{1,20}?)(?:[，。]|$)", t2):
        lab = m.group(1).strip(" ，,、")
        if lab and not any(i["label"] == lab for i in items):
            items.append({"label": lab, "status": "todo"})
    parsed["items"] = items[:8]
    return parsed


def save_task_event(engine, parsed: dict, source_text: str = "") -> Optional[StrictMemory]:
    """写入/更新任务档案：同主题 active 旧记录置 HISTORICAL，新记录为最新版本。"""
    try:
        store = engine.store
        subject = (parsed.get("subject") or "").strip()[:40]
        if not subject:
            return None
        slot = _SLOT_PREFIX + subject
        now = _now_iso()
        user = "nex_user"
        existing = store.list_memories(user, slot_key=slot) or []
        active = [m for m in existing if m.status not in _SKIP_STATUS
                  and m.status != LifecycleStatus.HISTORICAL]
        new_version = max([m.version or 1 for m in existing] or [0]) + 1
        for m in active:
            store.put_memory(replace(m, status=LifecycleStatus.HISTORICAL,
                                     version=(m.version or 1) + 1, updated_at=now))
        semantic = json.dumps({
            "subject": subject, "when": parsed.get("when") or "", "where": parsed.get("where") or "",
            "items": parsed.get("items") or [], "version": new_version, "updated": now,
            "superseded_count": len(active),
        }, ensure_ascii=False)
        record = StrictMemory(
            memory_id=_stable_id(f"{user}|{slot}|{now}"),
            user_id=user,
            memory_family=FAMILY,
            candidate_kind="event",
            slot_key=slot,
            semantic_value=semantic,
            condition={},
            scope={"subject": subject},
            cardinality="single",
            status=LifecycleStatus.STABLE,
            evidence_ids=("task_event:" + now,),
            support_unit_ids=(),
            oppose_unit_ids=(),
            applicable_unit_ids=(),
            valid_from=now,
            valid_to="",
            predecessor_memory_ids=(),
            successor_memory_ids=(),
            conflict_group_ids=(),
            confidence={"value": 1.0, "method": "explicit_persist.v1"},
            stability={"value": 0.6, "method": "explicit_persist.v1"},
            provenance={"extractor": "task_event.v1", "source": (source_text or parsed.get("raw") or "")[:200]},
            version=new_version,
            created_at=now,
            updated_at=now,
        )
        store.put_memory(record)
        return record
    except Exception as e:
        print(f"[task_memory] save err: {e}", flush=True)
        return None


def _events(engine) -> list[StrictMemory]:
    try:
        mems = engine.store.list_memories("nex_user") or []
        return [m for m in mems if (m.memory_family or "") == FAMILY
                and m.status not in _SKIP_STATUS]
    except Exception:
        return []


def _record_text(m: StrictMemory) -> str:
    try:
        d = json.loads(m.semantic_value or "{}")
    except Exception:
        d = {}
    parts = [str(d.get("subject") or m.scope.get("subject") or "安排")]
    if d.get("when"):
        parts.append(str(d["when"]))
    if d.get("where"):
        parts.append(str(d["where"]))
    items = d.get("items") or []
    if items:
        parts.append("；".join("%s(%s)" % (i.get("label", ""), "已完成" if i.get("status") == "done" else "未完成")
                              for i in items[:6]))
    return "，".join(p for p in parts if str(p))


def archive_block(engine, limit: int = 4) -> str:
    events = _events(engine)
    if not events:
        return ""
    by_slot: dict[str, list] = {}
    for m in events:
        by_slot.setdefault(m.slot_key, []).append(m)
    lines = []
    for slot in sorted(by_slot.keys())[:limit]:
        group = by_slot[slot]
        active = [m for m in group if m.status != LifecycleStatus.HISTORICAL]
        if not active:
            continue
        latest = max(active, key=lambda m: m.updated_at or "")
        hist = len(group) - 1
        line = "- " + _record_text(latest)
        if hist > 0:
            line += f"（该主题共 {hist + 1} 个版本，最新为当前有效；可询问历史依据）"
        lines.append(line)
    return "\n".join(lines)


def history_block(engine, subject: str) -> str:
    mems = _events(engine)
    slot = _SLOT_PREFIX + subject
    group = sorted([m for m in mems if m.slot_key == slot], key=lambda m: m.version or 1)
    if not group:
        return ""
    lines = []
    for m in group:
        d = {}
        try:
            d = json.loads(m.semantic_value or "{}")
        except Exception:
            pass
        upd = (d.get("updated") or m.updated_at or "")[:19].replace("T", " ")
        lines.append(f"- 版本 {d.get('version') or m.version}（{m.status.value}，更新于 {upd}）：{_record_text(m)}")
    return "\n".join(lines)
