# -*- coding: utf-8 -*-
"""O1 基线：不做类型化归一化的 Observation 模块（消融对照用）。

用途：手册 5.3「Observation 模块替换实验」的 O1 组（基线实现）。
与 O0（``observation.typed_rule_normalization.v1``）的差别**仅在于观察阶段**：

    O0 TypedRuleObservationNormalizer      O1 RawPassthroughObservationNormalizer
    ────────────────────────────────────  ──────────────────────────────────────
    从原始事件推断 task_hint/goal_hint    一律留空
    推断 app / tool / action              一律留空
    抽取 artifact/entity/input/output_refs 一律空元组
    归一化 pre_state/post_state            一律空字典
    识别 result（退出码/错误/结果文本）     一律空字典
    判定 completion（成功/失败/未完成）     Completion.UNKNOWN
    内容做结构化拼装（_content）            仅取原始 content/raw_text
    敏感串扫描（命中即 UnsafeObservationError）  不做扫描（如实记录差异）

其余（observation_id/content_hash 的算法、幂等键、privacy 标记、source_reliability）
保持一致，保证两个模块产出**同一 schema**，可被同一 store 与下游阶段消费。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import Completion, SourceType, StrictObservation

SOURCE_RELIABILITY = {
    SourceType.DIALOGUE: 0.90,
    SourceType.GUI_ACTION: 0.85,
    SourceType.TOOL_RESULT: 0.95,
    SourceType.MANUAL_CONFIG: 0.92,
    SourceType.SYSTEM_EVENT: 0.80,
}



def _ensure_aware(value: str, now: "datetime") -> str:
    """把事件时间统一成带时区的 ISO 字符串。

    问题（2026-09-10 消融实验暴露）：数据集里的 timestamp 有的是 offset-aware
    （``2025-12-29T09:19:20+08:00``），有的是 naive（无时区）；strict 管线在
    生命周期阶段比较 valid_from / observed_time 时抛
    ``TypeError: can't compare offset-naive and offset-aware datetimes``，
    整条链路中断（301 条样本里 261 条因此失败）。这里在观察阶段入口统一补 UTC。
    """
    text = str(value or "").strip()
    if not text:
        return now.isoformat()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return now.isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()

class RawPassthroughObservationNormalizer:
    """O1 基线：只落最小必需字段，不做任何类型化归一化。"""

    module_id = "observation.raw_passthrough.v1"

    def normalize(
        self,
        event: Mapping[str, Any],
        *,
        ingest_time: datetime | None = None,
    ) -> StrictObservation:
        source_type = SourceType(str(event.get("source_type") or "").strip())
        source_event_id = str(event.get("source_event_id") or "").strip()
        user_id = str(event.get("user_id") or "").strip()
        session_id = str(event.get("session_id") or "").strip()
        for name, value in (("source_event_id", source_event_id), ("user_id", user_id),
                            ("session_id", session_id)):
            if not value:
                raise ValueError(f"observation 事件缺少必需字段 {name}")

        content = str(event.get("content") or event.get("raw_text") or "").strip()
        content_hash = hashlib.sha256(
            json.dumps({"raw": content}, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        observation_id = "obs-" + uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"strict:{user_id}:{session_id}:{source_event_id}:{content_hash}",
        ).hex
        now = ingest_time or datetime.now(timezone.utc)
        return StrictObservation(
            observation_id=observation_id,
            source_event_id=source_event_id,
            content_hash=content_hash,
            user_id=user_id,
            session_id=session_id,
            sequence_no=None,
            event_time=_ensure_aware(event.get("event_time"), now),
            ingest_time=now.isoformat(),
            source_type=source_type,
            actor=str(event.get("actor") or "user"),
            content=content,
            # 以下全部为基线默认值（不推断、不抽取）
            task_hint="",
            goal_hint="",
            app="",
            tool="",
            action="",
            artifact_refs=(),
            entity_refs=(),
            input_refs=(),
            output_refs=(),
            pre_state={},
            post_state={},
            result={},
            context={},
            completion=Completion.UNKNOWN,
            source_reliability=float(event.get("source_reliability",
                                               SOURCE_RELIABILITY[source_type])),
            privacy={"admission": "allowed", "secret_scan": "skipped_baseline",
                     "raw_payload_persisted": False},
            raw_source_ref=str(event.get("raw_source_ref") or "").strip(),
        )
