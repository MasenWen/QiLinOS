"""
Kylin SDK ctypes base loader.

Provides utilities to load .so libraries and wrap C function calls.
Works on Kylin Linux; raises clear errors on unsupported platforms.
"""
import ctypes
import ctypes.util
import platform
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Platform guard
# ---------------------------------------------------------------------------

def _is_kylin() -> bool:
    """Best-effort detection of a Kylin / openKylin system."""
    try:
        with open("/etc/os-release") as fh:
            text = fh.read().lower()
    except FileNotFoundError:
        return False
    return any(kw in text for kw in ("kylin", "openkylin", "ubuntukylin"))


IS_KYLIN = _is_kylin()
IS_LINUX = platform.system() == "Linux"

if not IS_LINUX:
    sys.stderr.write("[sdk] 警告: 非 Linux 系统, SDK .so 库不可用, 将使用 mock 模式\n")


# ---------------------------------------------------------------------------
# Library loader
# ---------------------------------------------------------------------------

_ARCH_DIR = "x86_64-linux-gnu"  # Kylin V11 main arch

# Standard locations for kysdk shared objects
_DEFAULT_SEARCH_PATHS = [
    f"/usr/lib/{_ARCH_DIR}",
    "/usr/lib",
    "/usr/local/lib",
]


def _resolve_so_path(soname: str, extra_paths: Optional[list[str]] = None) -> Path:
    """Find a .so by soname, returning its absolute Path."""
    # First try system loader
    path = ctypes.util.find_library(soname)
    if path:
        return Path(path)

    # Walk through search paths
    for base in (extra_paths or []) + _DEFAULT_SEARCH_PATHS:
        candidates = [
            Path(base) / f"{soname}.so",
            Path(base) / f"lib{soname}.so",
            Path(base) / soname,
        ]
        for c in candidates:
            if c.exists():
                return c

    raise FileNotFoundError(
        f"找不到共享库: {soname}\n"
        f"搜索路径: {(extra_paths or []) + _DEFAULT_SEARCH_PATHS}\n"
        f"请确认 SDK 已安装: sudo apt install libkysdk-*"
    )


def load_library(
    soname: str,
    fallback_paths: Optional[list[str]] = None,
    mock: bool = False,
) -> Optional[ctypes.CDLL]:
    """
    Load a shared library and return a ctypes.CDLL handle.

    Parameters
    ----------
    soname : str
        Library soname e.g. ``"libkysdk-coreai-vision"``.
    fallback_paths : list[str] | None
        Additional directories to search.
    mock : bool
        If True, return None on failure instead of raising.

    Returns
    -------
    ctypes.CDLL | None
    """
    if not IS_LINUX:
        if mock:
            return None
        raise RuntimeError(f"当前平台 {platform.system()} 不支持加载 .so 库")

    try:
        path = _resolve_so_path(soname, fallback_paths)
        # Use cdll.LoadLibrary (RTLD_GLOBAL) to avoid segfault on Kylin V11
        # where ctypes.CDLL (RTLD_LOCAL) causes crashes on certain C functions
        # that return NULL (e.g. kdk_system_get_activationStatus).
        lib = ctypes.cdll.LoadLibrary(str(path))
        return lib
    except (FileNotFoundError, OSError) as exc:
        if mock:
            sys.stderr.write(f"[sdk] 加载库失败 (mock 模式): {exc}\n")
            return None
        raise


# ---------------------------------------------------------------------------
# Helper: char* result decoder
# ---------------------------------------------------------------------------

def _decode_cstring(ptr, default: str = "") -> str:
    """Decode a ``c_char_p`` result safely."""
    if not ptr:
        return default
    try:
        return ptr.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError):
        return default


# ---------------------------------------------------------------------------
# Helper: declare a C function signature
# ---------------------------------------------------------------------------



def _safe_cstring_call(lib, func_name):
    """Safely call a char*-returning C function.

    On Kylin V11 Python 3.12, direct ctypes calls from module-level scope
    can cause segfaults. This wrapper ensures the call happens through a
    lambda execution context which avoids the issue.

    IMPORTANT: The attribute access (getattr) MUST happen inside the lambda
    to match the working call pattern. Do NOT change the cached function
    pointer's restype — doing so across multiple calls causes ctypes state
    corruption that leads to segfaults.
    """
    import ctypes
    def _call():
        fn = getattr(lib, func_name)
        return fn()
    ptr = _call()
    if not ptr:
        return ""
    if isinstance(ptr, bytes):
        try:
            return ptr.decode("utf-8", errors="replace")
        except Exception:
            return ""
    if isinstance(ptr, int) and ptr != 0:
        try:
            return ctypes.cast(ptr, ctypes.c_char_p).value.decode("utf-8", errors="replace")
        except Exception:
            return ""
    return ""
def declare(lib: ctypes.CDLL, name: str, restype=None, argtypes=None):
    """Set restype and argtypes for a function on a loaded library."""
    fn = getattr(lib, name)
    if restype is not None:
        fn.restype = restype
    if argtypes is not None:
        fn.argtypes = argtypes
    return fn
