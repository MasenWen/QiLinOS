"""
表单验证器

负责整体表单的完整性、一致性和结构验证。
"""

from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

from ..config.settings import ConfigManager
from ..utils.logger import get_logger
from .types import ValidationIssue, ValidationSeverity


class FormValidator:
    """
    表单验证器
    
    主要功能:
    - 表单完整性验证
    - 字段依赖关系验证
    - 表单结构验证
    - 数据一致性验证
    """
    
    def __init__(self, settings: ConfigManager):
        self.settings = settings
        self.logger = get_logger(__name__)
        
        # 表单类型配置
        self.form_configs = self._initialize_form_configs()
        
    def _initialize_form_configs(self) -> Dict[str, Any]:
        """初始化表单配置"""
        return {
            'personal_info': {
                'required_fields': ['姓名'],
                'recommended_fields': ['联系电话', '电子邮箱'],
                'optional_fields': ['年龄', '性别', '地址'],
                'field_groups': {
                    'basic_info': ['姓名', '性别', '年龄'],
                    'contact_info': ['联系电话', '电子邮箱', '地址'],
                    'identity_info': ['身份证号']
                },
                'dependencies': {
                    '身份证号': ['姓名'],  # 如果有身份证号，必须有姓名
                    '工作单位': ['联系电话']  # 如果有工作单位，建议有联系电话
                }
            },
            'work_info': {
                'required_fields': ['姓名', '公司名称'],
                'recommended_fields': ['职位', '部门'],
                'optional_fields': ['工作年限', '月薪', '工作地址'],
                'field_groups': {
                    'basic_info': ['姓名', '公司名称', '职位'],
                    'detail_info': ['部门', '工作年限', '月薪'],
                    'location_info': ['工作地址']
                },
                'dependencies': {
                    '月薪': ['职位'],
                    '部门': ['公司名称']
                }
            },
            'education_info': {
                'required_fields': ['姓名'],
                'recommended_fields': ['学历', '毕业院校'],
                'optional_fields': ['专业', '毕业时间', '在校成绩'],
                'field_groups': {
                    'basic_info': ['姓名', '学历'],
                    'school_info': ['毕业院校', '专业', '毕业时间'],
                    'performance_info': ['在校成绩']
                },
                'dependencies': {
                    '专业': ['毕业院校'],
                    '毕业时间': ['毕业院校'],
                    '在校成绩': ['学历']
                }
            }
        }
    
    async def validate_completeness(self, data: Dict[str, Any], 
                                  form_info: Dict[str, Any]) -> List[ValidationIssue]:
        """验证表单完整性"""
        issues = []
        form_type = form_info.get('form_type', 'unknown')
        
        # 获取表单配置
        config = self.form_configs.get(form_type, {})
        if not config:
            issues.append(ValidationIssue(
                field_name='form_type',
                issue_type='unknown_form_type',
                severity=ValidationSeverity.WARNING,
                message=f'未知的表单类型: {form_type}',
                suggestions=['请检查表单类型配置']
            ))
            return issues
        
        # 检查必填字段
        required_fields = config.get('required_fields', [])
        for field in required_fields:
            if field not in data or not data[field]:
                issues.append(ValidationIssue(
                    field_name=field,
                    issue_type='required_field_missing',
                    severity=ValidationSeverity.ERROR,
                    message=f'必填字段"{field}"缺失',
                    suggestions=[f'请填写{field}']
                ))
        
        # 检查推荐字段
        recommended_fields = config.get('recommended_fields', [])
        missing_recommended = []
        for field in recommended_fields:
            if field not in data or not data[field]:
                missing_recommended.append(field)
        
        if missing_recommended:
            issues.append(ValidationIssue(
                field_name='recommended_fields',
                issue_type='recommended_fields_missing',
                severity=ValidationSeverity.WARNING,
                message=f'建议填写以下字段以提高表单完整性: {", ".join(missing_recommended)}',
                suggestions=[f'考虑填写: {", ".join(missing_recommended)}']
            ))
        
        # 检查字段依赖关系
        dependency_issues = self._validate_field_dependencies(data, config)
        issues.extend(dependency_issues)
        
        # 检查字段组完整性
        group_issues = self._validate_field_groups(data, config)
        issues.extend(group_issues)
        
        return issues
    
    def _validate_field_dependencies(self, data: Dict[str, Any], 
                                   config: Dict[str, Any]) -> List[ValidationIssue]:
        """验证字段依赖关系"""
        issues = []
        dependencies = config.get('dependencies', {})
        
        for dependent_field, required_fields in dependencies.items():
            # 如果依赖字段存在且有值
            if dependent_field in data and data[dependent_field]:
                # 检查所有必需字段是否存在
                missing_deps = []
                for required_field in required_fields:
                    if required_field not in data or not data[required_field]:
                        missing_deps.append(required_field)
                
                if missing_deps:
                    issues.append(ValidationIssue(
                        field_name=dependent_field,
                        issue_type='dependency_not_satisfied',
                        severity=ValidationSeverity.WARNING,
                        message=f'字段"{dependent_field}"依赖以下字段: {", ".join(missing_deps)}',
                        suggestions=[f'如果填写了{dependent_field}，建议同时填写: {", ".join(missing_deps)}']
                    ))
        
        return issues
    
    def _validate_field_groups(self, data: Dict[str, Any], 
                             config: Dict[str, Any]) -> List[ValidationIssue]:
        """验证字段组完整性"""
        issues = []
        field_groups = config.get('field_groups', {})
        
        for group_name, group_fields in field_groups.items():
            filled_fields = []
            empty_fields = []
            
            for field in group_fields:
                if field in data and data[field]:
                    filled_fields.append(field)
                else:
                    empty_fields.append(field)
            
            # 如果组内有字段已填写，建议完善整个组
            if filled_fields and empty_fields:
                completion_rate = len(filled_fields) / len(group_fields) * 100
                
                if completion_rate < 50:  # 完成度低于50%
                    issues.append(ValidationIssue(
                        field_name=group_name,
                        issue_type='group_incomplete',
                        severity=ValidationSeverity.INFO,
                        message=f'字段组"{group_name}"完成度较低 ({completion_rate:.0f}%)',
                        suggestions=[f'考虑完善以下字段: {", ".join(empty_fields)}']
                    ))
                elif completion_rate < 80:  # 完成度低于80%
                    issues.append(ValidationIssue(
                        field_name=group_name,
                        issue_type='group_partially_complete',
                        severity=ValidationSeverity.INFO,
                        message=f'字段组"{group_name}"接近完成 ({completion_rate:.0f}%)',
                        suggestions=[f'建议补充: {", ".join(empty_fields)}']
                    ))
        
        return issues
    
    async def validate_form_structure(self, data: Dict[str, Any], 
                                    form_info: Dict[str, Any]) -> List[ValidationIssue]:
        """验证表单结构"""
        issues = []
        
        # 检查表单是否为空
        if not data:
            issues.append(ValidationIssue(
                field_name='form',
                issue_type='empty_form',
                severity=ValidationSeverity.ERROR,
                message='表单为空',
                suggestions=['请至少填写一个字段']
            ))
            return issues
        
        # 检查字段数量
        field_count = len(data)
        if field_count < 2:
            issues.append(ValidationIssue(
                field_name='form',
                issue_type='insufficient_fields',
                severity=ValidationSeverity.WARNING,
                message=f'表单字段过少 (仅有{field_count}个字段)',
                suggestions=['建议填写更多字段以提供完整信息']
            ))
        
        # 检查重复字段（不同的键但可能是同一信息）
        duplicate_issues = self._check_duplicate_fields(data)
        issues.extend(duplicate_issues)
        
        # 检查无效字段（空值或无意义的值）
        invalid_issues = self._check_invalid_fields(data)
        issues.extend(invalid_issues)
        
        return issues
    
    def _check_duplicate_fields(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """检查重复字段"""
        issues = []
        
        # 定义可能重复的字段组
        duplicate_groups = [
            ['电话', '联系电话', '手机号码', '手机'],
            ['邮箱', '电子邮箱', 'email', 'Email'],
            ['姓名', '真实姓名', '用户名'],
            ['地址', '联系地址', '住址', '家庭地址']
        ]
        
        for group in duplicate_groups:
            found_fields = []
            for field in group:
                if field in data and data[field]:
                    found_fields.append(field)
            
            if len(found_fields) > 1:
                # 检查值是否相同
                values = [str(data[field]).strip() for field in found_fields]
                if len(set(values)) == 1:  # 所有值都相同
                    issues.append(ValidationIssue(
                        field_name=', '.join(found_fields),
                        issue_type='duplicate_fields',
                        severity=ValidationSeverity.INFO,
                        message=f'检测到重复字段: {", ".join(found_fields)}',
                        suggestions=['考虑只保留一个字段，或确认是否需要不同的值']
                    ))
                else:
                    issues.append(ValidationIssue(
                        field_name=', '.join(found_fields),
                        issue_type='conflicting_fields',
                        severity=ValidationSeverity.WARNING,
                        message=f'相似字段有不同的值: {", ".join(f"{field}={data[field]}" for field in found_fields)}',
                        suggestions=['请确认哪个值是正确的']
                    ))
        
        return issues
    
    def _check_invalid_fields(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """检查无效字段"""
        issues = []
        
        for field_name, value in data.items():
            if not value:
                continue
            
            value_str = str(value).strip()
            
            # 检查明显无效的值
            invalid_patterns = [
                'test', 'xxx', '测试', '待填', '暂无', 'null', 'none', 'n/a',
                '111', '000', '123', 'abc', '---', '***'
            ]
            
            if value_str.lower() in invalid_patterns:
                issues.append(ValidationIssue(
                    field_name=field_name,
                    issue_type='placeholder_value',
                    severity=ValidationSeverity.WARNING,
                    message=f'字段"{field_name}"似乎包含占位符或测试值: {value}',
                    suggestions=['请填写真实有效的信息']
                ))
            
            # 检查过短的值（对于某些字段）
            if field_name in ['姓名', '公司名称', '毕业院校'] and len(value_str) == 1:
                issues.append(ValidationIssue(
                    field_name=field_name,
                    issue_type='value_too_short',
                    severity=ValidationSeverity.WARNING,
                    message=f'字段"{field_name}"的值过短: {value}',
                    suggestions=['请确认输入的信息是否完整']
                ))
            
            # 检查特殊字符过多
            special_char_count = sum(1 for c in value_str if not c.isalnum() and not c.isspace())
            if special_char_count > len(value_str) * 0.5:  # 特殊字符超过50%
                issues.append(ValidationIssue(
                    field_name=field_name,
                    issue_type='too_many_special_chars',
                    severity=ValidationSeverity.INFO,
                    message=f'字段"{field_name}"包含较多特殊字符: {value}',
                    suggestions=['请确认输入的格式是否正确']
                ))
        
        return issues
    
    async def validate_cross_field_consistency(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """验证跨字段一致性"""
        issues = []
        
        # 性别一致性检查
        if '姓名' in data and '性别' in data:
            name = str(data['姓名']).strip()
            gender = str(data['性别']).strip()
            
            # 简单的姓名性别一致性检查（基于常见姓名）
            male_indicators = ['先生', '男']
            female_indicators = ['女士', '小姐', '女']
            
            name_suggests_male = any(indicator in name for indicator in male_indicators)
            name_suggests_female = any(indicator in name for indicator in female_indicators)
            
            if name_suggests_male and gender in ['女', 'female', 'F']:
                issues.append(ValidationIssue(
                    field_name='性别',
                    issue_type='name_gender_inconsistency',
                    severity=ValidationSeverity.INFO,
                    message='姓名与性别可能不一致，请确认',
                    suggestions=['请确认姓名和性别信息是否正确']
                ))
            elif name_suggests_female and gender in ['男', 'male', 'M']:
                issues.append(ValidationIssue(
                    field_name='性别',
                    issue_type='name_gender_inconsistency',
                    severity=ValidationSeverity.INFO,
                    message='姓名与性别可能不一致，请确认',
                    suggestions=['请确认姓名和性别信息是否正确']
                ))
        
        # 地址一致性检查
        address_fields = ['地址', '联系地址', '工作地址', '家庭地址']
        addresses = {field: data[field] for field in address_fields if field in data and data[field]}
        
        if len(addresses) > 1:
            # 检查是否所有地址都在同一城市
            cities = set()
            for addr in addresses.values():
                addr_str = str(addr)
                # 简单的城市提取（查找"市"字）
                city_match = addr_str.find('市')
                if city_match > 0:
                    city = addr_str[:city_match + 1]
                    cities.add(city)
            
            if len(cities) > 1:
                issues.append(ValidationIssue(
                    field_name='地址信息',
                    issue_type='multiple_cities',
                    severity=ValidationSeverity.INFO,
                    message=f'检测到多个不同城市的地址: {", ".join(cities)}',
                    suggestions=['请确认地址信息是否正确']
                ))
        
        return issues
    
    def get_form_completion_score(self, data: Dict[str, Any], 
                                form_type: str) -> Dict[str, Any]:
        """计算表单完成度评分"""
        config = self.form_configs.get(form_type, {})
        if not config:
            return {'score': 0, 'details': 'Unknown form type'}
        
        total_score = 0
        max_score = 0
        details = {}
        
        # 必填字段评分 (60分)
        required_fields = config.get('required_fields', [])
        required_score = 0
        required_max = len(required_fields) * 60 // len(required_fields) if required_fields else 0
        
        for field in required_fields:
            if field in data and data[field]:
                required_score += 60 // len(required_fields)
        
        total_score += required_score
        max_score += required_max
        details['required_fields'] = {
            'score': required_score,
            'max_score': required_max,
            'completion': f"{len([f for f in required_fields if f in data and data[f]])}/{len(required_fields)}"
        }
        
        # 推荐字段评分 (30分)
        recommended_fields = config.get('recommended_fields', [])
        recommended_score = 0
        recommended_max = 30
        
        if recommended_fields:
            filled_recommended = len([f for f in recommended_fields if f in data and data[f]])
            recommended_score = int(30 * filled_recommended / len(recommended_fields))
        
        total_score += recommended_score
        max_score += recommended_max
        details['recommended_fields'] = {
            'score': recommended_score,
            'max_score': recommended_max,
            'completion': f"{len([f for f in recommended_fields if f in data and data[f]])}/{len(recommended_fields)}"
        }
        
        # 可选字段评分 (10分)
        optional_fields = config.get('optional_fields', [])
        optional_score = 0
        optional_max = 10
        
        if optional_fields:
            filled_optional = len([f for f in optional_fields if f in data and data[f]])
            optional_score = int(10 * filled_optional / len(optional_fields))
        
        total_score += optional_score
        max_score += optional_max
        details['optional_fields'] = {
            'score': optional_score,
            'max_score': optional_max,
            'completion': f"{len([f for f in optional_fields if f in data and data[f]])}/{len(optional_fields)}"
        }
        
        # 计算百分比
        percentage = (total_score / max_score * 100) if max_score > 0 else 0
        
        return {
            'score': total_score,
            'max_score': max_score,
            'percentage': round(percentage, 1),
            'details': details,
            'level': self._get_completion_level(percentage)
        }
    
    def _get_completion_level(self, percentage: float) -> str:
        """获取完成度等级"""
        if percentage >= 90:
            return '优秀'
        elif percentage >= 75:
            return '良好'
        elif percentage >= 60:
            return '及格'
        elif percentage >= 40:
            return '待改进'
        else:
            return '不完整' 