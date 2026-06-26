"""
核心模块包

定义了系统的核心接口、基类和常量。
所有模块都应该遵循这里定义的接口规范。
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Union
from enum import Enum


class ProcessingStatus(Enum):
    """处理状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing" 
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InfoType(Enum):
    """信息类型枚举"""
    # 收集器类型
    SYSTEM = "system"
    USER = "user"
    ALL = "all"
    
    # 具体信息字段类型
    NAME = "name"
    PHONE = "phone"
    EMAIL = "email"
    ADDRESS = "address"
    ID_NUMBER = "id_number"
    BIRTHDAY = "birthday"
    GENDER = "gender"
    ORGANIZATION = "organization"
    POSITION = "position"
    EDUCATION = "education"
    OTHER = "other"


class DocumentType(Enum):
    """文档类型枚举"""
    PDF = "pdf"
    DOC = "doc"
    DOCX = "docx"
    XLS = "xls"
    XLSX = "xlsx"
    TXT = "txt"
    RTF = "rtf"
    IMAGE = "image"
    UNKNOWN = "unknown"


class BaseProcessor(ABC):
    """所有处理器的基类"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.status = ProcessingStatus.PENDING
    
    @abstractmethod
    def process(self, input_data: Any) -> Any:
        """处理输入数据并返回结果"""
        pass
    
    @abstractmethod
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性"""
        pass
    
    def get_status(self) -> ProcessingStatus:
        """获取当前处理状态"""
        return self.status


class BaseCollector(BaseProcessor):
    """信息收集器基类"""
    
    @abstractmethod
    def collect(self) -> Dict[str, Any]:
        """收集信息并返回结构化数据"""
        pass


class BaseParser(BaseProcessor):
    """文档解析器基类"""
    
    @abstractmethod
    def parse(self, file_path: str) -> Dict[str, Any]:
        """解析文档并提取信息"""
        pass
    
    @abstractmethod
    def get_supported_formats(self) -> List[DocumentType]:
        """返回支持的文档格式列表"""
        pass


class BaseAnalyzer(BaseProcessor):
    """分析器基类"""
    
    @abstractmethod
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """分析数据并返回分析结果"""
        pass


class BaseFiller(BaseProcessor):
    """填写器基类"""
    
    @abstractmethod
    def fill(self, form_data: Dict[str, Any], user_info: Dict[str, Any]) -> Dict[str, Any]:
        """填写表单并返回填写结果"""
        pass


class BaseValidator(BaseProcessor):
    """验证器基类"""
    
    @abstractmethod
    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """验证数据并返回验证结果"""
        pass


# 导出核心类和枚举
__all__ = [
    "ProcessingStatus",
    "InfoType", 
    "DocumentType",
    "BaseProcessor",
    "BaseCollector",
    "BaseParser", 
    "BaseAnalyzer",
    "BaseFiller",
    "BaseValidator"
] 