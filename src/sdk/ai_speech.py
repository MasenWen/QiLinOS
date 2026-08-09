"""
Kylin AI Speech SDK - ctypes Python bindings.
Wraps: coreai/speech/ asr.h, tts.h
Provides: speech-to-text, text-to-speech, speaker recognition
"""
import ctypes, os as _os
from typing import Optional, List, Tuple
from .base import load_library, _decode_cstring, declare, IS_LINUX, IS_KYLIN

_LIB = None

def _get_lib():
    global _LIB
    if _LIB is None:
        _LIB = load_library("libkysdk-coreai-speech", mock=not IS_KYLIN)
    return _LIB

def speech_to_text(audio_path, streaming=False):
    """Convert speech audio to text. Returns transcribed text."""
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "speech_recognition_recognize",
                    restype=ctypes.c_char_p,
                    argtypes=[ctypes.c_char_p, ctypes.c_bool])
            raw = lib.speech_recognition_recognize(audio_path.encode(), streaming)
            if raw: return True, _decode_cstring(raw)
        except: pass
    return _fallback_stt(audio_path)

def _fallback_stt(audio_path):
    """Fallback: use API for speech recognition."""
    try:
        import requests
        api_key = _os.getenv("BASIC_API_KEY", "")
        base_url = _os.getenv("BASIC_BASE_URL", "")
        with open(audio_path, 'rb') as f:
            resp = requests.post(
                f"{base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": f},
                data={"model": "whisper-1"},
                timeout=120,
            )
        if resp.status_code == 200:
            return True, resp.json().get("text", "")
    except: pass
    return False, "Speech recognition failed"

def text_to_speech(text, output_path, voice=None):
    """Convert text to speech audio file. Returns (success, path)."""
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "text_to_speech_synthesize",
                    restype=ctypes.c_char_p,
                    argtypes=[ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p])
            raw = lib.text_to_speech_synthesize(
                text.encode(), output_path.encode(), (voice or "").encode())
            if raw:
                return True, _decode_cstring(raw)
        except: pass
    return _fallback_tts(text, output_path, voice)

def _fallback_tts(text, output_path, voice=None):
    """Fallback: use API for TTS."""
    try:
        import requests
        api_key = _os.getenv("BASIC_API_KEY", "")
        base_url = _os.getenv("BASIC_BASE_URL", "")
        resp = requests.post(
            f"{base_url}/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "tts-1", "input": text, "voice": voice or "alloy"},
            timeout=60,
        )
        if resp.status_code == 200:
            with open(output_path, 'wb') as f: f.write(resp.content)
            return True, output_path
    except: pass
    return False, "TTS failed"

is_available = lambda: _get_lib() is not None
