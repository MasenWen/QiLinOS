"""
Kylin AI Speech SDK - ctypes Python bindings.
Wraps: coreai/speech/recognizer.h, synthesizer.h, libkysdk-coreai-speech.so
Provides: speech-to-text, text-to-speech

注: 麒麟语音 SDK 由 libkysdk-coreai-speech 提供 (安装包: libkysdk-coreai-speech-dev)，
    函数前缀为 speech_recognizer_* / speech_synthesizer_*。
    原先引用的 speech_recognition_recognize / text_to_speech_synthesize 等函数并不存在，已修正。
"""
import ctypes
import os as _os
import threading
from typing import List, Optional

from .base import load_library, _decode_cstring, declare, IS_KYLIN

_LIB = None
_lock = threading.Lock()

# void (*...ResultCallback)(Result*, void*)
_ResultCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)

# SpeechResultReason (coreai/speech/result.h)
_SPEECH_ERROR_OCCURRED = 1
_SPEECH_RECOGNIZING = 3
_SPEECH_RECOGNIZED = 4
_SPEECH_RECOGNITION_COMPLETED = 5
_SPEECH_SYNTHESIZING = 7
_SPEECH_SYNTHESIS_COMPLETED = 8


def _get_lib():
    global _LIB
    if _LIB is None:
        with _lock:
            if _LIB is None:
                try:
                    _LIB = load_library("libkysdk-coreai-speech", mock=not IS_KYLIN)
                except Exception:
                    _LIB = False
    return _LIB if _LIB else None


def _declare(lib):
    """Declare speech_recognizer_* / speech_synthesizer_* signatures."""
    declare(lib, "speech_recognizer_create_session", restype=ctypes.c_void_p)
    declare(lib, "speech_recognizer_init_session", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "speech_recognizer_destroy_session", restype=None,
            argtypes=[ctypes.POINTER(ctypes.c_void_p)])
    declare(lib, "speech_recognizer_result_set_callback", restype=None,
            argtypes=[ctypes.c_void_p, _ResultCallback, ctypes.c_void_p])
    declare(lib, "speech_recognizer_recognize_once_async", restype=None,
            argtypes=[ctypes.c_void_p])
    declare(lib, "speech_recognizer_enable_internal_event_loop", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_bool])

    declare(lib, "speech_recognition_result_get_text", restype=ctypes.c_char_p,
            argtypes=[ctypes.c_void_p])
    declare(lib, "speech_recognition_result_get_reason", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "speech_recognition_result_get_error_code", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "speech_recognition_result_get_error_message", restype=ctypes.c_char_p,
            argtypes=[ctypes.c_void_p])

    declare(lib, "speech_synthesizer_create_session", restype=ctypes.c_void_p)
    declare(lib, "speech_synthesizer_init_session", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "speech_synthesizer_destroy_session", restype=None,
            argtypes=[ctypes.POINTER(ctypes.c_void_p)])
    declare(lib, "speech_synthesizer_result_set_callback", restype=None,
            argtypes=[ctypes.c_void_p, _ResultCallback, ctypes.c_void_p])
    declare(lib, "speech_synthesizer_synthesize_text_async", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32])
    declare(lib, "speech_synthesizer_enable_internal_event_loop", restype=None,
            argtypes=[ctypes.c_void_p, ctypes.c_bool])

    declare(lib, "speech_synthesis_result_get_data",
            restype=ctypes.POINTER(ctypes.c_uint8),
            argtypes=[ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)])
    declare(lib, "speech_synthesis_result_get_reason", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "speech_synthesis_result_get_error_code", restype=ctypes.c_int,
            argtypes=[ctypes.c_void_p])
    declare(lib, "speech_synthesis_result_get_error_message", restype=ctypes.c_char_p,
            argtypes=[ctypes.c_void_p])


class _RecognitionAccumulator:
    """Collect final recognized text from streaming callbacks."""

    def __init__(self, lib):
        self._lib = lib
        self.text = ""
        self.error: Optional[str] = None
        self.done = threading.Event()
        self._callback = _ResultCallback(self._on_result)  # 保持存活

    def _on_result(self, result_ptr, user_data):
        lib = self._lib
        try:
            reason = lib.speech_recognition_result_get_reason(result_ptr)
            if reason == _SPEECH_ERROR_OCCURRED:
                code = lib.speech_recognition_result_get_error_code(result_ptr)
                msg = lib.speech_recognition_result_get_error_message(result_ptr)
                self.error = _decode_cstring(msg) if msg else f"error code {code}"
                self.done.set()
                return
            text = lib.speech_recognition_result_get_text(result_ptr)
            if text:
                self.text = _decode_cstring(text)
            if reason in (_SPEECH_RECOGNIZED, _SPEECH_RECOGNITION_COMPLETED):
                self.done.set()
        except Exception as e:  # pragma: no cover
            self.error = str(e)
            self.done.set()


class _SynthesisAccumulator:
    """Collect synthesized audio bytes from streaming callbacks."""

    def __init__(self, lib):
        self._lib = lib
        self.chunks: List[bytes] = []
        self.error: Optional[str] = None
        self.done = threading.Event()
        self._callback = _ResultCallback(self._on_result)  # 保持存活

    def _on_result(self, result_ptr, user_data):
        lib = self._lib
        try:
            reason = lib.speech_synthesis_result_get_reason(result_ptr)
            if reason == _SPEECH_ERROR_OCCURRED:
                code = lib.speech_synthesis_result_get_error_code(result_ptr)
                msg = lib.speech_synthesis_result_get_error_message(result_ptr)
                self.error = _decode_cstring(msg) if msg else f"error code {code}"
                self.done.set()
                return
            length = ctypes.c_uint32(0)
            data_ptr = lib.speech_synthesis_result_get_data(result_ptr, ctypes.byref(length))
            if data_ptr and length.value > 0:
                self.chunks.append(ctypes.string_at(data_ptr, length.value))
            if reason == _SPEECH_SYNTHESIS_COMPLETED:
                self.done.set()
        except Exception as e:  # pragma: no cover
            self.error = str(e)
            self.done.set()


def speech_to_text(audio_path, streaming=False):
    """Recognize speech via the SDK recognizer (default audio input). Returns (ok, text)."""
    lib = _get_lib()
    if lib:
        try:
            _declare(lib)
            session = lib.speech_recognizer_create_session()
            if not session:
                return False, "create session failed"
            try:
                if lib.speech_recognizer_init_session(session) != 0:
                    return False, "init session failed"
                acc = _RecognitionAccumulator(lib)
                lib.speech_recognizer_result_set_callback(session, acc._callback, None)
                lib.speech_recognizer_enable_internal_event_loop(session, True)
                lib.speech_recognizer_recognize_once_async(session)
                acc.done.wait(timeout=30)
                if acc.error:
                    return False, acc.error
                if acc.text:
                    return True, acc.text
            finally:
                ptr = ctypes.c_void_p(session)
                lib.speech_recognizer_destroy_session(ctypes.byref(ptr))
        except Exception:
            pass
    return _fallback_stt(audio_path)


def _fallback_stt(audio_path):
    """Fallback: use API for speech recognition."""
    try:
        import requests
        api_key = _os.getenv("BASIC_API_KEY", "")
        base_url = _os.getenv("BASIC_BASE_URL", "")
        if not all([api_key, base_url]):
            return False, "No ASR API config available"
        with open(audio_path, "rb") as f:
            resp = requests.post(
                f"{base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": f},
                data={"model": "whisper-1"},
                timeout=120,
            )
        if resp.status_code == 200:
            return True, resp.json().get("text", "")
    except Exception:
        pass
    return False, "Speech recognition failed"


def text_to_speech(text, output_path, voice=None):
    """Convert text to speech audio file. Returns (success, path)."""
    if not text:
        return False, "Empty text"
    lib = _get_lib()
    if lib:
        try:
            _declare(lib)
            session = lib.speech_synthesizer_create_session()
            if not session:
                return False, "create session failed"
            try:
                if lib.speech_synthesizer_init_session(session) != 0:
                    return False, "init session failed"
                acc = _SynthesisAccumulator(lib)
                lib.speech_synthesizer_result_set_callback(session, acc._callback, None)
                lib.speech_synthesizer_enable_internal_event_loop(session, True)
                data = text.encode("utf-8")
                lib.speech_synthesizer_synthesize_text_async(session, data, len(data))
                acc.done.wait(timeout=60)
                if acc.error or not acc.chunks:
                    return False, acc.error or "no audio data"
                with open(output_path, "wb") as f:
                    for chunk in acc.chunks:
                        f.write(chunk)
                return True, output_path
            finally:
                ptr = ctypes.c_void_p(session)
                lib.speech_synthesizer_destroy_session(ctypes.byref(ptr))
        except Exception:
            pass
    return _fallback_tts(text, output_path, voice)


def _fallback_tts(text, output_path, voice=None):
    """Fallback: use API for TTS."""
    try:
        import requests
        api_key = _os.getenv("BASIC_API_KEY", "")
        base_url = _os.getenv("BASIC_BASE_URL", "")
        if not all([api_key, base_url]):
            return False, "No TTS API config available"
        resp = requests.post(
            f"{base_url}/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "tts-1", "input": text, "voice": voice or "alloy"},
            timeout=60,
        )
        if resp.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return True, output_path
    except Exception:
        pass
    return False, "TTS failed"


is_available = lambda: _get_lib() is not None
