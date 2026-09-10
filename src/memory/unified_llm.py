# -*- coding: utf-8 -*-
"""统一 LLM 适配器：把 mem0 内部的 LLM 调用（Memory Extractor 等）接到同一个 key。

背景（2026-09-10 审计）：
  · 走 src/llm_client 的调用点（主对话/记忆审查/遗忘/标题/槽位分类）受
    ~/.nex-agent/llm_config.json 控制；
  · 但 mem0 的主库、长期库、归档库此前硬编码 provider="kylin_sdk"
    （src/memory/kylin_llm.py → 麒麟千问 qwen3.7-max 免费额度），
    额度耗尽后每轮 store.add 要等 15~25s 重试，且事实提取退化为存原文。

本模块让 mem0 也走 llm_client：
  provider=api → OpenAI 兼容 API（DeepSeek/Grok…，即"选定的那把 key"）
  provider=sdk → 回退 KylinLLM（麒麟千问），保持零 key 场景可用
环境变量逃生口：
  NEX_MEM0_LLM=unified|kylin_sdk  强制指定 mem0 的 LLM 路线
"""
import os
from typing import Optional

from mem0.llms.base import LLMBase
from mem0.configs.llms.base import BaseLlmConfig


def _lc_config() -> dict:
    try:
        from src import llm_client
        return llm_client.load_config() or {}
    except Exception:
        return {}


def llm_routes() -> dict:
    """返回各 LLM 调用点的实际路线（供启动自检与 /api/llm_config 展示）。"""
    cfg = _lc_config()
    prov = str(cfg.get("provider") or "sdk")
    if prov == "api":
        main = "api:%s" % (cfg.get("api_choice") or "?")
        model = str(cfg.get("model") or "")
        base = str(cfg.get("base_url") or "")
        key = str(cfg.get("api_key") or "")
    else:
        main = "sdk:kylin"
        model = "qwen（麒麟千问）"
        base = "本机 kylin-ai-runtime"
        key = ""
    forced = (os.getenv("NEX_MEM0_LLM") or "").strip().lower()
    mem0_route = forced if forced in ("unified", "kylin_sdk") else (
        "unified" if prov == "api" else "kylin_sdk")
    return {
        "main": main,
        "model": model,
        "base_url": base,
        "api_key_tail": ("…" + key[-4:]) if key else "",
        "chat": "llm_client（%s）" % main,
        "review": "llm_client（%s）" % main,
        "forget": "llm_client（%s）" % main,
        "title": "llm_client（%s）" % main,
        "slot": "llm_client（%s）" % main,
        "mem0": ("llm_client（%s）" % main) if mem0_route == "unified"
                else "麒麟千问 SDK（qwen3.7-max，免费额度）",
        "embed": "本地 ONNX / 麒麟运行时（非 LLM，无 key）",
    }


def llm_provider_name() -> str:
    """给 mem0 配置用的 provider 名：unified（跟 key）或 kylin_sdk（千问）。"""
    return "unified" if llm_routes()["mem0"].startswith("llm_client") else "kylin_sdk"


class UnifiedLLM(LLMBase):
    """mem0 LLM 接口 → src.llm_client（统一 key）。"""

    def __init__(self, config: Optional[BaseLlmConfig] = None):
        super().__init__(config)

    def generate_response(self, messages, tools=None, tool_choice="auto", **kwargs):
        cfg = _lc_config()
        if str(cfg.get("provider")) != "api":
            # provider=sdk（或未配 key）：保持麒麟千问路线
            from src.memory.kylin_llm import KylinLLM
            return KylinLLM(self.config).generate_response(
                messages, tools=tools, tool_choice=tool_choice, **kwargs)

        system_txt, user_txt = _split_messages(messages)
        from src import llm_client
        out = llm_client.generate(user_txt, cfg, system=system_txt)
        return (out or "").strip()

    @staticmethod
    def _split(messages):
        return _split_messages(messages)


def _split_messages(messages) -> tuple[str, str]:
    """把 mem0 的 messages 拆成 (system, 其余拼接)——API 模式按角色分开发送。"""
    system_parts, other_parts = [], []
    for m in messages or []:
        role = (m.get("role") or "user") if isinstance(m, dict) else "user"
        content = (m.get("content") or "") if isinstance(m, dict) else str(m)
        if role == "system":
            system_parts.append(str(content))
        elif role == "assistant":
            other_parts.append("助手：%s" % content)
        else:
            other_parts.append("用户：%s" % content)
    return "\n".join(system_parts), "\n".join(other_parts)
