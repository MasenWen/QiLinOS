# -*- coding: utf-8 -*-
"""内存充足条件下的优化开关。

设计意图：把"稀疏草图候选预筛"与"贝叶斯先验平滑"两项优化挂到**内存资源充足**这一前提上——
内存充足时启用（扩大召回 + 草图发现的额外候选 + 先验平滑），内存不足时保持既有精确路径。
判定与回落逻辑集中在本模块，便于观测与复现。

环境变量：
  ``NEX_MEM_OPTIMIZATION``        ``auto``（默认）｜``on``｜``off``
  ``NEX_MEM_OPT_MIN_AVAILABLE_MB``  auto 模式下的可用内存阈值（默认 1024 MB）

对外接口：
  :func:`memory_snapshot`       读取系统内存（MB）
  :func:`optimization_decision` 给出本次是否启用优化及原因
"""
from __future__ import annotations

import os
from typing import Any, Mapping

VERSION = "resource.memory_gate.v1"
DEFAULT_MIN_AVAILABLE_MB = 1024.0
MEMINFO_PATH = "/proc/meminfo"


def _meminfo() -> dict[str, float]:
    """读取 /proc/meminfo（单位 MB）；读取失败返回空字典表示无法判断。"""
    values: dict[str, float] = {}
    try:
        with open(MEMINFO_PATH, encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                parts = rest.strip().split()
                if parts and parts[0].isdigit():
                    values[key] = int(parts[0]) / 1024.0
    except OSError:
        return {}
    return values


def memory_snapshot() -> dict[str, Any]:
    """返回当前内存快照：总内存、可用内存（MB）与是否可读。"""
    info = _meminfo()
    return {
        "total_mb": round(info.get("MemTotal", 0.0), 1),
        "available_mb": round(info.get("MemAvailable", 0.0), 1),
        "readable": bool(info),
    }


def optimization_decision(
    min_available_mb: float | None = None,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """判定是否启用内存充足条件下的优化。

    返回字段：``enabled``（是否启用）、``mode``（实际生效模式）、``reason``（判定原因）、
    ``available_mb`` / ``total_mb`` / ``threshold_mb``（用于日志与追溯）。
    ``snapshot`` 可注入，便于测试与在无 /proc 环境下复用。
    """
    mode = (os.getenv("NEX_MEM_OPTIMIZATION", "auto") or "auto").strip().lower()
    if min_available_mb is None:
        raw = os.getenv("NEX_MEM_OPT_MIN_AVAILABLE_MB", "")
        try:
            min_available_mb = float(raw) if raw.strip() else DEFAULT_MIN_AVAILABLE_MB
        except ValueError:
            min_available_mb = DEFAULT_MIN_AVAILABLE_MB

    snap = dict(snapshot) if snapshot is not None else memory_snapshot()
    base = {
        "version": VERSION,
        "mode": mode if mode in ("auto", "on", "off") else "auto",
        "threshold_mb": float(min_available_mb),
        "total_mb": snap.get("total_mb"),
        "available_mb": snap.get("available_mb"),
    }

    if mode in ("off", "0", "false", "no"):
        return {**base, "enabled": False, "reason": "explicit_off"}
    if mode in ("on", "1", "true", "yes"):
        return {**base, "enabled": True, "reason": "explicit_on"}
    if not snap.get("readable"):
        return {**base, "enabled": False, "reason": "memory_unreadable"}
    available = float(snap.get("available_mb") or 0.0)
    enabled = available >= float(min_available_mb)
    return {
        **base,
        "enabled": enabled,
        "reason": "available_above_threshold" if enabled else "available_below_threshold",
    }


def decision_summary(decision: Mapping[str, Any]) -> str:
    """把判定结果压成一行日志，便于启动自检与运行追溯。"""
    return "[内存优化] %s（模式=%s，原因=%s，可用 %.0f MB / 阈值 %.0f MB）" % (
        "已启用" if decision.get("enabled") else "未启用",
        decision.get("mode"),
        decision.get("reason"),
        float(decision.get("available_mb") or 0.0),
        float(decision.get("threshold_mb") or 0.0),
    )
