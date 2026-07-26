from __future__ import annotations

import hashlib
import re

from .models import Evidence, Observation


PREFERENCE_MARKERS = ("喜欢", "偏好", "习惯", "默认", "通常", "经常", "希望", "总是", "每次")
SAFETY_MARKERS = ("发送前", "必须确认", "不要保存", "不要记录", "禁止", "先确认")
EXTERNAL_SEND_MARKERS = ("外部邮件", "外部发送", "发邮件", "发送邮件")
CONFIRM_MARKERS = ("确认", "批准", "同意")


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _slot_for_fact(fact: str) -> str:
    normalized = fact.strip().lower()
    rules = (
        (("usd", "人民币", "美元", "币种"), "preference:currency"),
        (("简洁", "详细", "回复风格", "回答风格"), "preference:response_style"),
        (("发送前", "确认后发送", "先确认", "外部邮件"), "safety:external_send_confirmation"),
        (("保存到", "保存目录", "文件夹"), "preference:save_location"),
        (("标题", "字体", "字号"), "preference:document_style"),
        (("图表", "折线图", "柱状图"), "preference:chart_type"),
        (("vscode", "terminal", "终端", "git status"), "preference:development_workflow"),
    )
    for markers, slot in rules:
        if any(marker in normalized for marker in markers):
            return slot
    tokens = re.findall(r"[a-z0-9_./-]{2,}|[\u4e00-\u9fff]{2,}", normalized)
    signature = "|".join(tokens[:6]) or normalized
    return f"fact:{hashlib.sha256(signature.encode('utf-8')).hexdigest()[:16]}"


def explicit_fact_to_evidence(observation: Observation, fact: str) -> Evidence:
    value = fact.strip()
    slot = _slot_for_fact(value)
    is_safety = any(marker in value for marker in SAFETY_MARKERS) or (
        any(marker in value for marker in EXTERNAL_SEND_MARKERS)
        and any(marker in value for marker in CONFIRM_MARKERS)
    )
    is_preference = (
        is_safety
        or slot.startswith("preference:")
        or any(marker in value for marker in PREFERENCE_MARKERS)
    )
    memory_family = "preference" if is_preference else "knowledge"
    category = "safety_strategy" if is_safety else ("explicit_preference" if is_preference else "personal_fact")
    memory_type = "mid_term"
    evidence_id = _stable_id("ev", f"{observation.observation_id}|{slot}|{value}")
    return Evidence(
        evidence_id=evidence_id,
        user_id=observation.user_id,
        evidence_type="explicit_statement",
        memory_family=memory_family,
        memory_type=memory_type,
        memory_category=category,
        claim_subject=observation.user_id,
        claim_slot=slot,
        claim_value=value,
        claim_polarity="support",
        observed_time=observation.event_time,
        source_observation_ids=(observation.observation_id,),
        independent_unit_id=observation.session_id or observation.source_event_id,
        valid_from=observation.event_time,
        source_reliability=observation.source_reliability,
        extraction_confidence=1.0,
        statistics={"explicit_count": 1},
        extractor={"method": "reviewed_fact_rule", "version": "1.0.0"},
        privacy=observation.privacy,
    )
