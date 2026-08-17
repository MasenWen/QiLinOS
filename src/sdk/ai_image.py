"""
Kylin AI Image Generation SDK - ctypes Python bindings.
Wraps: genai/vision/image.h, libkysdk-genai-vision.so
Provides: text-to-image generation

注: 麒麟"图像生成"能力由 libkysdk-genai-vision 提供 (安装包: libkysdk-genai-vision-dev)，
    函数前缀为 genai_image_* / image_result_*。
    原先引用的 libkysdk-coreai-image 库并不存在，已修正为 genai-vision。
"""
import base64
import ctypes
import os as _os
import threading
from typing import List, Optional

from .base import load_library, _decode_cstring, declare, IS_KYLIN

_LIB = None
_lock = threading.Lock()
_MODEL_NAME: Optional[str] = None

# void (*ImageResultCallback)(VisionImageResult*, void*)
_ImageResultCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)


def _get_lib():
    global _LIB
    if _LIB is None:
        with _lock:
            if _LIB is None:
                try:
                    _LIB = load_library("libkysdk-genai-vision", mock=not IS_KYLIN)
                except Exception:
                    _LIB = False
    return _LIB if _LIB else None


def _declare(lib):
    """Declare genai_image_* / image_result_* signatures."""
    declare(lib, "genai_image_create_session", restype=ctypes.c_void_p)
    declare(lib, "genai_image_init_session", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "genai_image_destroy_session", restype=None,
            argtypes=[ctypes.POINTER(ctypes.c_void_p)])
    declare(lib, "genai_image_result_set_callback", restype=None,
            argtypes=[ctypes.c_void_p, _ImageResultCallback, ctypes.c_void_p])
    declare(lib, "genai_image_generate_image_async", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_char_p])
    declare(lib, "genai_image_enable_internal_event_loop", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_bool])

    declare(lib, "image_result_get_data", restype=ctypes.POINTER(ctypes.c_uint8),
            argtypes=[ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)])
    declare(lib, "image_result_get_total", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "image_result_get_index", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "image_result_get_error_code", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "image_result_get_error_message", restype=ctypes.c_char_p,
            argtypes=[ctypes.c_void_p])


class _ImageAccumulator:
    """Collect generated image bytes from streaming callbacks."""

    def __init__(self, lib):
        self._lib = lib
        self.images: List[bytes] = []
        self.error: Optional[str] = None
        self.done = threading.Event()
        self._callback = _ImageResultCallback(self._on_result)  # 保持存活，防止被 GC

    def _on_result(self, result_ptr, user_data):
        lib = self._lib
        try:
            code = lib.image_result_get_error_code(result_ptr)
            if code != 0:
                msg = lib.image_result_get_error_message(result_ptr)
                self.error = _decode_cstring(msg) if msg else f"error code {code}"
                self.done.set()
                return
            length = ctypes.c_int(0)
            data_ptr = lib.image_result_get_data(result_ptr, ctypes.byref(length))
            if data_ptr and length.value > 0:
                buf = ctypes.string_at(data_ptr, length.value)
                self.images.append(buf)
            total = lib.image_result_get_total(result_ptr)
            index = lib.image_result_get_index(result_ptr)
            if total > 0 and index >= total - 1:
                self.done.set()
        except Exception as e:  # pragma: no cover
            self.error = str(e)
            self.done.set()


def generate_image(prompt, style=None, size=None, output_path=None):
    """Generate an image from text description. Returns (success, image_data_or_path)."""
    if not prompt:
        return False, "Empty prompt"
    lib = _get_lib()
    if lib:
        try:
            _declare(lib)
            session = lib.genai_image_create_session()
            if not session:
                return False, "create session failed"
            try:
                if lib.genai_image_init_session(session) != 0:
                    return False, "init session failed"
                acc = _ImageAccumulator(lib)
                lib.genai_image_result_set_callback(session, acc._callback, None)
                lib.genai_image_enable_internal_event_loop(session, True)
                lib.genai_image_generate_image_async(session, prompt.encode("utf-8"))
                acc.done.wait(timeout=120)
                if acc.error or not acc.images:
                    return False, acc.error or "no image data"
                data = acc.images[0]
                if output_path:
                    with open(output_path, "wb") as f:
                        f.write(data)
                    return True, output_path
                return True, base64.b64encode(data).decode("ascii")
            finally:
                ptr = ctypes.c_void_p(session)
                lib.genai_image_destroy_session(ctypes.byref(ptr))
        except Exception:
            pass
    return _fallback_image(prompt, style, size, output_path)


def _fallback_image(prompt, style=None, size=None, output_path=None):
    """Fallback: use VL model API for image generation."""
    try:
        import requests
        api_key = _os.getenv("VL_API_KEY", "")
        base_url = _os.getenv("VL_BASE_URL", "")
        model = _os.getenv("VL_MODEL", "")
        if not all([api_key, base_url, model]):
            return False, "No VL API config available"
        resp = requests.post(
            f"{base_url}/services/aigc/multimodal-generation/generation",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
                  "parameters": {"size": size or "1024*1024"}},
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            img_url = data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", [{}])[0].get("image_url", "")
            if img_url:
                if output_path:
                    img_resp = requests.get(img_url, timeout=30)
                    with open(output_path, "wb") as f:
                        f.write(img_resp.content)
                    return True, output_path
                return True, img_url
    except Exception:
        pass
    return False, "Image generation failed"


def set_image_model(model_name):
    """Record the image generation model (return True if SDK is available)."""
    global _MODEL_NAME
    lib = _get_lib()
    if lib:
        _MODEL_NAME = model_name
        return True
    return False


is_available = lambda: _get_lib() is not None
