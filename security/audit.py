"""Security audit logger — writes security-specific events to JSONL."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _now_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"


class SecurityAuditLogger:
    """Append-only JSONL audit log for security events.

    Runs in parallel with the existing ``mcp_server/mcp_host/audit_log.py``
    AuditLogger, which writes general operational events.  This logger is
    dedicated to security-specific events (threat blocks, permission denies,
    permission confirms, memory reviews).
    """

    def __init__(self, path: str | None = None):
        if path is None:
            project_root = Path(__file__).parent.parent
            path = str(project_root / "logs" / "security_audit.jsonl")
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def _write(self, event: str, payload: Dict[str, Any], request_id: Optional[str] = None):
        rec = {
            "ts": _now_ts(),
            "event": event,
            "request_id": request_id or str(uuid.uuid4()),
            "payload": payload,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def log_threat_block(self, content: str, threat_ids: list, severity: str,
                         request_id: Optional[str] = None):
        self._write("threat_block", {
            "content_preview": content[:200],
            "threat_ids": threat_ids,
            "severity": severity,
        }, request_id=request_id)

    def log_permission_deny(self, server_name: str, tool_name: str, reason: str,
                            request_id: Optional[str] = None):
        self._write("permission_deny", {
            "server_name": server_name,
            "tool_name": tool_name,
            "reason": reason,
        }, request_id=request_id)

    def log_permission_confirm(self, server_name: str, tool_name: str,
                               request_id: Optional[str] = None):
        self._write("permission_confirm", {
            "server_name": server_name,
            "tool_name": tool_name,
        }, request_id=request_id)

    def log_memory_review(self, category: str, source: str, allowed: bool,
                          threat_ids: list, reason: str = "",
                          request_id: Optional[str] = None):
        self._write("memory_review", {
            "category": category,
            "source": source,
            "allowed": allowed,
            "threat_ids": threat_ids,
            "reason": reason,
        }, request_id=request_id)
