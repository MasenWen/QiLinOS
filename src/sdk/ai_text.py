"""
Kylin AI Text Generation SDK - ctypes Python bindings.
Wraps: genai/text/chat.h, libkysdk-genai-nlp.so
Provides: text generation, chat, model config

注: 麒麟"文本生成"能力由 libkysdk-genai-nlp 提供 (安装包: libkysdk-genai-nlp-dev)，
    头文件为 <kylin-ai/genai/text/chat.h>，函数前缀为 genai_text_* / chat_model_config_*。
    原先引用的 libkysdk-coreai-text 库并不存在，已修正为 genai-nlp。
"""
import ctypes
import threading
from typing import Optional, List

from .base import load_library, _decode_cstring, declare, IS_KYLIN

_LIB = None
_lock = threading.Lock()

# void (*ChatResultCallback)(ChatResult*, void*)
_ChatResultCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)

# ModelDeployType (common/enums.h): OnDevice=0, PublicCloud=1, PrivateCloud=2
_DEPLOY_TYPE = {"local": 0, "ondevice": 0, "cloud": 1, "public": 1, "private": 2}

# 模块级默认模型配置，在 init_text_session 成功后应用
_MODEL_NAME: Optional[str] = None
_MODEL_DEPLOY_TYPE = 1  # PublicCloud


def _get_lib():
    global _LIB
    if _LIB is None:
        with _lock:
            if _LIB is None:
                try:
                    _LIB = load_library("libkysdk-genai-nlp", mock=not IS_KYLIN)
                except Exception:
                    _LIB = False
    return _LIB if _LIB else None


def _declare(lib):
    """Declare all genai_text / chat_model_config / chat_result signatures."""
    declare(lib, "genai_text_create_session", restype=ctypes.c_void_p)
    declare(lib, "genai_text_init_session", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "genai_text_destroy_session", restype=None,
            argtypes=[ctypes.POINTER(ctypes.c_void_p)])
    declare(lib, "genai_text_result_set_callback", restype=None,
            argtypes=[ctypes.c_void_p, _ChatResultCallback, ctypes.c_void_p])
    declare(lib, "genai_text_enable_internal_event_loop", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_bool])
    declare(lib, "genai_text_generate_content_async", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_char_p])
    declare(lib, "genai_text_chat_async", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_char_p])
    declare(lib, "genai_text_clear_chat_history_messages", restype=None,
            argtypes=[ctypes.c_void_p])
    declare(lib, "genai_text_set_model_config", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_void_p])

    declare(lib, "chat_model_config_create", restype=ctypes.c_void_p)
    declare(lib, "chat_model_config_destroy", restype=None,
            argtypes=[ctypes.POINTER(ctypes.c_void_p)])
    declare(lib, "chat_model_config_set_name", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_char_p])
    declare(lib, "chat_model_config_set_deploy_type", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_int])

    declare(lib, "chat_result_get_assistant_message", restype=ctypes.c_char_p,
            argtypes=[ctypes.c_void_p])
    declare(lib, "chat_result_get_error_code", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "chat_result_get_error_message", restype=ctypes.c_char_p,
            argtypes=[ctypes.c_void_p])
    declare(lib, "chat_result_get_is_end", restype=ctypes.c_bool,
            argtypes=[ctypes.c_void_p])


class _ResultAccumulator:
    """Collect streaming callbacks into a single final string."""

    def __init__(self, lib):
        self._lib = lib
        self._parts: List[str] = []
        self.error: Optional[str] = None
        self.done = threading.Event()
        self._callback = _ChatResultCallback(self._on_result)  # 保持存活，防止被 GC

    def _on_result(self, result_ptr, user_data):
        lib = self._lib
        try:
            code = lib.chat_result_get_error_code(result_ptr)
            if code != 0:
                msg = lib.chat_result_get_error_message(result_ptr)
                self.error = _decode_cstring(msg) if msg else f"error code {code}"
                self.done.set()
                return
            msg = lib.chat_result_get_assistant_message(result_ptr)
            if msg:
                text = _decode_cstring(msg)
                if text:
                    self._parts.append(text)
            if lib.chat_result_get_is_end(result_ptr):
                self.done.set()
        except Exception as e:  # pragma: no cover
            self.error = str(e)
            self.done.set()


def create_text_session():
    """Create a text generation session. Returns session pointer as int."""
    lib = _get_lib()
    if lib:
        try:
            _declare(lib)
            return lib.genai_text_create_session()
        except Exception:
            pass
    return None


def init_text_session(session):
    """Initialize a text generation session. Returns 0 on success."""
    if session is None:
        return -1
    lib = _get_lib()
    if lib:
        try:
            _declare(lib)
            ret = lib.genai_text_init_session(session)
            if ret == 0 and _MODEL_NAME:
                _apply_model_config(lib, session)
            return ret
        except Exception:
            pass
    return -1


def _apply_model_config(lib, session):
    """Apply the stored module-level model config to a session."""
    config = lib.chat_model_config_create()
    if not config:
        return
    try:
        lib.chat_model_config_set_name(config, _MODEL_NAME.encode("utf-8"))
        lib.chat_model_config_set_deploy_type(config, _MODEL_DEPLOY_TYPE)
        lib.genai_text_set_model_config(session, config)
    finally:
        lib.chat_model_config_destroy(ctypes.byref(config))


def _run_async(lib, session, text, chat_mode):
    """Run an async generation and block until the final result."""
    acc = _ResultAccumulator(lib)
    lib.genai_text_result_set_callback(session, acc._callback, None)
    lib.genai_text_enable_internal_event_loop(session, True)
    if chat_mode:
        lib.genai_text_chat_async(session, text.encode("utf-8"))
    else:
        lib.genai_text_generate_content_async(session, text.encode("utf-8"))
    acc.done.wait(timeout=120)
    if acc.error:
        return ""
    return "".join(acc._parts)


def generate_text(prompt, session=None):
    """Generate text from a prompt. Returns generated text."""
    if not prompt:
        return ""
    lib = _get_lib()
    if lib and session:
        try:
            _declare(lib)
            result = _run_async(lib, session, prompt, chat_mode=False)
            if result:
                return result
        except Exception:
            pass
    return _fallback_generate(prompt)


def _fallback_generate(prompt):
    """Fallback: use OpenAI-compatible API if available."""
    try:
        import os, requests
        api_key = os.getenv("BASIC_API_KEY", "")
        base_url = os.getenv("BASIC_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("BASIC_MODEL", "gpt-3.5-turbo")
        if not api_key:
            return ""
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return ""


def chat(message, history=None, session=None):
    """Chat with the model. history is list of {role, content} dicts."""
    if not message:
        return ""
    lib = _get_lib()
    if lib and session:
        try:
            _declare(lib)
            result = _run_async(lib, session, message, chat_mode=True)
            if result:
                return result
        except Exception:
            pass
    messages = history or []
    messages.append({"role": "user", "content": message})
    full_prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    return _fallback_generate(full_prompt)


def set_model_config(model_name, deploy_type="cloud"):
    """Set model configuration (applied on next session init)."""
    global _MODEL_NAME, _MODEL_DEPLOY_TYPE
    lib = _get_lib()
    if lib:
        _MODEL_NAME = model_name
        _MODEL_DEPLOY_TYPE = _DEPLOY_TYPE.get(deploy_type, 1)
        return True, f"Model: {model_name}"
    return False, "SDK not available"


def destroy_text_session(session):
    """Destroy a text generation session."""
    if session is None:
        return
    lib = _get_lib()
    if lib:
        try:
            _declare(lib)
            ptr = ctypes.c_void_p(session)
            lib.genai_text_destroy_session(ctypes.byref(ptr))
        except Exception:
            pass


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
