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
    # 预置 OpenAI 兼容 API（deepseek + grok），provider=api 时可用 api_choice 切换
    "api_providers": {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "",   # 真实 key 在 ~/.nex-agent/llm_config.json（不入库）
            "model": "deepseek-v4-flash",
        },
        "grok": {
            "base_url": "https://api.x.ai/v1",
            "api_key": "",   # 真实 key 在 ~/.nex-agent/llm_config.json（不入库）
            "model": "grok-4",
        },
    },
    "api_choice": "deepseek",
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
            # api_providers 深合并（配置文件中的真实 key 覆盖占位符）
            _fp = d.get("api_providers") or {}
            if _fp:
                _merged = {}
                for _pk, _pv in (cfg.get("api_providers") or {}).items():
                    _merged[_pk] = dict(_pv)
                for _pk, _pv in _fp.items():
                    _merged.setdefault(_pk, {})
                    _merged[_pk].update({kk: vv for kk, vv in _pv.items() if vv})
                cfg["api_providers"] = _merged
    except Exception:
        pass
    # api_choice 选中的预置 provider 生效（覆盖 base_url/api_key/model）
    if cfg.get("provider") == "api":
        choice = cfg.get("api_choice") or "deepseek"
        prov = (cfg.get("api_providers") or {}).get(choice) or {}
        if prov:
            cfg["base_url"] = prov.get("base_url") or cfg["base_url"]
            cfg["api_key"] = prov.get("api_key") or cfg["api_key"]
            cfg["model"] = prov.get("model") or cfg["model"]
    # 安全加固（2026-08-30）：环境变量覆盖 API Key（systemd 注入，key 可不落盘）
    _env_key = os.getenv("NEX_DEEPSEEK_API_KEY") or ""
    _env_grok = os.getenv("NEX_GROK_API_KEY") or ""
    if cfg.get("provider") == "api":
        if cfg.get("api_choice") == "deepseek" and _env_key:
            cfg["api_key"] = _env_key
        if cfg.get("api_choice") == "grok" and _env_grok:
            cfg["api_key"] = _env_grok
    # 同时回填 api_providers（回退链用）
    _provs = cfg.get("api_providers") or {}
    if _env_key and "deepseek" in _provs:
        _provs["deepseek"]["api_key"] = _env_key
    if _env_grok and "grok" in _provs:
        _provs["grok"]["api_key"] = _env_grok
    return cfg


def save_config(cfg: dict) -> None:
    """持久化 LLM 配置。"""
    with _lock:
        os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        # 安全加固（2026-08-30）：含 API Key 的配置仅属主可读写
        try:
            os.chmod(_CONFIG_PATH, 0o600)
        except Exception:
            pass


def generate(prompt: str, cfg_override: dict | None = None,
             system: str = "") -> str:
    """统一文本生成入口。cfg_override 可覆盖全局配置（会话级作用域，dsh scope）。

    system: 可选的系统提示词。API 模式按 role 拆分发送（system/user）；
            SDK 模式拼接在 prompt 前（麒麟 SDK 仅接受单文本）。
    """
    if not prompt:
        return ""
    cfg = cfg_override or load_config()
    if cfg.get("provider") == "api" and cfg.get("api_key"):
        # 失败回退：当前 API 调用失败/超时 → 自动尝试其他预置 provider → 最后回退麒麟 SDK
        try:
            return _api_generate(prompt, cfg, system=system)
        except Exception as e:
            print(f"[llm] API 调用失败({cfg.get('api_choice')}): {str(e)[:80]}，尝试回退", flush=True)
            _provs = cfg.get("api_providers") or {}
            _choice = cfg.get("api_choice") or ""
            for _key, _p in _provs.items():
                if _key == _choice or not (_p.get("api_key") or ""):
                    continue
                print(f"[llm] 回退到 {_key}", flush=True)
                try:
                    _fall = dict(cfg)
                    _fall["api_choice"] = _key
                    _fall["base_url"] = _p.get("base_url") or _fall["base_url"]
                    _fall["api_key"] = _p.get("api_key") or _fall["api_key"]
                    _fall["model"] = _p.get("model") or _fall["model"]
                    return _api_generate(prompt, _fall, system=system)
                except Exception as e2:
                    print(f"[llm] 回退 {_key} 也失败: {str(e2)[:60]}", flush=True)
            print("[llm] 全部 API 失败，回退麒麟 SDK", flush=True)
    # 默认路径：麒麟 SDK（拼接 system + user）
    if system:
        prompt = system + "\n\n" + prompt
    from src.sdk import ai_text
    with ai_text.TextSession() as t:
        return t.generate(prompt)


def _api_generate(prompt: str, cfg: dict, system: str = "") -> str:
    """OpenAI 兼容接口调用（DeepSeek/OpenAI/通义等），支持 system/user 角色拆分。"""
    import requests
    base = (cfg.get("base_url") or DEFAULTS["base_url"]).rstrip("/")
    model = cfg.get("model") or DEFAULTS["model"]
    temperature = float(cfg.get("temperature") or 0.7)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages}
    if 0 <= temperature <= 2:
        payload["temperature"] = temperature
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json=payload,
        timeout=int(os.getenv("NEX_API_TIMEOUT", "45")),  # 45s，失败快速回退
    )
    resp.raise_for_status()
    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        return f"（API 返回异常: {e}）"
