"""
LLM模块基类和数据结构

定义了与大语言模型交互的标准接口和数据结构。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from enum import Enum

from ..core import BaseProcessor, ProcessingStatus
from ..utils.logger import get_logger
from src.utils.db_manager import node_state

class LLMProvider(Enum):
    """LLM提供商枚举"""
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    CLAUDE = "claude"
    LOCAL = "local"
    CUSTOM = "custom"


class MessageRole(Enum):
    """消息角色枚举"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION = "function"


@dataclass
class LLMMessage:
    """LLM消息数据结构"""
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass 
class LLMRequest:
    """LLM请求数据结构"""
    messages: List[LLMMessage]
    model: Optional[str] = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    stop: Optional[List[str]] = None
    stream: bool = False
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "messages": [msg.to_dict() for msg in self.messages],
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            # "top_p": self.top_p,
            # "frequency_penalty": self.frequency_penalty,
            # "presence_penalty": self.presence_penalty,
            # "stop": self.stop,
            "stream": self.stream,
            # "user_id": self.user_id,
            # "request_id": self.request_id
        }


@dataclass
class LLMUsage:
    """LLM使用统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens
        }


@dataclass
class LLMResponse:
    """LLM响应数据结构"""
    content: str
    status: ProcessingStatus
    request_id: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[LLMUsage] = None
    response_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def success(self) -> bool:
        """是否成功"""
        return self.status == ProcessingStatus.SUCCESS
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "content": self.content,
            "status": self.status.value,
            "request_id": self.request_id,
            "model": self.model,
            "usage": self.usage.to_dict() if self.usage else None,
            "response_time": self.response_time,
            "timestamp": self.timestamp.isoformat(),
            "error_message": self.error_message,
            "metadata": self.metadata
        }


class BaseLLMClient(BaseProcessor):
    """LLM客户端基类"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化LLM客户端
        
        Args:
            config: 客户端配置
        """
        super().__init__(config)
        self.logger = get_logger(self.__class__.__name__)
        self.provider = self._get_provider()
        
        # 统计信息
        self.request_count = 0
        self.total_tokens_used = 0
        self.total_response_time = 0.0
    
    @abstractmethod
    def _get_provider(self) -> LLMProvider:
        """获取LLM提供商"""
        pass
    
    @abstractmethod
    def _send_request(self, request: LLMRequest) -> LLMResponse:
        """发送请求到LLM服务"""
        pass
    
    def process(self, input_data: Any) -> LLMResponse:
        """处理输入数据（实现基类方法）"""
        if isinstance(input_data, str):
            # 简单文本输入
            message = LLMMessage(role=MessageRole.USER, content=input_data)
            request = LLMRequest(messages=[message])
        elif isinstance(input_data, LLMRequest):
            request = input_data
        else:
            raise ValueError(f"不支持的输入类型: {type(input_data)}")
        
        return self.chat(request)
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据有效性"""
        if isinstance(input_data, str):
            return len(input_data.strip()) > 0
        elif isinstance(input_data, LLMRequest):
            return len(input_data.messages) > 0 and all(
                msg.content.strip() for msg in input_data.messages
            )
        return False
    
    def chat(self, request: LLMRequest) -> LLMResponse:
        """
        发送聊天请求
        
        Args:
            request: LLM请求对象
            
        Returns:
            LLMResponse: LLM响应对象
        """
        start_time = datetime.now()
        
        try:
            # 验证请求
            if not self.validate_input(request):
                return LLMResponse(
                    content="",
                    status=ProcessingStatus.FAILED,
                    error_message="无效的请求数据",
                    request_id=request.request_id
                )
            
            self.status = ProcessingStatus.PROCESSING
            
            # 记录请求
            self.logger.info(
                "发送LLM请求",
                extra={
                    "provider": self.provider.value,
                    "message_count": len(request.messages),
                    "model": request.model,
                    "request_id": request.request_id
                }
            )
            print(request.to_dict())
            # 发送请求
            response = self._send_request(request)
            
            # 计算响应时间
            response.response_time = (datetime.now() - start_time).total_seconds()
            
            # 更新统计信息
            self.request_count += 1
            self.total_response_time += response.response_time
            if response.usage:
                self.total_tokens_used += response.usage.total_tokens
            
            # 记录响应
            self.logger.info(
                "收到LLM响应",
                extra={
                    "provider": self.provider.value,
                    "success": response.success,
                    "response_time": response.response_time,
                    "content_length": len(response.content),
                    "request_id": request.request_id
                }
            )
            
            self.status = ProcessingStatus.SUCCESS if response.success else ProcessingStatus.FAILED
            return response
            
        except Exception as e:
            self.status = ProcessingStatus.FAILED
            response_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.error(
                f"LLM请求失败: {e}",
                extra={
                    "provider": self.provider.value,
                    "response_time": response_time,
                    "request_id": request.request_id
                },
                exc_info=True
            )
            
            return LLMResponse(
                content="",
                status=ProcessingStatus.FAILED,
                error_message=str(e),
                response_time=response_time,
                request_id=request.request_id
            )
    
    def simple_chat(self, message: str, system_prompt: Optional[str] = None) -> str:
        """
        简单聊天接口
        
        Args:
            message: 用户消息
            system_prompt: 系统提示词（可选）
            
        Returns:
            str: 模型响应内容
        """
        messages = []
        
        if system_prompt:
            messages.append(LLMMessage(
                role=MessageRole.SYSTEM,
                content=system_prompt
            ))
        
        messages.append(LLMMessage(
            role=MessageRole.USER,
            content=message
        ))
        
        request = LLMRequest(messages=messages)
        response = self.chat(request)
        
        return response.content if response.success else ""
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取客户端统计信息"""
        avg_response_time = (
            self.total_response_time / self.request_count 
            if self.request_count > 0 else 0
        )
        
        return {
            "provider": self.provider.value,
            "request_count": self.request_count,
            "total_tokens_used": self.total_tokens_used,
            "average_response_time": avg_response_time,
            "total_response_time": self.total_response_time
        }
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            # 发送简单的测试请求
            test_message = "Hello"
            response = self.simple_chat(test_message)
            
            return {
                "status": "healthy" if response else "unhealthy",
                "provider": self.provider.value,
                "test_successful": bool(response),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": self.provider.value,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


# 导出类和枚举
__all__ = [
    "LLMProvider",
    "MessageRole", 
    "LLMMessage",
    "LLMRequest",
    "LLMUsage",
    "LLMResponse",
    "BaseLLMClient"
] 