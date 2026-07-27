"""
Kylin AI Vision SDK (OCR) — ctypes Python bindings.

Wraps :file:`libkysdk-coreai-vision.so` C API for text recognition.
Use this to replace ``subprocess.run(["ocr_tool", ...])`` calls.

Requirements (Kylin server)::

    sudo apt install libkysdk-coreai-vision-dev

API reference: ``09-AI-SDK.md`` section 9.4.1
"""

import ctypes
import threading
import time
import os
from typing import Optional

from .base import load_library, _decode_cstring, declare

# ---------------------------------------------------------------------------
# Load the shared library
# ---------------------------------------------------------------------------

_lib_name = "libkysdk-coreai-vision"
_lib = load_library(_lib_name, mock=True)

# ---------------------------------------------------------------------------
# C type definitions (mirrors headers in /usr/include/kylin-ai/coreai/vision/)
# ---------------------------------------------------------------------------

class PixelPoint(ctypes.Structure):
    """2D pixel coordinate ( zero-indexed, origin top-left )."""
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
    ]


# Opaque handles — we never dereference from Python, just pass pointers
class _TextRecognitionSession(ctypes.Structure):
    pass


class _TextRecognitionResult(ctypes.Structure):
    pass


class _TextLine(ctypes.Structure):
    pass


class _TextRecognitionModelConfig(ctypes.Structure):
    pass


# Callback type: void (*)(TextRecognitionResult *, void *)
TextRecognitionResultCallback = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(_TextRecognitionResult),
    ctypes.c_void_p,
)

# ModelDeployType enum
MODEL_DEPLOY_ON_DEVICE = 0
MODEL_DEPLOY_PUBLIC_CLOUD = 1
MODEL_DEPLOY_PRIVATE_CLOUD = 2

# ---------------------------------------------------------------------------
# Declare function signatures (only when library is loaded)
# ---------------------------------------------------------------------------

if _lib is not None:
    # Session lifecycle
    declare(_lib, "text_recognition_create_session",
            restype=ctypes.POINTER(_TextRecognitionSession))

    declare(_lib, "text_recognition_destroy_session",
            restype=None,
            argtypes=[ctypes.POINTER(ctypes.POINTER(_TextRecognitionSession))])

    declare(_lib, "text_recognition_init_session",
            restype=ctypes.c_int,
            argtypes=[ctypes.POINTER(_TextRecognitionSession)])

    # Result callback
    declare(_lib, "text_recognition_result_set_callback",
            restype=None,
            argtypes=[ctypes.POINTER(_TextRecognitionSession),
                      TextRecognitionResultCallback,
                      ctypes.c_void_p])

    # Model config
    declare(_lib, "text_recognition_model_config_create",
            restype=ctypes.POINTER(_TextRecognitionModelConfig))

    declare(_lib, "text_recognition_model_config_destroy",
            restype=None,
            argtypes=[ctypes.POINTER(ctypes.POINTER(_TextRecognitionModelConfig))])

    declare(_lib, "text_recognition_model_config_set_name",
            restype=None,
            argtypes=[ctypes.POINTER(_TextRecognitionModelConfig),
                      ctypes.c_char_p])

    declare(_lib, "text_recognition_model_config_set_deploy_type",
            restype=None,
            argtypes=[ctypes.POINTER(_TextRecognitionModelConfig),
                      ctypes.c_int])

    declare(_lib, "text_recognition_set_model_config",
            restype=None,
            argtypes=[ctypes.POINTER(_TextRecognitionSession),
                      ctypes.POINTER(_TextRecognitionModelConfig)])

    # Async recognition
    declare(_lib, "text_recognition_recognize_text_from_image_file_async",
            restype=None,
            argtypes=[ctypes.POINTER(_TextRecognitionSession),
                      ctypes.c_char_p])

    declare(_lib, "text_recognition_recognize_text_from_image_file_async_with_request_id",
            restype=None,
            argtypes=[ctypes.POINTER(_TextRecognitionSession),
                      ctypes.c_char_p,
                      ctypes.c_char_p])

    # Internal event loop
    declare(_lib, "text_recognition_enable_internal_event_loop",
            restype=None,
            argtypes=[ctypes.POINTER(_TextRecognitionSession),
                      ctypes.c_bool])

    # ---- Result accessors (read-only, called inside callback) ----
    declare(_lib, "text_recognition_result_get_value",
            restype=ctypes.c_char_p,
            argtypes=[ctypes.POINTER(_TextRecognitionResult)])

    declare(_lib, "text_recognition_result_get_text_lines",
            restype=ctypes.POINTER(ctypes.POINTER(_TextLine)),
            argtypes=[ctypes.POINTER(_TextRecognitionResult),
                      ctypes.POINTER(ctypes.c_int)])

    declare(_lib, "text_recognition_result_get_error_code",
            restype=ctypes.c_int,
            argtypes=[ctypes.POINTER(_TextRecognitionResult)])

    declare(_lib, "text_recognition_result_get_error_message",
            restype=ctypes.c_char_p,
            argtypes=[ctypes.POINTER(_TextRecognitionResult)])

    declare(_lib, "text_recognition_result_get_request_id",
            restype=ctypes.c_char_p,
            argtypes=[ctypes.POINTER(_TextRecognitionResult)])

    # ---- Text line accessor ----
    declare(_lib, "text_line_get_value",
            restype=ctypes.c_char_p,
            argtypes=[ctypes.POINTER(_TextLine)])

    declare(_lib, "text_line_get_corner_points",
            restype=ctypes.POINTER(PixelPoint),
            argtypes=[ctypes.POINTER(_TextLine),
                      ctypes.POINTER(ctypes.c_int)])


# ---------------------------------------------------------------------------
# High-level Python API
# ---------------------------------------------------------------------------

class TextRecognitionError(RuntimeError):
    """Raised when OCR SDK operations fail."""
    pass


def _check_lib():
    if _lib is None:
        raise TextRecognitionError(
            "OCR SDK (libkysdk-coreai-vision) 不可用。"
            "请确认在 Kylin 服务器上已安装: sudo apt install libkysdk-coreai-vision-dev"
        )


def recognize_text(image_path: str, timeout: float = 60.0) -> str:
    """
    Extract text from an image using the Kylin AI OCR engine.

    This function replaces the old ``subprocess.run(["ocr_tool", image_path])``
    pattern with a direct SDK call.

    Parameters
    ----------
    image_path : str
        Absolute path to the image file (PNG, JPG, BMP, TIFF, WebP).
    timeout : float
        Maximum wait time in seconds (default 60).

    Returns
    -------
    str
        Recognized text content.  Returns empty string on failure.

    Raises
    ------
    TextRecognitionError
        If the SDK library is not available or the session fails.
    FileNotFoundError
        If *image_path* does not exist.
    """
    _check_lib()

    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    # Accumulator for callback result
    result_holder = {"text": "", "error": None, "done": threading.Event()}

    @TextRecognitionResultCallback
    def _on_result(result_ptr, _user_data):
        try:
            if not result_ptr:
                result_holder["error"] = "OCR SDK 返回了空结果指针"
                result_holder["done"].set()
                return

            err_code = _lib.text_recognition_result_get_error_code(result_ptr)
            if err_code != 0:
                err_msg = _decode_cstring(
                    _lib.text_recognition_result_get_error_message(result_ptr),
                    f"未知错误码 {err_code}"
                )
                result_holder["error"] = f"OCR 识别失败 (code={err_code}): {err_msg}"
                result_holder["done"].set()
                return

            text = _decode_cstring(
                _lib.text_recognition_result_get_value(result_ptr), ""
            )
            result_holder["text"] = text
        except Exception as exc:
            result_holder["error"] = str(exc)
        finally:
            result_holder["done"].set()

    # Create and initialize session
    session = _lib.text_recognition_create_session()
    if not session:
        raise TextRecognitionError("创建 OCR 会话失败")

    try:
        _lib.text_recognition_enable_internal_event_loop(session, True)

        ret = _lib.text_recognition_init_session(session)
        if ret != 0:
            raise TextRecognitionError(f"初始化 OCR 会话失败, 错误码: {ret}")

        _lib.text_recognition_result_set_callback(session, _on_result, None)

        # Encode path as UTF-8 bytes for the C layer
        path_bytes = image_path.encode("utf-8")
        _lib.text_recognition_recognize_text_from_image_file_async(
            session, path_bytes
        )

        # Wait for the async callback to fire
        if not result_holder["done"].wait(timeout):
            raise TextRecognitionError(f"OCR 识别超时 ({timeout}s)")

        if result_holder["error"]:
            raise TextRecognitionError(result_holder["error"])

        return result_holder["text"]

    finally:
        _lib.text_recognition_destroy_session(ctypes.byref(session))


def is_available() -> bool:
    """Return True if the OCR SDK library is loaded and usable."""
    return _lib is not None
