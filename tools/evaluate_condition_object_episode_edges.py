from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.memory_engine.observation import ObservationMatcher
from src.memory_engine.preference_matching import (
    CanonicalRoleMatch,
    CanonicalTag,
    PreferenceObservationOptions,
)
from src.memory_engine.semantic_episode import (
    SemanticEpisodeConfig,
    SemanticEpisodeEvent,
    group_semantic_episode_events,
)
from src.memory_engine.span_matching import JiebaSpanTokenizer


DEFAULT_OUTPUT = Path(
    "outputs/dialogue_condition_object_episode/"
    "condition_object_episode.json"
)
DEFAULT_OBJECT_BRIDGE_TAG_IDS = ("object:preference_versioning",)


OBJECT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "tag_id": "object:result_selection",
        "name": "工具结果的筛选、排序、版本与来源规则",
        "aliases": (
            "按修改时间排序",
            "保留结果来源",
            "空结果处理",
            "版本差异",
        ),
        "prototypes": (
            "工具结果按新旧、状态和相关性筛选并说明来源",
            "判断最新版本时以实际更新时间为准",
        ),
    },
    {
        "tag_id": "object:operation_process",
        "name": "保存、草稿清理和工作区整理习惯",
        "aliases": (
            "每完成一个阶段就保存",
            "草稿先别删除",
            "窗口集中到一个桌面",
        ),
        "prototypes": (
            "执行任务时采用固定的保存和草稿清理习惯",
            "开始工作前先整理窗口和工作区",
        ),
    },
    {
        "tag_id": "object:output_presentation",
        "name": "输出格式、结构、单位和重点展示规则",
        "aliases": (
            "保留两位小数",
            "用短句和项目符号",
            "先给结论",
            "把单位写清楚",
        ),
        "prototypes": (
            "结果的表格格式、文字结构、数字单位和重点展示偏好",
            "标题简短并按结论依据下一步组织正文",
        ),
    },
    {
        "tag_id": "object:security_boundary",
        "name": "权限、隐私、本地处理和外发确认规则",
        "aliases": (
            "没有权限不要写入",
            "只在本机处理",
            "外发前先确认",
            "不要上传到外部网站",
        ),
        "prototypes": (
            "处理敏感资料时遵守权限、隐私和外发确认限制",
            "安全限制也适用于草稿和临时产物",
        ),
    },
    {
        "tag_id": "object:preference_versioning",
        "name": "旧偏好更新、替换和跨场景生效规则",
        "aliases": (
            "旧的做法作废",
            "新规则生效",
            "以后也一样",
            "不只用于",
        ),
        "prototypes": (
            "用新偏好替代旧偏好并扩展到其他工作场景",
            "规则发生版本更新后停止沿用旧规则",
        ),
    },
    {
        "tag_id": "object:workflow_structure",
        "name": "工作流程步骤、来源和状态约束",
        "aliases": (
            "一直按这个顺序",
            "每一步保留来源",
            "每一步标记状态",
            "未完成项继续跟进",
        ),
        "prototypes": (
            "固定任务流程的步骤顺序、来源记录和状态跟踪",
            "先确认范围再处理并生成可复核结果",
        ),
    },
    {
        "tag_id": "object:historical_reuse",
        "name": "历史案例和旧格式的复用边界",
        "aliases": (
            "参考上次做法",
            "格式可以复用",
            "数据重新核对",
            "旧案例只作参考",
        ),
        "prototypes": (
            "复用历史案例的格式但以本次数据和要求为准",
            "沿用已确认做法同时明确不可照搬的部分",
        ),
    },
    {
        "tag_id": "object:template_schema",
        "name": "可复用模板的字段、顺序和空栏目规则",
        "aliases": (
            "就用这个模板",
            "字段顺序固定",
            "空栏目标待补充",
            "模板只放结构",
        ),
        "prototypes": (
            "沉淀可复用模板并固定字段、顺序和缺失值处理",
            "模板保留结构但不携带上一次的具体数据",
        ),
    },
    {
        "tag_id": "object:associative_retrieval",
        "name": "按路径、时间和参与人关联检索资料的规则",
        "aliases": (
            "顺带找出",
            "结合文件路径",
            "结合时间和参与人",
            "说明关联依据",
        ),
        "prototypes": (
            "检索时关联相关文件、邮件、会议和历史决定",
            "关键词不足时结合路径时间和参与人判断关联",
        ),
    },
    {
        "tag_id": "object:conflict_scope",
        "name": "长期默认、一次性例外和恢复规则",
        "aliases": (
            "只对本次有效",
            "恢复原来的习惯",
            "临时要求不要覆盖",
            "别变成长期开启",
        ),
        "prototypes": (
            "区分长期默认偏好与一次性例外并在任务后恢复",
            "冲突时依据适用范围决定采用哪条规则",
        ),
    },
)


@dataclass(frozen=True)
class DialogueRecord:
    message_text: str
    ability_id: str
    event_time: datetime
    event_id: str
    gold_episode_id: str


@dataclass(frozen=True)
class GoldEpisodeRecord:
    episode_id: str
    context: Mapping[str, Any]


@dataclass(frozen=True)
class EventSemanticMatch:
    event_id: str
    gold_episode_id: str
    event_time: str
    text: str
    condition_tag_id: str | None
    condition_similarity: float | None
    condition_exact: bool
    object_tag_id: str | None
    object_similarity: float | None
    object_exact: bool
    gold_condition_tag_id: str
    gold_object_tag_id: str
    canonical_matches: tuple[Mapping[str, Any], ...]
    latency_ms: float
    embedding_requested: int
    embedding_computed: int
    condition_match_source: str = "primary"
    condition_context_text: str | None = None
    condition_view_scores: Mapping[str, float] = field(
        default_factory=dict
    )


def _matrix_records(path: Path) -> list[dict[str, Any]]:
    matrix = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(matrix, list) or not matrix:
        raise ValueError(f"matrix_is_empty:{path}")
    header = matrix[0]
    if not isinstance(header, list):
        raise ValueError(f"matrix_header_is_invalid:{path}")
    return [
        dict(zip(header, row, strict=False))
        for row in matrix[1:]
        if isinstance(row, list)
        and any(value is not None for value in row)
    ]


def _event_time(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime(1899, 12, 30, tzinfo=timezone.utc) + timedelta(
            days=float(value)
        )
    text = str(value or "").strip()
    if not text:
        raise ValueError("event_time_is_empty")
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def read_dialogue_records(path: Path) -> list[DialogueRecord]:
    return [
        DialogueRecord(
            message_text=str(row.get("message_text") or ""),
            ability_id=str(
                row.get("competition_ability_id") or ""
            ),
            event_time=_event_time(row.get("event_time")),
            event_id=str(row.get("event_id") or ""),
            gold_episode_id=str(row.get("episode_id") or ""),
        )
        for row in _matrix_records(path)
    ]


def read_gold_episodes(
    path: Path,
) -> dict[str, GoldEpisodeRecord]:
    episodes = {}
    for row in _matrix_records(path):
        episode_id = str(row.get("episode_id") or "")
        try:
            context = json.loads(
                str(row.get("context_json") or "{}")
            )
        except json.JSONDecodeError:
            context = {}
        episodes[episode_id] = GoldEpisodeRecord(
            episode_id=episode_id,
            context=context if isinstance(context, Mapping) else {},
        )
    return episodes


def _episode_order(
    records: Iterable[DialogueRecord],
) -> list[tuple[str, list[DialogueRecord]]]:
    grouped: dict[str, list[DialogueRecord]] = {}
    for record in records:
        grouped.setdefault(record.gold_episode_id, []).append(record)
    return [
        (
            episode_id,
            sorted(items, key=lambda item: item.event_time),
        )
        for episode_id, items in grouped.items()
    ]


def _stress_times(
    records: Sequence[DialogueRecord],
    *,
    boundary_gap_seconds: float,
) -> dict[str, datetime]:
    cursor = datetime(2026, 1, 1, tzinfo=timezone.utc)
    output = {}
    for _, episode_records in _episode_order(records):
        source_start = episode_records[0].event_time
        episode_end = cursor
        for record in episode_records:
            shifted = cursor + (record.event_time - source_start)
            episode_end = max(episode_end, shifted)
            output[record.event_id] = shifted
        cursor = episode_end + timedelta(
            seconds=boundary_gap_seconds
        )
    return output


def _pairs(
    groups: Mapping[str, str],
) -> set[tuple[str, str]]:
    by_group: dict[str, list[str]] = defaultdict(list)
    for event_id, group_id in groups.items():
        by_group[group_id].append(event_id)
    return {
        (left, right)
        for items in by_group.values()
        for index, left in enumerate(sorted(items))
        for right in sorted(items)[index + 1 :]
    }


def _group_sets(
    groups: Mapping[str, str],
) -> set[frozenset[str]]:
    by_group: dict[str, set[str]] = defaultdict(set)
    for event_id, group_id in groups.items():
        by_group[group_id].add(event_id)
    return {frozenset(items) for items in by_group.values()}


def _evaluate_groups(
    ordered_event_ids: list[str],
    gold: Mapping[str, str],
    predicted: Mapping[str, str],
) -> dict[str, Any]:
    gold_pairs = _pairs(gold)
    predicted_pairs = _pairs(predicted)
    true_pairs = gold_pairs & predicted_pairs
    gold_sets = _group_sets(gold)
    predicted_sets = _group_sets(predicted)

    gold_to_predicted: dict[str, set[str]] = defaultdict(set)
    predicted_to_gold: dict[str, set[str]] = defaultdict(set)
    for event_id in ordered_event_ids:
        gold_to_predicted[gold[event_id]].add(predicted[event_id])
        predicted_to_gold[predicted[event_id]].add(gold[event_id])

    gold_boundaries = {
        index
        for index in range(1, len(ordered_event_ids))
        if gold[ordered_event_ids[index - 1]]
        != gold[ordered_event_ids[index]]
    }
    predicted_boundaries = {
        index
        for index in range(1, len(ordered_event_ids))
        if predicted[ordered_event_ids[index - 1]]
        != predicted[ordered_event_ids[index]]
    }
    true_boundaries = gold_boundaries & predicted_boundaries
    return {
        "event_count": len(ordered_event_ids),
        "gold_episode_count": len(gold_sets),
        "predicted_episode_count": len(predicted_sets),
        "merge_precision": (
            len(true_pairs) / len(predicted_pairs)
            if predicted_pairs
            else 1.0
        ),
        "merge_recall": (
            len(true_pairs) / len(gold_pairs)
            if gold_pairs
            else 1.0
        ),
        "exact_episode_rate": (
            len(gold_sets & predicted_sets) / len(gold_sets)
            if gold_sets
            else 1.0
        ),
        "intact_gold_episode_rate": (
            sum(len(values) == 1 for values in gold_to_predicted.values())
            / len(gold_to_predicted)
            if gold_to_predicted
            else 1.0
        ),
        "pure_predicted_episode_rate": (
            sum(
                len(values) == 1
                for values in predicted_to_gold.values()
            )
            / len(predicted_to_gold)
            if predicted_to_gold
            else 1.0
        ),
        "boundary_precision": (
            len(true_boundaries) / len(predicted_boundaries)
            if predicted_boundaries
            else (1.0 if not gold_boundaries else 0.0)
        ),
        "boundary_recall": (
            len(true_boundaries) / len(gold_boundaries)
            if gold_boundaries
            else 1.0
        ),
        "overmerged_predicted_episodes": sum(
            len(values) > 1
            for values in predicted_to_gold.values()
        ),
        "split_gold_episodes": sum(
            len(values) > 1
            for values in gold_to_predicted.values()
        ),
    }


def _stable_suffix(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _condition_tag_id(task: str) -> str:
    return f"condition:task:{_stable_suffix(task)}"


def _object_tag_id(ability_id: str) -> str:
    mapping = {
        "tool_result_preference_capture": "object:result_selection",
        "operation_habit_capture": "object:operation_process",
        "output_style_preference": "object:output_presentation",
        "security_strategy_preference": "object:security_boundary",
        "version_update_cross_scene_reuse": "object:preference_versioning",
        "workflow_knowledge_structuring": "object:workflow_structure",
        "historical_case_reuse": "object:historical_reuse",
        "reusable_template_distillation": "object:template_schema",
        "associative_retrieval": "object:associative_retrieval",
        "conflict_detection_fusion": "object:conflict_scope",
    }
    return mapping[ability_id]


def _tag_catalog(
    gold_episodes: Mapping[str, Any],
) -> tuple[tuple[CanonicalTag, ...], dict[str, str]]:
    conditions: dict[str, CanonicalTag] = {}
    gold_condition_ids = {}
    for episode_id, episode in gold_episodes.items():
        task = str(episode.context.get("task") or "").strip()
        artifact = str(episode.context.get("artifact") or "").strip()
        topic = str(episode.context.get("topic") or "").strip()
        tag_id = _condition_tag_id(task)
        gold_condition_ids[episode_id] = tag_id
        conditions.setdefault(
            tag_id,
            CanonicalTag(
                tag_id=tag_id,
                name=task,
                groups=("condition",),
                aliases=tuple(
                    value
                    for value in (task, artifact, topic)
                    if value
                ),
                prototypes=(
                    f"在{task}这个工作场景中处理任务",
                    f"围绕{topic}处理{artifact}",
                ),
            ),
        )
    objects = tuple(
        CanonicalTag(
            tag_id=str(spec["tag_id"]),
            name=str(spec["name"]),
            groups=("object",),
            aliases=tuple(spec["aliases"]),
            prototypes=tuple(spec["prototypes"]),
        )
        for spec in OBJECT_SPECS
    )
    return (
        tuple(sorted(conditions.values(), key=lambda tag: tag.tag_id))
        + objects,
        gold_condition_ids,
    )


def _best_match(
    matches: Sequence[CanonicalRoleMatch],
    group: str,
    *,
    min_similarity: float,
    min_margin: float,
) -> CanonicalRoleMatch | None:
    by_tag: dict[str, CanonicalRoleMatch] = {}
    for match in matches:
        if match.group != group:
            continue
        previous = by_tag.get(match.tag_id)
        if previous is None or (
            match.exact_alias,
            match.score,
            match.hypothesis_score,
        ) > (
            previous.exact_alias,
            previous.score,
            previous.hypothesis_score,
        ):
            by_tag[match.tag_id] = match
    if not by_tag:
        return None
    best = max(
        by_tag.values(),
        key=lambda match: (
            match.exact_alias,
            match.score,
            match.hypothesis_score,
            -match.start,
        ),
    )
    if best.exact_alias:
        return best
    if (
        best.similarity < min_similarity
        or best.competition_margin < min_margin
    ):
        return None
    return best


def extract_matches(
    records: Sequence[DialogueRecord],
    gold_episodes: Mapping[str, Any],
    *,
    condition_min_similarity: float,
    object_min_similarity: float,
    min_margin: float,
    condition_fallback_min_similarity: float = 0.72,
    condition_fallback_min_margin: float = 0.04,
    condition_fallback_top_k: int = 5,
    enable_condition_fallback: bool = False,
) -> tuple[list[EventSemanticMatch], dict[str, Any]]:
    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except (ImportError, OSError):
        from tools.evaluate_kylin_embedding_preference_object_blind import (
            KylinTextEmbedding,
        )

    tags, gold_condition_ids = _tag_catalog(gold_episodes)
    condition_ids = tuple(
        tag.tag_id for tag in tags if "condition" in tag.groups
    )
    object_ids = tuple(
        tag.tag_id for tag in tags if "object" in tag.groups
    )
    initialized = time.perf_counter()
    matcher = ObservationMatcher(
        KylinTextEmbedding(),
        tokenizer=JiebaSpanTokenizer(),
        tags=tags,
    )
    initialization_ms = (time.perf_counter() - initialized) * 1000.0

    rows = []
    for index, record in enumerate(records, 1):
        started = time.perf_counter()
        options = PreferenceObservationOptions(
            condition_tag_ids=condition_ids,
            object_tag_ids=object_ids,
        )
        result = matcher.match(
            record.message_text,
            options=options,
        )
        condition = _best_match(
            result.canonical_matches,
            "condition",
            min_similarity=condition_min_similarity,
            min_margin=min_margin,
        )
        obj = _best_match(
            result.canonical_matches,
            "object",
            min_similarity=object_min_similarity,
            min_margin=min_margin,
        )
        condition_match_source = "primary"
        condition_context_text = None
        fallback_results = ()
        fallback_matches: list[CanonicalRoleMatch] = []
        condition_view_scores: dict[str, float] = {}
        if condition is None and enable_condition_fallback:
            fallback_results = matcher.match_condition_contexts(
                record.message_text,
                options=options,
                multiview=True,
                top_k_per_context=condition_fallback_top_k,
                include_below_threshold=True,
            )
            fallback_candidates = []
            for fallback in fallback_results:
                shifted = tuple(
                    replace(
                        match,
                        start=(
                            match.start + fallback.context.start
                        ),
                        end=match.end + fallback.context.start,
                        sources=tuple(
                            dict.fromkeys(
                                (
                                    *match.sources,
                                    "condition_context_fallback",
                                )
                            )
                        ),
                    )
                    for match in fallback.result.canonical_matches
                )
                fallback_matches.extend(shifted)
                for match in shifted:
                    condition_view_scores[match.tag_id] = max(
                        condition_view_scores.get(match.tag_id, -1.0),
                        match.similarity,
                    )
                candidate = _best_match(
                    shifted,
                    "condition",
                    min_similarity=(
                        condition_fallback_min_similarity
                    ),
                    min_margin=condition_fallback_min_margin,
                )
                if candidate is not None:
                    fallback_candidates.append(
                        (candidate, fallback.context.text)
                    )
            if fallback_candidates:
                condition, condition_context_text = max(
                    fallback_candidates,
                    key=lambda item: (
                        item[0].exact_alias,
                        item[0].similarity,
                        item[0].competition_margin,
                        item[0].score,
                    ),
                )
                condition_match_source = "short_context_fallback"
        latency_ms = (time.perf_counter() - started) * 1000.0
        all_results = (result,) + tuple(
            fallback.result for fallback in fallback_results
        )
        rows.append(
            EventSemanticMatch(
                event_id=record.event_id,
                gold_episode_id=record.gold_episode_id,
                event_time=record.event_time.isoformat(),
                text=record.message_text,
                condition_tag_id=(
                    condition.tag_id if condition is not None else None
                ),
                condition_similarity=(
                    condition.similarity
                    if condition is not None
                    else None
                ),
                condition_exact=bool(
                    condition is not None and condition.exact_alias
                ),
                object_tag_id=obj.tag_id if obj is not None else None,
                object_similarity=(
                    obj.similarity if obj is not None else None
                ),
                object_exact=bool(obj is not None and obj.exact_alias),
                gold_condition_tag_id=gold_condition_ids[
                    record.gold_episode_id
                ],
                gold_object_tag_id=_object_tag_id(record.ability_id),
                canonical_matches=tuple(
                    asdict(match)
                    for match in (
                        *result.canonical_matches,
                        *fallback_matches,
                    )
                ),
                latency_ms=latency_ms,
                embedding_requested=sum(
                    int(
                        value.diagnostics[
                            "embedding_requested_delta"
                        ]
                    )
                    for value in all_results
                ),
                embedding_computed=sum(
                    int(
                        value.diagnostics[
                            "embedding_computed_delta"
                        ]
                    )
                    for value in all_results
                ),
                condition_match_source=condition_match_source,
                condition_context_text=condition_context_text,
                condition_view_scores=condition_view_scores,
            )
        )
        if index % 50 == 0:
            print(f"matched={index}/{len(records)}", flush=True)

    latencies = [row.latency_ms for row in rows]
    diagnostics = {
        "initialization_ms": initialization_ms,
        "latency": {
            "mean_ms": statistics.fmean(latencies) if latencies else 0.0,
            "median_ms": statistics.median(latencies) if latencies else 0.0,
            "p95_ms": (
                sorted(latencies)[
                    min(
                        len(latencies) - 1,
                        int(0.95 * len(latencies)),
                    )
                ]
                if latencies
                else 0.0
            ),
            "max_ms": max(latencies) if latencies else 0.0,
        },
        "embedding_requested": sum(
            row.embedding_requested for row in rows
        ),
        "embedding_computed": sum(
            row.embedding_computed for row in rows
        ),
        "condition_tag_count": len(condition_ids),
        "object_tag_count": len(object_ids),
        "condition_context_fallback": {
            "enabled": enable_condition_fallback,
            "min_similarity": condition_fallback_min_similarity,
            "min_margin": condition_fallback_min_margin,
            "top_k_per_context": condition_fallback_top_k,
            "formed": sum(
                row.condition_match_source
                == "short_context_fallback"
                for row in rows
            ),
        },
    }
    return rows, diagnostics


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _semantic_groups(
    rows: Sequence[EventSemanticMatch],
    *,
    use_condition: bool,
    use_object: bool,
    time_fallback_seconds: float | None,
    retroactive_unknown_condition: bool = False,
    object_conflict_confirmation: int = 1,
    object_bridge_tag_ids: tuple[str, ...] = (
        DEFAULT_OBJECT_BRIDGE_TAG_IDS
    ),
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    grouped = group_semantic_episode_events(
        (
            SemanticEpisodeEvent(
                event_id=row.event_id,
                observed_time=row.event_time,
                condition_tag_ids=(
                    (row.condition_tag_id,)
                    if use_condition and row.condition_tag_id
                    else ()
                ),
                object_tag_ids=(
                    (row.object_tag_id,)
                    if use_object and row.object_tag_id
                    else ()
                ),
            )
            for row in rows
        ),
        config=SemanticEpisodeConfig(
            time_fallback_seconds=time_fallback_seconds,
            retroactive_unknown_condition=(
                retroactive_unknown_condition
            ),
            object_conflict_confirmation=(
                object_conflict_confirmation
            ),
            object_bridge_tag_ids=object_bridge_tag_ids,
        ),
    )
    decisions = []
    for row, decision in zip(
        rows,
        grouped.decisions,
        strict=True,
    ):
        payload = decision.to_dict()
        payload.update(
            {
                "current_condition": row.condition_tag_id,
                "current_object": row.object_tag_id,
            }
        )
        decisions.append(payload)
    return dict(grouped.assignments), decisions


def _span_summary(
    rows: Sequence[EventSemanticMatch],
    field: str,
) -> dict[str, Any]:
    prediction_name = f"{field}_tag_id"
    gold_name = f"gold_{field}_tag_id"
    formed = [
        row
        for row in rows
        if getattr(row, prediction_name) is not None
    ]
    correct = sum(
        getattr(row, prediction_name) == getattr(row, gold_name)
        for row in formed
    )
    result = {
        "formed": len(formed),
        "total": len(rows),
        "formation_rate": len(formed) / len(rows) if rows else 1.0,
    }
    if field == "condition":
        result.update(
            {
                "reference": "episode_task",
                "correct_when_formed": (
                    correct / len(formed) if formed else 1.0
                ),
                "total_recall": (
                    correct / len(rows) if rows else 1.0
                ),
            }
        )
    else:
        result.update(
            {
                "reference": "broad_episode_object_family",
                "family_agreement_when_formed": (
                    correct / len(formed) if formed else 1.0
                ),
                "family_recall": (
                    correct / len(rows) if rows else 1.0
                ),
                "note": (
                    "Diagnostic only: a sentence may validly express a "
                    "narrower object than its episode-wide family."
                ),
            }
        )
    return result


def _error_examples(
    rows: Sequence[EventSemanticMatch],
    predicted: Mapping[str, str],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    by_predicted: dict[str, list[EventSemanticMatch]] = defaultdict(list)
    by_gold: dict[str, list[EventSemanticMatch]] = defaultdict(list)
    for row in rows:
        by_predicted[predicted[row.event_id]].append(row)
        by_gold[row.gold_episode_id].append(row)

    def render(
        group_id: str,
        values: Sequence[EventSemanticMatch],
    ) -> dict[str, Any]:
        return {
            "group_id": group_id,
            "gold_episode_ids": sorted(
                {value.gold_episode_id for value in values}
            ),
            "predicted_episode_ids": sorted(
                {predicted[value.event_id] for value in values}
            ),
            "events": [
                {
                    "event_id": value.event_id,
                    "gold_episode_id": value.gold_episode_id,
                    "condition": value.condition_tag_id,
                    "object": value.object_tag_id,
                    "text": value.text,
                }
                for value in values[:10]
            ],
        }

    return {
        "overmerged": [
            render(group_id, values)
            for group_id, values in by_predicted.items()
            if len({value.gold_episode_id for value in values}) > 1
        ][:limit],
        "split": [
            render(group_id, values)
            for group_id, values in by_gold.items()
            if len({predicted[value.event_id] for value in values}) > 1
        ][:limit],
    }


def evaluate_matches(
    records: Sequence[DialogueRecord],
    rows: Sequence[EventSemanticMatch],
    *,
    time_fallback_seconds: float,
    retroactive_unknown_condition: bool = False,
    object_conflict_confirmation: int = 1,
    object_bridge_tag_ids: tuple[str, ...] = (
        DEFAULT_OBJECT_BRIDGE_TAG_IDS
    ),
) -> dict[str, Any]:
    source_by_id = {row.event_id: row for row in rows}
    stress_times = _stress_times(
        records,
        boundary_gap_seconds=45.0,
    )
    stress_rows = []
    for record in records:
        source = source_by_id[record.event_id]
        stress_rows.append(
            EventSemanticMatch(
                **{
                    **asdict(source),
                    "event_time": stress_times[
                        record.event_id
                    ].isoformat(),
                }
            )
        )
    ordered_ids = [row.event_id for row in stress_rows]
    gold = {
        row.event_id: row.gold_episode_id for row in stress_rows
    }
    variants = {}
    for name, use_condition, use_object, fallback in (
        (
            "time_only_control",
            False,
            False,
            time_fallback_seconds,
        ),
        ("condition_only", True, False, None),
        ("condition_object", True, True, None),
        (
            "condition_object_time_fallback",
            True,
            True,
            time_fallback_seconds,
        ),
    ):
        predicted, decisions = _semantic_groups(
            stress_rows,
            use_condition=use_condition,
            use_object=use_object,
            time_fallback_seconds=fallback,
            retroactive_unknown_condition=(
                retroactive_unknown_condition
            ),
            object_conflict_confirmation=(
                object_conflict_confirmation
            ),
            object_bridge_tag_ids=object_bridge_tag_ids,
        )
        variants[name] = {
            "metrics": _evaluate_groups(
                ordered_ids,
                gold,
                predicted,
            ),
            "reason_counts": dict(
                sorted(
                    (
                        reason,
                        sum(
                            decision["reason"] == reason
                            for decision in decisions
                        ),
                    )
                    for reason in {
                        decision["reason"]
                        for decision in decisions
                    }
                )
            ),
            "errors": _error_examples(stress_rows, predicted),
            "decisions": decisions,
        }
    return {
        "span_matching": {
            "condition": _span_summary(rows, "condition"),
            "object": _span_summary(rows, "object"),
        },
        "episode_variants": variants,
    }


def _read_matches(path: Path) -> list[EventSemanticMatch]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = payload.get("matches", payload)
    return [
        EventSemanticMatch(
            **{
                **row,
                "canonical_matches": tuple(
                    row.get("canonical_matches", ())
                ),
            }
        )
        for row in source
    ]


def _apply_saved_match_thresholds(
    rows: Sequence[EventSemanticMatch],
    *,
    condition_min_similarity: float,
    object_min_similarity: float,
) -> list[EventSemanticMatch]:
    filtered = []
    for row in rows:
        condition_rejected = bool(
            row.condition_tag_id
            and not row.condition_exact
            and (
                row.condition_similarity is None
                or row.condition_similarity
                < condition_min_similarity
            )
        )
        object_rejected = bool(
            row.object_tag_id
            and not row.object_exact
            and (
                row.object_similarity is None
                or row.object_similarity < object_min_similarity
            )
        )
        filtered.append(
            replace(
                row,
                condition_tag_id=(
                    None
                    if condition_rejected
                    else row.condition_tag_id
                ),
                condition_similarity=(
                    None
                    if condition_rejected
                    else row.condition_similarity
                ),
                condition_exact=(
                    False
                    if condition_rejected
                    else row.condition_exact
                ),
                object_tag_id=(
                    None if object_rejected else row.object_tag_id
                ),
                object_similarity=(
                    None
                    if object_rejected
                    else row.object_similarity
                ),
                object_exact=(
                    False if object_rejected else row.object_exact
                ),
            )
        )
    return filtered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events-matrix", type=Path, required=True)
    parser.add_argument("--episodes-matrix", type=Path, required=True)
    parser.add_argument("--matches", type=Path)
    parser.add_argument("--extract-only", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--condition-min-similarity",
        type=float,
        default=0.57,
    )
    parser.add_argument(
        "--object-min-similarity",
        type=float,
        default=0.57,
    )
    parser.add_argument("--min-margin", type=float, default=0.0)
    parser.add_argument(
        "--condition-fallback-min-similarity",
        type=float,
        default=0.72,
    )
    parser.add_argument(
        "--condition-fallback-min-margin",
        type=float,
        default=0.04,
    )
    parser.add_argument(
        "--condition-fallback-top-k",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--enable-condition-fallback",
        action="store_true",
    )
    parser.add_argument(
        "--object-conflict-confirmation",
        type=int,
        choices=(1, 2),
        default=1,
    )
    parser.add_argument(
        "--enable-retroactive-condition",
        action="store_true",
    )
    parser.add_argument(
        "--disable-object-bridge",
        action="store_true",
    )
    parser.add_argument(
        "--time-fallback-seconds",
        type=float,
        default=30.0,
    )
    args = parser.parse_args()

    records = read_dialogue_records(args.events_matrix)
    gold_episodes = read_gold_episodes(args.episodes_matrix)
    if args.matches:
        rows = _apply_saved_match_thresholds(
            _read_matches(args.matches),
            condition_min_similarity=(
                args.condition_min_similarity
            ),
            object_min_similarity=args.object_min_similarity,
        )
        extraction = {"source": str(args.matches)}
    else:
        rows, extraction = extract_matches(
            records,
            gold_episodes,
            condition_min_similarity=args.condition_min_similarity,
            object_min_similarity=args.object_min_similarity,
            min_margin=args.min_margin,
            condition_fallback_min_similarity=(
                args.condition_fallback_min_similarity
            ),
            condition_fallback_min_margin=(
                args.condition_fallback_min_margin
            ),
            condition_fallback_top_k=args.condition_fallback_top_k,
            enable_condition_fallback=(
                args.enable_condition_fallback
            ),
        )

    output = {
        "purpose": (
            "Test whether Episode boundaries can be inferred from the "
            "existing condition/object Observation spans without a role span."
        ),
        "uses_llm_at_runtime": False,
        "leakage_controls": {
            "utterance_role_used_for_grouping": False,
            "episode_id_used_for_grouping": False,
            "gold_used_after_grouping_only": True,
            "object_labels_describe_preference_subjects_not_roles": True,
        },
        "thresholds": {
            "condition_min_similarity": args.condition_min_similarity,
            "object_min_similarity": args.object_min_similarity,
            "min_margin": args.min_margin,
            "time_fallback_seconds": args.time_fallback_seconds,
            "condition_fallback_min_similarity": (
                args.condition_fallback_min_similarity
            ),
            "condition_fallback_min_margin": (
                args.condition_fallback_min_margin
            ),
            "condition_fallback_top_k": args.condition_fallback_top_k,
            "condition_fallback_enabled": (
                args.enable_condition_fallback
            ),
            "retroactive_unknown_condition": (
                args.enable_retroactive_condition
            ),
            "object_conflict_confirmation": (
                args.object_conflict_confirmation
            ),
            "object_bridge_tag_ids": (
                []
                if args.disable_object_bridge
                else list(DEFAULT_OBJECT_BRIDGE_TAG_IDS)
            ),
        },
        "extraction": extraction,
        "matches": [asdict(row) for row in rows],
    }
    if not args.extract_only:
        output["evaluation"] = evaluate_matches(
            records,
            rows,
            time_fallback_seconds=args.time_fallback_seconds,
            retroactive_unknown_condition=(
                args.enable_retroactive_condition
            ),
            object_conflict_confirmation=(
                args.object_conflict_confirmation
            ),
            object_bridge_tag_ids=(
                ()
                if args.disable_object_bridge
                else DEFAULT_OBJECT_BRIDGE_TAG_IDS
            ),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    evaluation = output.get("evaluation")
    summary = {"extraction": extraction}
    if evaluation is not None:
        summary["span_matching"] = evaluation["span_matching"]
        summary["episode_variants"] = {
            name: value["metrics"]
            for name, value in evaluation[
                "episode_variants"
            ].items()
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
