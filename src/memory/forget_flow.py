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
                        _stale = _age > 300   # 5 分钟（确认流程 5 分钟内完成足够，超时视为脏状态）
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
            deleted = self._execute_delete(
                ids,
                [c.get("text", "") for c in candidates if c.get("id") in ids],
                st.get("keywords") or [],
            )
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
        # ========== 判断是否遗忘：LLM 优先 ==========
        # 先用 LLM 判断是否遗忘意图；LLM 判定 forget 后才进入记忆流程
        # （ForgetFlow 候选检索/确认/删除）。规则层降为回退（LLM 失败/关闭时）。
        _Q = ("？", "?", "吗", "呢", "什么", "怎么", "为啥", "为何", "是否", "哪", "谁",
              "多少", "几", "how", "what", "why", "which", "where", "when")
        # 安全防线（仍在前）：问句/否定语境绝不判遗忘
        if any(q in msg for q in _Q):
            return False, []
        if any(n in msg for n in ("别忘", "别忘了", "不要忘", "不要忘记", "没忘", "不忘",
                                  "难忘", "难以忘", "别忘记", "别忘掉")):
            return False, []
        # LLM 主判断（默认开，FORGET_LLM_ROUTING=0 关闭时走规则回退）
        if self._llm_routing:
            try:
                raw = self._llm(self._ROUTE_PROMPT + "\n用户消息：" + msg)
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    obj = json.loads(m.group(0))
                    if obj.get("forget"):
                        kws = [str(k).strip() for k in (obj.get("keywords") or []) if str(k).strip()]
                        # LLM 原始关键词过清洗链：口语前缀/修饰词剥离 → 中英别名扩展
                        # （否则「我最喜欢的歌手」整串检索，记忆「用户最喜欢的歌手是周杰伦」字面不命中）
                        cleaned = []
                        for k in kws:
                            cleaned.extend(self._split_keywords(k))
                        cleaned = [k for k in cleaned if k]
                        return True, cleaned or self._extract_keywords(msg)
                    return False, []
            except Exception:
                pass  # LLM 失败 → 规则回退
        # ========== 规则回退（LLM 关闭/失败时）==========
        target = extract_forget_target(msg)
        if target:
            return True, self._split_keywords(target)
        if any(w in msg for w in ("记忆", "记住", "偏好")) and any(
                w in msg for w in ("删除", "删掉", "清除", "移除", "清空",
                                   "remove", "delete", "forget")):
            return True, self._extract_keywords(msg)
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
    # 口语前缀剥离：「我喜欢喝X」「我住在X」「我养了X」→ 只留实体核心
    _KW_TALK_PREFIX = re.compile(
        r"^(?:我|他|她|你|用户)?(?:喜欢|爱好|偏爱|住在|居住|养了|养|有|是|买|用|爱喝|喝|吃|用|玩|读|看|听|去|来|在|的)?"
        r"(?:喝|吃|住|养|用|玩|喜欢|爱)?(?:的是|的是|的|和|与)?")
    # 修饰词剥离：「电脑品牌的记忆」「猫的名字」→ 核心实体（品牌/型号/名字等修饰词删掉）
    _KW_MODIFIERS = (
        "品牌", "型号", "名字", "名称", "信息", "记录", "偏好", "习惯",
        "资料", "内容", "事项", "相关", "细节", "情况", "事项", "类别",
        "的电脑", "的手机", "的宠物", "的猫", "的狗", "的家乡", "的住址",
        "brand", "model", "name", "info", "record",
    )
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
        # 修饰词剥离：为每个关键词生成去修饰词的核心变体（如「电脑品牌」→「电脑」）
        for p in list(out):
            for mod in cls._KW_MODIFIERS:
                if mod and mod in p:
                    core = p.replace(mod, "").strip(" ，,、的")
                    if core and core not in out:
                        out.append(core)
        # 口语前缀剥离：生成纯实体变体（如「我喜欢喝豆浆」→「豆浆」）
        for p in list(out):
            core = cls._KW_TALK_PREFIX.sub("", p).strip(" ，,、的")
            if core and core != p and core not in out:
                out.append(core)
        return out[:8]

    # ------------------------------------------------- 候选检索（④ 多关键词）
    # 中英对照词典：中文关键词 → 英文变体（记忆可能存为英文）
    _EN_ALIASES = {
        "豆浆": ["soy milk", "soymilk"], "北京": ["beijing", "peking"],
        "上海": ["shanghai"], "联想": ["lenovo"], "华为": ["huawei"],
        "蓝色": ["blue"], "绿色": ["green"], "仓鼠": ["hamster"], "乌龟": ["turtle", "tortoise"],
        "足球": ["football", "soccer"], "猫": ["cat"], "狗": ["dog"],
        "电脑": ["computer", "laptop"], "手机": ["phone", "mobile"],
        "咖啡": ["coffee"], "茶": ["tea"], "跑步": ["running", "run"],
        "篮球": ["basketball"], "羽毛球": ["badminton"], "健身": ["fitness", "workout", "exercise"], "歌手": ["singer", "musician"], "音乐": ["music", "song"],
        "生日": ["birthday"], "住": ["live", "lives", "living"], "宠物": ["pet"],
        # 城市（mem0 提取可能用英文城市名：User's ... residence is Guangzhou）
        "广州": ["guangzhou"], "深圳": ["shenzhen"], "杭州": ["hangzhou"],
        "南京": ["nanjing"], "成都": ["chengdu"], "武汉": ["wuhan"],
        "重庆": ["chongqing"], "西安": ["xian", "xi'an"], "苏州": ["suzhou"],
        "天津": ["tianjin"], "长沙": ["changsha"], "青岛": ["qingdao"],
    }

    def _expand_keywords(cls, keywords: list[str]) -> list[str]:
        """扩展关键词：原文 + 英文别名（记忆可能存为英文）。"""
        out = list(keywords)
        for k in keywords:
            for en in cls._EN_ALIASES.get(k, []):
                if en not in out:
                    out.append(en)
        return out

    # LLM 审查匹配提示词：判断记忆是否与遗忘目标相关
    _MATCH_PROMPT = (
        "你是记忆审查器。用户想遗忘某个主题，以下是用户记忆库中的全部记忆。\n"
        "请判断哪些记忆与遗忘目标相关（应被删除），哪些不相关（应保留）。\n\n"
        "【遗忘目标】\n{keywords}\n\n"
        "【记忆列表】\n{memories}\n\n"
        "【判定标准】\n"
        "- 相关：记忆的**核心主题/实体**就是遗忘目标（如目标「蓝色」→ 记忆「用户喜欢蓝色」）\n"
        "- 不相关：记忆的核心主题是其他实体（如目标「蓝色」→ 记忆「用户喜欢绿色」），"
        "即使记忆文本中顺带出现过目标词，只要主题不是目标就不相关\n"
        "- 语义相近也判不相关：北京/上海、蓝/绿 是不同实体，互不相关\n\n"
        "只输出 JSON：{{\"match_ids\": [\"记忆id列表\"]}}\n"
        "没有相关记忆时输出：{{\"match_ids\": []}}"
    )

    def _retrieve_candidates(self, keywords: list[str], limit: int = 12) -> list[dict]:
        store = self._get_store()
        if store is None:
            return []
        # 需求：进记忆系统前不用文本检索——直接 LLM 审查匹配
        # 步骤：list_all 拉全量记忆 → LLM 判断哪些与遗忘目标相关
        try:
            all_items = store.list_all(top_k=300) or []
        except Exception:
            all_items = []
        if not all_items:
            return []
        # 记忆文本压缩（防止提示词超长）
        mem_lines = []
        for it in all_items:
            mid = it.get("id") or it.get("memory_id")
            text = str(it.get("memory") or "")
            if mid and text:
                mem_lines.append(f"- id={mid} | {text[:120]}")
        if not mem_lines:
            return []
        kw_text = "、".join(k for k in keywords if k)
        prompt = self._MATCH_PROMPT.format(
            keywords=kw_text,
            memories="\n".join(mem_lines[:150]),   # 最多 150 条
        )
        match_ids: set[str] = set()
        try:
            raw = self._llm(prompt)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                obj = json.loads(m.group(0))
                match_ids = {str(i) for i in (obj.get("match_ids") or []) if str(i)}
        except Exception:
            pass  # LLM 失败 → 无候选（安全：不误删）
        merged: dict[str, dict] = {}
        for it in all_items:
            mid = it.get("id") or it.get("memory_id")
            if mid and str(mid) in match_ids:
                merged[str(mid)] = {"id": str(mid), "text": str(it.get("memory") or ""), "score": 0.9}
        # 敏感标记（HIGH/CRITICAL → sensitive=True，需二次确认）
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
    def _execute_delete(self, ids: list[str], texts: list[str] | None = None,
                        keywords: list[str] | None = None) -> list[str]:
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
        # ---- 遗忘联动（2026-08-28 融合）：mem0 删除后同步四层状态 + KG 节点 ----
        # 否则四层/KG 通道会把「已遗忘」的记忆重新注入对话（遗忘复活）
        # 匹配用关键词（包含匹配，覆盖同义改写文本：候选「用户喜欢打网球」+
        # 审查提取「喜欢打网球」→ 关键词「打网球」两者都命中）
        _kws = [k for k in (list(keywords or []) + [t for t in (texts or []) if t]) if k]
        if _kws:
            try:
                self._linkage_delete(_kws)
            except Exception:
                pass
        return deleted

    def _linkage_delete(self, keywords: list[str]) -> None:
        """遗忘联动：按关键词包含匹配——四层 memories 标记 deleted + KG 节点删除。"""
        # ① 四层 memories 状态标记（读侧仲裁据此过滤，防遗忘复活）
        try:
            from src.memory_engine.store import MemoryEngineStore
            from datetime import datetime as _dt
            mstore = MemoryEngineStore()
            for t in keywords:
                t = (t or "").strip()
                if not t:
                    continue
                try:
                    for m in mstore.search_memories("nex_user", t[:40]) or []:
                        if m.status in ("deleted", "blocked"):
                            continue
                        mstore.set_memory_status(m.memory_id, "deleted",
                                                 _dt.now().isoformat(timespec="seconds"))
                        print(f"[遗忘联动] 四层记忆标记 deleted: {m.semantic_value[:40]}",
                              flush=True)
                except Exception:
                    pass
        except Exception as _e:
            print(f"[遗忘联动] 四层标记跳过: {_e}", flush=True)
        # ② 知识图谱节点删除（KG 通道同样会注入对话；包含匹配防同义节点残留）
        try:
            from src.memory_engine.knowledge_graph import KnowledgeGraph
            kg_path = os.path.expanduser("~/.nex-agent/memory_kg.json")
            kg = KnowledgeGraph.load(kg_path) if os.path.exists(kg_path) else KnowledgeGraph()
            removed = 0
            for t in keywords:
                t = (t or "").strip()
                if not t:
                    continue
                for nid, node in list(kg._nodes.items()):
                    _text = str(node.text or "")
                    if t in _text or _text in t:
                        kg.remove_node_by_id(nid)
                        removed += 1
                        print(f"[遗忘联动] KG 节点删除: {_text[:40]}", flush=True)
            if removed:
                kg.save(kg_path)
        except Exception as _e:
            print(f"[遗忘联动] KG 删除跳过: {_e}", flush=True)
        # ③ strict 库联动（B 方案：NEX_STRICT_ENGINE 启用时 strict 记忆同样注入对话，
        #   必须同步删除，防「遗忘复活」）
        #   匹配：全量扫描 + 关键词变体（去「的」/去后缀）包含匹配——
        #   严格子串会漏（「平面设计的工作」vs「请记住：用户工作是平面设计」）
        try:
            from src.memory_engine.strict import StrictMemoryEngine, StrictMemoryEngineConfig
            seng = StrictMemoryEngine(config=StrictMemoryEngineConfig.load())

            def _kw_variants(k: str) -> set[str]:
                k = (k or "").strip()
                if not k:
                    return set()
                vs = {k, k.replace("的", "")}
                for suf in ("的记忆", "记忆", "的工作", "工作", "偏好", "的信息", "信息"):
                    if k.endswith(suf) and len(k) > len(suf) + 1:
                        vs.add(k[: -len(suf)])
                        vs.add(k[: -len(suf)].replace("的", ""))
                return vs

            all_variants: set[str] = set()
            for t in keywords:
                all_variants |= _kw_variants(t)
            all_variants = {v for v in all_variants if len(v) >= 2}
            # 核心词集合（无序全含匹配，解决倒序：关键词「平面设计的工作」
            # vs 记忆「用户工作是平面设计」——子串无解，词级判定）
            _tokens: set[str] = set()
            for v in all_variants:
                for _b in re.findall(r"[\u4e00-\u9fff]{2,}", v):
                    if len(_b) >= 2:
                        _tokens.add(_b)
            _ids: list[str] = []
            try:
                _mems = seng.store.list_memories("nex_user") or []
            except Exception:
                _mems = []
            for m in _mems:
                sv = str(getattr(m, "semantic_value", "") or "")
                if not _tokens:
                    continue
                _hit = False
                # ① 变体子串匹配（语序一致场景）
                for v in all_variants:
                    if v in sv or sv in v:
                        _hit = True
                        break
                # ② 核心词全含匹配（倒序/虚词差异场景）
                if not _hit and all(_tk in sv for _tk in _tokens):
                    _hit = True
                if _hit:
                    _ids.append(m.memory_id)
            if _ids:
                _res = seng.forget({"user_id": "nex_user", "memory_ids": _ids}, dry_run=False)
                print(f"[遗忘联动] strict 记忆删除: {len(_ids)} 条 ({_res.get('status', '')})",
                      flush=True)
        except Exception as _e:
            print(f"[遗忘联动] strict 删除跳过: {_e}", flush=True)
        # ④ long 库联动（三档流转后主库记忆在 long 库；遗忘只删主库会漏 long 残留，
        #   英文变体如 "User's ... residence is Guangzhou" 从 search_both 通道复活）
        #   安全：中英别名扩展 + 文本包含过滤，防误删不相关记忆
        try:
            from src.memory.memory_lifecycle import _get_long
            long_mem = _get_long()
            for t in keywords:
                t = (t or "").strip()
                if not t:
                    continue
                for kw in self._expand_keywords([t]):
                    kw = (kw or "").strip()
                    if not kw or len(kw) < 2:
                        continue
                    try:
                        _r = long_mem.search(kw, filters={"user_id": "nex_user"},
                                             limit=10, threshold=0.5)
                        _hits = _r.get("results", []) if isinstance(_r, dict) else []
                        for _it in _hits:
                            _txt = str(_it.get("memory", "") or "")
                            if kw.lower() not in _txt.lower():
                                continue
                            try:
                                long_mem.delete(_it.get("id"))
                                print(f"[遗忘联动] long 库记忆删除: {_txt[:40]}", flush=True)
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception as _e:
            print(f"[遗忘联动] long 删除跳过: {_e}", flush=True)

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
