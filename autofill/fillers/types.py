"""
填写器模块的类型定义

包含所有填写器模块共享的类型、枚举和数据类
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum


class FillMode(Enum):
    """填写模式"""
    AUTOMATIC = "automatic"      # 全自动填写
    INTERACTIVE = "interactive"  # 交互式填写
    TEMPLATE = "template"        # 模板填写
    STRATEGY = "strategy"        # 策略填写


class FillStrategy(Enum):
    """填写策略"""
    CONSERVATIVE = "conservative"  # 保守策略，只填写高置信度字段
    BALANCED = "balanced"         # 平衡策略，填写中等以上置信度字段
    AGGRESSIVE = "aggressive"     # 激进策略，尽可能多地填写字段


@dataclass
class FillRequest:
    """填写请求"""
    form_info: Dict[str, Any]                    # 表单信息
    user_info: Dict[str, Any]                    # 用户信息
    mode: FillMode = FillMode.AUTOMATIC          # 填写模式
    strategy: FillStrategy = FillStrategy.BALANCED  # 填写策略
    template_id: Optional[str] = None            # 模板ID（用于模板模式）
    custom_rules: Dict[str, Any] = None          # 自定义规则
    validate_before_fill: bool = True            # 填写前验证
    save_backup: bool = True                     # 保存备份


@dataclass
class FillResult:
    """填写结果"""
    success: bool                                # 是否成功
    filled_fields: Dict[str, Any]               # 已填写的字段
    skipped_fields: List[str]                   # 跳过的字段
    failed_fields: List[str]                    # 失败的字段
    confidence_scores: Dict[str, float]         # 置信度分数
    validation_results: Dict[str, Any]          # 验证结果
    processing_time: float                      # 处理时间（秒）
    errors: List[str]                           # 错误信息
    warnings: List[str]                         # 警告信息


@dataclass
class StrategyRule:
    """策略规则"""
    name: str                                   # 规则名称
    description: str                            # 规则描述
    field_patterns: List[str]                   # 字段模式匹配
    confidence_threshold: float                 # 置信度阈值
    priority: int                               # 优先级（数字越小优先级越高）
    conditions: Dict[str, Any] = None           # 触发条件
    actions: Dict[str, Any] = None              # 执行动作


# 导出所有类型
__all__ = [
    "FillMode",
    "FillStrategy", 
    "FillRequest",
    "FillResult",
    "StrategyRule"
] 