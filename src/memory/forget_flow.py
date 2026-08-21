"""精准遗忘交互流程（ForgetFlow）— 对应状态图实现

graph TD
    A[用户发出删除记忆] --> B[coordinator_node]
    B --> C{检查 state.get('forget_pending_candidates')}
    C -- 非空 --> D[跳过LLM，返回next(forget)]
    C -- 空 --> E[LLM路由，handoff_to_forget]
    D --> F[forget_node]
    E --> F
    F --> G{再次检查 forget_pending_candidates}
    G -- 非空 --> H[分析用户回复]
    H --> I{用户指令判断}
    I -- 取消 --> J[取消删除] --> End
    I -- 确认/删除某条 --> K[检索相关记忆] --> L[执行删除] --> M[保存状态 forget_pending_candidates.json] --> End
    G -- 空 --> N[提取关键词 存储: forget_pending_keyword] --> O[检索相关记忆] --> P[向用户展示检索结果] --> Q[询问用户是否删除] --> End

设计要点:
- coordinator_node: 有 pending → 跳过 LLM 直接进入 forget_node(确认分支)；无 pending → LLM 路由判断遗忘意图
- forget_node: 有 pending → 解析用户回复(取消/确认全部/删除某条)；无 pending → 提取关键词→检索→展示→询问
- 状态持久化到 ~/.nex-agent/forget_pending_candidates.json（跨请求/跨重启保持）
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from typing import Any, Optional

from src.memory_engine.forget_api import extract_forget_target

_STATE_PATH = os.path.expanduser("~/.nex-agent/forget_pending_candidates.json")
_lock = threading.Lock()

# 取消类关键词（用户指令判断：取消）
_CANCEL_WORDS = ("取消", "不删", "算了", "别删", "不删除", "不执行", "不需要", "停")
# 确认全删类关键词
_CONFIRM_ALL_WORDS = ("确认", "是的", "全部删", "都删", "删掉", "删除", "确认删除", "对")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ForgetFlow:
    """精准遗忘交互状态机：handle() 返回 (回复文本, 是否已处理)。"""

    def __init__(self, state_path: str = _STATE_PATH,
                 store: Any = None, llm=None):
        self.state_path = state_path
        self._store = store          # mem0_store（惰性注入）
        self._llm = llm or self._default_llm
        self._state: Optional[dict] = None

    # ---------------------------------------------------------------- 外部入口
    def handle(self, message: str, session_id: str = "default") -> tuple[str, bool]:
        """对话入口：coordinator_node 路由 → forget_node 执行。
        返回 (reply, handled)；handled=False 时调用方继续走正常 LLM 对话。"""
        msg = (message or "").strip()
        if not msg:
            return "", False
        st = self._load_state()
        # ---- coordinator_node: 检查 forget_pending_candidates ----
        if st and st.get("active") and st.get("candidates"):
            # 非空：跳过 LLM 编排，直接进入 forget_node（确认分支）
            # 仅同会话可继续确认；其他会话不打扰
            if st.get("session_id") != session_id:
                return "", False
            return self._forget_node_confirm(msg, st)
        # ---- coordinator_node: 无 pending → LLM 路由 handoff_to_forget ----
        forget, keyword = self._route_forget_intent(msg)
        if not forget:
            return "", False
        return self._forget_node_discover(msg, keyword, session_id)

    # ------------------------------------------------- forget_node: 确认分支（G 非空）
    def _forget_node_confirm(self, msg: str, st: dict) -> tuple[str, bool]:
        candidates = st.get("candidates") or []
        decision, ids = self._parse_user_decision(msg, candidates)
        if decision == "cancel":
            self._save_state({"active": False, "candidates": [],
                              "keyword": st.get("keyword"), "session_id": st.get("session_id"),
                              "created_at": st.get("created_at"),
                              "resolved_at": _now(), "resolution": "cancelled"})
            return "已取消删除，记忆保持不变 ✅", True
        if decision in ("confirm_all", "confirm_ids") and ids:
            deleted = self._execute_delete(ids)
            self._save_state({"active": False, "candidates": [],
                              "keyword": st.get("keyword"), "session_id": st.get("session_id"),
                              "created_at": st.get("created_at"),
                              "resolved_at": _now(), "resolution": "deleted",
                              "deleted_count": len(deleted)})
            if deleted:
                return f"已删除 {len(deleted)} 条相关记忆 ✅：" + "\n".join(
                    f"- {c.get('text', '')[:60]}" for c in candidates if c.get("id") in deleted), True
            return "没有找到可删除的记忆（可能已被清理）", True
        # 无法解析：再次展示候选并请用户明确
        return self._render_candidates(candidates, st.get("keyword", ""),
                                       note="请回复「确认删除」或「取消」，或告诉我删除哪几条（如：删除第1、3条）。"), True

    # ------------------------------------------------- forget_node: 发现分支（G 空）
    def _forget_node_discover(self, msg: str, keyword: str, session_id: str) -> tuple[str, bool]:
        if not keyword:
            keyword = self._extract_keyword(msg)
        if not keyword:
            return "", False
        candidates = self._retrieve_candidates(keyword)
        if not candidates:
            self._save_state({"active": False, "candidates": [],
                              "keyword": keyword, "session_id": session_id,
                              "created_at": _now(), "resolved_at": _now(),
                              "resolution": "no_match"})
            return f"我没有找到与「{keyword}」相关的记忆，无需删除。", True
        # 存储: forget_pending_candidates + forget_pending_keyword
        self._save_state({"active": True, "candidates": candidates,
                          "keyword": keyword, "session_id": session_id,
                          "created_at": _now()})
        return self._render_candidates(candidates, keyword), True

    # ---------------------------------------------------------------- 渲染
    def _render_candidates(self, candidates: list[dict], keyword: str, note: str = "") -> str:
        lines = [f"我找到了以下与「{keyword}」相关的记忆，请确认是否删除：", ""]
        for i, c in enumerate(candidates, 1):
            score = c.get("score", 0)
            lines.append(f"{i}. {c.get('text', '')[:80]}  (相关度 {score:.2f})")
        if note:
            lines.append("")
            lines.append(note)
        else:
            lines.append("")
            lines.append("回复「确认删除」删除全部，或指定「删除第1条」；回复「取消」则不删除。")
        return "\n".join(lines)

    # ------------------------------------------------- 意图路由（LLM + 规则回退）
    _ROUTE_PROMPT = (
        "你是意图路由器。判断用户消息是否表达「删除/忘记/清除自己的记忆」意图。\n"
        "只输出 JSON：{\"forget\": true/false, \"keyword\": \"待删除记忆的关键词，无则空串\"}\n"
        "示例：\"忘记我喜欢喝咖啡\" → {\"forget\": true, \"keyword\": \"咖啡\"}\n"
        "\"帮我查一下CPU\" → {\"forget\": false, \"keyword\": \"\"}"
    )

    def _route_forget_intent(self, msg: str) -> tuple[bool, str]:
        # 规则优先：动词表命中即遗忘意图（零 LLM 成本、稳定）
        target = extract_forget_target(msg)
        if target:
            return True, target
        if any(w in msg for w in ("记忆", "记住", "偏好")) and any(
                w in msg for w in ("删", "忘", "清", "remove", "delete", "forget")):
            return True, self._extract_keyword(msg)
        # LLM 路由兜底（handoff_to_forget）
        try:
            raw = self._llm(self._ROUTE_PROMPT + "\n用户消息：" + msg)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                obj = json.loads(m.group(0))
                if obj.get("forget"):
                    kw = str(obj.get("keyword") or "").strip()
                    return True, kw or self._extract_keyword(msg)
        except Exception:
            pass
        return False, ""

    # ------------------------------------------------- 关键词提取
    def _extract_keyword(self, msg: str) -> str:
        kw = extract_forget_target(msg)
        if kw:
            return kw
        # 更宽泛：去动词后取前 12 字
        for v in ("忘记", "忘了", "忘掉", "删除", "删掉", "移除", "清除", "抹除"):
            if v in msg:
                return msg.split(v, 1)[1].strip("，,、 的")[:12]
        return ""

    # ------------------------------------------------- 候选检索
    def _retrieve_candidates(self, keyword: str, limit: int = 8) -> list[dict]:
        store = self._get_store()
        if store is None:
            return []
        merged: dict[str, dict] = {}
        # 语义检索相关度门槛：低于 SEMANTIC_MIN_SCORE 的记忆视为无关，不进入候选
        # （实测 mem0 阈值 0.5 会召回大量 0.55~0.6 的无关记忆，确认删除会误删）
        SEMANTIC_MIN_SCORE = 0.65
        # 1) 语义检索（高分候选）
        try:
            for it in store.search(keyword, top_k=10) or []:
                mid = it.get("id") or it.get("memory_id")
                score = float(it.get("score") or 0)
                if not mid or score < SEMANTIC_MIN_SCORE:
                    continue
                merged[mid] = {"id": mid, "text": str(it.get("memory") or ""),
                               "score": score}
        except Exception:
            pass
        # 2) 文本包含匹配（关键词精准命中 → 给 0.9，排在语义结果之前）
        try:
            for it in store.list_all(top_k=300) or []:
                text = str(it.get("memory") or "")
                mid = it.get("id") or it.get("memory_id")
                if mid and keyword and keyword.lower() in text.lower():
                    if mid not in merged:
                        merged[mid] = {"id": mid, "text": text, "score": 0.9}
                    else:
                        merged[mid]["text"] = text
                        merged[mid]["score"] = max(merged[mid].get("score", 0), 0.9)
        except Exception:
            pass
        items = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return items[:limit]

    # ------------------------------------------------- 用户指令判断（LLM + 规则）
    _DECISION_PROMPT = (
        "用户之前请求删除记忆，以下是候选列表。现在用户回复了，请判断其意图。\n"
        "只输出 JSON：{\"action\": \"cancel\" | \"confirm_all\" | \"confirm_ids\", \"ids\": [候选id]}\n"
        "cancel=取消删除；confirm_all=确认删除全部；confirm_ids=只删除指定的候选id。\n"
        "候选：{candidates}"
    )

    def _parse_user_decision(self, msg: str, candidates: list[dict]) -> tuple[str, list[str]]:
        # 规则优先
        low = msg.lower()
        if any(w in msg for w in _CANCEL_WORDS):
            return "cancel", []
        if any(w in msg for w in _CONFIRM_ALL_WORDS) and not re.search(r"第\d|\b\d+\b", msg):
            return "confirm_all", [c["id"] for c in candidates]
        # 删除某条：第1条 / 删除1、3 / 只要1号
        m = re.search(r"第?\s*(\d+)\s*(?:条|个)?", msg)
        if m and ("删" in msg or "删" in low or "去" in msg or "只" in msg or "留下" in msg):
            idx = int(m.group(1))
            if 1 <= idx <= len(candidates):
                return "confirm_ids", [candidates[idx - 1]["id"]]
        # LLM 兜底
        try:
            cand_text = "\n".join(f"{i+1}. {c.get('id')}: {c.get('text', '')[:60]}"
                                    for i, c in enumerate(candidates))
            raw = self._llm(self._DECISION_PROMPT.format(candidates=cand_text) + "\n用户回复：" + msg)
            m2 = re.search(r"\{.*\}", raw, re.DOTALL)
            if m2:
                obj = json.loads(m2.group(0))
                action = obj.get("action")
                if action == "cancel":
                    return "cancel", []
                ids = [i for i in obj.get("ids") or [] if i in {c["id"] for c in candidates}]
                if action == "confirm_all" or (action == "confirm_ids" and ids):
                    return ("confirm_ids" if ids else "confirm_all"), (ids or [c["id"] for c in candidates])
        except Exception:
            pass
        return "", []

    # ------------------------------------------------- 执行删除
    def _execute_delete(self, ids: list[str]) -> list[str]:
        store = self._get_store()
        deleted: list[str] = []
        if store is None:
            return deleted
        for mid in ids:
            try:
                store._memory.delete(memory_id=mid)
                deleted.append(mid)
            except Exception:
                continue
        return deleted

    # ------------------------------------------------- 状态持久化
    def _load_state(self) -> dict:
        if self._state is not None:
            return self._state
        try:
            with _lock:
                with open(self.state_path, encoding="utf-8") as f:
                    self._state = json.load(f)
        except Exception:
            self._state = {"active": False, "candidates": [], "keyword": ""}
        return self._state

    def _save_state(self, state: dict):
        self._state = state
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with _lock:
                with open(self.state_path, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ForgetFlow] 状态保存失败: {e}", flush=True)

    def _get_store(self):
        if self._store is not None:
            return self._store
        try:
            from src.memory.mem0_store import mem0_store
            self._store = mem0_store
        except Exception:
            self._store = None
        return self._store

    @staticmethod
    def _default_llm(prompt: str) -> str:
        try:
            from src import llm_client
            return llm_client.generate(prompt)
        except Exception as e:
            print(f"[ForgetFlow] LLM 调用失败: {e}", flush=True)
            return ""
