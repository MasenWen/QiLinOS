"""Python facade for the Kylin AI Vector Database SDK.

Production mode talks to ``libkysdk-vector-engine-client`` through a tiny C++
bridge process. Legacy embedded Milvus-Lite access is still available behind
``NEX_AGENT_KYLIN_VECTOR_MODE=embedded`` so old databases can be re-enabled
without deleting or migrating them.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_FILE = os.path.expanduser("~/.nex-agent/mem0_vector_engine.db")
DEFAULT_APP_ID = "nex_agent_memory"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_SOURCE = PROJECT_ROOT / "tools" / "kylin_vector_engine_bridge.cpp"
BRIDGE_BINARY = PROJECT_ROOT / "runtime" / "bin" / "kylin_vector_engine_bridge"


class KylinVectorEngineError(RuntimeError):
    """Raised when the Kylin vector database SDK call fails."""


def open_kylin_vector_client(
    *,
    path: str | None = None,
    uri: str | None = None,
    timeout: float = 30.0,
    mode: str | None = None,
):
    """Open the configured vector database client.

    Default mode uses the Kylin AI Vector Database SDK. ``embedded`` mode keeps
    the old pymilvus/Milvus-Lite path available as an explicit fallback.
    """

    selected_mode = (mode or os.getenv("NEX_AGENT_KYLIN_VECTOR_MODE", "sdk")).lower()
    if selected_mode in {"sdk", "kylin", "service"}:
        return KylinVectorEngineClient(
            db_file=_resolve_db_file(path),
            app_id=os.getenv("NEX_AGENT_KYLIN_VECTOR_APP_ID", DEFAULT_APP_ID),
            timeout=timeout,
        )
    if selected_mode == "embedded":
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise KylinVectorEngineError(
                "Legacy embedded vector DB mode requires pymilvus. "
                "Install pymilvus or use NEX_AGENT_KYLIN_VECTOR_MODE=sdk."
            ) from exc
        db_path = os.path.expanduser(path or "~/.nex-agent/mem0_vectordb.db")
        logger.warning("Using legacy embedded Milvus-Lite vector DB: %s", db_path)
        return MilvusClient(uri=db_path, timeout=timeout)
    raise KylinVectorEngineError(
        f"Unsupported NEX_AGENT_KYLIN_VECTOR_MODE={selected_mode!r}"
    )


class KylinVectorEngineClient:
    """Small compatibility client backed by libkysdk-vector-engine-client."""

    def __init__(self, db_file: str, app_id: str, timeout: float = 30.0):
        self.db_file = db_file
        self.app_id = app_id
        self.timeout = timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._ensure_service()
        self._ensure_bridge()
        self._start_bridge()

    def has_collection(self, collection_name: str) -> bool:
        res = self._request({"op": "has_collection", "collection": collection_name})
        return bool(res.get("exists", False))

    def create_collection(self, collection_name: str, **kwargs) -> None:
        dim = kwargs.get("dimension") or kwargs.get("dim")
        schema = kwargs.get("schema")
        if dim is None and schema is not None:
            dim = _schema_vector_dim(schema)
        self._request(
            {
                "op": "create_collection",
                "collection": collection_name,
                "dim": int(dim or 768),
            }
        )

    def load_collection(self, collection_name: str) -> None:
        return None

    def insert(self, collection_name: str, data: list[dict[str, Any]]) -> dict[str, Any]:
        rows = [_row_to_bridge(item) for item in data]
        res = self._request({"op": "insert", "collection": collection_name, "rows": rows})
        return {"ids": res.get("ids", [])}

    def upsert(self, collection_name: str, data: list[dict[str, Any]]) -> dict[str, Any]:
        rows = [_row_to_bridge(item) for item in data]
        res = self._request({"op": "upsert", "collection": collection_name, "rows": rows})
        return {"ids": res.get("ids", [])}

    def search(
        self,
        collection_name: str,
        data: list[list[float]],
        limit: int = 5,
        filter: str | None = None,
        output_fields: list[str] | None = None,
        **_: Any,
    ) -> list[list[dict[str, Any]]]:
        results = []
        for vector in data:
            res = self._request(
                {
                    "op": "search",
                    "collection": collection_name,
                    "vector": _as_float_list(vector),
                    "top_k": int(limit),
                    "filters": _parse_simple_filter(filter),
                    "timeout_ms": int(self.timeout * 1000),
                }
            )
            hits = []
            for hit in res.get("hits", []):
                metadata = hit.get("metadata", {}) or {}
                external_id = hit.get("external_id") or metadata.get("_external_id")
                entity = {
                    "id": str(external_id or hit.get("id", "")),
                    "metadata": _clean_metadata(metadata),
                    "text": metadata.get("text", ""),
                }
                hits.append(
                    {
                        "id": str(external_id or hit.get("id", "")),
                        "distance": float(hit.get("score", 0.0)),
                        "entity": entity,
                    }
                )
            results.append(hits)
        return results

    def query(
        self,
        collection_name: str,
        filter: str | None = None,
        limit: int = 100,
        output_fields: list[str] | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        res = self._request(
            {
                "op": "query",
                "collection": collection_name,
                "filters": _parse_simple_filter(filter),
                "limit": int(limit),
                "timeout_ms": int(self.timeout * 1000),
            }
        )
        rows = []
        for row in res.get("rows", []):
            metadata = row.get("metadata", {}) or {}
            external_id = metadata.get("_external_id", row.get("id"))
            rows.append(
                {
                    "id": str(external_id),
                    "metadata": _clean_metadata(metadata),
                    "text": metadata.get("text", ""),
                }
            )
        return rows

    def get(
        self,
        collection_name: str,
        ids: list[str],
        output_fields: list[str] | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        rows = []
        for vector_id in ids:
            res = self._request(
                {
                    "op": "query",
                    "collection": collection_name,
                    "filters": {"_external_id": str(vector_id)},
                    "limit": 1,
                    "timeout_ms": int(self.timeout * 1000),
                }
            )
            for row in res.get("rows", []):
                metadata = row.get("metadata", {}) or {}
                rows.append(
                    {
                        "id": str(metadata.get("_external_id", row.get("id"))),
                        "metadata": _clean_metadata(metadata),
                        "text": metadata.get("text", ""),
                    }
                )
        return rows

    def delete(
        self,
        collection_name: str,
        ids: list[str] | None = None,
        filter: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        deleted = []
        if ids:
            for vector_id in ids:
                res = self._request(
                    {
                        "op": "delete",
                        "collection": collection_name,
                        "external_id": str(vector_id),
                    }
                )
                deleted.extend(res.get("ids", []))
            return {"ids": deleted}
        res = self._request(
            {
                "op": "delete",
                "collection": collection_name,
                "filters": _parse_simple_filter(filter),
            }
        )
        return {"ids": res.get("ids", [])}

    def drop_collection(self, collection_name: str) -> None:
        self._request({"op": "drop_collection", "collection": collection_name})

    def list_collections(self) -> list[str]:
        res = self._request({"op": "list_collections"})
        return list(res.get("collections", []))

    def get_collection_stats(self, collection_name: str) -> dict[str, Any]:
        res = self._request({"op": "stats", "collection": collection_name})
        return {"row_count": res.get("row_count")}

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            self._request({"op": "close"})
        except Exception:
            pass
        if proc.poll() is None:
            proc.terminate()
        self._proc = None

    def _start_bridge(self) -> None:
        Path(self.db_file).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(
            [str(BRIDGE_BINARY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._request(
            {
                "op": "init",
                "db_file": self.db_file,
                "app_id": self.app_id,
                "connect_timeout_ms": int(self.timeout * 1000),
            }
        )

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
                raise KylinVectorEngineError("Kylin vector bridge is not running")
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    stderr = ""
                    if self._proc.stderr is not None:
                        stderr = self._proc.stderr.read()
                    raise KylinVectorEngineError(
                        f"Kylin vector bridge exited unexpectedly: {stderr.strip()}"
                    )
                try:
                    response = json.loads(line)
                    break
                except json.JSONDecodeError:
                    logger.debug("Ignored non-JSON Kylin bridge output: %s", line.rstrip())
        if not response.get("ok", False):
            raise KylinVectorEngineError(response.get("error", "unknown SDK error"))
        return response

    def _ensure_bridge(self) -> None:
        if BRIDGE_BINARY.exists() and BRIDGE_BINARY.stat().st_mtime >= BRIDGE_SOURCE.stat().st_mtime:
            return
        if shutil.which("g++") is None:
            raise KylinVectorEngineError("g++ is required to build the Kylin vector SDK bridge")
        BRIDGE_BINARY.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "g++",
            "-std=c++17",
            str(BRIDGE_SOURCE),
            "-o",
            str(BRIDGE_BINARY),
            "-lkysdk-vector-engine-client",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise KylinVectorEngineError(
                "Failed to build Kylin vector SDK bridge: "
                + (result.stderr or result.stdout).strip()
            )

    def _ensure_service(self) -> None:
        socket_path = f"/tmp/kylin-ai-vector-engine-{os.geteuid()}.sock"
        if os.path.exists(socket_path):
            return
        subprocess.run(
            ["systemctl", "--user", "start", "kylin-ai-vector-engine"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def _resolve_db_file(path: str | None) -> str:
    configured = os.getenv("NEX_AGENT_KYLIN_VECTOR_DB_FILE")
    if configured:
        return os.path.expanduser(configured)
    if not path:
        return DEFAULT_DB_FILE
    expanded = os.path.expanduser(path)
    if expanded.endswith(".db"):
        return expanded
    return expanded.rstrip("/\\") + ".db"


def _row_to_bridge(row: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(row.get("metadata") or {})
    text = row.get("text") or metadata.get("data") or metadata.get("memory") or ""
    if text:
        metadata.setdefault("text", text)
    out = {
        "vector": _as_float_list(row.get("vector", [])),
        "metadata": metadata,
        "text": text,
    }
    if "id" in row:
        out["external_id"] = str(row["id"])
    return out


def _as_float_list(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(item) for item in vector]


def _parse_simple_filter(expr: str | None) -> dict[str, Any]:
    if not expr:
        return {}
    # Handles expressions produced by KylinMem0Adapter._build_filter:
    # (metadata["user_id"] == "abc") and (metadata["x"] == 1)
    filters: dict[str, Any] = {}
    for part in expr.split(" and "):
        part = part.strip().strip("()")
        marker = 'metadata["'
        if not part.startswith(marker) or '"] ==' not in part:
            continue
        key, raw = part[len(marker) :].split('"] ==', 1)
        raw = raw.strip()
        if raw.startswith('"') and raw.endswith('"'):
            filters[key] = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        else:
            try:
                filters[key] = json.loads(raw)
            except json.JSONDecodeError:
                filters[key] = raw
    return filters


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(metadata)
    cleaned.pop("_external_id", None)
    cleaned.pop("text", None)
    return cleaned


def _schema_vector_dim(schema: Any) -> Optional[int]:
    for field in getattr(schema, "fields", []) or []:
        params = getattr(field, "params", {}) or {}
        if "dim" in params:
            return int(params["dim"])
    return None
