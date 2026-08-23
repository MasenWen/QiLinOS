# -*- coding: utf-8 -*-
"""统一 LLM 客户端：默认麒麟 SDK，可切换 OpenAI 兼容 API。

配置存储: ~/.nex-agent/llm_config.json
  {"provider": "sdk"|"api", "base_url": "...", "api_key": "...", "model": "..."}

- provider == "sdk"（默认）: 走麒麟 SDK（src.sdk.ai_text.TextSession）
- provider == "api"       : 走 OpenAI 兼容接口（DeepSeek/OpenAI 等），
                            base_url 默认 https://api.deepseek.com/v1
"""
import json
import os
import threading

_CONFIG_PATH = os.path.expanduser("~/.nex-agent/llm_config.json")
_lock = threading.Lock()

DEFAULTS = {
    "provider": "sdk",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "temperature": 0.7,
}


def load_config() -> dict:
    """读取 LLM 配置（缺省回退到 sdk）。"""
    cfg = dict(DEFAULTS)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k in DEFAULTS:
                if d.get(k) is not None:
                    cfg[k] = d[k]
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    """持久化 LLM 配置。"""
    with _lock:
        os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)


def generate(prompt: str, cfg_override: dict | None = None) -> str:
    """统一文本生成入口。cfg_override 可覆盖全局配置（会话级作用域，dsh scope）。"""
    if not prompt:
        return ""
    cfg = cfg_override or load_config()
    if cfg.get("provider") == "api" and cfg.get("api_key"):
        return _api_generate(prompt, cfg)
    # 默认路径：麒麟 SDK
    from src.sdk import ai_text
    with ai_text.TextSession() as t:
        return t.generate(prompt)


def _api_generate(prompt: str, cfg: dict) -> str:
    """OpenAI 兼容接口调用（DeepSeek/OpenAI/通义等）。"""
    import requests
    base = (cfg.get("base_url") or DEFAULTS["base_url"]).rstrip("/")
    model = cfg.get("model") or DEFAULTS["model"]
    temperature = float(cfg.get("temperature") or 0.7)
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if 0 <= temperature <= 2:
        payload["temperature"] = temperature
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json=payload,
        timeout=180,
    )
    resp.raise_for_status()
    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        return f"（API 返回异常: {e}）"
