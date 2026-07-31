"""Permission engine — server/tool and DSL action authorization.

Matches the configured permission_rules.yaml to determine whether an
operation is ALLOW'd, REQUIRES_CONFIRM, or DENY'd.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class Permission(Enum):
    ALLOW = "allow"                      # L0 — automatic
    REQUIRE_CONFIRM = "require_confirm"   # L1 — user must confirm
    DENY = "deny"                         # L2 — blocked


LEVEL_MAP = {
    "L0": Permission.ALLOW,
    "L1": Permission.REQUIRE_CONFIRM,
    "L2": Permission.DENY,
}


@dataclass
class PermissionResult:
    permission: Permission
    level: str          # "L0" / "L1" / "L2"
    reason: str = ""


_RULES_YAML = Path(__file__).parent / "permission_rules.yaml"


class PermissionEngine:
    """Loads permission_rules.yaml and answers permission queries.

    Matching order:
    1. Exact match on server_name + tool_name
    2. Wildcard match on server_name ("*" tool)
    3. Default: L0 (ALLOW) — fail-open with audit warning
    """

    def __init__(self, rules_path: Optional[Path] = None):
        self._rules_path = rules_path or _RULES_YAML
        self._servers: dict[str, dict[str, str]] = {}    # server → tool → level
        self._dsl: dict[str, str] = {}                    # dsl → level
        self._reload()

    def _reload(self):
        if not self._rules_path.exists():
            logger.warning(
                "permission_rules.yaml not found at %s, all operations ALLOW (fail-open)",
                self._rules_path,
            )
            self._servers = {}
            self._dsl = {"*": "L0"}
            return

        try:
            with open(self._rules_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load permission_rules.yaml: {e}, all operations ALLOW")
            self._servers = {}
            self._dsl = {"*": "L0"}
            return

        self._servers = data.get("servers", {}) or {}
        self._dsl = data.get("dsl_actions", {}) or {}

    def check(self, server_name: str, tool_name: str) -> PermissionResult:
        """Check permission for a server + tool combination."""
        rules = self._servers.get(server_name)

        if rules is None:
            # Unknown server — fail-open with audit warning
            logger.warning(
                "Unregistered server '%s' (tool='%s') — defaulting to ALLOW (L0)",
                server_name, tool_name,
            )
            return PermissionResult(
                Permission.ALLOW, "L0",
                reason=f"未注册的 server '{server_name}'，默认放行",
            )

        # Exact tool match
        if tool_name in rules:
            level = rules[tool_name]
            return PermissionResult(
                LEVEL_MAP[level], level,
                reason=f"精确匹配 server={server_name} tool={tool_name} → {level}",
            )

        # Wildcard match
        if "*" in rules:
            level = rules["*"]
            return PermissionResult(
                LEVEL_MAP[level], level,
                reason=f"通配匹配 server={server_name} tool=* → {level}",
            )

        # No match — fail-open
        logger.warning(
            "No rule for server='%s' tool='%s' — defaulting to ALLOW (L0)",
            server_name, tool_name,
        )
        return PermissionResult(
            Permission.ALLOW, "L0",
            reason=f"未注册的 tool '{tool_name}'，默认放行",
        )

    def check_action(self, dsl: str) -> PermissionResult:
        """Check permission for a DSL action string."""
        dsl = dsl.strip()

        # Remove braces for matching
        key = dsl
        if key.startswith("{") and key.endswith("}"):
            key = key[1:-1]

        # Exact match (without braces)
        if key in self._dsl:
            level = self._dsl[key]
            return PermissionResult(
                LEVEL_MAP[level], level,
                reason=f"精确匹配 DSL='{key}' → {level}",
            )

        # Exact match (with braces)
        if dsl in self._dsl:
            level = self._dsl[dsl]
            return PermissionResult(
                LEVEL_MAP[level], level,
                reason=f"精确匹配 DSL='{dsl}' → {level}",
            )

        # Prefix match for dynamic patterns like "set background <path>"
        for rule_key, rule_level in self._dsl.items():
            rk = rule_key.strip()
            if rk.startswith("{") and rk.endswith("}"):
                rk = rk[1:-1]
            if key.startswith(rk) and rk != "*":
                return PermissionResult(
                    LEVEL_MAP[rule_level], rule_level,
                    reason=f"前缀匹配 DSL='{key}' → {rule_key} → {rule_level}",
                )

        # Wildcard match
        if "*" in self._dsl:
            level = self._dsl["*"]
            return PermissionResult(
                LEVEL_MAP[level], level,
                reason=f"通配匹配 DSL='*' → {level}",
            )

        # Default L0
        logger.warning("Unregistered DSL action '%s' — defaulting to ALLOW (L0)", key)
        return PermissionResult(
            Permission.ALLOW, "L0",
            reason=f"未注册的 DSL '{key}'，默认放行",
        )


# ========== Module-level singleton ==========

_permission_engine: Optional[PermissionEngine] = None


def get_permission_engine() -> PermissionEngine:
    global _permission_engine
    if _permission_engine is None:
        _permission_engine = PermissionEngine()
    return _permission_engine
