"""Security module — threat scanning, permission engine, memory guard, audit logging."""

# Public re-exports
from .threat import ThreatScanner, ThreatResult, scan_content, is_safe, first_threat
from .permission import PermissionEngine, Permission, PermissionResult
from .memory_guard import MemoryGuard, ContentReviewResult
from .audit import SecurityAuditLogger


# ========== Lazy singleton factories (avoid circular imports) ==========

def get_threat_scanner() -> 'ThreatScanner':
    from .threat import get_threat_scanner as _get
    return _get()


def get_permission_engine() -> 'PermissionEngine':
    from .permission import get_permission_engine as _get
    return _get()


def get_memory_guard() -> 'MemoryGuard':
    from .memory_guard import get_memory_guard as _get
    return _get()


def get_audit_logger() -> 'SecurityAuditLogger':
    from .audit import SecurityAuditLogger
    return SecurityAuditLogger()


__all__ = [
    # Threat
    'ThreatScanner', 'ThreatResult', 'scan_content', 'is_safe', 'first_threat',
    'get_threat_scanner',
    # Permission
    'PermissionEngine', 'Permission', 'PermissionResult', 'get_permission_engine',
    # Memory guard
    'MemoryGuard', 'ContentReviewResult', 'get_memory_guard',
    # Audit
    'SecurityAuditLogger', 'get_audit_logger',
]
