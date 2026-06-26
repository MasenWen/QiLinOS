import os
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


def _now_ts() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


class AuditLogger:
    """追加写 JSONL 日志（便于现场排障/展示）。"""

    def __init__(self, path: str = "logs/mcp_host.log.jsonl"):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def log(self, event: str, payload: Dict[str, Any], request_id: Optional[str] = None):
        rec = {
            "ts": _now_ts(),
            "event": event,
            "request_id": request_id or str(uuid.uuid4()),
            "payload": payload,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def read_recent(
        self,
        limit: int = 100,
        event: Optional[str] = None,
        server: Optional[str] = None,
        tool: Optional[str] = None,
        success: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []

        rows: List[Dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue

        rows.reverse()

        def ok(rec: Dict[str, Any]) -> bool:
            if event and rec.get("event") != event:
                return False
            pay = rec.get("payload") or {}
            if server is not None and pay.get("server") != server:
                return False
            if tool is not None and pay.get("tool") != tool:
                return False
            if success is not None and pay.get("success") is not success:
                return False
            return True

        out = [r for r in rows if ok(r)]
        return out[: max(1, min(limit, 1000))]
