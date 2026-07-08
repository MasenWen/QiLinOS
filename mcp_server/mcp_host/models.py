from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ConnectRequest(BaseModel):
    path: Optional[str] = Field(default=None, description="Server 脚本路径。不传则使用 registry 的 abs_path。")
    timeout_ms: Optional[int] = Field(default=5000, ge=0, le=120_000, description="等待初始化超时（毫秒）。0=不等待")


class ToolCallRequest(BaseModel):
    args: Dict[str, Any] = Field(default_factory=dict)
    timeout_ms: Optional[int] = Field(default=30_000, ge=0, le=600_000)


class RegisterServerRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Server 名称，例如 api_server")
    filename: Optional[str] = Field(default=None, description="server 目录下文件名，例如 api_server.py")
    abs_path: Optional[str] = Field(default=None, description="Server 脚本绝对/相对路径")
    description: str = Field(default="")
    auto_start: bool = Field(default=False)
    overwrite: bool = Field(default=False, description="为 true 时覆盖已有同名条目")


class UpdateServerRequest(BaseModel):
    filename: Optional[str] = None
    abs_path: Optional[str] = None
    description: Optional[str] = None
    auto_start: Optional[bool] = None


class AgentAskRequest(BaseModel):
    session_id: Optional[int] = Field(default=None, description="会话ID（可选；用于写入 call_logs）")
    query: str
    context_messages: Optional[str] = Field(default=None, description="最近对话上下文（多轮对话的前几轮摘要，用于保持上下文连贯）")
    allow_servers: Optional[List[str]] = None
    dry_run: bool = False
    timeout_ms: int = Field(default=60_000, ge=1_000, le=600_000)