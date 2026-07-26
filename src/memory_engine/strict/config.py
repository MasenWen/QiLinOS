from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import StrictConfigurationError


STAGE_ORDER = (
    "observation",
    "stm",
    "episode_repair",
    "evidence",
    "tool_preference",
    "output_style",
    "safety",
    "fact",
    "workflow",
    "case",
    "template",
    "memory_update",
    "conflict_classifier",
    "static_resolver",
    "dynamic_resolver",
    "conditional_resolver",
    "confidence",
    "stability",
    "lifecycle",
    "activation",
    "retrieval",
    "forgetting",
    "reflection",
)


@dataclass(frozen=True)
class EpisodeConfig:
    idle_gap_seconds: int
    split_threshold: float
    merge_threshold: float
    merge_gap_seconds: int
    split_weights: Mapping[str, float]
    merge_weights: Mapping[str, float]


@dataclass(frozen=True)
class StrictMemoryEngineConfig:
    schema_version: str
    implementation_id: str
    pipeline_status: str
    strict_full_activation: bool
    database_path: Path
    modules: Mapping[str, str]
    episode: EpisodeConfig
    confidence: Mapping[str, Any]
    stability: Mapping[str, Any]
    lifecycle: Mapping[str, Any]
    conflict: Mapping[str, Any]
    activation: Mapping[str, Any]
    retrieval: Mapping[str, Any]
    source_path: Path

    @classmethod
    def load(
        cls,
        path: str | os.PathLike[str] | None = None,
        *,
        database_path: str | os.PathLike[str] | None = None,
    ) -> "StrictMemoryEngineConfig":
        source = Path(path) if path else _default_config_path()
        with source.open("rb") as stream:
            raw = tomllib.load(stream)
        configured_db = database_path or os.getenv("NEX_MEMORY_ENGINE_STRICT_DB")
        db_path = Path(
            os.path.expanduser(str(configured_db or raw["database_path"]))
        )
        episode = raw.get("episode") or {}
        config = cls(
            schema_version=str(raw.get("schema_version") or ""),
            implementation_id=str(raw.get("implementation_id") or ""),
            pipeline_status=str(raw.get("pipeline_status") or ""),
            strict_full_activation=bool(raw.get("strict_full_activation")),
            database_path=db_path,
            modules=dict(raw.get("modules") or {}),
            episode=EpisodeConfig(
                idle_gap_seconds=int(episode.get("idle_gap_seconds", 900)),
                split_threshold=float(episode.get("split_threshold", 0.60)),
                merge_threshold=float(episode.get("merge_threshold", 0.70)),
                merge_gap_seconds=int(episode.get("merge_gap_seconds", 300)),
                split_weights=dict(episode.get("split_weights") or {}),
                merge_weights=dict(episode.get("merge_weights") or {}),
            ),
            confidence=dict(raw.get("confidence") or {}),
            stability=dict(raw.get("stability") or {}),
            lifecycle=dict(raw.get("lifecycle") or {}),
            conflict=dict(raw.get("conflict") or {}),
            activation=dict(raw.get("activation") or {}),
            retrieval=dict(raw.get("retrieval") or {}),
            source_path=source,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema_version != "memory_engine.strict.config.v1":
            raise StrictConfigurationError(
                f"unsupported strict config schema: {self.schema_version!r}"
            )
        missing = [stage for stage in STAGE_ORDER if not self.modules.get(stage)]
        if missing:
            raise StrictConfigurationError(
                f"strict config has no module id for: {', '.join(missing)}"
            )
        if any(module_id.endswith((".legacy", ".disabled")) for module_id in self.modules.values()):
            raise StrictConfigurationError("strict config cannot select legacy/disabled modules")
        _unit_interval("episode.split_threshold", self.episode.split_threshold)
        _unit_interval("episode.merge_threshold", self.episode.merge_threshold)
        _weights("episode.split_weights", self.episode.split_weights)
        _weights("episode.merge_weights", self.episode.merge_weights)
        lifecycle = self.lifecycle
        promote = float(lifecycle.get("promote_threshold", 0))
        demote = float(lifecycle.get("demote_threshold", 0))
        archive = float(lifecycle.get("archive_threshold", 0))
        recover = float(lifecycle.get("recover_threshold", 0))
        if not promote > demote > archive:
            raise StrictConfigurationError(
                "lifecycle thresholds must satisfy promote > demote > archive"
            )
        if recover <= archive:
            raise StrictConfigurationError(
                "recover threshold must be greater than archive threshold"
            )
        if int(self.conflict.get("behavior_dynamic_min_support", 0)) < 2:
            raise StrictConfigurationError(
                "behavior dynamic support threshold must be at least 2"
            )
        _weights(
            "activation weights",
            {
                key: float(self.activation.get(key, 0.0))
                for key in (
                    "condition_weight",
                    "slot_weight",
                    "task_goal_weight",
                    "semantic_weight",
                    "recency_weight",
                )
            },
        )
        lexical_weight = float(self.retrieval.get("lexical_weight", 0.0))
        semantic_weight = float(
            self.retrieval.get("kylin_semantic_weight", 0.0)
        )
        if abs(lexical_weight + semantic_weight - 1.0) > 1e-9:
            raise StrictConfigurationError(
                "retrieval lexical and Kylin semantic weights must sum to 1.0"
            )

    def stages_through(self, stage: str) -> tuple[str, ...]:
        try:
            index = STAGE_ORDER.index(stage)
        except ValueError as exc:
            raise StrictConfigurationError(f"unknown strict stage: {stage}") from exc
        return STAGE_ORDER[: index + 1]


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "memory_engine_strict_v1.toml"


def _unit_interval(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise StrictConfigurationError(f"{name} must be between 0 and 1")


def _weights(name: str, values: Mapping[str, float]) -> None:
    if not values:
        raise StrictConfigurationError(f"{name} must not be empty")
    total = sum(float(value) for value in values.values())
    if abs(total - 1.0) > 1e-9:
        raise StrictConfigurationError(f"{name} must sum to 1.0, got {total}")
