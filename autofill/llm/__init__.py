"""
大语言模型模块

提供与大语言模型交互的功能，包括：
- 模型客户端管理
- 请求/响应处理
- 提示词管理
- 智能分析功能
"""

from .base import BaseLLMClient, LLMResponse, LLMRequest
from .deepseek_client import DeepSeekClient
from .prompt_manager import PromptManager, PromptTemplate
from .analyzers import (
    FormLLMAnalyzer,
    InfoExtractor, 
    FieldMatcher,
    ContentAnalyzer
)

# 导出主要类和函数
__all__ = [
    # 基础类
    "BaseLLMClient",
    "LLMResponse", 
    "LLMRequest",
    
    # 客户端实现
    "DeepSeekClient",
    
    # 提示词管理
    "PromptManager",
    "PromptTemplate",
    
    # 分析器
    "FormLLMAnalyzer",
    "InfoExtractor",
    "FieldMatcher", 
    "ContentAnalyzer"
] 