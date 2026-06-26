from typing import Literal

# Define available LLM types
LLMType = Literal["basic", "reasoning", "vision"]

# Define agent-LLM mapping
AGENT_LLM_MAP: dict[str, LLMType] = {
    "coordinator": "basic",  # 协调默认使用basic llm
    "planner": "reasoning",  # 计划默认使用basic llm
    "supervisor": "reasoning",  # 决策使用basic llm
    "researcher": "basic",  # 简单搜索任务使用basic llm
    "coder": "basic",  # 编程任务使用basic llm
    "browser": "vision",  # 浏览器操作使用vision llm
    "reporter": "basic",  # 编写报告使用basic llm
    "ppt_generator": "basic",
    "ui_automator": "basic",
    "knowledge_manager": "basic",
    "form_filler": "basic",
    "ocr_tool": "basic",
    "pic_maker": "basic",
}
