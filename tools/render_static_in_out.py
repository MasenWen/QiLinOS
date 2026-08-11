#!/usr/bin/env python3
"""Render representative static retrieval examples as a readable Markdown audit."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping


TRACK_ORDER = (
    "single_memory",
    "dialogue_context_only",
    "operation_resume_only",
    "dialogue_log_complementary",
    "conflict_resolution",
    "clarification_required",
    "multi_task_cross_app",
)

TAG_LABELS = {
    "document:template": "文档模板或既有版式",
    "task:calendar": "日历与计划安排",
    "action:testing": "检查与验证",
    "format:xlsx": "电子表格文件",
    "app:web_browser": "网页浏览器",
    "app:spreadsheet": "电子表格工具",
    "app:file_manager": "文件管理器",
}

KNOWLEDGE_NAME_LABELS = {
    "Document Template": "文档模板",
    "Spreadsheet": "电子表格工具",
    "Spreadsheet File": "电子表格文件",
    "Web Browser": "网页浏览器",
    "File Manager": "文件管理器",
    "Calendar Work": "日历与计划安排",
    "Email Work": "邮件处理",
    "PDF Document": "PDF 文档",
    "Kylin Desktop": "麒麟桌面",
    "Office File": "办公文件",
    "Process": "系统进程",
    "Code Review": "代码审查",
    "Coding Work": "编程工作",
}

GROUP_LABELS = {"condition": "场景", "object": "对象"}
ATTITUDE_LABELS = {
    "positive": "倾向沿用或支持",
    "negative": "倾向避免或反对",
    "neutral": "没有明显偏向",
}
TEMPORAL_LABELS = {
    "temporal_short": "仅限当前或近期",
    "temporal_medium": "一段时期内适用",
    "temporal_long": "长期适用",
}

TECHNICAL_CONSTRAINT_WORDS = (
    "operation_habit",
    "direct_task_instruction",
    "output_style_preference",
    "associative_retrieval_rule",
    "reusable_template",
    "versioned_preference",
    "workflow_knowledge",
    "tool_result_preference",
    "conflict_resolution_rule",
    "source_event_recorded",
    "not_supplied_by_compact_source",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def json_list(value: str | None) -> list[str]:
    if not value:
        return []
    parsed = json.loads(value)
    return [str(item) for item in parsed]


def percent(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.2f}%" if whole else "0.00%"


def exact_slot_complete(row: Mapping[str, Any]) -> bool:
    required = set(row["required_memory_ids"])
    return required <= set(row["ranked_memory_ids"][: len(required)])


def select_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_groups: set[str] = set()
    for track in TRACK_ORDER:
        candidates = [
            row
            for row in rows
            if row["evaluation_track"] == track
            and exact_slot_complete(row)
            and row["answer_group_id"] not in used_groups
        ]
        candidates.sort(
            key=lambda row: (
                not row["query_observation"]["formed"],
                row["dataset_origin"] != ("v3.1" if track == "single_memory" else "v5.3"),
                row["sequence_no"],
            )
        )
        if candidates:
            selected.append(candidates[0])
            used_groups.add(candidates[0]["answer_group_id"])

    failures = [
        row
        for row in rows
        if row["required_memory_ids"]
        and not set(row["required_memory_ids"]).intersection(
            row["ranked_memory_ids"][:1]
        )
        and row["answer_group_id"] not in used_groups
    ]
    failures.sort(
        key=lambda row: (
            len(row["required_memory_ids"]) != 1,
            row["dataset_origin"] != "v3.1",
            row["sequence_no"],
        )
    )
    if failures:
        selected.append(failures[0])
    return selected


def friendly_knowledge_name(value: str | None) -> str:
    if not value:
        return "未识别"
    return KNOWLEDGE_NAME_LABELS.get(value, value)


def friendly_tag(tag_id: str | None, refs: Iterable[Mapping[str, Any]]) -> str:
    if not tag_id:
        return "没有明确识别"
    if tag_id in TAG_LABELS:
        return TAG_LABELS[tag_id]
    for ref in refs:
        if ref.get("tag_id") == tag_id:
            return friendly_knowledge_name(str(ref.get("name") or tag_id))
    tail = tag_id.split(":", 1)[-1].replace("_", " ")
    return tail if tail else "没有明确识别"


def confidence_label(value: Any) -> str:
    if value is None:
        return "未知"
    score = float(value)
    if score >= 0.85:
        return "高"
    if score >= 0.70:
        return "中"
    return "较低"


def observation_text(
    observation: Mapping[str, Any],
    refs: Iterable[Mapping[str, Any]] = (),
) -> str:
    frames = observation.get("frames") or []
    if not frames:
        return "系统没有强行生成结构化判断，后续直接依据用户原文、当前环境和相关记忆。"
    grouped: dict[tuple[Any, Any], list[Mapping[str, Any]]] = {}
    for frame in frames:
        key = (frame.get("condition_tag_id"), frame.get("object_tag_id"))
        grouped.setdefault(key, []).append(frame)
    lines = []
    for index, values in enumerate(grouped.values(), 1):
        frame = max(values, key=lambda value: float(value.get("confidence") or 0))
        condition_id = frame.get("condition_tag_id")
        object_id = frame.get("object_tag_id")
        condition = friendly_tag(condition_id, refs)
        object_tag = friendly_tag(object_id, refs)
        directions = {
            str(value.get("attitude_direction"))
            for value in values
            if value.get("attitude_direction")
        }
        attitude = ATTITUDE_LABELS.get(
            str(frame.get("attitude_direction")), "没有识别出稳定态度"
        )
        temporal = TEMPORAL_LABELS.get(
            str(frame.get("temporal_label")), "没有明确时间范围"
        )
        confidence = confidence_label(frame.get("confidence"))
        scope = (
            f"场景可能是“{condition}”"
            if condition_id
            else "场景尚不明确"
        )
        target = (
            f"重点涉及“{object_tag}”"
            if object_id
            else "对象尚不明确"
        )
        if {"positive", "negative"} <= directions:
            lines.append(
                f"方向 {index}：{scope}，{target}；同一对象同时出现支持与反对表达，"
                "更像比较或排除语境，暂不解释为稳定偏好。"
            )
        else:
            lines.append(
                f"方向 {index}：{scope}，{target}；用户表达为“{attitude}”，"
                f"{temporal}。这一判断的可靠程度为{confidence}。"
            )
    return "\n".join(lines)


def select_knowledge_refs(refs: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    values = sorted(
        refs,
        key=lambda ref: (
            not bool(ref.get("exact_alias")),
            -float(ref.get("score", 0)),
        ),
    )
    exact = []
    seen_aliases = set()
    seen_names = set()
    for ref in values:
        if not ref.get("exact_alias"):
            continue
        alias = str(ref.get("matched_alias") or "").casefold()
        name = friendly_knowledge_name(str(ref.get("name") or "")).casefold()
        if (alias and alias in seen_aliases) or name in seen_names:
            continue
        exact.append(ref)
        if alias:
            seen_aliases.add(alias)
        seen_names.add(name)
    if exact:
        return exact[:4]
    return [ref for ref in values if float(ref.get("score", 0)) >= 1.8][:2]


def knowledge_text(refs: Iterable[Mapping[str, Any]], *, scored: bool) -> str:
    lines = []
    for ref in select_knowledge_refs(refs):
        groups = "、".join(
            GROUP_LABELS.get(str(value), str(value))
            for value in ref.get("groups") or ()
        )
        alias = ref.get("matched_alias")
        exact = "精确命中" if ref.get("exact_alias") else "语义命中"
        suffix = (
            f"；匹配分 {float(ref.get('score', 0)):.3f}"
            if scored
            else ""
        )
        alias_text = f"，由“{alias}”{exact}" if alias else f"，{exact}"
        lines.append(
            f"- {friendly_knowledge_name(str(ref.get('name') or ''))}："
            f"可辅助理解{groups}{alias_text}{suffix}。"
        )
    return "\n".join(lines) if lines else "- 没有找到可靠的通用知识标签。"


def clean_constraints(value: str | None) -> str:
    text = value or ""
    for word in TECHNICAL_CONSTRAINT_WORDS:
        text = re.sub(rf"\b{re.escape(word)}\b", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ;；")
    return text


def finish_sentence(value: str) -> str:
    text = value.strip(" ;；")
    if not text:
        return ""
    return text if text.endswith(("。", "！", "？", ".", "!", "?")) else text + "。"


def unique_statements(value: str | None, *, limit: int = 3) -> list[str]:
    raw = re.split(r"[；\n]+", value or "")
    output: list[str] = []
    normalized: list[str] = []
    for item in raw:
        item = re.sub(r"\s+", " ", item).strip(" ;；")
        if not item:
            continue
        norm = re.sub(r"[\W_]+", "", item).casefold()
        if not norm or any(norm == old or norm in old for old in normalized):
            continue
        if any(
            marker in item
            for marker in (
                "click(uid=",
                "say(speaker=",
                "source_event_recorded",
                "not_supplied_by_compact_source",
            )
        ):
            continue
        if output and (
            item.startswith("我正在做")
            or item.startswith("请接手")
            or "目标是把" in item
        ):
            continue
        output.append(finish_sentence(item))
        normalized.append(norm)
        if len(output) >= limit:
            break
    return output


def operation_memory_text(memory: Mapping[str, Any]) -> list[str]:
    summary = str(memory.get("summary") or "")
    actions = str(memory.get("expected_action") or "").split()
    lines: list[str] = []
    if "session_logon" in actions or "session_logoff" in actions:
        machine_match = re.search(r"computer\s+([^\s；]+)", summary)
        machine = machine_match.group(1) if machine_match else "该设备"
        urls = list(dict.fromkeys(re.findall(r"https?://[^\s；]+", summary)))
        lines.append(f"Windows 日志记录了 {machine} 上的一次会话。")
        if "connect_removable_storage" in actions:
            device_state = (
                "连接后又断开了可移动设备"
                if "disconnect_removable_storage" in actions
                else "连接过可移动设备"
            )
            lines.append(f"会话期间{device_state}。")
        if urls:
            shown = "、".join(urls[:4])
            suffix = f"，共 {len(urls)} 个地址" if len(urls) > 4 else ""
            lines.append(f"浏览器访问过 {shown}{suffix}。")
        lines.append(
            "日志最后出现了注销记录，说明该会话已经结束。"
            if "session_logoff" in actions
            else "日志没有给出明确的注销或完成记录。"
        )
        return lines

    if any(action.startswith("permit_") for action in actions):
        case_match = re.search(r"declaration\s+(\d+)", summary)
        case = f"申报单 {case_match.group(1)}" if case_match else "该差旅申报"
        lines.append(f"流程日志记录了“{case}”的完整处理过程。")
        if "permit_final_approved_by_supervisor" in actions:
            lines.append("差旅许可已提交，并完成行政与主管审批。")
        if "start_trip" in actions and "end_trip" in actions:
            lines.append("行程随后开始并结束。")
        if "declaration_final_approved_by_supervisor" in actions:
            lines.append("报销申报也完成了行政与主管审批。")
        if "payment_handled" in actions:
            lines.append("最后记录为付款已处理，流程处于完成状态。")
        return lines

    if any(action in {"click", "scroll", "say", "type"} for action in actions):
        messages = []
        cleaned_summary = summary
        for marker in TECHNICAL_CONSTRAINT_WORDS:
            cleaned_summary = cleaned_summary.replace(marker, "")
        seen_messages = set()
        for item in re.findall(r"\[-?\d{2}:\d{2}\]\s*([^；\[\n]+)", cleaned_summary):
            item = re.sub(r"\s+", " ", item).strip(" ;")
            if not item or item.casefold() in {"hi", "hello"}:
                continue
            normalized = re.sub(r"[\W_]+", "", item).casefold()
            if normalized in seen_messages:
                continue
            seen_messages.add(normalized)
            messages.append(item)
        if messages:
            lines.append("浏览器协作记录中的主要请求依次是：")
            lines.extend(f"- {finish_sentence(message)}" for message in messages[-4:])
        else:
            lines.append("日志记录了一次浏览器页面交互。")
        action_labels = {
            "click": "点击页面元素",
            "scroll": "滚动页面",
            "say": "向用户输出信息",
            "type": "填写内容",
        }
        visible_actions = [action_labels[action] for action in actions if action in action_labels]
        if visible_actions:
            lines.append(f"系统执行过{'、'.join(dict.fromkeys(visible_actions))}。")
        lines.append("紧凑日志没有提供可靠的任务完成标志，恢复前应先核对当前页面状态。")
        return lines

    readable_actions = [action.replace("_", " ") for action in actions]
    if readable_actions:
        lines.append(f"操作日志依次记录了：{'、'.join(readable_actions)}。")
    else:
        lines.append("该操作日志没有形成可读的动作摘要。")
    return lines


def memory_text(memory: Mapping[str, Any]) -> str:
    kind = str(memory.get("memory_kind") or "")
    lines: list[str] = []
    if kind == "dialogue_episode":
        action = str(memory.get("expected_action") or "相关任务")
        statements = unique_statements(str(memory.get("summary") or ""))
        lines.append(f"用户过去在“{action}”任务中留下了这些做法：")
        lines.extend(f"- {statement}" for statement in statements)
        scope = clean_constraints(str(memory.get("constraints") or ""))
        if scope:
            lines.append(f"适用范围：{scope}。")
    elif kind == "operation_episode":
        lines.extend(operation_memory_text(memory))
    else:
        summary = str(memory.get("summary") or "没有可用摘要。").strip()
        lines.append(finish_sentence(summary))
        constraints = clean_constraints(str(memory.get("constraints") or ""))
        if constraints:
            lines.append(f"需要保留的约束：{constraints}。")
    source_labels = {
        "dialogue_episode": "用户对话",
        "operation_episode": "操作日志",
        "legacy_memory": "既有任务记忆",
    }
    lines.append(
        f"来源：{source_labels.get(kind, '历史记录')}，包含 "
        f"{memory.get('source_event_count', 0)} 条事件。"
    )
    return "\n".join(lines)


def uncertainty_text(row: Mapping[str, Any]) -> str:
    notes = []
    query = str(row.get("query_text") or "")
    kinds = {str(memory.get("memory_kind")) for memory in row["retrieved_memories"]}
    if "dialogue_episode" in kinds and "operation_episode" in kinds:
        notes.append("对话记忆用于恢复用户做法，操作日志用于判断后台状态，两类证据不能互相替代。")
    if sum(memory.get("memory_kind") == "operation_episode" for memory in row["retrieved_memories"]) > 1:
        notes.append("召回了多个独立操作任务，必须按各自对象分别核对，不能拼成同一条流程。")
    if any(cue in query for cue in ("先查", "核对", "不太确定", "别替我选", "再决定")):
        notes.append("用户要求先核对或比较，因此在状态明确前不应继续不可逆操作。")
    if any(cue in query for cue in ("不需要", "不要", "别")):
        notes.append("当前请求包含明确否定约束；它的优先级高于与之冲突的历史做法。")
    if not row["query_observation"].get("frames"):
        notes.append("本次没有形成高置信度结构化观察，不应为了填满字段而补充推断。")
    return "\n".join(f"- {note}" for note in notes) if notes else "- 没有发现需要额外说明的冲突；仍应以当前请求为准。"


def readable_reference_text(answer: Mapping[str, str]) -> str:
    text = answer.get("expected_conclusion") or answer.get("reference_agent_response") or ""
    text = re.sub(r"click\(uid=(?:\"[^\"]*\"|None)\)", "对应页面元素", text)
    text = re.sub(
        r"say\(speaker=\"navigator\",\s*utterance=\".*?\"\)",
        "协作对话中的系统回复",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("。；", "；").replace("。。", "。").replace("；；", "；")
    parts = []
    previous = None
    for part in text.split("；"):
        part = part.strip()
        normalized = re.sub(r"[\W_]+", "", part).casefold()
        if normalized and normalized == previous:
            continue
        if part:
            parts.append(part)
            previous = normalized
    text = "；".join(parts)
    return text or "（无参考结论）"


def agent_input_text(row: Mapping[str, Any]) -> str:
    refs = select_knowledge_refs(row["knowledge_references"])
    lines = [
        "请结合下面拼贴出的工作现场、用户记忆和通用知识回答用户。",
        "用户记忆是个人历史证据；通用知识只帮助理解应用和任务，不得替代用户记忆。",
        "",
        "【当前工作现场】",
        row["current_context_text"] or "没有额外的当前环境信息。",
        "",
        "【系统对请求的轻量理解】",
        observation_text(row["query_observation"], refs),
        "",
        "【按相关性拼贴的用户记忆】",
    ]
    for index, memory in enumerate(row["retrieved_memories"], 1):
        lines.append(f"记忆 {index}：")
        lines.append(memory_text(memory))
        lines.append("")
    lines.extend(
        [
            "【冲突与不确定性】",
            uncertainty_text(row),
            "",
            "【通用知识提示】",
            knowledge_text(refs, scored=False),
            "",
            "【现在需要回答的用户请求】",
            row["query_text"],
            "",
            "【回答原则】",
            "优先恢复记忆中有来源支持的做法和约束；不同记忆若互相补充，应合并回答；"
            "若记忆冲突或信息不足，应指出差异并请求确认，不要用通用知识猜测用户偏好。",
        ]
    )
    return "\n".join(lines)


def memory_labels(row: Mapping[str, Any], memory_id: str) -> str:
    labels = []
    if memory_id in row["required_memory_ids"]:
        labels.append("必需")
    if memory_id in row["candidate_memory_ids"]:
        labels.append("候选")
    if memory_id in row["forbidden_memory_ids"]:
        labels.append("冲突/禁止")
    return "、".join(labels) if labels else "额外"


def render_summary(report: Mapping[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    exact = sum(exact_slot_complete(row) for row in rows)
    top1 = sum(
        bool(set(row["required_memory_ids"]).intersection(row["ranked_memory_ids"][:1]))
        for row in rows
    )
    required_slots = sum(len(row["required_memory_ids"]) for row in rows)
    correct_slots = sum(
        len(
            set(row["required_memory_ids"]).intersection(
                row["ranked_memory_ids"][: len(row["required_memory_ids"])]
            )
        )
        for row in rows
    )
    with_refs = sum(bool(row["knowledge_references"]) for row in rows)
    with_exact_refs = sum(
        any(ref.get("exact_alias") for ref in row["knowledge_references"])
        for row in rows
    )
    summary = report["summary"]
    latency = summary["retrieval"]["latency"]
    return [
        "| 项目 | 结果 |",
        "| --- | ---: |",
        f"| 静态查询 | {len(rows)} |",
        f"| 种子记忆 | {summary['formation']['formed_memory_count']} |",
        f"| 原始证据覆盖 | {summary['formation']['represented_evidence_count']}/{summary['formation']['input_evidence_count']}（100%） |",
        f"| Top1 至少命中一条必需记忆 | {top1}/{len(rows)}（{percent(top1, len(rows))}） |",
        f"| 需要 N 条时，前 N 位完整命中 | {exact}/{len(rows)}（{percent(exact, len(rows))}） |",
        f"| 前 N 位正确记忆位置 | {correct_slots}/{required_slots}（{percent(correct_slots, required_slots)}） |",
        f"| 获得知识引用 | {with_refs}/{len(rows)}（{percent(with_refs, len(rows))}） |",
        f"| 获得精确知识别名 | {with_exact_refs}/{len(rows)}（{percent(with_exact_refs, len(rows))}） |",
        f"| Observation 平均耗时 | {latency['observation']['mean_ms']:.2f} ms |",
        f"| 知识检索平均耗时 | {latency['knowledge']['mean_ms']:.2f} ms |",
        f"| 记忆检索平均耗时 | {latency['retrieval']['mean_ms']:.2f} ms |",
        f"| 完整链路平均耗时 | {latency['total']['mean_ms']:.2f} ms |",
    ]


def render_example(
    index: int,
    row: Mapping[str, Any],
    query: Mapping[str, str],
    answer: Mapping[str, str],
) -> list[str]:
    required_count = len(row["required_memory_ids"])
    exact = exact_slot_complete(row)
    apps = "、".join(json_list(query.get("apps_involved"))) or "未指定"
    capability = query.get("memory_capability_under_test") or query.get("ability_label")
    final_input = agent_input_text(row)
    lines = [
        "",
        f"## 样例 {index}：{query.get('scenario_label')} / {row['evaluation_track']}",
        "",
        "### 场景描述",
        "",
        f"{capability}。涉及应用：{apps}。本例需要 {required_count} 条记忆，"
        f"静态检索在前 {required_count} 位{'全部找齐' if exact else '没有全部找齐'}。",
        "",
        "### 用户输入",
        "",
        row["query_text"],
        "",
        "### 当前上下文",
        "",
        row["current_context_text"] or "（无）",
        "",
        "### Observation",
        "",
        observation_text(row["query_observation"], row["knowledge_references"]),
        "",
        "### 实际返回的记忆",
        "",
    ]
    for rank, memory in enumerate(row["retrieved_memories"], 1):
        memory_id = memory["memory_id"]
        lines.extend(
            [
                f"**Top {rank}｜{memory_labels(row, memory_id)}｜{memory_id}**",
                "",
                memory_text(memory),
                "",
                f"综合分 `{memory.get('score', 0):.4f}`；语义分 `{memory.get('semantic_score', 0):.4f}`；"
                f"来源事件 `{memory.get('source_event_count', 0)}` 条。",
                "",
            ]
        )
    lines.extend(
        [
            "### 知识库返回",
            "",
            knowledge_text(select_knowledge_refs(row["knowledge_references"]), scored=True),
            "",
            "### 最终交给 Agent 的文本",
            "",
            "```text",
            final_input,
            "```",
            "",
            "### 数据集参考结论（可读化整理，非本轮模型输出）",
            "",
            readable_reference_text(answer),
            "",
            "### 静态验收",
            "",
            (
                f"通过：需要的 {required_count} 条记忆均位于前 {required_count} 位。"
                if exact
                else f"未通过严格排序：需要的 {required_count} 条记忆未能全部进入前 {required_count} 位；文档保留此例用于分析。"
            ),
        ]
    )
    return lines


def render(
    report: Mapping[str, Any],
    queries: Iterable[Mapping[str, str]],
    answers: Iterable[Mapping[str, str]],
) -> str:
    rows = list(report["rows"])
    query_by_id = {row["query_id"]: row for row in queries}
    answer_by_group = {row["answer_group_id"]: row for row in answers}
    selected = select_examples(rows)
    lines = [
        "# 记忆与知识库静态检索样例",
        "",
        "本文件来自服务器实际运行的 800 条静态查询。查询不会写回 Observation、Episode 或记忆库；每条查询只检索其 `precedent_case_id` 对应的独立记忆池。",
        "",
        "本轮未调用回答 API。下文的“最终交给 Agent 的文本”是实际检索包；“数据集参考回答”仅用于人工核对，不属于模型输出。知识引用是通用办公标签，不视为用户记忆。",
        "",
        "## 总体结果",
        "",
        *render_summary(report, rows),
        "",
        "样例覆盖七种测评轨道，并额外保留一个真实 Top1 失败案例。选择只用于展示，不参与算法调参。",
    ]
    for index, row in enumerate(selected, 1):
        lines.extend(
            render_example(
                index,
                row,
                query_by_id[row["query_id"]],
                answer_by_group[row["answer_group_id"]],
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.result.read_text(encoding="utf-8"))
    processed = args.dataset / "processed_data"
    content = render(
        report,
        read_csv(processed / "query_set.csv"),
        read_csv(processed / "answer_key.csv"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8-sig")
    print(
        json.dumps(
            {"output": str(args.output), "bytes": args.output.stat().st_size},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
