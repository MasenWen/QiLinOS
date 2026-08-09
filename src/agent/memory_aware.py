"""
Phase 3: Memory-Aware Tool Selector — retrieval-augmented tool selection.

Given a user query, retrieves relevant memories and uses them to:
  1. Rank/recommend the most relevant tools
  2. Extract parameter defaults from preference memories
  3. Detect conflicting memories that need user resolution
  4. Build memory context for LLM prompt injection

Architecture:
  User Query → MemoryAwareToolSelector.select(query)
    ├─ 1. engine.retrieve(query, top_k=10) → memories
    ├─ 2. _classify_memories() → categorized
    ├─ 3. _rank_tools() → ranked tool list (BM25 + usage frequency)
    ├─ 4. _preferences_to_params() → param defaults
    ├─ 5. _detect_conflicts() → conflict pairs
    └─ 6. _build_prompt_context() → formatted text for LLM
       → ToolSelectionResult
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("agent.memory_aware")


# ============================================================================
# Data types
# ============================================================================

@dataclass
class ConflictPair:
    """Two or more memories that contradict each other on the same key."""
    key: str
    memories: List[Dict[str, Any]]
    resolution: str  # "latest_wins" | "highest_confidence" | "needs_user"
    description: str


@dataclass
class ToolSelectionResult:
    """Output of MemoryAwareToolSelector.select()."""
    ranked_tools: List[Tuple[Any, float]]   # (BaseTool, score) descending
    parameter_defaults: Dict[str, Dict[str, Any]]  # tool_name → {param: default}
    relevant_memories: List[Dict[str, Any]]
    has_conflicts: bool
    conflicts: List[ConflictPair]
    memory_context_text: str  # pre-formatted for LLM prompt injection
    memory_summary: str  # human-readable summary


# ============================================================================
# Memory classification
# ============================================================================

class MemoryClassifier:
    """Classify retrieved memories by type for downstream processing."""

    PREFERENCE_MARKERS = [
        "preference", "default", "偏好", "习惯", "总是", "通常", "默认",
        "喜欢", "prefer", "always", "usually",
    ]

    TOOL_USAGE_MARKERS = [
        "tool_result", "tool_preference", "工具", "使用", "执行",
        "execute", "run", "call",
    ]

    FACT_MARKERS = [
        "fact", "knowledge", "事实", "知识", "流程", "workflow",
    ]

    @classmethod
    def classify(cls, memories: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        result = {
            "preferences": [],
            "tool_usages": [],
            "facts": [],
            "conflicts": [],
            "other": [],
        }
        for mem in memories:
            kind = cls._classify_one(mem)
            result[kind].append(mem)
        return result

    @classmethod
    def _classify_one(cls, mem: Dict[str, Any]) -> str:
        slot = str(mem.get("slot_key", "")).lower()
        family = str(mem.get("memory_family", "")).lower()
        candidate = str(mem.get("candidate_kind", "")).lower()
        value = str(mem.get("semantic_value", "")).lower()

        combined = f"{slot} {family} {candidate} {value}"

        # Check conflict groups
        if mem.get("conflict_group_ids"):
            return "conflicts"

        # Check tool usage
        if any(m in combined for m in cls.TOOL_USAGE_MARKERS):
            return "tool_usages"

        # Check preferences
        if any(m in combined for m in cls.PREFERENCE_MARKERS):
            return "preferences"

        # Check facts
        if any(m in combined for m in cls.FACT_MARKERS):
            return "facts"

        # Default: check if it looks like a preference (key-value pair)
        if "preference" in family or "preference" in candidate:
            return "preferences"
        if "tool" in family or "tool" in candidate:
            return "tool_usages"

        return "other"


# ============================================================================
# Tool ranking
# ============================================================================

class ToolRanker:
    """Rank tools by relevance to the query and historical usage."""

    def __init__(self):
        self._usage_counts: Dict[str, int] = {}

    def rank(
        self,
        query: str,
        tools: List[Any],
        tool_usages: List[Dict[str, Any]],
    ) -> List[Tuple[Any, float]]:
        """Score and rank tools."""
        # Build usage frequency from memory
        for mem in tool_usages:
            tool_name = mem.get("tool_name") or mem.get("tool", "")
            if tool_name:
                self._usage_counts[tool_name] = self._usage_counts.get(tool_name, 0) + 1

        scored = []
        for tool in tools:
            score = self._score_tool(query, tool)
            scored.append((tool, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _score_tool(self, query: str, tool: Any) -> float:
        """Score a single tool against the query."""
        name = getattr(tool, "name", "")
        description = getattr(tool, "description", "")
        keywords = getattr(tool, "memory_hints", None)
        hint_keywords = getattr(keywords, "keywords", []) if keywords else []

        all_text = f"{name} {description} {' '.join(hint_keywords)}"
        query_lower = query.lower()

        # BM25-like scoring (simplified)
        score = 0.0

        # Exact name match
        if name.lower() in query_lower:
            score += 3.0

        # Keyword overlap
        for word in all_text.lower().split():
            if word in query_lower:
                score += 0.5

        # Description overlap
        desc_words = set(description.lower().split())
        query_words = set(query_lower.split())
        overlap = desc_words & query_words
        if overlap:
            score += len(overlap) * 0.3

        # Usage frequency boost
        usage = self._usage_counts.get(name, 0)
        if usage > 0:
            score += min(usage * 0.1, 1.0)  # cap at 1.0 boost

        return score


# ============================================================================
# Preference → Parameter mapping
# ============================================================================

class PreferenceMapper:
    """Extract tool parameter defaults from preference memories."""

    # Known preference key patterns and their tool mappings
    KNOWN_PATTERNS = {
        "timezone": {
            "tools": ["timezone", "set_timezone"],
            "params": {"default_timezone": "timezone", "preferred_timezone": "timezone"},
        },
        "terminal": {
            "tools": ["terminal", "set_terminal"],
            "params": {"columns": "cols", "rows": "rows", "font_size": "font_size"},
        },
        "language": {
            "tools": ["locale", "set_language"],
            "params": {"language": "lang", "locale": "locale"},
        },
        "volume": {
            "tools": ["volume", "set_volume"],
            "params": {"volume_level": "level", "default_volume": "level"},
        },
        "display": {
            "tools": ["display", "set_resolution", "set_brightness"],
            "params": {"resolution": "resolution", "brightness": "brightness"},
        },
    }

    @classmethod
    def extract(
        cls,
        preferences: List[Dict[str, Any]],
        tools: List[Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Extract parameter defaults from preference memories.

        Returns: {tool_name: {param_name: default_value}}
        """
        tool_param_defaults: Dict[str, Dict[str, Any]] = {}

        for pref in preferences:
            slot = str(pref.get("slot_key", "")).lower()
            value = pref.get("semantic_value", "")
            if not value:
                continue

            # Match preferences to tools via KNOWN_PATTERNS
            for pattern_key, mapping in cls.KNOWN_PATTERNS.items():
                if pattern_key in slot or pattern_key in str(value).lower():
                    for pref_key, param_key in mapping["params"].items():
                        if pref_key in slot:
                            for tool_name in mapping["tools"]:
                                if tool_name not in tool_param_defaults:
                                    tool_param_defaults[tool_name] = {}
                                tool_param_defaults[tool_name][param_key] = value
                            break

            # Also check tool memory_hints
            for tool in tools:
                hints = getattr(tool, "memory_hints", None)
                if hints is None:
                    continue
                param_mapping = getattr(hints, "param_mapping", {})
                for mem_key, param_name in param_mapping.items():
                    if mem_key.lower() in slot:
                        if tool.name not in tool_param_defaults:
                            tool_param_defaults[tool.name] = {}
                        tool_param_defaults[tool.name][param_name] = value

        return tool_param_defaults


# ============================================================================
# Conflict detection
# ============================================================================

class ConflictDetector:
    """Detect conflicting memories that need user resolution."""

    @staticmethod
    def detect(memories: List[Dict[str, Any]]) -> List[ConflictPair]:
        conflicts: List[ConflictPair] = []

        # Group by slot_key
        by_slot: Dict[str, List[Dict]] = {}
        for mem in memories:
            slot = str(mem.get("slot_key", "unknown"))
            by_slot.setdefault(slot, []).append(mem)

        # Detect conflicts within each group
        for slot, group in by_slot.items():
            if len(group) < 2:
                continue

            # Check for contradictory values
            values = [str(m.get("semantic_value", "")) for m in group]
            unique_values = list(set(v for v in values if v))

            if len(unique_values) > 1:
                # Determine resolution strategy
                confidences = [m.get("confidence", {}) for m in group]
                abs_confs = [
                    c.get("absolute", 0.5) if isinstance(c, dict) else 0.5
                    for c in confidences
                ]
                max_conf = max(abs_confs) if abs_confs else 0.5
                max_count = abs_confs.count(max_conf)

                if max_count == 1:
                    resolution = "highest_confidence"
                else:
                    # Check recency
                    resolution = "needs_user"

                conflicts.append(ConflictPair(
                    key=slot,
                    memories=group,
                    resolution=resolution,
                    description=(
                        f"Conflicting memories for '{slot}': "
                        f"{', '.join(unique_values[:3])}"
                    ),
                ))

        return conflicts


# ============================================================================
# MemoryAwareToolSelector
# ============================================================================

class MemoryAwareToolSelector:
    """Retrieves memories and uses them to enhance tool selection.

    Usage::

        selector = MemoryAwareToolSelector(memory_engine, tool_registry)
        result = selector.select("set timezone to UTC")
        # result.ranked_tools → [(TimezoneTool, 3.5), ...]
        # result.parameter_defaults → {"timezone": {"timezone": "UTC"}}
        # result.memory_context_text → formatted text for LLM prompt
    """

    def __init__(
        self,
        memory_engine: Any = None,
        tool_registry: Any = None,
        top_k: int = 10,
    ):
        self._engine = memory_engine
        self._registry = tool_registry
        self.top_k = top_k
        self._classifier = MemoryClassifier()
        self._ranker = ToolRanker()
        self._mapper = PreferenceMapper()
        self._detector = ConflictDetector()

    def select(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolSelectionResult:
        """Run the full memory-aware tool selection pipeline."""
        # Step 1: Retrieve memories
        memories = self._retrieve(query, context)

        # Step 2: Classify by type
        classified = self._classifier.classify(memories)

        # Step 3: Rank tools
        tools = self._get_tools()
        ranked = self._ranker.rank(query, tools, classified["tool_usages"])

        # Step 4: Extract parameter defaults
        defaults = self._mapper.extract(classified["preferences"], tools)

        # Step 5: Detect conflicts
        conflicts = self._detector.detect(memories)

        # Step 6: Build context
        context_text = self._build_context(classified, conflicts)

        # Step 7: Summary
        summary = self._build_summary(ranked, defaults, conflicts)

        return ToolSelectionResult(
            ranked_tools=ranked,
            parameter_defaults=defaults,
            relevant_memories=memories,
            has_conflicts=bool(conflicts),
            conflicts=conflicts,
            memory_context_text=context_text,
            memory_summary=summary,
        )

    def _retrieve(self, query: str, context: Optional[Dict] = None) -> List[Dict]:
        if self._engine is None:
            return []
        try:
            response = self._engine.retrieve(query, context=context, top_k=self.top_k)
            if hasattr(response, "items"):
                return response.items
            if isinstance(response, dict):
                return response.get("items", response.get("memories", []))
            return list(response) if response else []
        except Exception as e:
            logger.debug("Memory retrieval skipped: %s", e)
            return []

    def _get_tools(self) -> List[Any]:
        if self._registry is None:
            return []
        try:
            return self._registry.get_tools_for_agent()
        except Exception:
            try:
                return [self._registry.get(n) for n in self._registry.list_all()]
            except Exception:
                return []

    def _build_context(
        self,
        classified: Dict[str, List],
        conflicts: List[ConflictPair],
    ) -> str:
        """Build memory context text for LLM prompt injection."""
        parts = []

        # Preferences
        prefs = classified.get("preferences", [])
        if prefs:
            parts.append("## 🧠 用户偏好记忆")
            for p in prefs[:5]:
                slot = p.get("slot_key", "?")
                value = p.get("semantic_value", "?")
                parts.append(f"- **{slot}**: {value}")
            parts.append("")

        # Tool usage patterns
        usages = classified.get("tool_usages", [])
        if usages:
            parts.append("## 🔧 过往工具使用")
            for u in usages[:5]:
                tool = u.get("tool_name", u.get("tool", "?"))
                status = u.get("action", u.get("status", "?"))
                parts.append(f"- {tool}: {status}")
            parts.append("")

        # Conflicts
        if conflicts:
            parts.append("## ⚠️ 检测到记忆冲突（需确认）")
            for c in conflicts:
                parts.append(f"- **{c.key}**: {c.description}")
            parts.append("")

        return "\n".join(parts) if parts else ""

    def _build_summary(
        self,
        ranked: List[Tuple[Any, float]],
        defaults: Dict[str, Dict[str, Any]],
        conflicts: List[ConflictPair],
    ) -> str:
        lines = []
        if ranked:
            top3 = ranked[:3]
            lines.append(f"推荐工具: {', '.join(t.name for t, _ in top3)}")
        if defaults:
            lines.append(f"参数默认值: {defaults}")
        if conflicts:
            unresolved = [c for c in conflicts if c.resolution == "needs_user"]
            if unresolved:
                lines.append(f"需确认冲突: {len(unresolved)} 项")
        if not lines:
            lines.append("（无相关记忆）")
        return " | ".join(lines)


# ============================================================================
# Integration: MemoryContextBuilder
# ============================================================================

class MemoryContextBuilder:
    """Build memory-enriched prompts for agent nodes (supervisor, planner, etc.).

    This is the component that should be called in LangGraph nodes to inject
    memory context into the LLM prompt.
    """

    @staticmethod
    def inject(
        state: Dict[str, Any],
        selector: Optional[MemoryAwareToolSelector] = None,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Inject memory context into the state before LLM call.

        Usage in supervisor_node:
            state = MemoryContextBuilder.inject(state, selector)
            messages = apply_prompt_template("supervisor", state)
        """
        if selector is None:
            try:
                from src.agent.memory_aware import MemoryAwareToolSelector
                from src.memory_engine.engine import MemoryEngine
                from src.toolkit.base import get_registry
                selector = MemoryAwareToolSelector(
                    memory_engine=MemoryEngine(),
                    tool_registry=get_registry(),
                )
            except Exception:
                return state

        query_text = query or ""
        if not query_text:
            # Extract query from messages
            msgs = state.get("messages", [])
            if msgs:
                last = msgs[-1]
                query_text = getattr(last, "content", str(last))

        if not query_text:
            return state

        result = selector.select(query_text)

        new_state = dict(state)
        new_state["memory_context"] = result.memory_context_text
        new_state["memory_summary"] = result.memory_summary
        new_state["recommended_tools"] = [
            t.name for t, _ in result.ranked_tools[:5]
        ]
        new_state["parameter_defaults"] = result.parameter_defaults
        new_state["memory_conflicts"] = [
            {"key": c.key, "description": c.description}
            for c in result.conflicts
        ]

        return new_state
