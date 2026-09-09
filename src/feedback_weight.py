"""回复点赞/点踩 → 偏好采纳权重。

把界面上的 👍/👎 反馈落到「该回复采用的偏好」上：每条偏好维护支持/反对计数，
采纳率按 ``Beta(1+支持, 1+反对)`` 后验均值计算；生成上下文时按采纳率降序排列，
反对占优（连续点踩）的偏好不再进入提示块。

与创新模块的 Beta--Bernoulli 共轭更新同构；此处为产品侧独立小实现，
只依赖标准库，不接入主链路其他模块。
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List, Optional

_lock = threading.Lock()


def _store_path() -> str:
    """反馈文件路径（环境变量可覆盖，便于测试隔离）。"""
    return os.environ.get(
        "NEX_FEEDBACK_PATH",
        os.path.join(os.path.expanduser("~/.nex-agent"), "feedback_weight.json"),
    )

_PREFIXES = ("稳定偏好：", "请记住：", "偏好：", "用户的")


def normalize(text: str) -> str:
    """偏好文本 → 稳定的计数键（去前缀、压缩空白、限长）。"""
    t = (text or "").strip()
    for p in _PREFIXES:
        if t.startswith(p):
            t = t[len(p):].strip()
            break
    return " ".join(t.split())[:120]


def _load() -> Dict[str, dict]:
    try:
        with open(_store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: Dict[str, dict]) -> None:
    try:
        p = _store_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except Exception:
        pass


def record(keys: List[str], vote: str) -> dict:
    """给一组偏好记一次支持（up）或反对（down）。

    ``keys`` 为稳定标识：优先传 strict 记忆 id（文本改写不影响），
    无 id 时传偏好文本（内部做规范化）。
    """
    if vote not in ("up", "down"):
        return {"ok": False, "note": "vote 需为 up/down"}
    updated = 0
    with _lock:
        data = _load()
        for p in keys or []:
            key = p if isinstance(p, str) and not p.startswith(("-", "稳定", "请记住")) else normalize(p)
            key = str(key or "").strip()
            if not key or key in ("-",):
                continue
            item = data.setdefault(key, {"support": 0, "oppose": 0, "updated": 0.0})
            if vote == "up":
                item["support"] = int(item.get("support") or 0) + 1
            else:
                item["oppose"] = int(item.get("oppose") or 0) + 1
            item["updated"] = time.time()
            updated += 1
        _save(data)
    return {"ok": True, "updated": updated}


def record_pairs(pairs: List[tuple], vote: str) -> dict:
    """按 (id, text) 对记录反馈：以 id 计数，同时保存文本快照用于匹配回退。"""
    if vote not in ("up", "down"):
        return {"ok": False, "note": "vote 需为 up/down"}
    updated = 0
    with _lock:
        data = _load()
        for _id, _text in pairs or []:
            key = str(_id or "").strip() or normalize(_text or "")
            if not key:
                continue
            item = data.setdefault(key, {"support": 0, "oppose": 0, "updated": 0.0})
            if vote == "up":
                item["support"] = int(item.get("support") or 0) + 1
            else:
                item["oppose"] = int(item.get("oppose") or 0) + 1
            item["updated"] = time.time()
            item["text"] = normalize(_text or "")   # 文本快照：记忆重写换 id 后仍可命中
            updated += 1
        _save(data)
    return {"ok": True, "updated": updated}


def _item_by_text(data: Dict[str, dict], text: str) -> Optional[dict]:
    """按文本快照反查计数条目（id 已失效时的回退匹配）。"""
    t = normalize(text)
    if not t:
        return None
    for v in data.values():
        if normalize(str(v.get("text") or "")) == t:
            return v
    return None


def score(key: str) -> float:
    """采纳率 = Beta(1+支持, 1+反对) 后验均值 = (1+s)/(2+s+m)。"""
    with _lock:
        data = _load()
        item = data.get(key) or {}
    s = int(item.get("support") or 0)
    m = int(item.get("oppose") or 0)
    return (1.0 + s) / (2.0 + s + m)


def rank_preference_pairs(pairs: List[tuple], limit: int) -> List[tuple]:
    """按采纳率降序过滤 (key, text) 偏好对；反对占优的直接剔除。

    key 为稳定标识（记忆 id 或规范化文本）。返回过滤/排序后的 pairs。
    """
    if not pairs:
        return []
    with _lock:
        data = _load()
    scored = []
    for key, text in pairs:
        item = data.get(str(key)) or _item_by_text(data, text) or {}
        s = int(item.get("support") or 0)
        m = int(item.get("oppose") or 0)
        sc = (1.0 + s) / (2.0 + s + m)
        scored.append((sc, s, m, key, text))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out: List[tuple] = []
    for sc, s, m, key, text in scored:
        if sc < 0.5 and m >= 2:
            continue  # 连续反对：不再默认采用
        out.append((key, text))
        if len(out) >= limit:
            break
    return out


def rank_preference_lines(lines: List[str], limit: int) -> List[str]:
    """按采纳率降序排列偏好行；反对占优（>=2 且采纳率 < 0.5）的直接剔除。

    返回前 ``limit`` 条，供上下文提示块使用。
    """
    if not lines:
        return []
    with _lock:
        data = _load()
    scored = []
    for line in lines:
        key = normalize(line)
        if not key:
            continue
        item = data.get(key) or {}
        s = int(item.get("support") or 0)
        m = int(item.get("oppose") or 0)
        sc = (1.0 + s) / (2.0 + s + m)
        scored.append((sc, s, m, key, line))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out: List[str] = []
    for sc, s, m, key, line in scored:
        if sc < 0.5 and m >= 2:
            continue  # 连续反对：不再默认采用
        out.append(line)
        if len(out) >= limit:
            break
    return out


def stats() -> dict:
    """反馈统计摘要（供调试/验证）。"""
    with _lock:
        data = _load()
    total_up = sum(int(v.get("support") or 0) for v in data.values())
    total_down = sum(int(v.get("oppose") or 0) for v in data.values())
    return {"prefs_tracked": len(data), "total_up": total_up, "total_down": total_down}
