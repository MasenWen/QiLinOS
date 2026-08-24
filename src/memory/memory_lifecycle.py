# -*- coding: utf-8 -*-
"""记忆自动流转 — 融入自 QiLinOS src/memory/memory_lifecycle.py（适配 dev1）

第4层: 压缩提取 — token 超限时压缩旧消息并提取记忆
第5层: LLM 判断 — 替代固定数量阈值，用 LLM 判断是否该流转（中期 → 长期）
第6层: 时间老化 — 记忆 stale(30天) → archive(90天)

存储:
  中期: ~/.nex-agent/mem0_vectordb.db   （dev1 mem0_store 主库）
  长期: ~/.nex-agent/mem0_longterm.db   （独立库）
  归档: ~/.nex-agent/mem0_archive.db    （独立库）

适配点（相对 QiLinOS 原版）:
  - LLM 统一走 dev1 llm_client.generate（麒麟 SDK / DeepSeek API 双路径）
  - 长期/归档库沿用 dev1 的 kylin_vectordb 后端 + MEM0_DB_PATH 支持
  - 写操作带只读降级保护（mem0_store._degraded 时跳过，不静默丢记忆）
  - 线程锁防并发流转竞态（沿用 QiLinOS trigger_rotation 设计）
"""
import os
import time
import logging
import threading
from datetime import datetime, timezone

from mem0 import Memory
from mem0.configs.base import MemoryConfig

logger = logging.getLogger(__name__)

LONG_TERM_PATH = os.environ.get("NEX_LONG_TERM_PATH",
                                os.path.expanduser("~/.nex-agent/mem0_longterm.db"))
ARCHIVE_PATH = os.environ.get("NEX_ARCHIVE_PATH",
                              os.path.expanduser("~/.nex-agent/mem0_archive.db"))

# 流转触发阈值：中期记忆条数 >= THRESHOLD 时 LLM 判断
THRESHOLD = int(os.getenv("NEX_ROTATION_THRESHOLD", "10"))
# 老化：长期 > ARCHIVE_DAYS → 归档；中期 > ARCHIVE_DAYS → 清理
ARCHIVE_DAYS = int(os.getenv("NEX_ARCHIVE_DAYS", "90"))
# 流转节流间隔（秒）
ROTATION_INTERVAL_SEC = int(os.getenv("NEX_ROTATION_INTERVAL", "3600"))
# 归档检查间隔（秒）
CURATOR_INTERVAL = int(os.getenv("NEX_CURATOR_INTERVAL", "86400"))
# 压缩阈值（token 估算）
COMPRESS_THRESHOLD_TOKENS = int(os.getenv("NEX_COMPRESS_THRESHOLD", "3000"))


def _llm(prompt: str) -> str:
    """统一 LLM 调用（dev1 llm_client，麒麟 SDK / API 双路径）。"""
    from src import llm_client
    return llm_client.generate(prompt) or ""


# ---- 长期记忆实例（独立库，kylin_vectordb 后端）----
def _build_mem_config(path: str, collection: str) -> MemoryConfig:
    cfg = MemoryConfig(
        embedder={"provider": "openai", "config": {"model": "gte-base", "embedding_dims": 768}},
        vector_store={"provider": "qdrant", "config": {
            "collection_name": collection, "embedding_model_dims": 768, "path": path}},
        llm={"provider": "openai", "config": {"model": "qwen3.7-max"}},
        history_db_path=os.path.join(os.path.dirname(path), "history_" + collection + ".db"),
        version="v1.1",
    )
    cfg.embedder.provider = "kylin_sdk"
    cfg.vector_store.provider = "kylin_vectordb"
    cfg.llm.provider = "kylin_sdk"
    return cfg


_long = None
_archive = None
_mem_inst_lock = threading.Lock()


def _get_long() -> Memory:
    global _long
    if _long is None:
        with _mem_inst_lock:
            if _long is None:
                _long = Memory(_build_mem_config(LONG_TERM_PATH, "mem0_longterm"))
    return _long


def _get_archive() -> Memory:
    global _archive
    if _archive is None:
        with _mem_inst_lock:
            if _archive is None:
                _archive = Memory(_build_mem_config(ARCHIVE_PATH, "mem0_archive"))
    return _archive


def _store_ok(store) -> bool:
    """只读降级保护：主库降级时不流转（避免记忆写临时库/静默丢失）。"""
    if store is None:
        return False
    degraded = getattr(store, "_degraded", False)
    if degraded:
        logger.warning("[流转] mem0 只读降级中，跳过记忆流转（重启后恢复）")
    return not degraded


# ============================================================
# 第4层：压缩提取 — token 超限时压缩旧消息并提取记忆
# ============================================================
def compress_and_extract(messages: list, mem0_store_obj,
                         threshold_tokens: int = None) -> list:
    """token 超过阈值时压缩前半段对话并提取记忆（适配 dev1：消息对象用 content 属性）。"""
    if threshold_tokens is None:
        threshold_tokens = COMPRESS_THRESHOLD_TOKENS

    total = sum(len(str(getattr(m, "content", m))) // 4 for m in messages
                if m is not None)
    if total < threshold_tokens:
        return messages

    split = len(messages) // 2
    old = messages[:split]
    recent = messages[split:]

    try:
        old_text = "\n".join(
            f"[{getattr(m, 'name', '?')}]: {str(getattr(m, 'content', m))[:300]}"
            for m in old if m is not None)
        summary = _llm(f"用200字以内总结以下对话关键信息(偏好/知识/事实):\n{old_text}")

        if summary and is_safe(f"对话摘要：{summary}"):
            mem0_store_obj.add([
                {"role": "user", "content": f"对话摘要: {summary}"},
                {"role": "assistant", "content": "已处理"},
            ])
            summary_msg = type(old[0])(content=f"[对话摘要] {summary}", name="system") if old else None
            logger.info("[压缩] %d条消息 → 1条摘要 + 记忆提取", len(old))
            print(f"[压缩] {len(old)}条消息 → 1条摘要 + 记忆提取")
            return ([summary_msg] if summary_msg else []) + list(recent)
        else:
            logger.warning("[压缩] 摘要包含威胁内容，跳过记忆存储")
    except Exception as e:
        logger.warning("[压缩] 失败: %s", e)

    return messages


# ============================================================
# 第5层：LLM 判断 — 中期 ≥ THRESHOLD 条时压缩为长期
# ============================================================
_rotation_last_run = 0
_rotation_lock = threading.Lock()


def trigger_rotation():
    """中期记忆 ≥ THRESHOLD 条时，LLM 判断是否压缩为长期（带节流 + 线程锁）。"""
    global _rotation_last_run

    now = time.time()
    if now - _rotation_last_run < ROTATION_INTERVAL_SEC:
        return

    from src.memory.mem0_store import mem0_store
    if not _store_ok(mem0_store):
        _rotation_last_run = now
        return

    try:
        r = mem0_store._memory.get_all(filters={"user_id": "nex_user"})
        items = r.get("results", []) if isinstance(r, dict) else []
        if len(items) < THRESHOLD:
            return

        text = "\n".join(f"- {m[memory]}" for m in items)

        # LLM 判断是否值得压缩
        try:
            verdict = _llm(
                f"你是一个记忆管理助手。判断以下中期记忆是否已经积累了足够的持久用户信息，"
                f"值得压缩为长期偏好。\n\n"
                f"【判断标准】\n值得压缩（回答 是）：\n"
                f"  - 出现了 3 条以上不重复的持久信息（背景/偏好/习惯/技能）\n"
                f"  - 多条记忆指向同一个核心偏好\n"
                f"  - 记录了用户的重要身份信息（职业/角色/技能栈）\n\n"
                f"不值得压缩（回答 否）：\n"
                f"  - 大部分是单次任务记录\n  - 大部分是瞬时状态或未验证的信息\n"
                f"  - 条数虽多但信息密度低\n\n"
                f"当前记忆（{len(items)}条）:\n{text[:2000]}\n\n请只回答 是 或 否：")
            if "否" in verdict:
                _rotation_last_run = now
                return
        except Exception:
            pass  # LLM 不可用时直接流转

        with _rotation_lock:
            # 重新读取（防止锁等待期间数据已变更）
            r = mem0_store._memory.get_all(filters={"user_id": "nex_user"})
            items = r.get("results", []) if isinstance(r, dict) else []
            if len(items) < THRESHOLD:
                _rotation_last_run = time.time()
                return

            text = "\n".join(f"- {m[memory]}" for m in items)
            item_ids = [m.get("id") for m in items if m.get("id")]

            try:
                _get_long().add([{
                    "role": "user",
                    "content": (
                        "从以下中期记忆中提取用户的长期核心偏好。\n\n"
                        "【提取规则】\n应提取（只提取以下类型）：\n"
                        "1. 个人基本背景：姓名、职业、所在地、家庭、技能栈\n"
                        "2. 长期偏好：语言/格式偏好、工作风格、沟通习惯、品味\n"
                        "3. 固定工作模式：用户反复强调的行为方式或流程偏好\n\n"
                        "必须排除（不要提取）：\n"
                        "1. 瞬时情绪或状态\n2. 单次事件\n3. 临时计划\n"
                        "4. 带具体日期或时间戳的事实\n"
                        "5. 环境依赖的失败（命令不存在、包未安装）\n"
                        "6. 对工具或系统的负面声明（XX坏了、XX不可用）\n"
                        "7. 系统推荐或猜测内容\n8. 别人的推荐或建议\n\n"
                        "【输出格式】每条一行，格式：PREF: <偏好描述>，"
                        "简短精炼，每条 30 字以内，最多 5 条。"
                        "如果没有任何值得保留的长期偏好，输出一行：NOTHING\n\n"
                        f"中期记忆:\n{text}"
                    )
                }], user_id="nex_user",
                    prompt=(
                        "只提取持久稳定的用户背景、偏好、习惯。\n"
                        "排除：瞬时状态、单次事件、临时计划、带日期的事实、\n"
                        "环境错误、负面声明、系统猜测、别人的推荐。\n"
                        "输出格式：PREF: <描述>，最多5条，无可提取时输出 NOTHING。"))

                # 确认长期写入成功后，再删除中期记忆
                for mid in item_ids:
                    try:
                        mem0_store._memory.delete(mid)
                    except Exception:
                        pass

                _rotation_last_run = time.time()
                logger.info("[流转] %d条中期 → 长期 (%s)", len(items), LONG_TERM_PATH)
                print(f"[流转] {len(items)}条中期 → 长期 ({LONG_TERM_PATH})")
            except Exception as e:
                logger.warning("[流转] 长期写入失败，中期记忆保留: %s", e)
                _rotation_last_run = time.time()

    except Exception as e:
        logger.warning("[流转] 执行失败: %s", e)


# ============================================================
# 第6层：时间老化 — 长期 stale → archive；中期过期清理
# ============================================================
_curator_last_run = 0


def curator_check():
    """定期检查长期记忆，超期自动老化/归档（24h 节流）。"""
    global _curator_last_run
    if time.time() - _curator_last_run < CURATOR_INTERVAL:
        return
    _curator_last_run = time.time()

    from src.memory.mem0_store import mem0_store
    if not _store_ok(mem0_store):
        return

    try:
        # 长期 → 归档
        for mem_instance, label in [(_get_long(), "长期"), (_get_archive(), "归档")]:
            r = mem_instance.get_all(filters={"user_id": "nex_user"})
            items = r.get("results", []) if isinstance(r, dict) else []
            now = datetime.now(timezone.utc)

            for item in items:
                ts = item.get("created_at")
                if not ts:
                    continue
                try:
                    created = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                age = (now - created).days

                if label == "长期" and age > ARCHIVE_DAYS:
                    _get_archive().add([{"role": "user", "content": item["memory"]}],
                                       user_id="nex_user")
                    mem_instance.delete(item["id"])
                    logger.info("[老化] %s... → 归档", str(item["memory"])[:30])
                    print(f"[老化] {str(item[memory])[:30]}... → 归档")

        # 中期过期（> ARCHIVE_DAYS 未更新的旧记忆直接丢弃）
        r = mem0_store._memory.get_all(filters={"user_id": "nex_user"})
        items = r.get("results", []) if isinstance(r, dict) else []
        now = datetime.now(timezone.utc)
        for item in items:
            ts = item.get("created_at")
            if not ts:
                continue
            try:
                created = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if (now - created).days > ARCHIVE_DAYS:
                mem0_store._memory.delete(item["id"])
                logger.info("[清理] 过期中期记忆: %s...", str(item["memory"])[:30])
                print(f"[清理] 过期中期记忆: {str(item[memory])[:30]}...")
    except Exception as e:
        logger.warning("[老化] 检查失败: %s", e)


# ============================================================
# 检索：中期 + 长期联合召回
# ============================================================
def search_both(query: str, top_k: int = 5) -> str:
    """联合检索中期 + 长期记忆，拼成提示文本。"""
    from src.memory.mem0_store import mem0_store
    if not _store_ok(mem0_store):
        return ""
    parts = []
    try:
        mid = mem0_store.search(query, user_id="nex_user", top_k=min(3, top_k))
        for m in mid:
            parts.append(str(m.get("memory", "")))
    except Exception:
        pass
    try:
        r = _get_long().search(query, filters={"user_id": "nex_user"},
                               limit=min(2, top_k), threshold=0.5)
        for m in (r.get("results", []) if isinstance(r, dict) else []):
            parts.append(str(m.get("memory", "")))
    except Exception:
        pass
    if not parts:
        return ""
    return "[用户相关记忆]\n" + "\n".join(f"- {p}" for p in dict.fromkeys(parts))


# ============================================================
# 回合级 LLM 审查（第4层前置：从对话提取值得保存的记忆）
# ============================================================
_MEMORY_REVIEW_PROMPT = (
    "审查以下对话，提取值得持久保存的用户信息。\n\n"
    "只提取以下类型的信息：\n"
    "1. 用户明确表达的个人背景（姓名、职业、所在地、家庭等）\n"
    "2. 用户的长期偏好/习惯/品味（如喜欢喝咖啡、习惯早上工作）\n"
    "3. 用户明确表达的工作模式或行为风格（如偏好简洁回复）\n"
    "4. 用户主动分享的知识或技能（如我会Python）\n\n"
    "必须排除以下（不要保存）：\n"
    "- 瞬时情绪或状态\n- 单次事件的叙述\n- 临时计划或待办事项\n"
    "- 带具体日期或时间的事实\n- 系统推荐、猜测、提醒内容\n"
    "- 工具报错、环境问题、调试信息\n- 对工具或功能的负面声明\n"
    "- 别人的推荐内容\n\n"
    "输出格式：\n"
    "如果没有需要保存的内容，只输出一行：NOTHING_TO_SAVE\n"
    "如果需要保存，每条一行，格式为：SAVE: <记忆内容>\n"
    "每条记忆用中文，简短精炼（30字以内）。最多输出5条。\n\n"
    "对话内容：\n"
)


def review_and_save_memory(user_input: str, assistant_output: str,
                           mem0_store_obj, context: dict | None = None):
    """LLM 审查对话，只提取持久信息存入 Mem0（带重试，不阻塞主流程）。"""
    if not user_input or not user_input.strip():
        return
    from src.memory.threat_patterns import is_safe
    if not _store_ok(mem0_store_obj):
        return

    try:
        conversation = (f"用户: {user_input[:800]}\n助手: {str(assistant_output)[:800]}")
        prompt = _MEMORY_REVIEW_PROMPT + conversation

        max_retries = 2
        verdict = None
        for attempt in range(max_retries + 1):
            try:
                verdict = _llm(prompt).strip()
                break
            except Exception as e:
                if attempt < max_retries:
                    logger.debug("[审查] LLM 调用失败，重试 %d/%d: %s",
                                 attempt + 1, max_retries, e)
                    time.sleep(2)
                else:
                    logger.warning("[审查] LLM 调用失败（已达最大重试）: %s", e)
                    return

        if not verdict or "NOTHING_TO_SAVE" in verdict:
            return

        facts = []
        for line in verdict.split("\n"):
            line = line.strip()
            if line.startswith("SAVE:"):
                fact = line[5:].strip()
                if fact and len(fact) >= 3:
                    facts.append(fact)
        if not facts:
            return

        for fact in facts:
            try:
                if not is_safe(fact):
                    logger.warning("[审查] 跳过疑似威胁内容: %s", fact[:60])
                    continue
                mem0_store_obj.add([
                    {"role": "user", "content": fact},
                    {"role": "assistant", "content": "已记录"},
                ])
                logger.info("[审查] 保存: %s", fact[:50])
            except Exception as e:
                logger.warning("[审查] 保存失败 %s: %s", fact[:30], e)

        print(f"[审查] 从对话中提取了 {len(facts)} 条记忆")
        return {"status": "ok", "facts": facts}
    except Exception as e:
        logger.warning("[审查] 执行失败: %s", e)
        return {"status": "error", "error": str(e)}
