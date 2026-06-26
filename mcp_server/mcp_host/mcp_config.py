from __future__ import annotations
import json
import os
from typing import Any, Dict

from .constants import HIDDEN_SERVERS


def _command_for_path(abs_path: str) -> str:
    return "python" if abs_path.endswith(".py") else "node"


def generate_mcp_config(registry_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"mcpServers": {}}
    for name, info in registry_data.items():
        if name in HIDDEN_SERVERS:
            continue
        desc = info.get("description", "")
        abs_path = os.path.abspath(info.get("abs_path", "")) if info.get("abs_path") else ""
        external_name = name.replace("_", "-")
        out["mcpServers"][external_name] = {
            "description": desc,
            "command": _command_for_path(abs_path),
            "args": [abs_path],
            "env": {"PYTHONUNBUFFERED": "1"},
        }
    return out


def write_mcp_config_file(registry_data: Dict[str, Dict[str, Any]], out_path: str) -> str:
    cfg = generate_mcp_config(registry_data)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return out_path
