from __future__ import annotations

import re
from typing import Any

from .models import RetrievalContext


CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("conflict_update", ("改为", "更新后的偏好", "当前偏好", "不再", "后续行为", "现在更常")),
    ("scenario_preference", ("场景偏好", "特定场景", "财务汇总", "历史偏好", "以前", "过去", "当时")),
    ("temporary_preference", ("临时偏好", "临时要求", "本次会话", "会话级", "一次性要求", "仅本次")),
    ("task_state", ("任务状态", "已完成步骤", "最近完成", "做到哪一步", "已经完成", "移动结果")),
    ("current_context", ("最近上下文", "最近工作对象", "当前上下文", "最后查看", "最后进入", "最近打开", "正确参考对象")),
    ("routine_pattern", ("例行", "固定流程", "启动流程", "第一步", "日常习惯", "通常先")),
    (
        "frequency_preference",
        ("多次", "反复", "经常", "常用", "通常", "近期偏好", "交付习惯", "频率偏好", "中期偏好", "中期命令", "中期收集", "中期处理"),
    ),
)

SCENE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("spreadsheet_processing", ("表格", "销售分析", "月报", "calc", "spreadsheet")),
    ("document_editing", ("文档", "周报", "writer", "document")),
    ("file_management", ("文件管理", "文件夹", "目录", "归档", "file manager")),
    ("meeting_notes", ("会议纪要", "组会纪要", "meeting")),
    ("code_development", ("代码", "开发", "调试", "仓库", "vscode", "terminal")),
    ("browser_research", ("浏览器", "资料调研", "参考页面", "技术资料", "browser")),
)

APP_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("libreoffice_calc", ("libreoffice calc", " calc ", "表格")),
    ("libreoffice_writer", ("libreoffice writer", " writer ", "文档")),
    ("file_manager", ("文件管理器", "file manager", "文件夹")),
    ("meeting_notes", ("会议纪要", "组会纪要")),
    ("vscode", ("vscode", "编辑器", "调试")),
    ("terminal", ("终端", "terminal", "仓库")),
    ("browser", ("浏览器", "browser", "参考页面")),
)


def infer_label(text: str, patterns: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    lowered = f" {text.lower()} "
    for label, phrases in patterns:
        if any(phrase in lowered for phrase in phrases):
            return label
    return ""


def infer_category(context: RetrievalContext) -> str:
    if context.memory_need:
        direct = infer_label(context.memory_need, CATEGORY_PATTERNS)
        if direct:
            return direct
    text = " ".join(
        part for part in (
            context.memory_need,
            context.current_step,
            context.goal,
            context.task,
            context.query_text,
        ) if part
    )
    return infer_label(text, CATEGORY_PATTERNS)


def infer_memory_type(category: str) -> str:
    if category in {"current_context", "temporary_preference", "task_state"}:
        return "short_term"
    if category:
        return "mid_term"
    return ""


def infer_scene(context: RetrievalContext) -> str:
    if context.scene:
        return context.scene.lower()
    return infer_label(" ".join((context.task, context.goal, context.current_step, context.query_text)), SCENE_PATTERNS)


def infer_apps(context: RetrievalContext) -> tuple[str, ...]:
    if context.apps:
        return tuple(app.lower() for app in context.apps)
    app = infer_label(" ".join((context.task, context.goal, context.current_step, context.query_text)), APP_PATTERNS)
    return (app,) if app else ()


def tokenize(text: Any) -> set[str]:
    value = str(text or "").lower()
    latin = re.findall(r"[a-z0-9_./-]{2,}", value)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", value)
    chinese = []
    for run in chinese_runs:
        if len(run) <= 3:
            chinese.append(run)
        else:
            chinese.extend(run[index:index + 2] for index in range(len(run) - 1))
    return set(latin + chinese)
