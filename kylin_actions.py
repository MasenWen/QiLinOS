"""
Kylin desktop action dispatcher — re-export of the canonical MCP server module.

The authoritative implementation lives in ``mcp_server/server/kylin_actions.py``
(Layer-0 DSL permission check + toolkit closed-loop + actuator fallback).
This root-level module is kept for backwards compatibility and delegates
everything to the canonical one, so behaviour stays identical.
"""
from mcp_server.server.kylin_actions import (  # noqa: F401
    ACTION_REGISTRY,
    _TOOLKIT_BRIDGE,
    execute_action,
)

__all__ = ["execute_action", "ACTION_REGISTRY", "_TOOLKIT_BRIDGE"]
