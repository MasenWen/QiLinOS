"""
Kylin AI Image Generation SDK - ctypes Python bindings.
Wraps: coreai/image/imagegeneration.h
Provides: text-to-image generation
"""
import ctypes, base64, os as _os
from typing import Optional, Tuple
from .base import load_library, _decode_cstring, declare, IS_LINUX, IS_KYLIN

_LIB = None

def _get_lib():
    global _LIB
    if _LIB is None:
        _LIB = load_library("libkysdk-coreai-image", mock=not IS_KYLIN)
    return _LIB

def generate_image(prompt, style=None, size=None, output_path=None):
    """Generate an image from text description. Returns (success, image_data_or_path)."""
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "image_generation_generate",
                    restype=ctypes.c_char_p,
                    argtypes=[ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p])
            style_bytes = (style or "default").encode()
            size_bytes = (size or "1024x1024").encode()
            raw = lib.image_generation_generate(prompt.encode(), style_bytes, size_bytes)
            if raw:
                data = _decode_cstring(raw)
                if output_path:
                    img_data = base64.b64decode(data)
                    with open(output_path, 'wb') as f:
                        f.write(img_data)
                    return True, output_path
                return True, data
        except: pass
    return _fallback_image(prompt, style, size, output_path)

def _fallback_image(prompt, style=None, size=None, output_path=None):
    """Fallback: use VL model API for image generation."""
    try:
        import requests, _os
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
                    with open(output_path, 'wb') as f: f.write(img_resp.content)
                    return True, output_path
                return True, img_url
    except: pass
    return False, "Image generation failed"

def set_image_model(model_name):
    """Set the image generation model."""
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "image_generation_set_model", restype=ctypes.c_int, argtypes=[ctypes.c_char_p])
            return lib.image_generation_set_model(model_name.encode()) == 0
        except: pass
    return False

is_available = lambda: _get_lib() is not None
