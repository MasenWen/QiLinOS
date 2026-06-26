"""
策略填写器

基于不同的填写策略来填写表单，提供灵活的填写方式。
"""

import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

from ..config.settings import ConfigManager
from ..utils.logger import get_logger, performance_monitor, error_handler
from .types import FillResult, FillStrategy, StrategyRule
from .field_filler import FieldFiller
from src.utils.db_manager import node_state

class StrategyFiller:
    """
    策略填写器
    
    主要功能:
    - 基于预定义策略填写表单
    - 支持自定义策略规则
    - 智能策略选择
    - 策略效果评估
    """
    
    def __init__(self, settings: ConfigManager):
        self.settings = settings
        self.logger = get_logger(__name__)
        self.field_filler = FieldFiller(settings)
        
        # 初始化策略规则
        self.strategies = self._initialize_strategies()
        
        # 策略统计
        self.strategy_stats = {}
        
        self.logger.info(f"{node_state}-=-填表员===策略填表初始化成功")
    
    def _initialize_strategies(self) -> Dict[str, List[StrategyRule]]:
        """初始化策略规则"""
        strategies = {
            FillStrategy.CONSERVATIVE.value: [
                StrategyRule(
                    name="高置信度姓名填写",
                    description="只填写高置信度的姓名字段",
                    field_patterns=["姓名", "name", "用户名"],
                    confidence_threshold=0.9,
                    priority=1
                ),
                StrategyRule(
                    name="高置信度邮箱填写",
                    description="只填写高置信度的邮箱字段",
                    field_patterns=["邮箱", "email", "电子邮件"],
                    confidence_threshold=0.9,
                    priority=1
                ),
                StrategyRule(
                    name="高置信度电话填写",
                    description="只填写高置信度的电话字段",
                    field_patterns=["电话", "phone", "手机"],
                    confidence_threshold=0.85,
                    priority=1
                )
            ],
            
            FillStrategy.BALANCED.value: [
                StrategyRule(
                    name="平衡姓名填写",
                    description="填写中等置信度以上的姓名字段（用户名）",
                    field_patterns=["姓名", "name", "用户名", "真实姓名"],
                    confidence_threshold=0.7,
                    priority=1
                ),
                StrategyRule(
                    name="平衡联系信息填写",
                    description="填写中等置信度以上的联系信息",
                    field_patterns=["邮箱", "email", "电话", "phone", "地址"],
                    confidence_threshold=0.6,
                    priority=2
                ),
                StrategyRule(
                    name="平衡身份信息填写",
                    description="填写中等置信度以上的身份信息",
                    field_patterns=["身份证", "年龄", "性别", "生日"],
                    confidence_threshold=0.65,
                    priority=3
                )
            ],
            
            FillStrategy.AGGRESSIVE.value: [
                StrategyRule(
                    name="激进基础信息填写",
                    description="填写所有基础信息字段",
                    field_patterns=["姓名", "name", "邮箱", "email", "电话", "phone"],
                    confidence_threshold=0.3,
                    priority=1
                ),
                StrategyRule(
                    name="激进详细信息填写",
                    description="填写所有详细信息字段",
                    field_patterns=["地址", "年龄", "性别", "职业", "教育"],
                    confidence_threshold=0.4,
                    priority=2
                ),
                StrategyRule(
                    name="激进扩展信息填写",
                    description="填写所有可能的字段",
                    field_patterns=["*"],  # 通配符表示所有字段
                    confidence_threshold=0.2,
                    priority=3
                )
            ]
        }
        
        return strategies
    
    @performance_monitor
    @error_handler
    async def fill_with_strategy(self, strategy: FillStrategy, 
                               form_info: Dict[str, Any],
                               user_info: Dict[str, Any],
                               matching_result: Dict[str, Any]) -> FillResult:
        """
        使用策略填写表单
        
        Args:
            strategy: 填写策略
            form_info: 表单信息
            user_info: 用户信息
            matching_result: 字段匹配结果
            
        Returns:
            填写结果
        """
        try:
            self.logger.info(f"{node_state}-=-填表员===开始策略填表: {strategy.value}")
            
            # 获取策略规则
            rules = self.strategies.get(strategy.value, [])
            if not rules:
                raise ValueError(f"No rules found for strategy: {strategy.value}")
            
            # 按优先级排序规则
            sorted_rules = sorted(rules, key=lambda r: r.priority)
            
            # 执行策略填写
            filled_fields = {}
            skipped_fields = []
            failed_fields = []
            confidence_scores = {}
            warnings = []
            
            matches = matching_result.get('matches', [])
            
            for match in matches:
                field_name = match.get('field_name', '')
                confidence = match.get('confidence', 0.0)
                
                # 寻找适用的规则
                applicable_rule = self._find_applicable_rule(field_name, sorted_rules)
                
                if applicable_rule:
                    # 检查置信度阈值
                    if confidence >= applicable_rule.confidence_threshold:
                        # 检查条件
                        if self._check_rule_conditions(applicable_rule, match, form_info):
                            try:
                                # 执行填写
                                fill_value = await self._execute_rule_actions(
                                    applicable_rule, match, user_info
                                )
                                
                                if fill_value is not None:
                                    filled_fields[field_name] = fill_value
                                    confidence_scores[field_name] = confidence
                                    
                                    self.logger.debug(
                                        f"Filled field {field_name} using rule {applicable_rule.name}"
                                    )
                                else:
                                    skipped_fields.append(field_name)
                                    warnings.append(f"Rule {applicable_rule.name} returned None for {field_name}")
                                    
                            except Exception as e:
                                failed_fields.append(field_name)
                                warnings.append(f"Rule {applicable_rule.name} failed for {field_name}: {str(e)}")
                                self.logger.warning(f"Rule execution failed: {str(e)}")
                        else:
                            skipped_fields.append(field_name)
                            warnings.append(f"Rule conditions not met for {field_name}")
                    else:
                        skipped_fields.append(field_name)
                        warnings.append(
                            f"Confidence {confidence} below threshold {applicable_rule.confidence_threshold} for {field_name}"
                        )
                else:
                    skipped_fields.append(field_name)
                    warnings.append(f"No applicable rule found for {field_name}")
            
            # 更新策略统计
            self._update_strategy_stats(strategy, len(filled_fields), len(skipped_fields), len(failed_fields))
            
            result = FillResult(
                success=len(failed_fields) == 0,
                filled_fields=filled_fields,
                skipped_fields=skipped_fields,
                failed_fields=failed_fields,
                confidence_scores=confidence_scores,
                validation_results={},
                processing_time=0.0,
                errors=[],
                warnings=warnings
            )
            
            self.logger.info(f"{node_state}-=-填表员===策略填表已完成: {len(filled_fields)} filled, {len(skipped_fields)} skipped")
            return result
            
        except Exception as e:
            self.logger.error(f"Strategy fill failed: {str(e)}")
            return FillResult(
                success=False,
                filled_fields={},
                skipped_fields=[],
                failed_fields=[],
                confidence_scores={},
                validation_results={},
                processing_time=0.0,
                errors=[str(e)],
                warnings=[]
            )
    
    def _find_applicable_rule(self, field_name: str, rules: List[StrategyRule]) -> Optional[StrategyRule]:
        """寻找适用的规则"""
        field_name_lower = field_name.lower()
        
        for rule in rules:
            for pattern in rule.field_patterns:
                if pattern == "*":  # 通配符匹配所有字段
                    return rule
                elif pattern.lower() in field_name_lower:
                    return rule
        
        return None
    
    def _check_rule_conditions(self, rule: StrategyRule, match: Dict[str, Any], 
                             form_info: Dict[str, Any]) -> bool:
        """检查规则条件"""
        if not rule.conditions:
            return True
        
        try:
            # 检查字段类型条件
            if 'field_type' in rule.conditions:
                required_type = rule.conditions['field_type']
                actual_type = match.get('field_type')
                if actual_type != required_type:
                    return False
            
            # 检查表单类型条件
            if 'form_type' in rule.conditions:
                required_form_type = rule.conditions['form_type']
                actual_form_type = form_info.get('form_type')
                if actual_form_type != required_form_type:
                    return False
            
            # 检查字段是否必填
            if 'required_only' in rule.conditions:
                if rule.conditions['required_only'] and not match.get('required', False):
                    return False
            
            # 检查自定义条件
            if 'custom' in rule.conditions:
                custom_condition = rule.conditions['custom']
                if not self._evaluate_custom_condition(custom_condition, match, form_info):
                    return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Error checking rule conditions: {str(e)}")
            return False
    
    def _evaluate_custom_condition(self, condition: Dict[str, Any], 
                                 match: Dict[str, Any], 
                                 form_info: Dict[str, Any]) -> bool:
        """评估自定义条件"""
        # 这里可以实现复杂的条件逻辑
        # 暂时返回True
        return True
    
    async def _execute_rule_actions(self, rule: StrategyRule, match: Dict[str, Any], 
                                  user_info: Dict[str, Any]) -> Any:
        """执行规则动作"""
        try:
            # 如果有自定义动作，执行自定义动作
            if rule.actions:
                return await self._execute_custom_actions(rule.actions, match, user_info)
            
            # 默认动作：使用字段填写器填写
            field_name = match.get('field_name')
            user_field = match.get('user_field')
            
            if field_name and user_field:
                return await self.field_filler.fill_field(
                    field_name, user_field, user_info, match
                )
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to execute rule actions: {str(e)}")
            raise
    
    async def _execute_custom_actions(self, actions: Dict[str, Any], 
                                    match: Dict[str, Any],
                                    user_info: Dict[str, Any]) -> Any:
        """执行自定义动作"""
        # 这里可以实现复杂的自定义动作逻辑
        # 例如：数据转换、格式化、计算等
        
        if 'transform' in actions:
            # 数据转换
            transform_func = actions['transform']
            return self._apply_transform(transform_func, match, user_info)
        
        if 'default_value' in actions:
            # 返回默认值
            return actions['default_value']
        
        if 'template' in actions:
            # 使用模板生成值
            template = actions['template']
            return self._apply_template(template, match, user_info)
        
        # 默认行为
        field_name = match.get('field_name')
        user_field = match.get('user_field')
        if field_name and user_field:
            return await self.field_filler.fill_field(
                field_name, user_field, user_info, match
            )
        
        return None
    
    def _apply_transform(self, transform_func: str, match: Dict[str, Any], 
                        user_info: Dict[str, Any]) -> Any:
        """应用数据转换"""
        # 实现常见的数据转换功能
        transforms = {
            'upper': lambda x: str(x).upper(),
            'lower': lambda x: str(x).lower(),
            'title': lambda x: str(x).title(),
            'strip': lambda x: str(x).strip(),
            'format_phone': lambda x: self._format_phone_number(x),
            'format_date': lambda x: self._format_date_string(x)
        }
        
        user_field = match.get('user_field')
        if user_field:
            value = user_info.get(user_field)
            if value and transform_func in transforms:
                return transforms[transform_func](value)
        
        return None
    
    def _apply_template(self, template: str, match: Dict[str, Any], 
                       user_info: Dict[str, Any]) -> str:
        """应用模板生成值"""
        # 简单的模板替换功能
        result = template
        
        # 替换用户信息变量
        for key, value in user_info.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        
        return result
    
    def _format_phone_number(self, phone: str) -> str:
        """格式化电话号码"""
        # 移除非数字字符
        digits = ''.join(filter(str.isdigit, str(phone)))
        
        # 格式化为 xxx-xxxx-xxxx
        if len(digits) == 11:
            return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
        elif len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        
        return phone
    
    def _format_date_string(self, date_str: str) -> str:
        """格式化日期字符串"""
        # 简单的日期格式化
        import re
        
        # 匹配 YYYY-MM-DD 格式
        if re.match(r'\d{4}-\d{2}-\d{2}', str(date_str)):
            return str(date_str)
        
        # 其他格式转换可以在这里添加
        return str(date_str)
    
    def _update_strategy_stats(self, strategy: FillStrategy, filled: int, 
                             skipped: int, failed: int):
        """更新策略统计"""
        strategy_name = strategy.value
        
        if strategy_name not in self.strategy_stats:
            self.strategy_stats[strategy_name] = {
                'total_uses': 0,
                'total_filled': 0,
                'total_skipped': 0,
                'total_failed': 0,
                'success_rate': 0.0
            }
        
        stats = self.strategy_stats[strategy_name]
        stats['total_uses'] += 1
        stats['total_filled'] += filled
        stats['total_skipped'] += skipped
        stats['total_failed'] += failed
        
        # 计算成功率
        total_attempts = stats['total_filled'] + stats['total_failed']
        if total_attempts > 0:
            stats['success_rate'] = stats['total_filled'] / total_attempts
    
    def add_custom_strategy(self, strategy_name: str, rules: List[StrategyRule]):
        """添加自定义策略"""
        self.strategies[strategy_name] = rules
        self.logger.info(f"{node_state}-=-填表员===添加自定义策略: {strategy_name} with {len(rules)} rules")
    
    def get_strategy_stats(self) -> Dict[str, Any]:
        """获取策略统计信息"""
        return self.strategy_stats.copy()
    
    def get_available_strategies(self) -> List[str]:
        """获取可用策略列表"""
        return list(self.strategies.keys()) 