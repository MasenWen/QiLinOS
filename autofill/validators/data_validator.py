"""
数据验证器

主要的数据验证器，负责验证填写数据的准确性、完整性和合规性。
提供多层次的验证机制，确保数据质量。
"""

import re
import json
from typing import Dict, List, Any, Optional, Union, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime, date

from ..core import BaseValidator, ProcessingStatus
from ..config.settings import ConfigManager
from ..utils.logger import get_logger, performance_monitor, error_handler
from .types import ValidationLevel, ValidationSeverity, ValidationIssue, ValidationRequest, ValidationResult


class DataValidator(BaseValidator):
    """
    数据验证器
    
    主要功能:
    - 多层次数据验证
    - 自动错误修正
    - 验证报告生成
    - 自定义验证规则
    """
    
    def __init__(self, settings: ConfigManager):
        self.settings = settings
        self.logger = get_logger(__name__)
        
        # 延迟初始化子验证器以避免循环导入
        self.field_validator = None
        self.form_validator = None
        self.business_validator = None
        
        # 验证规则配置
        self.validation_rules = self._initialize_validation_rules()
        
        # 验证统计
        self.validation_stats = {
            'total_validations': 0,
            'successful_validations': 0,
            'failed_validations': 0,
            'average_score': 0.0,
            'common_issues': {}
        }
        
        self.logger.info("DataValidator initialized successfully")
    
    def _get_field_validator(self):
        """延迟初始化field_validator"""
        if self.field_validator is None:
            from .field_validator import FieldValidator
            self.field_validator = FieldValidator(self.settings)
        return self.field_validator
    
    def _get_form_validator(self):
        """延迟初始化form_validator"""
        if self.form_validator is None:
            from .form_validator import FormValidator
            self.form_validator = FormValidator(self.settings)
        return self.form_validator
    
    def _get_business_validator(self):
        """延迟初始化business_validator"""
        if self.business_validator is None:
            from .business_validator import BusinessValidator
            self.business_validator = BusinessValidator(self.settings)
        return self.business_validator
    
    def _initialize_validation_rules(self) -> Dict[str, Any]:
        """初始化验证规则"""
        return {
            'required_fields': {
                'personal_info': ['姓名', '联系电话'],
                'work_info': ['姓名', '公司名称'],
                'education_info': ['姓名', '学历']
            },
            'field_formats': {
                'email': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
                'phone': r'^(\+86)?1[3-9]\d{9}$',
                'id_card': r'^[1-9]\d{5}(18|19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$',
                'postal_code': r'^\d{6}$'
            },
            'value_ranges': {
                'age': {'min': 0, 'max': 150},
                'salary': {'min': 0, 'max': 10000000},
                'experience': {'min': 0, 'max': 50}
            },
            'business_rules': {
                'age_consistency': 'age should match birth_date',
                'education_timeline': 'graduation_date should be before work_start_date',
                'contact_consistency': 'at least one contact method required'
            }
        }
    
    def process(self, input_data: Any) -> Dict[str, Any]:
        """处理输入数据并返回结果（实现抽象方法）"""
        if isinstance(input_data, ValidationRequest):
            # 同步包装异步方法
            import asyncio
            result = asyncio.run(self.validate_data(input_data))
            return asdict(result)
        else:
            raise ValueError("输入数据必须是ValidationRequest类型")
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性（实现抽象方法）"""
        return isinstance(input_data, ValidationRequest) and input_data.data and input_data.form_info
    
    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """验证数据并返回验证结果（实现抽象方法）"""
        # 创建验证请求
        request = ValidationRequest(
            data=data,
            form_info={},  # 默认空表单信息
            validation_level=ValidationLevel.STANDARD
        )
        # 同步包装异步方法
        import asyncio
        result = asyncio.run(self.validate_data(request))
        return asdict(result)
    
    @performance_monitor
    @error_handler()
    async def validate_data(self, request: ValidationRequest) -> ValidationResult:
        """
        验证数据
        
        Args:
            request: 验证请求
            
        Returns:
            验证结果
        """
        start_time = datetime.now()
        
        try:
            self.logger.info(f"{node_state}-=-填表员===Starting data validation with level: {request.validation_level.value}")
            
            issues = []
            corrected_data = request.data.copy() if request.fix_errors else None
            
            # 基础验证
            if request.validation_level.value in ['basic', 'standard', 'strict', 'comprehensive']:
                basic_issues = await self._perform_basic_validation(
                    request.data, request.form_info
                )
                issues.extend(basic_issues)
            
            # 标准验证（业务规则）
            if request.validation_level.value in ['standard', 'strict', 'comprehensive']:
                business_issues = await self._perform_business_validation(
                    request.data, request.form_info, request.custom_rules
                )
                issues.extend(business_issues)
            
            # 严格验证（完整性检查）
            if request.validation_level.value in ['strict', 'comprehensive']:
                completeness_issues = await self._perform_completeness_validation(
                    request.data, request.form_info
                )
                issues.extend(completeness_issues)
            
            # 全面验证（高级检查）
            if request.validation_level.value == 'comprehensive':
                advanced_issues = await self._perform_advanced_validation(
                    request.data, request.form_info
                )
                issues.extend(advanced_issues)
            
            # 应用自动修正
            if request.fix_errors and corrected_data:
                corrected_data = await self._apply_auto_corrections(
                    corrected_data, issues
                )
            
            # 过滤警告
            if request.ignore_warnings:
                issues = [issue for issue in issues 
                         if issue.severity != ValidationSeverity.WARNING]
            
            # 计算验证结果
            is_valid = self._determine_validity(issues)
            validation_score = self._calculate_validation_score(issues, len(request.data))
            
            # 生成摘要
            summary = self._generate_validation_summary(issues, request.data)
            
            # 计算处理时间
            processing_time = (datetime.now() - start_time).total_seconds()
            
            result = ValidationResult(
                is_valid=is_valid,
                issues=issues,
                corrected_data=corrected_data,
                validation_score=validation_score,
                processing_time=processing_time,
                summary=summary
            )
            
            # 更新统计
            self._update_validation_stats(result)
            
            self.logger.info(f"{node_state}-=-填表员===Data validation completed: valid={is_valid}, score={validation_score:.1f}")
            return result
            
        except Exception as e:
            self.logger.error(f"Data validation failed: {str(e)}")
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return ValidationResult(
                is_valid=False,
                issues=[ValidationIssue(
                    field_name="system",
                    issue_type="validation_error",
                    severity=ValidationSeverity.CRITICAL,
                    message=f"Validation system error: {str(e)}"
                )],
                processing_time=processing_time
            )
    
    async def _perform_basic_validation(self, data: Dict[str, Any], 
                                      form_info: Dict[str, Any]) -> List[ValidationIssue]:
        """执行基础验证"""
        issues = []
        

        print("="*60)
        for field_name, value in data.items():
            # 字段级验证
            field = next((field for field in form_info.get('fields', []) if field.get('id') == field_name), {})
            print(field)
            field_issues = await self._get_field_validator().validate_field(
                field_name, value, field
            )
            issues.extend(field_issues)
        print("="*60)
        return issues
    
    async def _perform_business_validation(self, data: Dict[str, Any], 
                                         form_info: Dict[str, Any],
                                         custom_rules: Optional[Dict[str, Any]]) -> List[ValidationIssue]:
        """执行业务验证"""
        return await self._get_business_validator().validate_business_rules(
            data, form_info, custom_rules
        )
    
    async def _perform_completeness_validation(self, data: Dict[str, Any], 
                                             form_info: Dict[str, Any]) -> List[ValidationIssue]:
        """执行完整性验证"""
        return await self._get_form_validator().validate_completeness(data, form_info)
    
    async def _perform_advanced_validation(self, data: Dict[str, Any], 
                                         form_info: Dict[str, Any]) -> List[ValidationIssue]:
        """执行高级验证"""
        issues = []
        
        # 一致性检查
        consistency_issues = await self._check_data_consistency(data)
        issues.extend(consistency_issues)
        
        # 逻辑性检查
        logic_issues = await self._check_data_logic(data)
        issues.extend(logic_issues)
        
        # 完整性检查
        integrity_issues = await self._check_data_integrity(data, form_info)
        issues.extend(integrity_issues)
        
        return issues
    
    async def _check_data_consistency(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """检查数据一致性"""
        issues = []
        
        # 年龄与出生日期一致性
        if '年龄' in data and '出生日期' in data:
            try:
                age = int(data['年龄'])
                birth_date_str = str(data['出生日期'])
                
                # 解析出生日期
                birth_date = None
                for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y']:
                    try:
                        birth_date = datetime.strptime(birth_date_str, fmt).date()
                        break
                    except ValueError:
                        continue
                
                if birth_date:
                    calculated_age = (date.today() - birth_date).days // 365
                    if abs(age - calculated_age) > 1:  # 允许1岁误差
                        issues.append(ValidationIssue(
                            field_name='年龄',
                            issue_type='consistency_error',
                            severity=ValidationSeverity.ERROR,
                            message=f'年龄({age})与出生日期({birth_date_str})不一致',
                            suggestions=['请检查年龄或出生日期是否正确']
                        ))
                        
            except (ValueError, TypeError):
                pass
        
        # 联系方式一致性（确保至少有一种联系方式）
        contact_fields = ['联系电话', '电子邮箱', '手机号码', '电话', '邮箱']
        has_contact = any(field in data and data[field] for field in contact_fields)
        
        if not has_contact:
            issues.append(ValidationIssue(
                field_name='联系方式',
                issue_type='completeness_error',
                severity=ValidationSeverity.ERROR,
                message='缺少有效的联系方式',
                suggestions=['请至少填写一种联系方式（电话或邮箱）']
            ))
        
        return issues
    
    async def _check_data_logic(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """检查数据逻辑性"""
        issues = []
        
        # 教育时间线逻辑
        if '毕业时间' in data and '入职时间' in data:
            try:
                grad_date_str = str(data['毕业时间'])
                work_date_str = str(data['入职时间'])
                
                grad_date = None
                work_date = None
                
                for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%Y-%m', '%Y']:
                    try:
                        grad_date = datetime.strptime(grad_date_str, fmt).date()
                        work_date = datetime.strptime(work_date_str, fmt).date()
                        break
                    except ValueError:
                        continue
                
                if grad_date and work_date and work_date < grad_date:
                    issues.append(ValidationIssue(
                        field_name='入职时间',
                        issue_type='logic_error',
                        severity=ValidationSeverity.WARNING,
                        message=f'入职时间({work_date_str})早于毕业时间({grad_date_str})',
                        suggestions=['请检查时间顺序是否正确']
                    ))
                    
            except (ValueError, TypeError):
                pass
        
        # 工作年限逻辑
        if '工作年限' in data and '年龄' in data:
            try:
                experience = int(data['工作年限'])
                age = int(data['年龄'])
                
                if experience > age - 16:  # 假设最早16岁开始工作
                    issues.append(ValidationIssue(
                        field_name='工作年限',
                        issue_type='logic_error',
                        severity=ValidationSeverity.WARNING,
                        message=f'工作年限({experience}年)相对于年龄({age}岁)过长',
                        suggestions=['请检查工作年限是否正确']
                    ))
                    
            except (ValueError, TypeError):
                pass
        
        return issues
    
    async def _check_data_integrity(self, data: Dict[str, Any], 
                                  form_info: Dict[str, Any]) -> List[ValidationIssue]:
        """检查数据完整性"""
        issues = []
        
        # 必填字段检查
        form_type = form_info.get('form_type', 'unknown')
        required_fields = self.validation_rules['required_fields'].get(form_type, [])
        
        for field in required_fields:
            if field not in data or not data[field]:
                issues.append(ValidationIssue(
                    field_name=field,
                    issue_type='required_field_missing',
                    severity=ValidationSeverity.ERROR,
                    message=f'必填字段"{field}"缺失或为空',
                    suggestions=[f'请填写{field}']
                ))
        
        # 关键信息完整性
        if form_type == 'personal_info':
            identity_fields = ['姓名', '身份证号', '联系电话']
            filled_identity = sum(1 for field in identity_fields if field in data and data[field])
            
            if filled_identity < 2:
                issues.append(ValidationIssue(
                    field_name='身份信息',
                    issue_type='incomplete_identity',
                    severity=ValidationSeverity.WARNING,
                    message='身份信息不够完整，建议填写更多信息',
                    suggestions=['建议至少填写姓名、身份证号和联系电话中的两项']
                ))
        
        return issues
    
    async def _apply_auto_corrections(self, data: Dict[str, Any], 
                                    issues: List[ValidationIssue]) -> Dict[str, Any]:
        """应用自动修正"""
        corrected_data = data.copy()
        
        for issue in issues:
            if issue.severity in [ValidationSeverity.WARNING, ValidationSeverity.INFO]:
                # 尝试自动修正
                corrected_value = await self._auto_correct_field(
                    issue.field_name, data.get(issue.field_name), issue
                )
                
                if corrected_value is not None:
                    corrected_data[issue.field_name] = corrected_value
                    self.logger.info(f"{node_state}-=-填表员===Auto-corrected field {issue.field_name}: {corrected_value}")
        
        return corrected_data
    
    async def _auto_correct_field(self, field_name: str, value: Any, 
                                issue: ValidationIssue) -> Optional[Any]:
        """自动修正字段值"""
        if not value:
            return None
        
        value_str = str(value).strip()
        
        # 电话号码修正
        if '电话' in field_name or '手机' in field_name:
            # 移除非数字字符
            digits = ''.join(filter(str.isdigit, value_str))
            if len(digits) == 11 and digits.startswith('1'):
                return digits
            elif len(digits) == 10:
                return '1' + digits  # 假设缺少开头的1
        
        # 邮箱修正
        if '邮箱' in field_name or 'email' in field_name.lower():
            # 简单的邮箱格式修正
            if '@' in value_str and '.' in value_str:
                return value_str.lower()
        
        # 姓名修正
        if '姓名' in field_name or 'name' in field_name.lower():
            # 移除多余空格
            return ' '.join(value_str.split())
        
        # 日期修正
        if '日期' in field_name or '时间' in field_name:
            # 尝试标准化日期格式
            for fmt_in, fmt_out in [
                ('%Y/%m/%d', '%Y-%m-%d'),
                ('%m/%d/%Y', '%Y-%m-%d'),
                ('%d/%m/%Y', '%Y-%m-%d')
            ]:
                try:
                    dt = datetime.strptime(value_str, fmt_in)
                    return dt.strftime(fmt_out)
                except ValueError:
                    continue
        
        return None
    
    def _determine_validity(self, issues: List[ValidationIssue]) -> bool:
        """确定验证是否通过"""
        # 有严重错误或错误则验证不通过
        for issue in issues:
            if issue.severity in [ValidationSeverity.CRITICAL, ValidationSeverity.ERROR]:
                return False
        return True
    
    def _calculate_validation_score(self, issues: List[ValidationIssue], 
                                  total_fields: int) -> float:
        """计算验证分数"""
        if total_fields == 0:
            return 0.0
        
        # 权重设置
        severity_weights = {
            ValidationSeverity.INFO: 0,
            ValidationSeverity.WARNING: 5,
            ValidationSeverity.ERROR: 20,
            ValidationSeverity.CRITICAL: 50
        }
        
        # 计算扣分
        total_deduction = sum(severity_weights.get(issue.severity, 0) for issue in issues)
        
        # 基础分100，根据问题严重程度扣分
        score = max(0, 100 - total_deduction)
        
        # 根据字段数量调整（字段越多，容错率越高）
        if total_fields > 10:
            score = min(100, score + (total_fields - 10) * 0.5)
        
        return round(score, 1)
    
    def _generate_validation_summary(self, issues: List[ValidationIssue], 
                                   data: Dict[str, Any]) -> Dict[str, Any]:
        """生成验证摘要"""
        severity_counts = {}
        issue_types = {}
        problem_fields = []
        
        for issue in issues:
            # 统计严重级别
            severity_counts[issue.severity.value] = severity_counts.get(issue.severity.value, 0) + 1
            
            # 统计问题类型
            issue_types[issue.issue_type] = issue_types.get(issue.issue_type, 0) + 1
            
            # 收集问题字段
            if issue.field_name not in problem_fields:
                problem_fields.append(issue.field_name)
        
        return {
            'total_fields': len(data),
            'total_issues': len(issues),
            'severity_distribution': severity_counts,
            'issue_types': issue_types,
            'problem_fields': problem_fields,
            'completion_rate': (len(data) - len(problem_fields)) / len(data) * 100 if data else 0
        }
    
    def _update_validation_stats(self, result: ValidationResult):
        """更新验证统计"""
        self.validation_stats['total_validations'] += 1
        
        if result.is_valid:
            self.validation_stats['successful_validations'] += 1
        else:
            self.validation_stats['failed_validations'] += 1
        
        # 更新平均分数
        total = self.validation_stats['total_validations']
        current_avg = self.validation_stats['average_score']
        new_avg = (current_avg * (total - 1) + result.validation_score) / total
        self.validation_stats['average_score'] = round(new_avg, 1)
        
        # 统计常见问题
        for issue in result.issues:
            issue_key = f"{issue.issue_type}_{issue.severity.value}"
            self.validation_stats['common_issues'][issue_key] = (
                self.validation_stats['common_issues'].get(issue_key, 0) + 1
            )
    
    def get_validation_stats(self) -> Dict[str, Any]:
        """获取验证统计信息"""
        return self.validation_stats.copy()
    
    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """实现基类的process方法"""
        request = ValidationRequest(**data)
        result = await self.validate_data(request)
        return asdict(result) 