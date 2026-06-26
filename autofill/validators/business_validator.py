"""
业务验证器

负责业务逻辑、规则和复杂验证场景的处理。
"""

import re
from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta

from ..config.settings import ConfigManager
from ..utils.logger import get_logger
from .types import ValidationIssue, ValidationSeverity


class BusinessValidator:
    """
    业务验证器
    
    主要功能:
    - 业务逻辑验证
    - 规则引擎验证
    - 复杂场景验证
    - 行业特定验证
    """
    
    def __init__(self, settings: ConfigManager):
        self.settings = settings
        self.logger = get_logger(__name__)
        
        # 业务规则配置
        self.business_rules = self._initialize_business_rules()
        
        # 行业特定规则
        self.industry_rules = self._initialize_industry_rules()
        
    def _initialize_business_rules(self) -> Dict[str, Any]:
        """初始化业务规则"""
        return {
            'age_rules': {
                'min_work_age': 16,      # 最小工作年龄
                'retirement_age': 65,    # 退休年龄
                'min_age': 0,           # 最小年龄
                'max_age': 150          # 最大年龄
            },
            'education_rules': {
                'degree_hierarchy': ['小学', '初中', '高中', '中专', '大专', '本科', '硕士', '博士'],
                'min_graduation_age': {
                    '小学': 12, '初中': 15, '高中': 18, '中专': 18,
                    '大专': 20, '本科': 22, '硕士': 25, '博士': 28
                }
            },
            'contact_rules': {
                'phone_prefixes': ['13', '14', '15', '16', '17', '18', '19'],
                'email_domains': ['.com', '.cn', '.net', '.org', '.edu'],
                'required_contact_methods': 0  # 至少需要一种联系方式
            },
            'work_rules': {
                'max_salary': 10000000,    # 最大月薪
                'min_salary': 0,           # 最小月薪
                'max_experience': 50,      # 最大工作年限
                'reasonable_salary_ranges': {
                    '实习生': (0, 5000),
                    '助理': (3000, 8000),
                    '专员': (5000, 15000),
                    '主管': (8000, 25000),
                    '经理': (15000, 50000),
                    '总监': (25000, 100000),
                    '总经理': (50000, 200000)
                }
            }
        }
    
    def _initialize_industry_rules(self) -> Dict[str, Dict[str, Any]]:
        """初始化行业特定规则"""
        return {
            'education': {
                'required_fields': ['学历', '毕业院校'],
                'validation_rules': {
                    'teacher_qualification': '需要教师资格证',
                    'education_background': '教育行业通常需要相关学历背景'
                }
            },
            'finance': {
                'required_fields': ['学历', '相关证书'],
                'validation_rules': {
                    'finance_license': '金融行业可能需要相关执业证书',
                    'education_requirement': '通常要求本科以上学历'
                }
            },
            'healthcare': {
                'required_fields': ['学历', '执业证书'],
                'validation_rules': {
                    'medical_license': '医疗行业需要执业医师证',
                    'education_requirement': '医学相关专业背景'
                }
            },
            'technology': {
                'required_fields': ['技能', '项目经验'],
                'validation_rules': {
                    'tech_skills': '技术岗位需要相关技能描述',
                    'project_experience': '项目经验有助于评估能力'
                }
            }
        }
    
    async def validate_business_rules(self, data: Dict[str, Any], 
                                    form_info: Dict[str, Any],
                                    custom_rules: Optional[Dict[str, Any]] = None) -> List[ValidationIssue]:
        """验证业务规则"""
        issues = []
        
        # 年龄相关业务规则
        age_issues = await self._validate_age_rules(data)
        issues.extend(age_issues)
        
        # 教育相关业务规则
        education_issues = await self._validate_education_rules(data)
        issues.extend(education_issues)
        
        # 工作相关业务规则
        work_issues = await self._validate_work_rules(data)
        issues.extend(work_issues)
        
        # 联系方式业务规则
        contact_issues = await self._validate_contact_rules(data)
        issues.extend(contact_issues)
        
        # 时间逻辑业务规则
        timeline_issues = await self._validate_timeline_rules(data)
        issues.extend(timeline_issues)
        
        # 行业特定规则
        industry_issues = await self._validate_industry_rules(data, form_info)
        issues.extend(industry_issues)
        
        # 自定义业务规则
        if custom_rules:
            custom_issues = await self._validate_custom_business_rules(data, custom_rules)
            issues.extend(custom_issues)
        
        return issues
    
    async def _validate_age_rules(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """验证年龄相关业务规则"""
        issues = []
        age_rules = self.business_rules['age_rules']
        
        age = None
        birth_date = None
        
        # 获取年龄信息
        if '年龄' in data:
            try:
                age = int(data['年龄'])
            except (ValueError, TypeError):
                pass
        
        # 获取出生日期
        if '出生日期' in data:
            birth_date_str = str(data['出生日期'])
            for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y']:
                try:
                    birth_date = datetime.strptime(birth_date_str, fmt).date()
                    if not age:
                        # 从出生日期计算年龄
                        age = (date.today() - birth_date).days // 365
                    break
                except ValueError:
                    continue
        
        if age is not None:
            # 年龄范围检查
            if age < age_rules['min_age']:
                issues.append(ValidationIssue(
                    field_name='年龄',
                    issue_type='age_too_young',
                    severity=ValidationSeverity.ERROR,
                    message=f'年龄{age}岁过小',
                    suggestions=['请确认年龄信息是否正确']
                ))
            elif age > age_rules['max_age']:
                issues.append(ValidationIssue(
                    field_name='年龄',
                    issue_type='age_too_old',
                    severity=ValidationSeverity.ERROR,
                    message=f'年龄{age}岁过大',
                    suggestions=['请确认年龄信息是否正确']
                ))
            
            # 工作年龄检查
            if '工作年限' in data or '职位' in data or '公司名称' in data:
                if age < age_rules['min_work_age']:
                    issues.append(ValidationIssue(
                        field_name='年龄',
                        issue_type='below_work_age',
                        severity=ValidationSeverity.WARNING,
                        message=f'年龄{age}岁低于法定工作年龄',
                        suggestions=['请确认工作信息是否正确']
                    ))
                elif age > age_rules['retirement_age']:
                    issues.append(ValidationIssue(
                        field_name='年龄',
                        issue_type='beyond_retirement_age',
                        severity=ValidationSeverity.INFO,
                        message=f'年龄{age}岁超过退休年龄',
                        suggestions=['请确认是否仍在工作']
                    ))
        
        return issues
    
    async def _validate_education_rules(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """验证教育相关业务规则"""
        issues = []
        education_rules = self.business_rules['education_rules']
        
        degree = data.get('学历')
        graduation_date = data.get('毕业时间')
        age = None
        
        if '年龄' in data:
            try:
                age = int(data['年龄'])
            except (ValueError, TypeError):
                pass
        
        if degree and age:
            # 检查学历与年龄的合理性
            min_grad_age = education_rules['min_graduation_age'].get(degree)
            if min_grad_age and age < min_grad_age:
                issues.append(ValidationIssue(
                    field_name='学历',
                    issue_type='education_age_mismatch',
                    severity=ValidationSeverity.WARNING,
                    message=f'年龄{age}岁获得{degree}学历可能过早',
                    suggestions=['请确认学历和年龄信息是否正确']
                ))
        
        if graduation_date and age:
            # 检查毕业时间与年龄的合理性
            try:
                for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%Y-%m', '%Y']:
                    try:
                        grad_date = datetime.strptime(str(graduation_date), fmt).date()
                        grad_age = (grad_date - date.today()).days // 365 + age
                        
                        if degree:
                            min_grad_age = education_rules['min_graduation_age'].get(degree, 18)
                            if grad_age < min_grad_age:
                                issues.append(ValidationIssue(
                                    field_name='毕业时间',
                                    issue_type='graduation_too_early',
                                    severity=ValidationSeverity.WARNING,
                                    message=f'毕业时年龄约{grad_age}岁，对{degree}学历来说可能过早',
                                    suggestions=['请确认毕业时间是否正确']
                                ))
                        break
                    except ValueError:
                        continue
            except:
                pass
        
        # 检查学历层次的合理性
        if '最高学历' in data and '学历' in data:
            highest_degree = data['最高学历']
            current_degree = data['学历']
            
            if highest_degree != current_degree:
                issues.append(ValidationIssue(
                    field_name='学历',
                    issue_type='degree_inconsistency',
                    severity=ValidationSeverity.INFO,
                    message=f'学历({current_degree})与最高学历({highest_degree})不一致',
                    suggestions=['请确认填写的是最高学历还是相关学历']
                ))
        
        return issues
    
    async def _validate_work_rules(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """验证工作相关业务规则"""
        issues = []
        work_rules = self.business_rules['work_rules']
        
        salary = data.get('月薪') or data.get('薪资')
        position = data.get('职位')
        experience = data.get('工作年限')
        age = None
        
        if '年龄' in data:
            try:
                age = int(data['年龄'])
            except (ValueError, TypeError):
                pass
        
        # 薪资合理性检查
        if salary:
            try:
                # 提取数字
                salary_num = float(''.join(filter(str.isdigit, str(salary))))
                
                if salary_num < work_rules['min_salary']:
                    issues.append(ValidationIssue(
                        field_name='月薪',
                        issue_type='salary_too_low',
                        severity=ValidationSeverity.INFO,
                        message=f'薪资{salary_num}元偏低',
                        suggestions=['请确认薪资信息是否正确']
                    ))
                elif salary_num > work_rules['max_salary']:
                    issues.append(ValidationIssue(
                        field_name='月薪',
                        issue_type='salary_too_high',
                        severity=ValidationSeverity.WARNING,
                        message=f'薪资{salary_num}元过高',
                        suggestions=['请确认薪资信息是否正确']
                    ))
                
                # 职位与薪资匹配检查
                if position:
                    for pos_keyword, (min_sal, max_sal) in work_rules['reasonable_salary_ranges'].items():
                        if pos_keyword in position:
                            if salary_num < min_sal:
                                issues.append(ValidationIssue(
                                    field_name='月薪',
                                    issue_type='salary_position_mismatch_low',
                                    severity=ValidationSeverity.INFO,
                                    message=f'{position}职位的薪资{salary_num}元可能偏低',
                                    suggestions=[f'{position}通常薪资范围在{min_sal}-{max_sal}元']
                                ))
                            elif salary_num > max_sal:
                                issues.append(ValidationIssue(
                                    field_name='月薪',
                                    issue_type='salary_position_mismatch_high',
                                    severity=ValidationSeverity.INFO,
                                    message=f'{position}职位的薪资{salary_num}元可能偏高',
                                    suggestions=[f'{position}通常薪资范围在{min_sal}-{max_sal}元']
                                ))
                            break
                            
            except (ValueError, TypeError):
                pass
        
        # 工作年限合理性检查
        if experience:
            try:
                exp_years = int(experience)
                
                if exp_years < 0:
                    issues.append(ValidationIssue(
                        field_name='工作年限',
                        issue_type='negative_experience',
                        severity=ValidationSeverity.ERROR,
                        message='工作年限不能为负数',
                        suggestions=['请输入正确的工作年限']
                    ))
                elif exp_years > work_rules['max_experience']:
                    issues.append(ValidationIssue(
                        field_name='工作年限',
                        issue_type='experience_too_long',
                        severity=ValidationSeverity.WARNING,
                        message=f'工作年限{exp_years}年过长',
                        suggestions=['请确认工作年限是否正确']
                    ))
                
                # 工作年限与年龄的合理性
                if age:
                    max_possible_exp = age - 16  # 假设最早16岁开始工作
                    if exp_years > max_possible_exp:
                        issues.append(ValidationIssue(
                            field_name='工作年限',
                            issue_type='experience_age_mismatch',
                            severity=ValidationSeverity.WARNING,
                            message=f'工作年限{exp_years}年相对于年龄{age}岁不合理',
                            suggestions=['请确认工作年限和年龄信息是否正确']
                        ))
                        
            except (ValueError, TypeError):
                pass
        
        return issues
    
    async def _validate_contact_rules(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """验证联系方式业务规则"""
        issues = []
        contact_rules = self.business_rules['contact_rules']
        
        # 检查是否有有效的联系方式
        contact_fields = ['联系电话', '手机号码', '电话', '手机', '电子邮箱', '邮箱', 'email']
        valid_contacts = []
        
        for field in contact_fields:
            if field in data and data[field]:
                valid_contacts.append(field)
        
        if len(valid_contacts) < contact_rules['required_contact_methods']:
            issues.append(ValidationIssue(
                field_name='联系方式',
                issue_type='insufficient_contact_methods',
                severity=ValidationSeverity.ERROR,
                message='缺少有效的联系方式',
                suggestions=['请至少提供一种联系方式（电话或邮箱）']
            ))
        
        # 手机号码格式业务验证
        phone_fields = ['联系电话', '手机号码', '电话', '手机']
        for field in phone_fields:
            if field in data and data[field]:
                phone = str(data[field]).strip()
                # 移除非数字字符
                digits = ''.join(filter(str.isdigit, phone))
                
                if len(digits) == 11:
                    prefix = digits[:2]
                    if prefix not in contact_rules['phone_prefixes']:
                        issues.append(ValidationIssue(
                            field_name=field,
                            issue_type='invalid_phone_prefix',
                            severity=ValidationSeverity.WARNING,
                            message=f'手机号码前缀{prefix}不在常见范围内',
                            suggestions=['请确认手机号码是否正确']
                        ))
        
        # 邮箱域名业务验证
        email_fields = ['电子邮箱', '邮箱', 'email']
        for field in email_fields:
            if field in data and data[field]:
                email = str(data[field]).strip().lower()
                
                # 检查是否包含常见域名
                has_common_domain = any(domain in email for domain in contact_rules['email_domains'])
                if not has_common_domain:
                    issues.append(ValidationIssue(
                        field_name=field,
                        issue_type='uncommon_email_domain',
                        severity=ValidationSeverity.INFO,
                        message=f'邮箱域名不常见: {email}',
                        suggestions=['请确认邮箱地址是否正确']
                    ))
        
        return issues
    
    async def _validate_timeline_rules(self, data: Dict[str, Any]) -> List[ValidationIssue]:
        """验证时间线业务规则"""
        issues = []
        
        # 收集所有日期字段
        date_fields = {}
        for field_name, value in data.items():
            if any(keyword in field_name for keyword in ['日期', '时间', '年']):
                try:
                    date_str = str(value)
                    for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%Y-%m', '%Y']:
                        try:
                            parsed_date = datetime.strptime(date_str, fmt).date()
                            date_fields[field_name] = parsed_date
                            break
                        except ValueError:
                            continue
                except:
                    pass
        
        # 教育-工作时间线检查
        grad_date = date_fields.get('毕业时间')
        work_start = date_fields.get('入职时间') or date_fields.get('工作开始时间')
        
        if grad_date and work_start:
            if work_start < grad_date:
                # 允许一些灵活性（实习、兼职等）
                days_diff = (grad_date - work_start).days
                if days_diff > 365:  # 超过一年
                    issues.append(ValidationIssue(
                        field_name='入职时间',
                        issue_type='work_before_graduation',
                        severity=ValidationSeverity.WARNING,
                        message=f'入职时间比毕业时间早{days_diff}天',
                        suggestions=['请确认是否有实习经历或时间信息是否正确']
                    ))
        
        # 年龄与各时间点的合理性
        birth_date = date_fields.get('出生日期')
        if birth_date:
            today = date.today()
            age_years = (today - birth_date).days // 365
            
            # 检查毕业年龄
            if grad_date:
                grad_age = (grad_date - birth_date).days // 365
                if grad_age < 15:  # 15岁前毕业不太可能
                    issues.append(ValidationIssue(
                        field_name='毕业时间',
                        issue_type='graduation_too_young',
                        severity=ValidationSeverity.WARNING,
                        message=f'毕业时年龄约{grad_age}岁，过于年轻',
                        suggestions=['请确认毕业时间和出生日期是否正确']
                    ))
            
            # 检查工作开始年龄
            if work_start:
                work_age = (work_start - birth_date).days // 365
                if work_age < 16:  # 16岁前工作需要注意
                    issues.append(ValidationIssue(
                        field_name='入职时间',
                        issue_type='work_start_too_young',
                        severity=ValidationSeverity.INFO,
                        message=f'开始工作时年龄约{work_age}岁',
                        suggestions=['请确认是否有特殊情况或时间信息是否正确']
                    ))
        
        return issues
    
    async def _validate_industry_rules(self, data: Dict[str, Any], 
                                     form_info: Dict[str, Any]) -> List[ValidationIssue]:
        """验证行业特定规则"""
        issues = []
        
        # 根据职业或公司推断行业
        industry = self._detect_industry(data)
        
        if industry and industry in self.industry_rules:
            rules = self.industry_rules[industry]
            
            # 检查行业必需字段
            required_fields = rules.get('required_fields', [])
            for field in required_fields:
                if field not in data or not data[field]:
                    issues.append(ValidationIssue(
                        field_name=field,
                        issue_type='industry_required_field_missing',
                        severity=ValidationSeverity.INFO,
                        message=f'{industry}行业通常需要填写{field}',
                        suggestions=[f'建议补充{field}信息']
                    ))
            
            # 应用行业特定验证规则
            validation_rules = rules.get('validation_rules', {})
            for rule_name, rule_desc in validation_rules.items():
                # 这里可以根据具体规则实现验证逻辑
                if rule_name == 'education_requirement' and '学历' in data:
                    degree = data['学历']
                    if industry == 'finance' and degree not in ['本科', '硕士', '博士']:
                        issues.append(ValidationIssue(
                            field_name='学历',
                            issue_type='industry_education_requirement',
                            severity=ValidationSeverity.INFO,
                            message='金融行业通常要求本科以上学历',
                            suggestions=['请确认学历信息是否准确']
                        ))
        
        return issues
    
    def _detect_industry(self, data: Dict[str, Any]) -> Optional[str]:
        """检测行业"""
        # 根据职位、公司名称等推断行业
        position = data.get('职位', '').lower()
        company = data.get('公司名称', '').lower()
        
        # 教育行业关键词
        if any(keyword in position for keyword in ['教师', '老师', '教授', '讲师']) or \
           any(keyword in company for keyword in ['学校', '大学', '学院', '教育']):
            return 'education'
        
        # 金融行业关键词
        if any(keyword in position for keyword in ['银行', '金融', '投资', '证券', '保险']) or \
           any(keyword in company for keyword in ['银行', '证券', '保险', '基金', '投资']):
            return 'finance'
        
        # 医疗行业关键词
        if any(keyword in position for keyword in ['医生', '护士', '医师', '药师']) or \
           any(keyword in company for keyword in ['医院', '诊所', '医疗', '制药']):
            return 'healthcare'
        
        # 技术行业关键词
        if any(keyword in position for keyword in ['程序员', '工程师', '开发', '技术', 'it']) or \
           any(keyword in company for keyword in ['科技', '软件', '互联网', '技术']):
            return 'technology'
        
        return None
    
    async def _validate_custom_business_rules(self, data: Dict[str, Any], 
                                            custom_rules: Dict[str, Any]) -> List[ValidationIssue]:
        """验证自定义业务规则"""
        issues = []
        
        # 这里可以实现自定义业务规则的验证逻辑
        # 例如：特定组织的规则、特殊场景的验证等
        
        for rule_name, rule_config in custom_rules.items():
            try:
                if rule_config.get('type') == 'field_relationship':
                    # 字段关系验证
                    field1 = rule_config.get('field1')
                    field2 = rule_config.get('field2')
                    relationship = rule_config.get('relationship')
                    
                    if field1 in data and field2 in data:
                        value1 = data[field1]
                        value2 = data[field2]
                        
                        if relationship == 'equal' and value1 != value2:
                            issues.append(ValidationIssue(
                                field_name=field1,
                                issue_type='custom_relationship_violation',
                                severity=ValidationSeverity.WARNING,
                                message=f'{field1}和{field2}应该相等',
                                suggestions=['请检查相关字段的一致性']
                            ))
                        elif relationship == 'not_equal' and value1 == value2:
                            issues.append(ValidationIssue(
                                field_name=field1,
                                issue_type='custom_relationship_violation',
                                severity=ValidationSeverity.WARNING,
                                message=f'{field1}和{field2}不应该相等',
                                suggestions=['请检查相关字段是否填写正确']
                            ))
                            
            except Exception as e:
                self.logger.warning(f"Custom business rule validation error: {str(e)}")
        
        return issues 