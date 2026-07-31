"""
NexAgent 威胁模式扫描 — 敏感信息识别

**已弃用**: 本模块的核心逻辑已迁移至 ``security/threat.py``。
保留此文件作为兼容层，重导出新模块的符号。
"""
import warnings

from security.threat import ThreatScanner, ThreatResult, scan_content, is_safe, first_threat

warnings.warn(
    "src.memory.threat_patterns 已弃用，请使用 security.threat",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "ThreatScanner", "ThreatResult",
    "scan_content", "is_safe", "first_threat",
]
