"""
文档解析器工厂

使用工厂模式和策略模式创建合适的文档解析器
"""

from pathlib import Path
from typing import Dict, Type, Optional

from ..core import BaseParser, DocumentType
from ..config import get_settings
from ..utils.logger import get_logger
from src.utils.db_manager import node_state

class DocumentParserFactory:
    """文档解析器工厂类"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.settings = get_settings()
        self._parsers: Dict[DocumentType, Type[BaseParser]] = {}
        self._register_parsers()
    
    def _register_parsers(self):
        """注册解析器"""
        try:
            from .pdf_parser import PDFParser
            from .doc_parser import DocParser
            from .excel_parser import ExcelParser
            from .text_parser import TextParser
            
            self._parsers = {
                DocumentType.PDF: PDFParser,
                DocumentType.DOC: DocParser,
                DocumentType.DOCX: DocParser,
                DocumentType.XLS: ExcelParser,
                DocumentType.XLSX: ExcelParser,
                DocumentType.TXT: TextParser,
                DocumentType.RTF: TextParser,
            }
            
            # print(f"注册了 {len(self._parsers)} 个文档解析器")
            
        except ImportError as e:
            self.logger.error(f"注册解析器失败: {e}")
            raise
    
    def create_parser(self, file_path: Path) -> Optional[BaseParser]:
        """
        根据文件路径创建合适的解析器
        
        Args:
            file_path: 文件路径
            
        Returns:
            解析器实例，如果不支持该格式则返回None
        """
        if not file_path.exists():
            self.logger.error(f"文件不存在: {file_path}")
            return None
        
        # 根据文件扩展名确定文档类型
        doc_type = self._get_document_type(file_path)
        
        if doc_type not in self._parsers:
            self.logger.warning(f"不支持的文档类型: {doc_type} ({file_path})")
            return None
        
        try:
            parser_class = self._parsers[doc_type]
            parser = parser_class()
            
            self.logger.info(f"{node_state}-=-填表员===创建解析器 {parser_class.__name__} 用于文件 {file_path}")
            return parser
            
        except Exception as e:
            self.logger.error(f"创建解析器失败: {e}")
            return None
    
    def create_parser_by_type(self, doc_type: DocumentType) -> Optional[BaseParser]:
        """
        根据文档类型创建解析器
        
        Args:
            doc_type: 文档类型
            
        Returns:
            解析器实例
        """
        if doc_type not in self._parsers:
            self.logger.warning(f"不支持的文档类型: {doc_type}")
            return None
        
        try:
            parser_class = self._parsers[doc_type]
            parser = parser_class()
            
            self.logger.info(f"{node_state}-=-填表员===创建解析器 {parser_class.__name__} 用于类型 {doc_type}")
            return parser
            
        except Exception as e:
            self.logger.error(f"创建解析器失败: {e}")
            return None
    
    def _get_document_type(self, file_path: Path) -> DocumentType:
        """根据文件扩展名确定文档类型"""
        suffix = file_path.suffix.lower()
        
        type_mapping = {
            '.pdf': DocumentType.PDF,
            '.doc': DocumentType.DOC,
            '.docx': DocumentType.DOCX,
            '.xls': DocumentType.XLS,
            '.xlsx': DocumentType.XLSX,
            '.txt': DocumentType.TXT,
            '.rtf': DocumentType.RTF,
        }
        
        return type_mapping.get(suffix, DocumentType.UNKNOWN)
    
    def get_supported_extensions(self) -> list[str]:
        """获取支持的文件扩展名列表"""
        extensions = []
        for doc_type in self._parsers.keys():
            if doc_type == DocumentType.PDF:
                extensions.append('.pdf')
            elif doc_type == DocumentType.DOC:
                extensions.append('.doc')
            elif doc_type == DocumentType.DOCX:
                extensions.append('.docx')
            elif doc_type == DocumentType.XLS:
                extensions.append('.xls')
            elif doc_type == DocumentType.XLSX:
                extensions.append('.xlsx')
            elif doc_type == DocumentType.TXT:
                extensions.append('.txt')
            elif doc_type == DocumentType.RTF:
                extensions.append('.rtf')
        
        return list(set(extensions))
    
    def is_supported(self, file_path: Path) -> bool:
        """检查文件格式是否支持"""
        doc_type = self._get_document_type(file_path)
        return doc_type in self._parsers 