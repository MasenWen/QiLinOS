"""
自动填写模块

该模块负责根据分析的表单结构和收集的用户信息，智能地填写表单内容。
提供多种填写策略和验证机制，确保填写的准确性和完整性。

主要组件:
- AutoFiller: 主要的自动填写器，协调整个填写过程
- FieldFiller: 单个字段的填写器
- StrategyFiller: 基于策略的填写器
- TemplateFiller: 基于模板的填写器

主要功能:
- 智能字段匹配
- 自动内容填写
- 填写结果验证
- 填写策略管理
"""

from .auto_filler import AutoFiller
from .field_filler import FieldFiller
from .strategy_filler import StrategyFiller
from .template_filler import TemplateFiller

__all__ = [
    'AutoFiller',
    'FieldFiller', 
    'StrategyFiller',
    'TemplateFiller'
] 