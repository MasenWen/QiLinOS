from typing import Literal, Dict, Optional
from typing_extensions import TypedDict
from langgraph.graph import MessagesState
from langchain_core.messages import (
    AnyMessage,
)
from pydantic import BaseModel, Field
from src.config import TEAM_MEMBERS
import threading
import sqlite3
from src.utils.interupt import intr
# Define routing options
# OPTIONS = TEAM_MEMBERS + ["FINISH"]


# "researcher", "coder", "opretor", "网页浏览员", "汇报员", "PPT专员", "图片制作员", "MCP服务", "结束"
class Router(TypedDict):
    """根据计划协调下一位团队成员执行任务. 如果计划的任务已完成, 则结束。"""
    next: Literal["研究员", "程序员", "操作员", "网页浏览员", "汇报员", "PPT专员","UI专员", "图片制作员", "MCP服务", "结束"] = Field(
        description="根据计划和任务执行情况，确定下一步需要执行的团队成员或结束"
    )
    reasoning: str = Field(
        default="无",
        description="决策的理由或说明"
    )

class State(MessagesState):
    """State for the agent system, extends MessagesState with next field."""

    # Constants
    TEAM_MEMBERS: list[str]

    # Runtime Variables
    session_id: int
    next: str
    cur: str
    last: str
    full_plan: str
    deep_thinking_mode: bool = True
    search_before_planning: bool
    waiting_for_review: bool = False  # 添加等待审查状态
    extra_info: str 
    # user_feedback: str = ""  # 添加用户反馈字段
    # history: list[AnyMessage] = []  # To allow other dynamic fields
