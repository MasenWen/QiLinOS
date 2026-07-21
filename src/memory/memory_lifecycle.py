"""
记忆自动流转 — 第4/5/6层
  第4层: 压缩提取 — token 超限时压缩旧消息并提取记忆
  第5层: LLM 判断 — 替代固定数量阈值，用 LLM 判断是否该流转
  第6层: 时间老化 — 记忆 stale(30天) → archive(90天)

存储:
  中期: ~/.nex-agent/mem0_vectordb.db
  长期: ~/.nex-agent/mem0_longterm.db
  归档: ~/.nex-agent/mem0_archive.db
"""
import os
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from mem0 import Memory
from mem0.configs.base import MemoryConfig
from dotenv import load_dotenv

from src.memory.threat_patterns import is_safe

load_dotenv()

logger = logging.getLogger(__name__)

LONG_TERM_PATH = os.path.expanduser("~/.nex-agent/mem0_longterm.db")
ARCHIVE_PATH = os.path.expanduser("~/.nex-agent/mem0_archive.db")
THRESHOLD = 10
STALE_DAYS = 30
ARCHIVE_DAYS = 90

# ============================================================
# 可配置参数
# ============================================================
# 压缩阈值（token 估算），根据模型上下文窗口调整
COMPRESS_THRESHOLD_TOKENS = int(os.getenv("NEX_COMPRESS_THRESHOLD", "3000"))
# 流转节流间隔（秒），两次 trigger_rotation 之间最小间隔
ROTATION_INTERVAL_SEC = int(os.getenv("NEX_ROTATION_INTERVAL", "3600"))

import src.memory  # noqa

QWEN_KEY = os.getenv("QWEN_API_KEY", "")

# ---- 长期记忆实例 ----
_long_cfg = MemoryConfig(
    embedder={"provider": "openai", "config": {"model": "gte-base", "embedding_dims": 768}},
    vector_store={"provider": "qdrant",
                  "config": {"collection_name": "mem0_longterm",
                             "embedding_model_dims": 768,
                             "path": LONG_TERM_PATH}},
    llm={"provider": "openai", "config": {"model": "qwen3.7-max",
         "api_key": QWEN_KEY,
         "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"}},
    history_db_path=os.path.expanduser("~/.nex-agent/mem0/history_long.db"),
    version="v1.1",
)
_long_cfg.embedder.provider = "kylin_sdk"
_long_cfg.vector_store.provider = "kylin_vectordb"
_long = Memory(_long_cfg)

# ---- 归档记忆实例 ----
_archive_cfg = MemoryConfig(
    embedder={"provider": "openai", "config": {"model": "gte-base", "embedding_dims": 768}},
    vector_store={"provider": "qdrant",
                  "config": {"collection_name": "mem0_archive",
                             "embedding_model_dims": 768,
                             "path": ARCHIVE_PATH}},
    llm={"provider": "openai", "config": {"model": "qwen3.7-max",
         "api_key": QWEN_KEY,
         "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"}},
    history_db_path=os.path.expanduser("~/.nex-agent/mem0/history_archive.db"),
    version="v1.1",
)
_archive_cfg.embedder.provider = "kylin_sdk"
_archive_cfg.vector_store.provider = "kylin_vectordb"
_archive = Memory(_archive_cfg)


# ============================================================
# 回合级 LLM 审查
# ============================================================
_MEMORY_REVIEW_PROMPT = (
    "审查以下对话，提取值得持久保存的用户信息。\n\n"
    "只提取以下类型的信息：\n"
    "1. 用户明确表达的个人背景（姓名、职业、所在地、家庭等）\n"
    "2. 用户的长期偏好/习惯/品味（如'喜欢喝咖啡'、'习惯早上工作'）\n"
    "3. 用户明确表达的工作模式或行为风格（如'偏好简洁回复'、'一次只做一件事'）\n"
    "4. 用户主动分享的知识或技能（如'我会Python'、'我在学日语'）\n\n"
    "必须排除以下（不要保存）：\n"
    "- 瞬时情绪或状态（'今天很累'、'现在很开心'）\n"
    "- 单次事件的叙述（'我昨天去了公园'、'我刚吃了一顿饭'）\n"
    "- 临时计划或待办事项（'我今晚要做报表'、'本周要交报告'）\n"
    "- 带具体日期或时间的事实\n"
    "- 系统推荐、猜测、提醒内容\n"
    "- 工具报错、环境问题、调试信息\n"
    "  （这些是环境问题，用户解决了就不该记，记下来会在未来变成自证预言）\n"
    "- 对工具或功能的负面声明（'XX坏了'、'XX不可用'）\n"
    "  （即使现在的确有问题，记下来后未来修复了你也不会再尝试）\n"
    "- 别人的推荐内容（'朋友推荐我喝...'）——这些不是你用户自己的偏好\n\n"
    "输出格式：\n"
    "如果没有需要保存的内容，只输出一行：NOTHING_TO_SAVE\n"
    "如果需要保存，每条一行，格式为：SAVE: <记忆内容>\n"
    "每条记忆用中文，简短精炼（30字以内）。最多输出5条。\n\n"
    "对话内容：\n"
)


def review_and_save_memory(user_input: str, assistant_output: str, mem0_store_obj):
    """LLM 审查对话，只提取持久信息存入 Mem0。

    通过 LLM 判断什么值得保存，什么只是瞬时噪音。
    带重试机制应对网络波动。
    """
    if not user_input or not user_input.strip():
        return

    try:
        from src.agent.llm import basic_llm

        # 构建审查消息
        conversation = (
            f"用户: {user_input[:800]}\n"
            f"助手: {str(assistant_output)[:800]}"
        )
        prompt = _MEMORY_REVIEW_PROMPT + conversation

        # 带重试的 LLM 调用
        max_retries = 2
        verdict = None
        for attempt in range(max_retries + 1):
            try:
                verdict = basic_llm.invoke(prompt).content.strip()
                break  # 成功则跳出
            except Exception as e:
                if attempt < max_retries:
                    logger.debug("[审查] LLM 调用失败，重试 %d/%d: %s", attempt + 1, max_retries, e)
                    import time
                    time.sleep(2)
                else:
                    logger.warning("[审查] LLM 调用失败（已达最大重试）: %s", e)
                    return  # 网络不行就放弃，不阻塞主流程

        if not verdict:
            return

        if "NOTHING_TO_SAVE" in verdict:
            logger.debug("[审查] 无需保存")
            return

        # 解析 SAVE 行
        facts = []
        for line in verdict.split("\n"):
            line = line.strip()
            if line.startswith("SAVE:"):
                fact = line[5:].strip()
                if fact and len(fact) >= 3:  # 至少要有内容
                    facts.append(fact)

        if not facts:
            return

        # 逐条存入 Mem0（每条作为独立记忆）
        for fact in facts:
            try:
                # --- 写入前扫描
                if not is_safe(fact):
                    logger.warning("[审查] 跳过疑似威胁内容: %s", fact[:60])
                    print(f"[审查] ⚠ 已拦截不安全记忆: {fact[:40]}...")
                    continue

                mem0_store_obj.add([
                    {"role": "user", "content": fact},
                    {"role": "assistant", "content": "已记录"},
                ])
                logger.info("[审查] 保存: %s", fact[:50])
            except Exception as e:
                logger.warning("[审查] 保存失败 '%s': %s", fact[:30], e)

        print(f"[审查] 从对话中提取了 {len(facts)} 条记忆")

    except Exception as e:
        logger.warning("[审查] 执行失败: %s", e)


# ============================================================
# 对话压缩提取 — token 超限时抢救即将丢弃的消息
# ============================================================
def compress_and_extract(messages: list, mem0_store_obj,
                         threshold_tokens: int = None) -> list:
    """token 超过阈值时压缩前半段对话并提取记忆"""
    if threshold_tokens is None:
        threshold_tokens = COMPRESS_THRESHOLD_TOKENS

    total = sum(len(str(m.content)) // 4 for m in messages if hasattr(m, 'content'))
    if total < threshold_tokens:
        return messages

    # 取前 50% 消息压缩
    split = len(messages) // 2
    old = messages[:split]
    recent = messages[split:]

    try:
        from src.agent.llm import basic_llm
        old_text = "\n".join(
            f"[{getattr(m, 'name', '?')}]: {str(m.content)[:300]}"
            for m in old if hasattr(m, 'content'))
        summary = basic_llm.invoke(
            f"用200字以内总结以下对话关键信息(偏好/知识/事实):\n{old_text}"
        ).content

        # --- 写入前扫描
        if is_safe(f"对话摘要：{summary}"):
            # 从摘要中提取记忆
            mem0_store_obj.add([
                {"role": "user", "content": f"对话摘要: {summary}"},
                {"role": "assistant", "content": "已处理"},
            ])
            from langchain_core.messages import HumanMessage
            summary_msg = HumanMessage(
                content=f"[对话摘要] {summary}", name="system")
            logger.info("[压缩] %d条消息 → 1条摘要 + 记忆提取", len(old))
            print(f"[压缩] {len(old)}条消息 → 1条摘要 + 记忆提取")
            return [summary_msg] + list(recent)
        else:
            logger.warning("[压缩] 摘要包含威胁内容，跳过记忆存储")
    except Exception as e:
        logger.warning("[压缩] 失败: %s", e)

    return messages


# ============================================================
# LLM 判断
# ============================================================
_rotation_last_run = 0
_rotation_lock = threading.Lock()


def trigger_rotation():
    """中期记忆 ≥ THRESHOLD 条时，LLM 判断是否压缩为长期。

    带节流控制：两次执行之间至少间隔 ROTATION_INTERVAL_SEC 秒。
    带线程锁：防止并发写入中期记忆时出现竞态条件。
    """
    global _rotation_last_run

    # 节流检查
    now = time.time()
    if now - _rotation_last_run < ROTATION_INTERVAL_SEC:
        return

    from src.memory.mem0_store import mem0_store
    try:
        r = mem0_store._memory.get_all(filters={"user_id": "nex_user"})
        items = r.get("results", []) if isinstance(r, dict) else []
        if len(items) < THRESHOLD:
            return

        text = "\n".join(f"- {m['memory']}" for m in items)

        # LLM 判断是否值得压缩
        try:
            from src.agent.llm import basic_llm
            verdict = basic_llm.invoke(
                f"你是一个记忆管理助手。判断以下中期记忆是否已经积累了足够的持久用户信息，"
                f"值得压缩为长期偏好。\n\n"
                f"【判断标准】\n"
                f"值得压缩（回答 是）：\n"
                f"  - 出现了 3 条以上不重复的持久信息（背景/偏好/习惯/技能）\n"
                f"  - 多条记忆指向同一个核心偏好（如多次提到喜欢简洁回复）\n"
                f"  - 记录了用户的重要身份信息（职业/角色/技能栈）\n\n"
                f"不值得压缩（回答 否）：\n"
                f"  - 大部分是单次任务记录（比如查询天气、下载文件等）\n"
                f"  - 大部分是瞬时状态或未验证的信息\n"
                f"  - 条数虽多但信息密度低\n\n"
                f"当前记忆（{len(items)}条）:\n{text[:2000]}\n\n"
                f"请只回答 是 或 否："
            ).content
            if "否" in verdict:
                _rotation_last_run = now  # 即使跳过也记录时间
                return
        except Exception:
            pass  # LLM 不可用时直接流转

        # 加锁保护：先提取长期记忆 → 确认写入成功 → 再删除中期
        with _rotation_lock:
            # 重新读取（防止锁等待期间数据已变更）
            r = mem0_store._memory.get_all(filters={"user_id": "nex_user"})
            items = r.get("results", []) if isinstance(r, dict) else []
            if len(items) < THRESHOLD:
                _rotation_last_run = time.time()
                return

            text = "\n".join(f"- {m['memory']}" for m in items)
            item_ids = [m.get("id") for m in items if m.get("id")]

            try:
                _long.add([{
                    "role": "user",
                    "content": (
                        "从以下中期记忆中提取用户的长期核心偏好。\n\n"
                        "【提取规则】\n"
                        "应提取（只提取以下类型）：\n"
                        "1. 个人基本背景：姓名、职业、所在地、家庭、技能栈\n"
                        "2. 长期偏好：语言/格式偏好、工作风格、沟通习惯、品味\n"
                        "3. 固定工作模式：用户反复强调的行为方式或流程偏好\n\n"
                        "必须排除（不要提取）：\n"
                        "1. 瞬时情绪或状态（今天很累/很开心/有点懵）\n"
                        "2. 单次事件（某天做了某事、某次对话的内容）\n"
                        "3. 临时计划（今晚/本周/近期要做的具体任务）\n"
                        "4. 带具体日期或时间戳的事实\n"
                        "5. 环境依赖的失败（某个命令不存在、某个包未安装）\n"
                        "   —— 这些是环境问题，用户装好就解决了，不应固化为记忆\n"
                        "6. 对工具或系统的负面声明（XX工具坏了、XX功能不可用）\n"
                        "   —— 这些会在未来会话变成自证预言，即使问题已修复\n"
                        "7. 系统推荐或猜测内容（系统建议你...、根据分析你可能...）\n"
                        "8. 别人的推荐或建议（朋友说...、某人推荐...）\n"
                        "   —— 这不是用户自己的偏好\n\n"
                        "【输出格式】\n"
                        "每条一行，格式：PREF: <偏好描述>\n"
                        "简短精炼，每条 30 字以内。最多输出 5 条。\n"
                        "如果没有任何值得保留的长期偏好，输出一行：NOTHING\n\n"
                        f"中期记忆:\n{text}"
                    )
                }], user_id="nex_user",
                    prompt=(
                        "只提取持久稳定的用户背景、偏好、习惯。\n"
                        "排除：瞬时状态、单次事件、临时计划、带日期的事实、\n"
                        "环境错误、负面声明、系统猜测、别人的推荐。\n"
                        "输出格式：PREF: <描述>，最多5条，无可提取时输出 NOTHING。"
                    ))

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
# 第6层：时间老化 — stale(30天) → archive(90天)
# ============================================================
_curator_last_run = 0
CURATOR_INTERVAL = 86400  # 24小时检查一次


def curator_check():
    """定期检查长期记忆，超期自动老化/归档"""
    global _curator_last_run
    if time.time() - _curator_last_run < CURATOR_INTERVAL:
        return
    _curator_last_run = time.time()

    from src.memory.mem0_store import mem0_store
    try:
        # 检查长期记忆
        for mem_instance, label in [(_long, "长期"), (_archive, "归档")]:
            r = mem_instance.get_all(
                filters={"user_id": "nex_user"})
            items = r.get("results", []) if isinstance(r, dict) else []
            now = datetime.now(timezone.utc)

            for item in items:
                ts = item.get("created_at")
                if not ts:
                    continue
                try:
                    created = datetime.fromisoformat(
                        ts.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                age = (now - created).days

                if label == "长期" and age > ARCHIVE_DAYS:
                    # 长期 → 归档
                    _archive.add([{"role": "user", "content": item["memory"]}],
                                 user_id="nex_user")
                    mem_instance.delete(item["id"])
                    logger.info("[老化] %s... → 归档", item['memory'][:30])
                    print(f"[老化] {item['memory'][:30]}... → 归档")

        # 检查中期过期 (90天未更新的旧记忆直接丢弃)
        r = mem0_store._memory.get_all(
            filters={"user_id": "nex_user"})
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
                logger.info("[清理] 过期中期记忆: %s...", item['memory'][:30])
                print(f"[清理] 过期中期记忆: {item['memory'][:30]}...")
    except Exception as e:
        logger.warning("[老化] 检查失败: %s", e)


# ============================================================
# 联合检索：中期 + 长期
# ============================================================
def search_both(query: str) -> str:
    """同时检索中期+长期"""
    from src.memory.mem0_store import mem0_store
    mid = mem0_store.search(query, user_id="nex_user", top_k=3)
    r = _long.search(query, filters={"user_id": "nex_user"}, limit=2, threshold=0.5)
    long_items = r.get("results", []) if isinstance(r, dict) else []
    lines = []
    if long_items:
        lines.append("[核心偏好]")
        for m in long_items:
            mem_text = m['memory']
            if not is_safe(mem_text):
                mem_text = "[已过滤: 内容匹配安全规则]"
            lines.append(f"- {mem_text}")
    if mid:
        lines.append("[近期记忆]")
        for m in mid:
            mem_text = m['memory']
            if not is_safe(mem_text):
                mem_text = "[已过滤: 内容匹配安全规则]"
            lines.append(f"- {mem_text}")
    return "\n".join(lines)


# ============================================================
# 自然语言精准遗忘
# ============================================================
def forget_by_keyword(keyword: str, dry_run: bool = True) -> dict:
    """
    自然语言精准遗忘：
    1. 用关键词检索中期和长期记忆
    2. dry_run=True → 返回候选列表
    3. dry_run=False → 直接删除全部匹配记忆
    """
    from src.memory.mem0_store import mem0_store

    # 分别检索中期和长期，收集结构化结果
    candidates = []
    # 中期
    mid_items = mem0_store.search(keyword, user_id="nex_user", top_k=5)
    for m in mid_items:
        candidates.append({
            "id": m.get("id", ""),
            "text": m.get("memory", ""),
            "score": m.get("score", 0),
            "tier": "中期",
        })
    # 长期
    r = _long.search(keyword, filters={"user_id": "nex_user"}, limit=5, threshold=0.5)
    long_items = r.get("results", []) if isinstance(r, dict) else []
    for m in long_items:
        candidates.append({
            "id": m.get("id", ""),
            "text": m.get("memory", ""),
            "score": m.get("score", 0),
            "tier": "长期",
        })

    if not candidates:
        return {"deleted": 0, "message": "未找到匹配的记忆", "candidates": []}

    if dry_run:
        return {
            "deleted": 0,
            "candidates": candidates,
            "message": f"找到 {len(candidates)} 条候选记忆，请确认后删除",
        }

    deleted = 0
    for c in candidates:
        try:
            if not c["id"]:
                continue
            if c["tier"] == "中期":
                mem0_store._memory.delete(c["id"])
            elif c["tier"] == "长期":
                _long.delete(c["id"])
            deleted += 1
        except Exception as e:
            logger.warning("[遗忘] 删除失败 %s: %s", c["id"], e)

    return {"deleted": deleted, "message": f"已删除 {deleted} 条记忆"}

def _get_long_store():
    """暴露长期存储实例，供 forget_by_keyword 使用"""
    return _long