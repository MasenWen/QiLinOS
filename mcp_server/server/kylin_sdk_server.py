#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麒麟硬件信息 MCP Server
零启动加载版本 - 所有库在工具函数内按需加载，避免启动时崩溃
"""

import json
import logging
import sys
import os
from mcp.server.fastmcp import FastMCP

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("KylinHardwareTools")

# ============================================================================
# 辅助函数 - 在调用时才加载库
# ============================================================================

_cpu_lib = None
_cpu_lib_error = None

def _get_cpu_lib():
    """延迟加载 CPU 库 - 只在第一次调用时加载"""
    global _cpu_lib, _cpu_lib_error
    
    if _cpu_lib is not None:
        return _cpu_lib
    if _cpu_lib_error is not None:
        return None
    
    lib_path = "/usr/lib/x86_64-linux-gnu/libkyhw.so"
    
    if not os.path.exists(lib_path):
        _cpu_lib_error = f"库文件不存在: {lib_path}"
        logger.error(_cpu_lib_error)
        return None
    
    try:
        import ctypes
        lib = ctypes.CDLL(lib_path)
        
        # 声明返回类型
        lib.kdk_cpu_get_arch.restype = ctypes.c_char_p
        lib.kdk_cpu_get_vendor.restype = ctypes.c_char_p
        lib.kdk_cpu_get_model.restype = ctypes.c_char_p
        lib.kdk_cpu_get_freq_MHz.restype = ctypes.c_char_p
        lib.kdk_cpu_get_corenums.restype = ctypes.c_uint
        lib.kdk_cpu_get_process.restype = ctypes.c_uint
        lib.kdk_cpu_get_max_freq_MHz.restype = ctypes.c_float
        lib.kdk_cpu_get_min_freq_MHz.restype = ctypes.c_float
        lib.kdk_cpu_get_virt.restype = ctypes.c_char_p
        lib.kdk_cpu_get_sockets.restype = ctypes.c_uint
        lib.kdk_cpu_get_running_time.restype = ctypes.c_char_p
        lib.kdk_cpu_get_L1d_cache.restype = ctypes.c_uint
        lib.kdk_cpu_get_L1i_cache.restype = ctypes.c_uint
        lib.kdk_cpu_get_L2_cache.restype = ctypes.c_uint
        lib.kdk_cpu_get_L3_cache.restype = ctypes.c_uint
        
        _cpu_lib = lib
        logger.info(f"✅ CPU 库加载成功: {lib_path}")
        return lib
    except Exception as e:
        _cpu_lib_error = str(e)
        logger.error(f"❌ CPU 库加载失败: {e}")
        return None

def _p(s):
    if s is None:
        return ""
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="replace")
    return str(s)

def _int_or(v, default=-1):
    if v is None or v == -1 or v == 4294967295:
        return default
    return v

# ============================================================================
# MCP 工具 - 每个工具内部才加载库
# ============================================================================

@mcp.tool()
async def query_cpu_info() -> str:
    """查询 CPU 完整信息：架构、厂商、型号、主频、核心数、线程数、缓存、虚拟化支持、插槽数、运行时间"""
    lib = _get_cpu_lib()
    if lib is None:
        return json.dumps({"error": _cpu_lib_error or "CPU 库不可用"}, ensure_ascii=False)
    
    try:
        result = {
            "架构": _p(lib.kdk_cpu_get_arch()),
            "厂商": _p(lib.kdk_cpu_get_vendor()),
            "型号": _p(lib.kdk_cpu_get_model()),
            "额定主频(MHz)": _p(lib.kdk_cpu_get_freq_MHz()),
            "核心数": _int_or(lib.kdk_cpu_get_corenums()),
            "线程数": _int_or(lib.kdk_cpu_get_process()),
            "最大频率(MHz)": round(lib.kdk_cpu_get_max_freq_MHz(), 2),
            "最小频率(MHz)": round(lib.kdk_cpu_get_min_freq_MHz(), 2),
            "虚拟化支持": _p(lib.kdk_cpu_get_virt()),
            "插槽数": _int_or(lib.kdk_cpu_get_sockets()),
            # "运行时间": _p(lib.kdk_cpu_get_running_time()),
            "L1d缓存(KB)": _int_or(lib.kdk_cpu_get_L1d_cache()),
            "L1i缓存(KB)": _int_or(lib.kdk_cpu_get_L1i_cache()),
            "L2缓存(KB)": _int_or(lib.kdk_cpu_get_L2_cache()),
            "L3缓存(KB)": _int_or(lib.kdk_cpu_get_L3_cache()),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("query_cpu_info 失败")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

@mcp.tool()
async def query_cpu_arch() -> str:
    """查询 CPU 架构（如 x86_64）"""
    lib = _get_cpu_lib()
    if lib is None:
        return _cpu_lib_error or "CPU 库不可用"
    return _p(lib.kdk_cpu_get_arch())

@mcp.tool()
async def query_cpu_cores() -> str:
    """查询 CPU 核心数和线程数"""
    lib = _get_cpu_lib()
    if lib is None:
        return json.dumps({"error": _cpu_lib_error or "CPU 库不可用"}, ensure_ascii=False)
    return json.dumps({
        "物理核心": _int_or(lib.kdk_cpu_get_corenums()),
        "逻辑线程": _int_or(lib.kdk_cpu_get_process()),
    }, ensure_ascii=False)

if __name__ == "__main__":
    logger.info("麒麟硬件 MCP 服务器启动中（延迟加载模式）...")
    mcp.run()
