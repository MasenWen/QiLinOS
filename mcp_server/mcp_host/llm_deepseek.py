from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import httpx

DS_API_KEY = os.getenv("DS_API_KEY", "<API_KEY>")
DS_API_BASE = os.getenv("DS_API_BASE", "https://api.deepseek.com/v1")
DS_API_MODEL = os.getenv("DS_API_MODEL", "deepseek-chat")


class DeepSeekClient:
    def __init__(self, api_key: str = DS_API_KEY, base_url: str = DS_API_BASE, model: str = DS_API_MODEL):
        if not api_key:
            raise RuntimeError("DS_API_KEY 未设置")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def chat_json(self, messages: List[Dict[str, Any]], timeout_ms: int = 60000) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 1000,
            "stream": False,
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        timeout = httpx.Timeout(timeout_ms / 1000.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            data = r.json()
        content = data["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except Exception:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start : end + 1])
            raise

    async def chat_text_stream(self, messages: List[Dict[str, Any]], timeout_ms: int = 60000) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {"model": self.model, "messages": messages, "max_tokens": 1000, "stream": True}
        timeout = httpx.Timeout(timeout_ms / 1000.0, connect=10.0)
        out_parts: List[str] = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=self._headers(), json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        line = line[len("data: "):].strip()
                    if line == "[DONE]":
                        break
                    try:
                        evt = json.loads(line)
                        delta = evt["choices"][0].get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            out_parts.append(piece)
                    except Exception:
                        continue

        return "".join(out_parts)
