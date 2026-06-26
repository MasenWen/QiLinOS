"""
字段填写器

负责单个字段的智能填写，包括数据转换、格式化、验证等。
"""

import re
import json
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum

from ..config.settings import ConfigManager
from ..utils.logger import get_logger, performance_monitor, error_handler
from src.utils.db_manager import node_state

class FieldType(Enum):
    """字段类型"""
    TEXT = "text"
    NUMBER = "number" 
    DATE = "date"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    NAME = "name"
    ID_CARD = "id_card"
    BOOLEAN = "boolean"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"


@dataclass
class FieldSpec:
    """字段规格"""
    name: str
    field_type: FieldType
    required: bool = False
    max_length: Optional[int] = None
    min_length: Optional[int] = None
    pattern: Optional[str] = None
    options: Optional[List[str]] = None
    default_value: Optional[Any] = None
    format_rules: Optional[Dict[str, Any]] = None


class FieldFiller:
    """
    字段填写器
    
    主要功能:
    - 单个字段的智能填写
    - 数据类型转换和格式化
    - 字段验证和清理
    - 自定义填写规则
    """
    
    def __init__(self, settings: ConfigManager):
        self.settings = settings
        self.logger = get_logger(__name__)

        # 字段类型检测模式
        self.field_patterns = {
            FieldType.EMAIL: r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            FieldType.PHONE: r'(\+?\d{1,3}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}',
            FieldType.ID_CARD: r'\d{15}|\d{18}',
            FieldType.DATE: r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',
            FieldType.NUMBER: r'^-?\d+\.?\d*$'
        }
        
        # 常见字段名称映射
        self.field_name_mapping = {
            'name': ['姓名', '名字', '用户名', 'username', 'full_name', 'real_name'],
            'email': ['邮箱', '电子邮件', 'email', 'mail', 'e_mail'],
            'phone': ['电话', '手机', '联系电话', 'phone', 'mobile', 'tel'],
            'address': ['地址', '住址', '联系地址', 'address', 'location'],
            'age': ['年龄', 'age'],
            'gender': ['性别', 'gender', 'sex'],
            'birthday': ['生日', '出生日期', 'birthday', 'birth_date'],
            'id_card': ['身份证', '身份证号', 'id_card', 'identity_card']
        }
        
        self.logger.info(f"{node_state}-=-填表员===字段填充初始化成功")
    
    @performance_monitor
    @error_handler
    async def fill_field(self, field_name: str, user_field: str, 
                        user_info: Dict[str, Any], 
                        match_info: Dict[str, Any]) -> Any:
        """
        填写单个字段
        
        Args:
            field_name: 表单字段名
            user_field: 用户信息字段名
            user_info: 用户信息
            match_info: 匹配信息
            
        Returns:
            填写的值
        """
        try:
            # 获取原始值
            raw_value = self._extract_field_value(user_field, user_info)
            if raw_value is None:
                return None
            
            # 检测字段类型
            field_type = self._detect_field_type(field_name, raw_value, match_info)
            
            # 创建字段规格
            field_spec = self._create_field_spec(field_name, field_type, match_info)
            
            # 转换和格式化值
            formatted_value = await self._format_field_value(
                raw_value, field_spec, match_info
            )
            
            # 验证值
            if not self._validate_field_value(formatted_value, field_spec):
                self.logger.warning(f"Field value validation failed for {field_name}")
                return None
            
            self.logger.debug(f"Successfully filled field {field_name}: {formatted_value}")
            return formatted_value
            
        except Exception as e:
            self.logger.error(f"Failed to fill field {field_name}: {str(e)}")
            raise
    
    def _extract_field_value(self, user_field: str, user_info: Dict[str, Any]) -> Any:
        """从用户信息中提取字段值"""
        # 支持嵌套字段访问，如 'personal.name'
        if '.' in user_field:
            keys = user_field.split('.')
            value = user_info
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return None
            return value
        else:
            return user_info.get(user_field)
    
    def _detect_field_type(self, field_name: str, value: Any, 
                         match_info: Dict[str, Any]) -> FieldType:
        """检测字段类型"""
        # 首先从匹配信息中获取类型
        if 'field_type' in match_info:
            try:
                return FieldType(match_info['field_type'])
            except ValueError:
                pass
        
        # 根据字段名称推断类型
        field_name_lower = field_name.lower()
        for field_type, patterns in self.field_name_mapping.items():
            if any(pattern in field_name_lower for pattern in patterns):
                return self._get_field_type_by_name(field_type)
        
        # 根据值内容推断类型
        if isinstance(value, str):
            for field_type, pattern in self.field_patterns.items():
                if re.match(pattern, value):
                    return field_type
        
        # 根据Python类型推断
        if isinstance(value, bool):
            return FieldType.BOOLEAN
        elif isinstance(value, (int, float)):
            return FieldType.NUMBER
        elif isinstance(value, (date, datetime)):
            return FieldType.DATE
        
        # 默认为文本类型
        return FieldType.TEXT
    
    def _get_field_type_by_name(self, name: str) -> FieldType:
        """根据名称获取字段类型"""
        type_mapping = {
            'name': FieldType.NAME,
            'email': FieldType.EMAIL,
            'phone': FieldType.PHONE,
            'address': FieldType.ADDRESS,
            'age': FieldType.NUMBER,
            'gender': FieldType.SELECT,
            'birthday': FieldType.DATE,
            'id_card': FieldType.ID_CARD
        }
        return type_mapping.get(name, FieldType.TEXT)
    
    def _create_field_spec(self, field_name: str, field_type: FieldType, 
                         match_info: Dict[str, Any]) -> FieldSpec:
        """创建字段规格"""
        return FieldSpec(
            name=field_name,
            field_type=field_type,
            required=match_info.get('required', False),
            max_length=match_info.get('max_length'),
            min_length=match_info.get('min_length'),
            pattern=match_info.get('pattern'),
            options=match_info.get('options'),
            default_value=match_info.get('default_value'),
            format_rules=match_info.get('format_rules', {})
        )
    
    async def _format_field_value(self, value: Any, field_spec: FieldSpec, 
                                match_info: Dict[str, Any]) -> Any:
        """格式化字段值"""
        if value is None:
            return field_spec.default_value
        
        try:
            if field_spec.field_type == FieldType.TEXT:
                return self._format_text(value, field_spec)
            elif field_spec.field_type == FieldType.NAME:
                return self._format_name(value, field_spec)
            elif field_spec.field_type == FieldType.EMAIL:
                return self._format_email(value, field_spec)
            elif field_spec.field_type == FieldType.PHONE:
                return self._format_phone(value, field_spec)
            elif field_spec.field_type == FieldType.ADDRESS:
                return self._format_address(value, field_spec)
            elif field_spec.field_type == FieldType.DATE:
                return self._format_date(value, field_spec)
            elif field_spec.field_type == FieldType.NUMBER:
                return self._format_number(value, field_spec)
            elif field_spec.field_type == FieldType.ID_CARD:
                return self._format_id_card(value, field_spec)
            elif field_spec.field_type == FieldType.BOOLEAN:
                return self._format_boolean(value, field_spec)
            elif field_spec.field_type in [FieldType.SELECT, FieldType.RADIO]:
                return self._format_select(value, field_spec)
            else:
                return str(value)
                
        except Exception as e:
            self.logger.warning(f"Failed to format value {value}: {str(e)}")
            return str(value)
    
    def _format_text(self, value: Any, field_spec: FieldSpec) -> str:
        """格式化文本字段"""
        text = str(value).strip()
        
        # 应用长度限制
        if field_spec.max_length:
            text = text[:field_spec.max_length]
        
        return text
    
    def _format_name(self, value: Any, field_spec: FieldSpec) -> str:
        """格式化姓名字段"""
        name = str(value).strip()
        
        # 标准化姓名格式
        if field_spec.format_rules.get('capitalize', True):
            # 每个单词首字母大写
            name = ' '.join(word.capitalize() for word in name.split())
        
        return name
    
    def _format_email(self, value: Any, field_spec: FieldSpec) -> str:
        """格式化邮箱字段"""
        email = str(value).strip().lower()
        
        # 验证邮箱格式
        if not re.match(self.field_patterns[FieldType.EMAIL], email):
            raise ValueError(f"Invalid email format: {email}")
        
        return email
    
    def _format_phone(self, value: Any, field_spec: FieldSpec) -> str:
        """格式化电话号码字段"""
        phone = str(value).strip()
        
        # 移除所有非数字字符（除了+号）
        cleaned_phone = re.sub(r'[^\d+]', '', phone)
        
        # 根据格式规则格式化
        format_style = field_spec.format_rules.get('style', 'standard')
        
        if format_style == 'international' and not cleaned_phone.startswith('+'):
            cleaned_phone = '+86' + cleaned_phone
        elif format_style == 'dashed' and len(cleaned_phone) == 11:
            cleaned_phone = f"{cleaned_phone[:3]}-{cleaned_phone[3:7]}-{cleaned_phone[7:]}"
        
        return cleaned_phone
    
    def _format_address(self, value: Any, field_spec: FieldSpec) -> str:
        """格式化地址字段"""
        address = str(value).strip()
        
        # 标准化地址格式
        if field_spec.format_rules.get('standardize', True):
            # 替换常见的地址缩写
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
    
    def _format_date(self, value: Any, field_spec: FieldSpec) -> str:
        """格式化日期字段"""
        if isinstance(value, (date, datetime)):
            date_obj = value
        elif isinstance(value, str):
            # 尝试解析日期字符串
            try:
                # 尝试多种日期格式
                for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y']:
                    try:
                        date_obj = datetime.strptime(value, fmt).date()
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(f"Unable to parse date: {value}")
            except ValueError:
                raise ValueError(f"Invalid date format: {value}")
        else:
            raise ValueError(f"Invalid date type: {type(value)}")
        
        # 根据格式规则格式化
        format_str = field_spec.format_rules.get('format', '%Y-%m-%d')
        return date_obj.strftime(format_str)
    
    def _format_number(self, value: Any, field_spec: FieldSpec) -> Union[int, float, str]:
        """格式化数字字段"""
        try:
            if isinstance(value, str):
                # 移除千位分隔符
                cleaned = value.replace(',', '').replace(' ', '')
                if '.' in cleaned:
                    return float(cleaned)
                else:
                    return int(cleaned)
            elif isinstance(value, (int, float)):
                return value
            else:
                return float(value)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid number format: {value}")
    
    def _format_id_card(self, value: Any, field_spec: FieldSpec) -> str:
        """格式化身份证号字段"""
        id_card = str(value).strip().replace(' ', '').replace('-', '')
        
        # 验证身份证号格式
        if not re.match(r'^\d{15}$|^\d{18}$', id_card):
            raise ValueError(f"Invalid ID card format: {id_card}")
        
        # 根据格式规则格式化
        if field_spec.format_rules.get('with_spaces', False):
            if len(id_card) == 18:
                id_card = f"{id_card[:6]} {id_card[6:14]} {id_card[14:]}"
            elif len(id_card) == 15:
                id_card = f"{id_card[:6]} {id_card[6:12]} {id_card[12:]}"
        
        return id_card
    
    def _format_boolean(self, value: Any, field_spec: FieldSpec) -> bool:
        """格式化布尔字段"""
        if isinstance(value, bool):
            return value
        elif isinstance(value, str):
            return value.lower() in ['true', '1', 'yes', '是', '对', '正确']
        elif isinstance(value, (int, float)):
            return bool(value)
        else:
            return False
    
    def _format_select(self, value: Any, field_spec: FieldSpec) -> str:
        """格式化选择字段"""
        str_value = str(value).strip()
        
        # 如果有选项列表，尝试匹配
        if field_spec.options:
            # 精确匹配
            if str_value in field_spec.options:
                return str_value
            
            # 模糊匹配
            for option in field_spec.options:
                if str_value.lower() in option.lower() or option.lower() in str_value.lower():
                    return option
            
            # 如果没有匹配，返回第一个选项或原值
            if field_spec.format_rules.get('strict_match', False):
                return field_spec.options[0]
        
        return str_value
    
    def _validate_field_value(self, value: Any, field_spec: FieldSpec) -> bool:
        """验证字段值"""
        try:
            # 必填字段检查
            if field_spec.required and (value is None or value == ''):
                return False
            
            # 长度检查
            if isinstance(value, str):
                if field_spec.min_length and len(value) < field_spec.min_length:
                    return False
                if field_spec.max_length and len(value) > field_spec.max_length:
                    return False
            
            # 模式检查
            if field_spec.pattern and isinstance(value, str):
                if not re.match(field_spec.pattern, value):
                    return False
            
            # 选项检查
            if field_spec.options and value not in field_spec.options:
                # 对于严格模式，值必须在选项中
                if field_spec.format_rules.get('strict_match', False):
                    return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Field validation error: {str(e)}")
            return False 