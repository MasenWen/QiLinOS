"""
模板填写器

基于预定义模板来填写表单，支持模板管理和动态加载。
"""

import json
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

from ..config.settings import ConfigManager
from ..utils.logger import get_logger, performance_monitor, error_handler
from .types import FillResult
from .field_filler import FieldFiller
from src.utils.db_manager import node_state

@dataclass
class TemplateField:
    """模板字段"""
    name: str                           # 字段名称
    source: str                         # 数据源字段
    transform: Optional[str] = None     # 转换函数
    default_value: Optional[Any] = None # 默认值
    required: bool = False              # 是否必填
    validation: Optional[str] = None    # 验证规则


@dataclass
class FormTemplate:
    """表单模板"""
    id: str                             # 模板ID
    name: str                           # 模板名称
    description: str                    # 描述
    form_type: str                      # 表单类型
    fields: List[TemplateField]         # 字段列表
    metadata: Optional[Dict[str, Any]] = None  # 元数据
    version: str = "1.0"                # 版本


class TemplateFiller:
    """
    模板填写器
    
    主要功能:
    - 基于模板填写表单
    - 模板管理和存储
    - 动态模板加载
    - 模板验证和更新
    """
    
    def __init__(self, settings: ConfigManager):
        self.settings = settings
        self.logger = get_logger(__name__)
        self.field_filler = FieldFiller(settings)
        
        # 模板存储
        self.templates: Dict[str, FormTemplate] = {}
        
        # 模板目录
        self.template_dir = Path(settings.data_dir) / "templates"
        self.template_dir.mkdir(exist_ok=True)
        
        # 加载预定义模板
        self._load_builtin_templates()
        
        # 从文件加载模板
        self._load_templates_from_files()
        
        self.logger.info(f"{node_state}-=-填表员===TemplateFiller initialized with {len(self.templates)} templates")
    
    def _load_builtin_templates(self):
        """加载内置模板"""
        # 个人信息表模板
        personal_info_template = FormTemplate(
            id="personal_info",
            name="个人信息表",
            description="通用个人信息表单模板",
            form_type="personal_info",
            fields=[
                TemplateField(
                    name="姓名",
                    source="personal.name",
                    required=True
                ),
                TemplateField(
                    name="性别",
                    source="personal.gender",
                    transform="gender_mapping"
                ),
                TemplateField(
                    name="年龄",
                    source="personal.age",
                    transform="string_to_int"
                ),
                TemplateField(
                    name="出生日期",
                    source="personal.birthday",
                    transform="format_date"
                ),
                TemplateField(
                    name="身份证号",
                    source="personal.id_card",
                    validation="id_card_format"
                ),
                TemplateField(
                    name="联系电话",
                    source="contact.phone",
                    transform="format_phone",
                    required=True
                ),
                TemplateField(
                    name="电子邮箱",
                    source="contact.email",
                    validation="email_format"
                ),
                TemplateField(
                    name="联系地址",
                    source="contact.address",
                    transform="format_address"
                )
            ]
        )
        
        # 工作信息表模板
        work_info_template = FormTemplate(
            id="work_info",
            name="工作信息表",
            description="工作相关信息表单模板",
            form_type="work_info",
            fields=[
                TemplateField(
                    name="姓名",
                    source="personal.name",
                    required=True
                ),
                TemplateField(
                    name="公司名称",
                    source="work.company",
                    required=True
                ),
                TemplateField(
                    name="职位",
                    source="work.position"
                ),
                TemplateField(
                    name="部门",
                    source="work.department"
                ),
                TemplateField(
                    name="工作年限",
                    source="work.experience",
                    transform="string_to_int"
                ),
                TemplateField(
                    name="月薪",
                    source="work.salary",
                    transform="format_salary"
                ),
                TemplateField(
                    name="工作地址",
                    source="work.address",
                    transform="format_address"
                )
            ]
        )
        
        # 教育信息表模板
        education_info_template = FormTemplate(
            id="education_info",
            name="教育信息表",
            description="教育背景信息表单模板",
            form_type="education_info",
            fields=[
                TemplateField(
                    name="姓名",
                    source="personal.name",
                    required=True
                ),
                TemplateField(
                    name="学历",
                    source="education.degree",
                    transform="degree_mapping"
                ),
                TemplateField(
                    name="毕业院校",
                    source="education.school"
                ),
                TemplateField(
                    name="专业",
                    source="education.major"
                ),
                TemplateField(
                    name="毕业时间",
                    source="education.graduation_date",
                    transform="format_date"
                ),
                TemplateField(
                    name="在校成绩",
                    source="education.gpa",
                    transform="format_gpa"
                )
            ]
        )
        
        # 注册模板
        self.templates[personal_info_template.id] = personal_info_template
        self.templates[work_info_template.id] = work_info_template
        self.templates[education_info_template.id] = education_info_template
    
    def _load_templates_from_files(self):
        """从文件加载模板"""
        try:
            for template_file in self.template_dir.glob("*.json"):
                try:
                    with open(template_file, 'r', encoding='utf-8') as f:
                        template_data = json.load(f)
                    
                    template = self._parse_template(template_data)
                    self.templates[template.id] = template
                    
                    self.logger.debug(f"Loaded template from file: {template_file}")
                    
                except Exception as e:
                    self.logger.warning(f"Failed to load template from {template_file}: {str(e)}")
                    
        except Exception as e:
            self.logger.warning(f"Failed to load templates from files: {str(e)}")
    
    def _parse_template(self, template_data: Dict[str, Any]) -> FormTemplate:
        """解析模板数据"""
        fields = []
        for field_data in template_data.get('fields', []):
            field = TemplateField(**field_data)
            fields.append(field)
        
        return FormTemplate(
            id=template_data['id'],
            name=template_data['name'],
            description=template_data['description'],
            form_type=template_data['form_type'],
            fields=fields,
            metadata=template_data.get('metadata'),
            version=template_data.get('version', '1.0')
        )
    
    @performance_monitor
    @error_handler
    async def fill_with_template(self, template_id: str, 
                               form_info: Dict[str, Any],
                               user_info: Dict[str, Any]) -> FillResult:
        """
        使用模板填写表单
        
        Args:
            template_id: 模板ID
            form_info: 表单信息
            user_info: 用户信息
            
        Returns:
            填写结果
        """
        try:
            self.logger.info(f"{node_state}-=-填表员===Starting template fill with template: {template_id}")
            
            # 获取模板
            template = self.templates.get(template_id)
            if not template:
                raise ValueError(f"Template not found: {template_id}")
            
            # 执行模板填写
            filled_fields = {}
            skipped_fields = []
            failed_fields = []
            confidence_scores = {}
            warnings = []
            
            for template_field in template.fields:
                try:
                    # 提取源数据
                    source_value = self._extract_source_value(template_field.source, user_info)
                    
                    if source_value is None:
                        if template_field.required:
                            failed_fields.append(template_field.name)
                            warnings.append(f"Required field {template_field.name} has no source data")
                        else:
                            # 使用默认值
                            if template_field.default_value is not None:
                                filled_fields[template_field.name] = template_field.default_value
                                confidence_scores[template_field.name] = 0.5  # 默认值的置信度较低
                            else:
                                skipped_fields.append(template_field.name)
                                warnings.append(f"No source data for optional field {template_field.name}")
                        continue
                    
                    # 应用转换
                    transformed_value = await self._apply_transform(
                        source_value, template_field.transform
                    )
                    
                    # 验证值
                    if template_field.validation:
                        if not self._validate_value(transformed_value, template_field.validation):
                            failed_fields.append(template_field.name)
                            warnings.append(f"Validation failed for field {template_field.name}")
                            continue
                    
                    # 填写字段
                    filled_fields[template_field.name] = transformed_value
                    confidence_scores[template_field.name] = 0.9  # 模板填写的置信度较高
                    
                    self.logger.debug(f"Filled field {template_field.name}: {transformed_value}")
                    
                except Exception as e:
                    failed_fields.append(template_field.name)
                    warnings.append(f"Failed to fill field {template_field.name}: {str(e)}")
                    self.logger.warning(f"Template field fill failed: {str(e)}")
            
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
            
            self.logger.info(f"{node_state}-=-填表员===Template fill completed: {len(filled_fields)} filled, {len(skipped_fields)} skipped")
            return result
            
        except Exception as e:
            self.logger.error(f"Template fill failed: {str(e)}")
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
    
    def _extract_source_value(self, source: str, user_info: Dict[str, Any]) -> Any:
        """提取源数据值"""
        # 支持嵌套路径，如 'personal.name'
        if '.' in source:
            keys = source.split('.')
            value = user_info
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return None
            return value
        else:
            return user_info.get(source)
    
    async def _apply_transform(self, value: Any, transform: Optional[str]) -> Any:
        """应用转换函数"""
        if not transform or value is None:
            return value
        
        try:
            transforms = {
                'upper': lambda x: str(x).upper(),
                'lower': lambda x: str(x).lower(),
                'title': lambda x: str(x).title(),
                'strip': lambda x: str(x).strip(),
                'string_to_int': lambda x: int(str(x)) if str(x).isdigit() else x,
                'string_to_float': lambda x: float(str(x)) if self._is_float(str(x)) else x,
                'format_phone': self._transform_format_phone,
                'format_date': self._transform_format_date,
                'format_address': self._transform_format_address,
                'format_salary': self._transform_format_salary,
                'format_gpa': self._transform_format_gpa,
                'gender_mapping': self._transform_gender_mapping,
                'degree_mapping': self._transform_degree_mapping
            }
            
            if transform in transforms:
                return transforms[transform](value)
            else:
                self.logger.warning(f"Unknown transform function: {transform}")
                return value
                
        except Exception as e:
            self.logger.warning(f"Transform failed: {str(e)}")
            return value
    
    def _is_float(self, value: str) -> bool:
        """检查字符串是否为浮点数"""
        try:
            float(value)
            return True
        except ValueError:
            return False
    
    def _transform_format_phone(self, phone: str) -> str:
        """格式化电话号码"""
        digits = ''.join(filter(str.isdigit, str(phone)))
        if len(digits) == 11:
            return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
        elif len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        return str(phone)
    
    def _transform_format_date(self, date_value: Any) -> str:
        """格式化日期"""
        from datetime import datetime, date
        
        if isinstance(date_value, (date, datetime)):
            return date_value.strftime('%Y-%m-%d')
        elif isinstance(date_value, str):
            # 尝试解析日期字符串
            try:
                for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y']:
                    try:
                        dt = datetime.strptime(date_value, fmt)
                        return dt.strftime('%Y-%m-%d')
                    except ValueError:
                        continue
            except:
                pass
        
        return str(date_value)
    
    def _transform_format_address(self, address: str) -> str:
        """格式化地址"""
        address = str(address).strip()
        # 标准化地址格式
        replacements = {
            '省': '省 ',
            '市': '市 ',
            '区': '区 ',
            '县': '县 ',
            '街道': '街道 ',
            '号': '号 '
        }
        for old, new in replacements.items():
            address = address.replace(old, new)
        
        # 移除多余空格
        address = re.sub(r'\s+', ' ', address).strip()
        return address
    
    def _transform_format_salary(self, salary: Any) -> str:
        """格式化薪资"""
        try:
            # 提取数字
            if isinstance(salary, str):
                digits = ''.join(filter(str.isdigit, salary))
                if digits:
                    salary_num = int(digits)
                else:
                    return str(salary)
            else:
                salary_num = int(salary)
            
            # 格式化为千位分隔符
            return f"{salary_num:,}元"
            
        except (ValueError, TypeError):
            return str(salary)
    
    def _transform_format_gpa(self, gpa: Any) -> str:
        """格式化GPA"""
        try:
            gpa_float = float(gpa)
            return f"{gpa_float:.2f}"
        except (ValueError, TypeError):
            return str(gpa)
    
    def _transform_gender_mapping(self, gender: str) -> str:
        """性别映射"""
        gender_map = {
            'male': '男',
            'female': '女',
            'm': '男',
            'f': '女',
            '1': '男',
            '0': '女',
            'man': '男',
            'woman': '女'
        }
        
        gender_lower = str(gender).lower().strip()
        return gender_map.get(gender_lower, str(gender))
    
    def _transform_degree_mapping(self, degree: str) -> str:
        """学历映射"""
        degree_map = {
            'bachelor': '本科',
            'master': '硕士',
            'phd': '博士',
            'doctorate': '博士',
            'high_school': '高中',
            'junior_college': '专科',
            'undergraduate': '本科',
            'graduate': '研究生'
        }
        
        degree_lower = str(degree).lower().strip()
        return degree_map.get(degree_lower, str(degree))
    
    def _validate_value(self, value: Any, validation: str) -> bool:
        """验证值"""
        try:
            validators = {
                'email_format': self._validate_email,
                'phone_format': self._validate_phone,
                'id_card_format': self._validate_id_card,
                'date_format': self._validate_date,
                'number_format': self._validate_number,
                'not_empty': self._validate_not_empty
            }
            
            if validation in validators:
                return validators[validation](value)
            else:
                self.logger.warning(f"Unknown validation rule: {validation}")
                return True
                
        except Exception as e:
            self.logger.warning(f"Validation failed: {str(e)}")
            return False
    
    def _validate_email(self, value: str) -> bool:
        """验证邮箱格式"""
        pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return bool(re.match(pattern, str(value)))
    
    def _validate_phone(self, value: str) -> bool:
        """验证电话格式"""
        digits = ''.join(filter(str.isdigit, str(value)))
        return len(digits) in [10, 11]
    
    def _validate_id_card(self, value: str) -> bool:
        """验证身份证格式"""
        pattern = r'^\d{15}$|^\d{18}$'
        return bool(re.match(pattern, str(value).replace(' ', '').replace('-', '')))
    
    def _validate_date(self, value: str) -> bool:
        """验证日期格式"""
        pattern = r'\d{4}[-/]\d{1,2}[-/]\d{1,2}'
        return bool(re.match(pattern, str(value)))
    
    def _validate_number(self, value: Any) -> bool:
        """验证数字格式"""
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False
    
    def _validate_not_empty(self, value: Any) -> bool:
        """验证非空"""
        return value is not None and str(value).strip() != ''
    
    def save_template(self, template: FormTemplate):
        """保存模板到文件"""
        try:
            template_file = self.template_dir / f"{template.id}.json"
            template_data = asdict(template)
            
            with open(template_file, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, ensure_ascii=False, indent=2)
            
            # 更新内存中的模板
            self.templates[template.id] = template
            
            self.logger.info(f"{node_state}-=-填表员===Template saved: {template.id}")
            
        except Exception as e:
            self.logger.error(f"Failed to save template {template.id}: {str(e)}")
            raise
    
    def get_template(self, template_id: str) -> Optional[FormTemplate]:
        """获取模板"""
        return self.templates.get(template_id)
    
    def list_templates(self) -> List[FormTemplate]:
        """列出所有模板"""
        return list(self.templates.values())
    
    def delete_template(self, template_id: str):
        """删除模板"""
        if template_id in self.templates:
            del self.templates[template_id]
            
            # 删除文件
            template_file = self.template_dir / f"{template_id}.json"
            if template_file.exists():
                template_file.unlink()
            
            self.logger.info(f"{node_state}-=-填表员===Template deleted: {template_id}")
        else:
            raise ValueError(f"{node_state}-=-填表员===Template not found: {template_id}") 