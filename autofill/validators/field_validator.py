"""
字段验证器

负责单个字段的格式、类型、范围等基础验证。
"""

import re
from typing import Dict, List, Any, Optional
from datetime import datetime, date

from ..config.settings import ConfigManager
from ..utils.logger import get_logger
from .types import ValidationIssue, ValidationSeverity


class FieldValidator:
    """
    字段验证器
    
    主要功能:
    - 数据类型验证
    - 格式规范验证
    - 长度范围验证
    - 正则表达式验证
    """
    
    def __init__(self, settings: ConfigManager):
        self.settings = settings
        self.logger = get_logger(__name__)
        
        # 预定义验证规则
        self.validation_patterns = {
            'email': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
            'phone': r'^(\+86)?1[3-9]\d{9}$',
            'mobile': r'^1[3-9]\d{9}$',
            'id_card': r'^[1-9]\d{5}(18|19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$',
            'postal_code': r'^\d{6}$',
            'url': r'^https?://(?:[-\w.])+(?:\:[0-9]+)?(?:/(?:[\w/_.])*(?:\?(?:[\w&=%.])*)?(?:\#(?:[\w.])*)?)?$',
            'ip': r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        }
        
        # 字段类型映射
        self.field_type_mapping = {
            '姓名': 'name',
            '电话': 'phone',
            '手机': 'mobile',
            '邮箱': 'email',
            '身份证': 'id_card',
            '年龄': 'number',
            '地址': 'text',
            '网址': 'url',
            'IP': 'ip'
        }
        
    async def validate_field(self, field_name: str, value: Any, 
                           field_config: Dict[str, Any]) -> List[ValidationIssue]:
        """
        验证单个字段
        
        Args:
            field_name: 字段名称
            value: 字段值
            field_config: 字段配置
            
        Returns:
            验证问题列表
        """
        issues = []
        
        # 空值检查
        if value is None or (isinstance(value, str) and not value.strip()):
            if field_config.get('required', False):
                issues.append(ValidationIssue(
                    field_name=field_name,
                    issue_type='required_field_empty',
                    severity=ValidationSeverity.ERROR,
                    message=f'必填字段"{field_name}"为空',
                    suggestions=[f'请填写{field_name}']
                ))
            return issues
        
        # 数据类型验证
        type_issues = self._validate_data_type(field_name, value, field_config)
        issues.extend(type_issues)
        
        # 格式验证
        format_issues = self._validate_format(field_name, value, field_config)
        issues.extend(format_issues)
        
        # 长度验证
        length_issues = self._validate_length(field_name, value, field_config)
        issues.extend(length_issues)
        
        # 范围验证
        range_issues = self._validate_range(field_name, value, field_config)
        issues.extend(range_issues)
        
        # 自定义验证
        custom_issues = self._validate_custom_rules(field_name, value, field_config)
        issues.extend(custom_issues)
        
        return issues
    
    def _validate_data_type(self, field_name: str, value: Any, 
                          field_config: Dict[str, Any]) -> List[ValidationIssue]:
        """验证数据类型"""
        issues = []
        expected_type = field_config.get('type', 'string')
        
        try:
            if expected_type == 'number':
                try:
                    float(value)
                except (ValueError, TypeError):
                    issues.append(ValidationIssue(
                        field_name=field_name,
                        issue_type='invalid_type',
                        severity=ValidationSeverity.ERROR,
                        message=f'"{field_name}"应该是数字，但是是: {type(value).__name__}',
                        suggestions=['请输入有效的数字']
                    ))
            
            elif expected_type == 'integer':
                try:
                    int(value)
                except (ValueError, TypeError):
                    issues.append(ValidationIssue(
                        field_name=field_name,
                        issue_type='invalid_type',
                        severity=ValidationSeverity.ERROR,
                        message=f'"{field_name}"应该是整数，但是是: {type(value).__name__}',
                        suggestions=['请输入有效的整数']
                    ))
            
            elif expected_type == 'boolean':
                if not isinstance(value, bool) and str(value).lower() not in ['true', 'false', '1', '0', 'yes', 'no', '是', '否']:
                    issues.append(ValidationIssue(
                        field_name=field_name,
                        issue_type='invalid_type',
                        severity=ValidationSeverity.ERROR,
                        message=f'"{field_name}"应该是布尔值（是/否），但是是: {value}',
                        suggestions=['请输入是或否']
                    ))
            
            elif expected_type == 'date':
                if not isinstance(value, (date, datetime)):
                    # 尝试解析日期字符串
                    date_str = str(value)
                    valid_date = False
                    for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y']:
                        try:
                            datetime.strptime(date_str, fmt)
                            valid_date = True
                            break
                        except ValueError:
                            continue
                    
                    if not valid_date:
                        issues.append(ValidationIssue(
                            field_name=field_name,
                            issue_type='invalid_type',
                            severity=ValidationSeverity.ERROR,
                            message=f'"{field_name}"不是有效的日期格式: {value}',
                            suggestions=['请使用YYYY-MM-DD格式的日期']
                        ))
        
        except Exception as e:
            issues.append(ValidationIssue(
                field_name=field_name,
                issue_type='type_validation_error',
                severity=ValidationSeverity.WARNING,
                message=f'类型验证出错: {str(e)}'
            ))
        
        return issues
    
    def _validate_format(self, field_name: str, value: Any, 
                        field_config: Dict[str, Any]) -> List[ValidationIssue]:
        """验证格式"""
        issues = []
        value_str = str(value).strip()
        
        # 根据字段名称推断验证类型
        field_type = self._detect_field_type(field_name, field_config)
        
        if field_type and field_type in self.validation_patterns:
            pattern = self.validation_patterns[field_type]
            if not re.match(pattern, value_str):
                issues.append(ValidationIssue(
                    field_name=field_name,
                    issue_type='invalid_format',
                    severity=ValidationSeverity.ERROR,
                    message=f'"{field_name}"格式不正确: {value}',
                    suggestions=self._get_format_suggestions(field_type)
                ))
        
        # 自定义正则表达式验证
        custom_pattern = field_config.get('pattern')
        if custom_pattern:
            try:
                if not re.match(custom_pattern, value_str):
                    issues.append(ValidationIssue(
                        field_name=field_name,
                        issue_type='custom_pattern_mismatch',
                        severity=ValidationSeverity.ERROR,
                        message=f'"{field_name}"不符合指定格式',
                        suggestions=['请检查输入格式是否正确']
                    ))
            except re.error:
                issues.append(ValidationIssue(
                    field_name=field_name,
                    issue_type='invalid_pattern',
                    severity=ValidationSeverity.WARNING,
                    message=f'自定义验证模式无效: {custom_pattern}'
                ))
        
        return issues
    
    def _validate_length(self, field_name: str, value: Any, 
                        field_config: Dict[str, Any]) -> List[ValidationIssue]:
        """验证长度"""
        issues = []
        value_str = str(value)
        length = len(value_str)
        
        min_length = field_config.get('min_length')
        max_length = field_config.get('max_length')
        
        if min_length is not None and length < min_length:
            issues.append(ValidationIssue(
                field_name=field_name,
                issue_type='too_short',
                severity=ValidationSeverity.ERROR,
                message=f'"{field_name}"长度不足，当前{length}字符，最少需要{min_length}字符',
                suggestions=[f'请输入至少{min_length}个字符']
            ))
        
        if max_length is not None and length > max_length:
            issues.append(ValidationIssue(
                field_name=field_name,
                issue_type='too_long',
                severity=ValidationSeverity.ERROR,
                message=f'"{field_name}"长度超限，当前{length}字符，最多允许{max_length}字符',
                suggestions=[f'请将内容缩短到{max_length}个字符以内']
            ))
        
        return issues
    
    def _validate_range(self, field_name: str, value: Any, 
                       field_config: Dict[str, Any]) -> List[ValidationIssue]:
        """验证数值范围"""
        issues = []
        
        # 只对数值类型进行范围验证
        try:
            numeric_value = float(value)
        except (ValueError, TypeError):
            return issues
        
        min_value = field_config.get('min_value')
        max_value = field_config.get('max_value')
        
        if min_value is not None and numeric_value < min_value:
            issues.append(ValidationIssue(
                field_name=field_name,
                issue_type='value_too_small',
                severity=ValidationSeverity.ERROR,
                message=f'"{field_name}"值过小，当前{numeric_value}，最小值为{min_value}',
                suggestions=[f'请输入大于等于{min_value}的值']
            ))
        
        if max_value is not None and numeric_value > max_value:
            issues.append(ValidationIssue(
                field_name=field_name,
                issue_type='value_too_large',
                severity=ValidationSeverity.ERROR,
                message=f'"{field_name}"值过大，当前{numeric_value}，最大值为{max_value}',
                suggestions=[f'请输入小于等于{max_value}的值']
            ))
        
        return issues
    
    def _validate_custom_rules(self, field_name: str, value: Any, 
                             field_config: Dict[str, Any]) -> List[ValidationIssue]:
        """验证自定义规则"""
        issues = []
        
        custom_validators = field_config.get('custom_validators', [])
        for validator in custom_validators:
            try:
                validator_name = validator.get('name')
                validator_params = validator.get('params', {})
                
                if validator_name == 'unique':
                    # 唯一性验证（需要额外的数据源）
                    pass
                elif validator_name == 'blacklist':
                    # 黑名单验证
                    blacklist = validator_params.get('values', [])
                    if str(value).lower() in [str(v).lower() for v in blacklist]:
                        issues.append(ValidationIssue(
                            field_name=field_name,
                            issue_type='blacklisted_value',
                            severity=ValidationSeverity.ERROR,
                            message=f'"{field_name}"包含不允许的值: {value}',
                            suggestions=['请使用其他值']
                        ))
                elif validator_name == 'whitelist':
                    # 白名单验证
                    whitelist = validator_params.get('values', [])
                    if str(value).lower() not in [str(v).lower() for v in whitelist]:
                        issues.append(ValidationIssue(
                            field_name=field_name,
                            issue_type='not_whitelisted',
                            severity=ValidationSeverity.ERROR,
                            message=f'"{field_name}"值不在允许范围内: {value}',
                            suggestions=['请从允许的值中选择']
                        ))
                        
            except Exception as e:
                issues.append(ValidationIssue(
                    field_name=field_name,
                    issue_type='custom_validation_error',
                    severity=ValidationSeverity.WARNING,
                    message=f'自定义验证出错: {str(e)}'
                ))
        
        return issues
    
    def _detect_field_type(self, field_name: str, field_config: Dict[str, Any]) -> Optional[str]:
        """检测字段类型"""
        # 首先从配置中获取
        explicit_type = field_config.get('validation_type')
        if explicit_type:
            return explicit_type
        
        # 根据字段名称推断
        field_name_lower = field_name.lower()
        for chinese_name, field_type in self.field_type_mapping.items():
            if chinese_name in field_name or field_type in field_name_lower:
                return field_type
        
        return None
    
    def _get_format_suggestions(self, field_type: str) -> List[str]:
        """获取格式建议"""
        suggestions = {
            'email': ['请输入有效的邮箱地址，如: user@example.com'],
            'phone': ['请输入有效的手机号码，如: 13812345678'],
            'mobile': ['请输入有效的手机号码，如: 13812345678'],
            'id_card': ['请输入有效的18位身份证号码'],
            'postal_code': ['请输入6位邮政编码'],
            'url': ['请输入有效的网址，如: https://www.example.com'],
            'ip': ['请输入有效的IP地址，如: 192.168.1.1']
        }
        
        return suggestions.get(field_type, ['请检查输入格式'])
    
    def add_custom_pattern(self, pattern_name: str, pattern: str, description: str = ""):
        """添加自定义验证模式"""
        try:
            # 验证正则表达式的有效性
            re.compile(pattern)
            self.validation_patterns[pattern_name] = pattern
            self.logger.info(f"{node_state}-=-填表员===Added custom validation pattern: {pattern_name}")
        except re.error as e:
            self.logger.error(f"Invalid regex pattern for {pattern_name}: {str(e)}")
            raise ValueError(f"Invalid regex pattern: {str(e)}")
    
    def get_available_patterns(self) -> Dict[str, str]:
        """获取所有可用的验证模式"""
        return self.validation_patterns.copy() 