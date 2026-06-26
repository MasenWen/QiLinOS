"""
验证器模块的类型定义

包含所有验证器模块共享的类型、枚举和数据类
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum


class ValidationSeverity(Enum):
    """验证问题严重程度"""
    INFO = "info"           # 信息
    WARNING = "warning"     # 警告
    ERROR = "error"         # 错误
    CRITICAL = "critical"   # 严重错误


class ValidationLevel(Enum):
    """验证级别"""
    BASIC = "basic"         # 基础验证
    STANDARD = "standard"   # 标准验证
    STRICT = "strict"       # 严格验证
    COMPREHENSIVE = "comprehensive"  # 全面验证


@dataclass
class ValidationIssue:
    """验证问题"""
    field_name: str                     # 字段名称
    issue_type: str                     # 问题类型
    severity: ValidationSeverity        # 严重程度
    message: str                        # 问题描述
    expected_value: Optional[str] = None    # 期望值
    actual_value: Optional[str] = None      # 实际值
    suggestion: Optional[str] = None        # 修复建议
    rule_name: Optional[str] = None         # 规则名称


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool                      # 是否验证通过
    validation_score: float             # 验证分数 (0-100)
    issues: List[ValidationIssue]       # 验证问题列表
    corrected_data: Dict[str, Any]      # 修正后的数据
    processing_time: float              # 处理时间
    summary: Dict[str, Any]             # 验证摘要
    
    def __post_init__(self):
        """初始化后处理"""
        if self.summary is None:
            self.summary = {}


@dataclass
class ValidationRequest:
    """验证请求"""
    data: Dict[str, Any]                # 待验证数据
    form_info: Dict[str, Any]           # 表单信息
    validation_level: ValidationLevel = ValidationLevel.STANDARD  # 验证级别
    fix_errors: bool = False            # 是否自动修复错误
    custom_rules: Dict[str, Any] = None # 自定义验证规则
    ignore_warnings: bool = True
    
    def __post_init__(self):
        """初始化后处理"""
        if self.custom_rules is None:
            self.custom_rules = {}


# 导出所有类型
__all__ = [
    "ValidationSeverity",
    "ValidationLevel",
    "ValidationIssue",
    "ValidationResult",
    "ValidationRequest"
] 