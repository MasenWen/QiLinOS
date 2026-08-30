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
        # ---- 2026-08-28 C 方案：单值属性语义归类槽位（供冲突分组，如「住深圳 vs 住杭州」）----
        # 注意：只归【单值属性】（地点/宠物/职业）——多值偏好（运动/饮食/音乐等）
        # 不归类（「喜欢打网球」与「喜欢踢足球」可并存，归同槽会误判冲突）
        (("住在", "居住", "家在", "工作地点", "工作地在", "搬到", "搬家到", "现居",
          "目前住", "目前在", "现在住", "现住在", "re:目前在", "re:现在住"), "personal:location"),
        (("养了", "养一只", "养了只", "宠物是", "宠物叫", "养猫", "养狗", "养了条"), "personal:pet"),
        (("是一名", "是名", "我的职业", "职业是", "工作是", "从事", "任职", "是位",
          "re:在.*上班", "re:在.*工作", "re:是个", "re:是一位"), "personal:occupation"),
    )
    for markers, slot in rules:
        if any(_slot_match(marker, normalized) for marker in markers):
            return slot
    # 职业补充：常见的「用户是X」句式（X 是职业词）→ personal:occupation
    _OCC = ("老师", "教师", "医生", "程序员", "工程师", "律师", "设计师", "会计",
            "护士", "警察", "经理", "主管", "销售", "运营", "产品", "研究员",
            "学生", "教授", "记者", "编辑", "翻译", "司机", "厨师", "电工",
            "木工", "顾问", "分析师", "架构师", "测试", "开发", "前端", "后端")
    if any("是" + w in normalized for w in _OCC) or any(w + "是" in normalized for w in _OCC):
        return "personal:occupation"
    tokens = re.findall(r"[a-z0-9_./-]{2,}|[一-鿿]{2,}", normalized)
    signature = "|".join(tokens[:6]) or normalized
    return f"fact:{hashlib.sha256(signature.encode('utf-8')).hexdigest()[:16]}"


def _slot_match(marker: str, text: str) -> bool:
    """标记匹配：re: 前缀按正则，其余按字面包含（2026-08-30 修复：原正则标记被当字面量）。"""
    if marker.startswith("re:"):
        try:
            return re.search(marker[3:], text) is not None
        except re.error:
            return False
    return marker in text


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
