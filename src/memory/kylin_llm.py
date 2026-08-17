"""麒麟千问 LLM — Mem0 LLMBase 适配器（用 ai_text SDK，零外部 key）。

mem0 需要 LLM 来把对话提炼成记忆事实。这里用麒麟 ai_text SDK（千问）
替代 OpenAI 兼容接口，全程零 API key、纯本地 SDK。
"""
from typing import Optional

from mem0.llms.base import LLMBase
from mem0.configs.llms.base import BaseLlmConfig

from src.sdk import ai_text


class KylinLLM(LLMBase):
    """把麒麟 ai_text SDK（千问）包装成 mem0 的 LLM 接口。"""

    def __init__(self, config: Optional[BaseLlmConfig] = None):
        super().__init__(config)

    def generate_response(self, messages, tools=None, tool_choice="auto", **kwargs):
        prompt = self._build_prompt(messages)
        with ai_text.TextSession() as t:
            reply = t.generate(prompt)
        return (reply or "").strip()

    @staticmethod
    def _build_prompt(messages):
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                parts.append(f"系统指令：{content}")
            elif role == "assistant":
                parts.append(f"助手：{content}")
            else:
                parts.append(f"用户：{content}")
        return "\n".join(parts)
