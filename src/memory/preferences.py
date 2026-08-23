"""用户偏好查询（User Preference Query）

从长期记忆（mem0）中识别并提取"用户偏好类"信息，
区别于系统操作快照（CPU/网速/磁盘查询记录等）。

方法:
  - is_preference(text): 偏好信号词命中 且 非快照词 → 判定为偏好
  - classify_preference(text): 偏好分类（饮食/沟通/工具/作息/界面/其他）
  - query_preferences(keyword=None): 从 mem0 检索偏好（可选关键词过滤）
"""
from __future__ import annotations
import re

from typing import Any, Optional

# 偏好信号词（中文 + 英文）
_PREF_MARKERS = (
    "喜欢", "偏好", "偏爱", "习惯", "希望", "想要", "通常", "每次", "经常",
    "最爱", "更喜欢", "不喜欢", "讨厌", "愿意", "倾向", "默认", "更倾向",
    "更愿意", "尽量", "务必", "一定要", "别", "不要", "prefer", "favorite",
    "like", "habit", "always", "never", "usually",
)
# 系统快照/操作记录词（命中则视为非偏好）
_SNAPSHOT_MARKERS = (
    "查询了", "测得", "返回", "占用率", "使用率", "进程", "网速", "电池",
    "电源", "负载", "cpu", "内存", "磁盘", "主机名", "创建了", "执行了",
    "识别", "mib", "gb", "ip地址", "桌面当前", "文件", "目录", "系统返回",
    "报告", "状态为", "无法获取", "总容量", "已使用",
)

# 偏好分类关键词
_CATEGORY_RULES = (
    ("饮食", ("吃", "喝", "咖啡", "茶", "菜", "饭", "早餐", "午餐", "晚餐", "零食")),
    ("沟通", ("称呼", "叫", "语言", "英文", "中文", "回复", "风格", "简洁", "详细")),
    ("工具", ("工具", "命令", "终端", "vim", "浏览器", "编辑器")),
    ("作息", ("早起", "晚睡", "作息", "睡觉", "起床", "熬夜", "早上", "晚上")),
    ("界面", ("主题", "深色", "浅色", "壁纸", "字体", "布局")),
)


def is_preference(text: str) -> bool:
    """判定一条记忆是否为用户偏好（排除系统快照）。"""
    t = (text or "").lower()
    if any(m in t for m in _SNAPSHOT_MARKERS):
        return False
    return any(m in t for m in _PREF_MARKERS)


def classify_preference(text: str) -> str:
    """偏好分类。"""
    t = (text or "").lower()
    for cat, kws in _CATEGORY_RULES:
        if any(k in t for k in kws):
            return cat
    return "其他"


def query_preferences(store: Any = None, keyword: Optional[str] = None,
                      limit: int = 20) -> list[dict]:
    """从 mem0 长期记忆检索用户偏好（过滤系统快照）。

    返回 [{text, category, created_at}]，可按关键词过滤。
    """
    try:
        if store is None:
            from src.memory.mem0_store import mem0_store
            store = mem0_store
        items = store.list_all(top_k=300)
    except Exception:
        return []
    prefs: list[dict] = []
    for it in items or []:
        text = str(it.get("memory") or "").strip()
        if not text or not is_preference(text):
            continue
        if keyword and keyword.lower() not in text.lower():
            continue
        prefs.append({
            "text": text,
            "category": classify_preference(text),
            "created_at": it.get("created_at") or "",
        })
    # 去重：按 (类别, 主题词) 聚合——同一偏好的不同表述只保留一条
    # 主题词 = "喜欢/偏好/希望..." 后的核心名词短语（前 8 字），去掉色值/数字变体
    def _theme(text: str) -> str:
        m = re.search(r"(?:喜欢|偏好|偏爱|最爱|希望|想要|习惯|通常)[^，。,。]{1,12}", text)
        frag = m.group(0) if m else text[:10]
        frag = re.sub(r"#[0-9a-fA-F]{3,8}|\d+", "", frag)  # 去色值/数字变体
        return frag.strip("，。,。 ")[:10]

    seen, out = set(), []
    for p in prefs:
        key = (p["category"], _theme(p["text"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= limit:
            break
    return out


def preferences_prompt_block(store: Any = None, limit: int = 15) -> str:
    """偏好 → 提示词分节文本（供 _build_context 注入）。"""
    prefs = query_preferences(store=store, limit=limit)
    if not prefs:
        return ""
    lines = ["- " + p["text"][:100] + f"（{p['category']}）" for p in prefs]
    return "\n".join(lines)
