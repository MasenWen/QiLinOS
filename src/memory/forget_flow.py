"""精准遗忘交互流程（ForgetFlow）— 对应状态图实现（增强版 v2）

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

v2 增强（2026-08-21）:
  ① 候选分页: >5 条时分页展示, 回复「下一页」翻页
  ② 高敏感二次确认: 命中 HIGH/CRITICAL 敏感记忆时, 需回复「确认删除敏感记忆」才执行
  ③ 删除审计: 所有取消/删除/无匹配写入 ~/.nex-agent/forget_audit.log
  ④ 批量遗忘: 支持「删除关于 X 和 Y 的记忆」多关键词
  ⑤ LLM 路由开关: FORGET_LLM_ROUTING=0 时纯规则模式（零 LLM 依赖）
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
_AUDIT_LOG = os.path.expanduser("~/.nex-agent/forget_audit.log")
_lock = threading.Lock()
_audit_lock = threading.Lock()

# 取消类关键词（用户指令判断：取消）
_CANCEL_WORDS = ("取消", "不删", "算了", "别删", "不删除", "不执行", "不需要", "停")
# 确认全删类关键词
_CONFIRM_ALL_WORDS = ("确认", "是的", "全部删", "都删", "删掉", "删除", "确认删除", "对")
# 敏感二次确认关键词
_CONFIRM_SENSITIVE_WORDS = ("确认删除敏感记忆", "删除敏感记忆", "确认删除敏感", "敏感记忆确认删除", "确认敏感删除")
# 翻页关键词
_NEXT_PAGE_WORDS = ("下一页", "下页", "更多", "继续", "next", "下一页候选")
# 批量关键词分隔符
_KEYWORD_SPLIT_RE = re.compile(r"[和与及跟、,，/以及]+")

_PAGE_SIZE = 5
# 敏感二次确认门槛：>= HIGH 需要二次确认
_SENSITIVE_CONFIRM_MIN = 3  # SensitivityLevel rank: none=0 low=1 medium=2 high=3 critical=4


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ForgetFlow:
    """精准遗忘交互状态机 v2：handle() 返回 (回复文本, 是否已处理)。"""

    def __init__(self, state_path: str = _STATE_PATH,
                 store: Any = None, llm=None,
                 llm_routing: Optional[bool] = None,
                 audit_path: str = _AUDIT_LOG):
        self.state_path = state_path
        self.audit_path = audit_path
        self._store = store          # mem0_store（惰性注入）
        self._llm = llm or self._default_llm
        # ⑤ LLM 路由开关：显式传参 > 环境变量 FORGET_LLM_ROUTING > 默认开启
        if llm_routing is None:
            env = os.getenv("FORGET_LLM_ROUTING", "").strip().lower()
            self._llm_routing = env not in ("0", "false", "off", "no", "")
        else:
            self._llm_routing = bool(llm_routing)
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
                # 修复：会话不匹配 + 状态过期（>30分钟）→ 视为脏状态清理并继续路由
                # （此前直接短路返回 False，导致精准遗忘在 webchat 中失效——评测残留状态污染）
                _stale = True
                try:
                    from datetime import datetime
                    _created = st.get("created_at") or ""
                    if _created:
                        _age = (datetime.now() - datetime.fromisoformat(_created)).total_seconds()
                        _stale = _age > 1800  # 30 分钟
                except Exception:
                    pass
                if _stale:
                    self._save_state({"active": False, "candidates": [],
                                      "keyword": "", "session_id": session_id,
                                      "created_at": st.get("created_at"),
                                      "resolved_at": _now(), "resolution": "stale_cleared"})
                else:
                    return "", False
            else:
                return self._forget_node_confirm(msg, st)
        # ---- coordinator_node: 无 pending → LLM 路由 handoff_to_forget ----
        forget, keywords = self._route_forget_intent(msg)
        if not forget:
            return "", False
        return self._forget_node_discover(msg, keywords, session_id)

    # ------------------------------------------------- forget_node: 确认分支（G 非空）
    def _forget_node_confirm(self, msg: str, st: dict) -> tuple[str, bool]:
        candidates = st.get("candidates") or []
        # ① 分页：回复「下一页」翻页
        if any(w in msg for w in _NEXT_PAGE_WORDS):
            page = int(st.get("page") or 1)
            total_pages = max(1, (len(candidates) + _PAGE_SIZE - 1) // _PAGE_SIZE)
            if page < total_pages:
                st["page"] = page + 1
                self._save_state(st)
                return self._render_candidates(candidates, st.get("keywords") or [st.get("keyword", "")],
                                               page=page + 1), True
            return "已经是最后一页了，请回复「确认删除」或「取消」。", True
        # ② 敏感二次确认：确认时若含未确认的敏感候选 → 要求二次确认
        sensitive_ids = [c["id"] for c in candidates if c.get("sensitive")]
        need_sensitive_confirm = bool(sensitive_ids) and not st.get("sensitive_confirmed")
        if need_sensitive_confirm and any(w in msg for w in _CONFIRM_SENSITIVE_WORDS):
            st["sensitive_confirmed"] = True
            self._save_state(st)
            return ("已确认敏感记忆的删除。请再次回复「确认删除」执行删除，或指定「删除第N条」。"), True
        decision, ids = self._parse_user_decision(msg, candidates)
        if decision == "cancel":
            self._audit("cancel", st, ids=[])
            self._save_state({"active": False, "candidates": [],
                              "keywords": st.get("keywords") or [],
                              "keyword": st.get("keyword"), "session_id": st.get("session_id"),
                              "created_at": st.get("created_at"),
                              "resolved_at": _now(), "resolution": "cancelled"})
            return "已取消删除，记忆保持不变 ✅", True
        if decision in ("confirm_all", "confirm_ids") and ids:
            # ② 敏感二次确认拦截
            if need_sensitive_confirm and any(i in sensitive_ids for i in ids):
                return ("⚠️ 候选包含敏感信息（手机号/身份证/密码/密钥等）。"
                        "如确认删除，请回复「确认删除敏感记忆」。"), True
            deleted = self._execute_delete(ids)
            self._audit("delete", st, ids=deleted)
            self._save_state({"active": False, "candidates": [],
                              "keywords": st.get("keywords") or [],
                              "keyword": st.get("keyword"), "session_id": st.get("session_id"),
                              "created_at": st.get("created_at"),
                              "resolved_at": _now(), "resolution": "deleted",
                              "deleted_count": len(deleted)})
            if deleted:
                return f"已删除 {len(deleted)} 条相关记忆 ✅：" + "\n".join(
                    f"- {c.get('text', '')[:60]}" for c in candidates if c.get("id") in deleted), True
            return "没有找到可删除的记忆（可能已被清理）", True
        # 无法解析：再次展示候选并请用户明确
        return self._render_candidates(candidates, st.get("keywords") or [st.get("keyword", "")],
                                       page=int(st.get("page") or 1),
                                       note="请回复「确认删除」或「取消」，或告诉我删除哪几条（如：删除第1、3条）。"), True

    # ------------------------------------------------- forget_node: 发现分支（G 空）
    def _forget_node_discover(self, msg: str, keywords: list[str], session_id: str) -> tuple[str, bool]:
        if not keywords:
            keywords = self._extract_keywords(msg)
        keywords = [k for k in keywords if k]
        if not keywords:
            return "", False
        candidates = self._retrieve_candidates(keywords)
        if not candidates:
            self._audit("no_match", {"session_id": session_id, "keywords": keywords}, ids=[])
            self._save_state({"active": False, "candidates": [],
                              "keywords": keywords, "keyword": keywords[0],
                              "session_id": session_id,
                              "created_at": _now(), "resolved_at": _now(),
                              "resolution": "no_match"})
            return f"我没有找到与「{'、'.join(keywords)}」相关的记忆，无需删除。", True
        # 存储: forget_pending_candidates + forget_pending_keyword（+ 分页/敏感字段）
        self._save_state({"active": True, "candidates": candidates,
                          "keywords": keywords, "keyword": keywords[0],
                          "session_id": session_id, "created_at": _now(),
                          "page": 1, "sensitive_confirmed": False})
        return self._render_candidates(candidates, keywords, page=1), True

    # ---------------------------------------------------------------- 渲染
    def _render_candidates(self, candidates: list[dict], keywords: list[str],
                           page: int = 1, note: str = "") -> str:
        total = len(candidates)
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        start = (page - 1) * _PAGE_SIZE
        page_items = candidates[start:start + _PAGE_SIZE]
        kw_text = "、".join(keywords) if keywords else "相关"
        lines = [f"我找到了 {total} 条与「{kw_text}」相关的记忆（第 {page}/{total_pages} 页），请确认是否删除：", ""]
        for i, c in enumerate(page_items, start + 1):
            score = c.get("score", 0)
            tag = " ⚠️[敏感]" if c.get("sensitive") else ""
            lines.append(f"{i}. {c.get('text', '')[:80]}{tag}  (相关度 {score:.2f})")
        if total_pages > 1:
            lines.append("")
            lines.append(f"共 {total} 条候选，回复「下一页」查看更多。")
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
        "只输出 JSON：{\"forget\": true/false, \"keywords\": [\"待删除记忆的关键词列表\"]}\n"
        "示例：\"忘记我喜欢喝咖啡和绿茶\" → {\"forget\": true, \"keywords\": [\"咖啡\", \"绿茶\"]}\n"
        "\"帮我查一下CPU\" → {\"forget\": false, \"keywords\": []}"
    )

    def _route_forget_intent(self, msg: str) -> tuple[bool, list[str]]:
        # 规则优先：动词表命中即遗忘意图（零 LLM 成本、稳定）
        target = extract_forget_target(msg)
        if target:
            return True, self._split_keywords(target)
        if any(w in msg for w in ("记忆", "记住", "偏好")) and any(
                w in msg for w in ("删", "忘", "清", "remove", "delete", "forget")):
            return True, self._extract_keywords(msg)
        # LLM 路由兜底（handoff_to_forget）— ⑤ 可通过 FORGET_LLM_ROUTING=0 关闭
        if self._llm_routing:
            try:
                raw = self._llm(self._ROUTE_PROMPT + "\n用户消息：" + msg)
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    obj = json.loads(m.group(0))
                    if obj.get("forget"):
                        kws = [str(k).strip() for k in (obj.get("keywords") or []) if str(k).strip()]
                        return True, kws or self._extract_keywords(msg)
            except Exception:
                pass
        return False, []

    # ------------------------------------------------- 关键词提取（④ 批量）
    def _extract_keywords(self, msg: str) -> list[str]:
        target = extract_forget_target(msg)
        if target:
            return self._split_keywords(target)
        for v in ("忘记", "忘了", "忘掉", "删除", "删掉", "移除", "清除", "抹除"):
            if v in msg:
                return self._split_keywords(msg.split(v, 1)[1].strip("，,、 的"))
        return []

    # 关键词杂质清洗：前缀（关于/跟/这些…）与后缀（的记忆/所有…）
    _KW_CLEAN_PREFIX = re.compile(r"^(?:关于|跟|与|和|以及|这些|那些|全部|所有|把)")
    _KW_CLEAN_SUFFIX = re.compile(r"(?:的记忆|记忆|的所有|所有|这些|那些|内容|信息)$")

    @classmethod
    def _split_keywords(cls, text: str) -> list[str]:
        """按分隔符拆多关键词并清洗杂质：
        删除关于咖啡和绿茶的所有记忆 → [咖啡, 绿茶]"""
        parts = [p.strip(" ，,、的") for p in _KEYWORD_SPLIT_RE.split(text or "")]
        out: list[str] = []
        for p in parts:
            p = cls._KW_CLEAN_PREFIX.sub("", p)
            # 后缀循环剥除（如「绿茶的所有记忆」→「绿茶的所有」→「绿茶」）
            for _ in range(3):
                p2 = cls._KW_CLEAN_SUFFIX.sub("", p)
                if p2 == p:
                    break
                p = p2
            p = p.strip(" ，,、的")
            if p and p not in out:
                out.append(p)
        return out[:5]

    # ------------------------------------------------- 候选检索（④ 多关键词）
    def _retrieve_candidates(self, keywords: list[str], limit: int = 12) -> list[dict]:
        store = self._get_store()
        if store is None:
            return []
        merged: dict[str, dict] = {}
        # 语义检索相关度门槛：低于 SEMANTIC_MIN_SCORE 的记忆视为无关，不进入候选
        SEMANTIC_MIN_SCORE = 0.65
        for keyword in keywords:
            # 1) 语义检索（高分候选）
            try:
                for it in store.search(keyword, top_k=10) or []:
                    mid = it.get("id") or it.get("memory_id")
                    score = float(it.get("score") or 0)
                    if not mid or score < SEMANTIC_MIN_SCORE:
                        continue
                    if mid not in merged:
                        merged[mid] = {"id": mid, "text": str(it.get("memory") or ""), "score": score}
                    else:
                        merged[mid]["score"] = max(merged[mid].get("score", 0), score)
            except Exception:
                pass
        # 2) 文本包含匹配（任一关键词精准命中 → 给 0.9，排在语义结果之前）
        try:
            for it in store.list_all(top_k=300) or []:
                text = str(it.get("memory") or "")
                mid = it.get("id") or it.get("memory_id")
                low_text = text.lower()
                if mid and any(k and k.lower() in low_text for k in keywords):
                    if mid not in merged:
                        merged[mid] = {"id": mid, "text": text, "score": 0.9}
                    else:
                        merged[mid]["text"] = text
                        merged[mid]["score"] = max(merged[mid].get("score", 0), 0.9)
        except Exception:
            pass
        # ② 敏感标记（HIGH/CRITICAL → sensitive=True，需二次确认）
        for c in merged.values():
            c["sensitive"] = self._is_sensitive(c.get("text", ""))
        items = sorted(merged.values(), key=lambda x: (x.get("sensitive", False), x["score"]), reverse=True)
        return items[:limit]

    @staticmethod
    def _is_sensitive(text: str) -> bool:
        """② 敏感识别：rank >= HIGH（手机号/身份证/密码/密钥等）。"""
        try:
            from security.sensitivity import classify, _LEVEL_RANK, SensitivityLevel
            result = classify(text or "")
            return _LEVEL_RANK.get(result.level, 0) >= _SENSITIVE_CONFIRM_MIN
        except Exception:
            return False

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
        # LLM 兜底 — ⑤ 可通过 FORGET_LLM_ROUTING=0 关闭
        if self._llm_routing:
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

    # ------------------------------------------------- 删除审计（③）
    def _audit(self, action: str, st: dict, ids: list[str]):
        """③ 审计日志：谁/何时/删了什么。追加写入 ~/.nex-agent/forget_audit.log"""
        try:
            os.makedirs(os.path.dirname(self.audit_path), exist_ok=True)
            cand_map = {c.get("id"): c.get("text", "") for c in (st.get("candidates") or [])}
            record = {
                "ts": _now(),
                "action": action,                      # delete / cancel / no_match / sensitive_confirm
                "session_id": st.get("session_id", ""),
                "keywords": st.get("keywords") or [st.get("keyword", "")],
                "deleted_ids": ids,
                "deleted_texts": [cand_map.get(i, "")[:80] for i in ids],
                "sensitive": bool(st.get("candidates") and any(
                    c.get("sensitive") for c in st.get("candidates") or [])),
            }
            with _audit_lock:
                with open(self.audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[ForgetFlow] 审计写入失败: {e}", flush=True)

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
