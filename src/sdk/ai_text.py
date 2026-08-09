"""
Kylin AI Text Generation SDK - ctypes Python bindings.
Wraps: coreai/text/textgeneration.h, libkysdk-coreai-text.so
Provides: text generation, chat, model config
"""
import ctypes, threading
from typing import Optional, Dict, Any, List, Tuple
from .base import load_library, _decode_cstring, declare, IS_LINUX, IS_KYLIN

_LIB = None
_CALLBACKS = {}
_lock = threading.Lock()

def _get_lib():
    global _LIB
    if _LIB is None:
        _LIB = load_library("libkysdk-coreai-text", mock=not IS_KYLIN)
    return _LIB

def create_text_session():
    """Create a text generation session. Returns session pointer as int."""
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "text_generation_create_session", restype=ctypes.c_void_p)
            ptr = lib.text_generation_create_session()
            if ptr: return ptr
        except: pass
    return None

def init_text_session(session):
    """Initialize a text generation session. Returns 0 on success."""
    if session is None: return -1
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "text_generation_init_session", restype=ctypes.c_int, argtypes=[ctypes.c_void_p])
            return lib.text_generation_init_session(session)
        except: pass
    return -1

def generate_text(prompt, session=None):
    """Generate text from a prompt. Returns generated text."""
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "text_generation_generate",
                    restype=ctypes.c_char_p,
                    argtypes=[ctypes.c_void_p, ctypes.c_char_p])
            raw = lib.text_generation_generate(session, prompt.encode() if prompt else b"")
            if raw: return _decode_cstring(raw)
        except: pass
    return _fallback_generate(prompt)

def _fallback_generate(prompt):
    """Fallback: use OpenAI-compatible API if available."""
    try:
        import os, requests
        api_key = os.getenv("BASIC_API_KEY", "")
        base_url = os.getenv("BASIC_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("BASIC_MODEL", "gpt-3.5-turbo")
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except: pass
    return ""

def chat(message, history=None, session=None):
    """Chat with the model. history is list of {role, content} dicts."""
    messages = history or []
    messages.append({"role": "user", "content": message})
    full_prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    return generate_text(full_prompt, session)

def set_model_config(model_name, deploy_type="cloud"):
    """Set model configuration globally."""
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "text_generation_model_config_set_name",
                    restype=None, argtypes=[ctypes.c_char_p])
            lib.text_generation_model_config_set_name(model_name.encode())
            return True, f"Model: {model_name}"
        except: pass
    return False, "SDK not available"

def destroy_text_session(session):
    """Destroy a text generation session."""
    if session is None: return
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "text_generation_destroy_session",
                    restype=None, argtypes=[ctypes.c_void_p])
            lib.text_generation_destroy_session(ctypes.c_void_p(session))
        except: pass

class TextSession:
    """Context manager for text generation sessions."""
    def __init__(self):
        self.session = None
    def __enter__(self):
        self.session = create_text_session()
        if self.session:
            init_text_session(self.session)
        return self
    def __exit__(self, *args):
        if self.session:
            destroy_text_session(self.session)
    def generate(self, prompt):
        return generate_text(prompt, self.session)
    def chat(self, message, history=None):
        return chat(message, history, self.session)

is_available = lambda: _get_lib() is not None
