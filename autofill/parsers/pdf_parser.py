"""
PDF文档解析器

解析PDF文档内容，提取文本、表格、表单字段等信息
"""

import io
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import PyPDF2
    import pdfplumber
    HAS_PDF_LIBS = True
except ImportError:
    PyPDF2 = None
    pdfplumber = None
    HAS_PDF_LIBS = False

from ..core import BaseParser, DocumentType, ProcessingStatus
from ..config import get_settings
from ..utils.logger import get_logger, performance_monitor, error_handler
from src.utils.db_manager import node_state

class PDFParser(BaseParser):
    """PDF文档解析器"""
    
    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        self.settings = get_settings()
        
        if not HAS_PDF_LIBS:
            self.logger.error("PDF解析库未安装，请安装 PyPDF2 和 pdfplumber")
            raise ImportError("PDF解析库未安装")
    
    def get_supported_formats(self) -> List[DocumentType]:
        """返回支持的文档格式列表"""
        return [DocumentType.PDF]
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性"""
        if isinstance(input_data, (str, Path)):
            file_path = Path(input_data)
            return file_path.exists() and file_path.suffix.lower() == '.pdf'
        return False
    
    def process(self, input_data: Any) -> Any:
        """处理输入数据并返回结果"""
        if isinstance(input_data, (str, Path)):
            return self.parse(Path(input_data))
        else:
            raise ValueError(f"不支持的输入类型: {type(input_data)}")
    
    @error_handler()
    @performance_monitor()
    def parse(self, file_path: Path) -> Dict[str, Any]:
        """
        解析PDF文档
        
        Args:
            file_path: PDF文件路径
            
        Returns:
            解析结果字典
        """
        self.logger.info(f"{node_state}-=-填表员===开始解析PDF文档: {file_path}")
        
        try:
            if not HAS_PDF_LIBS:
                raise ImportError("PDF处理库未安装，请安装 PyPDF2 和 pdfplumber")
            
            result = {
                'file_path': str(file_path),
                'file_size': file_path.stat().st_size,
                'document_type': DocumentType.PDF.value,
                'metadata': {},
                'pages': [],
                'text_content': '',
                'tables': [],
                'forms': [],
                'images': [],
            }
            
            # 使用PyPDF2解析基本信息和元数据
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                # 获取文档元数据
                result['metadata'] = self._extract_metadata(pdf_reader)
                result['page_count'] = len(pdf_reader.pages)
                
                # 使用PyPDF2提取文本
                for page_num, page in enumerate(pdf_reader.pages):
                    try:
                        page_text = page.extract_text()
                        result['pages'].append({
                            'page_number': page_num + 1,
                            'text': page_text,
                            'char_count': len(page_text),
                        })
                        result['text_content'] += page_text + '\n'
                    except Exception as e:
                        self.logger.warning(f"提取第{page_num + 1}页文本失败: {e}")
            
            # 使用pdfplumber提取表格和更精确的内容
            self._extract_with_pdfplumber(file_path, result)
            
            # 检测表单字段
            self._extract_form_fields(file_path, result)
            
            self.status = ProcessingStatus.SUCCESS
            self.logger.info(f"{node_state}-=-填表员===PDF解析完成: {file_path}")
            
            return result
            
        except Exception as e:
            self.status = ProcessingStatus.FAILED
            self.logger.error(f"PDF解析失败 {file_path}: {e}")
            raise
    
    def _extract_metadata(self, pdf_reader: "PyPDF2.PdfReader") -> Dict[str, Any]:
        """提取PDF元数据"""
        metadata = {}
        
        try:
            if pdf_reader.metadata:
                doc_info = pdf_reader.metadata
                metadata = {
                    'title': doc_info.get('/Title', ''),
                    'author': doc_info.get('/Author', ''),
                    'subject': doc_info.get('/Subject', ''),
                    'creator': doc_info.get('/Creator', ''),
                    'producer': doc_info.get('/Producer', ''),
                    'creation_date': str(doc_info.get('/CreationDate', '')),
                    'modification_date': str(doc_info.get('/ModDate', '')),
                }
                
                # 清理空值
                metadata = {k: v for k, v in metadata.items() if v}
                
        except Exception as e:
            self.logger.warning(f"提取PDF元数据失败: {e}")
        
        return metadata
    
    def _extract_with_pdfplumber(self, file_path: Path, result: Dict[str, Any]):
        """使用pdfplumber提取更精确的内容"""
        try:
            with pdfplumber.open(file_path) as pdf:
                # 提取表格
                for page_num, page in enumerate(pdf.pages):
                    try:
                        # 提取表格
                        tables = page.extract_tables()
                        for table_idx, table in enumerate(tables):
                            if table and len(table) > 0:
                                result['tables'].append({
                                    'page_number': page_num + 1,
                                    'table_index': table_idx,
                                    'rows': len(table),
                                    'columns': len(table[0]) if table[0] else 0,
                                    'data': table,
                                })
                        
                        # 更新页面信息
                        if page_num < len(result['pages']):
                            page_info = result['pages'][page_num]
                            
                            # 获取页面尺寸
                            page_info['width'] = page.width
                            page_info['height'] = page.height
                            
                            # 获取文本位置信息
                            chars = page.chars
                            page_info['char_positions'] = len(chars)
                            
                            # 检测可能的表单字段（基于文本模式）
                            text = page_info['text']
                            form_patterns = self._detect_form_patterns(text)
                            if form_patterns:
                                page_info['form_patterns'] = form_patterns
                                
                    except Exception as e:
                        self.logger.warning(f"pdfplumber处理第{page_num + 1}页失败: {e}")
                        
        except Exception as e:
            self.logger.warning(f"使用pdfplumber处理PDF失败: {e}")
    
    def _extract_form_fields(self, file_path: Path, result: Dict[str, Any]):
        """提取PDF表单字段"""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                # 检查是否有表单字段
                root = pdf_reader.trailer.get('/Root', {})
                
                # 如果root本身是IndirectObject，需要解引用
                if hasattr(root, 'get_object'):
                    root = root.get_object()
                
                if '/AcroForm' in root:
                    form = root['/AcroForm']
                    
                    # 如果form本身是IndirectObject，需要解引用
                    if hasattr(form, 'get_object'):
                        form = form.get_object()
                    
                    if '/Fields' in form:
                        fields = form['/Fields']
                        
                        # 如果fields是IndirectObject，需要解引用
                        if hasattr(fields, 'get_object'):
                            fields = fields.get_object()
                        
                        # 确保fields是可迭代的
                        if hasattr(fields, '__iter__') and not isinstance(fields, str):
                            for field in fields:
                                try:
                                    field_obj = field.get_object() if hasattr(field, 'get_object') else field
                                    field_info = self._parse_form_field(field_obj)
                                    if field_info:
                                        result['forms'].append(field_info)
                                except Exception as field_error:
                                    self.logger.warning(f"解析单个表单字段失败: {field_error}")
                        else:
                            self.logger.debug("PDF表单字段不是可迭代类型或为空")
                
        except Exception as e:
            self.logger.warning(f"提取PDF表单字段失败: {e}")
    
    def _parse_form_field(self, field_obj: Any) -> Optional[Dict[str, Any]]:
        """解析单个表单字段"""
        try:
            # 确保field_obj已经被解引用
            if hasattr(field_obj, 'get_object'):
                field_obj = field_obj.get_object()
            
            field_info = {
                'type': 'unknown',
                'name': '',
                'value': '',
                'options': [],
                'required': False,
                'readonly': False,
            }
            
            # 字段名称
            try:
                if hasattr(field_obj, '__contains__') and '/T' in field_obj:
                    name_obj = field_obj['/T']
                    if hasattr(name_obj, 'get_object'):
                        name_obj = name_obj.get_object()
                    field_info['name'] = str(name_obj)
            except Exception as name_error:
                self.logger.debug(f"解析字段名称失败: {name_error}")
                field_info['name'] = ''
            
            # 字段值
            try:
                if hasattr(field_obj, '__contains__') and '/V' in field_obj:
                    value_obj = field_obj['/V']
                    if hasattr(value_obj, 'get_object'):
                        value_obj = value_obj.get_object()
                    field_info['value'] = str(value_obj)
            except Exception as value_error:
                self.logger.debug(f"解析字段值失败: {value_error}")
                field_info['value'] = ''
            
            # 字段类型
            try:
                if hasattr(field_obj, '__contains__') and '/FT' in field_obj:
                    type_obj = field_obj['/FT']
                    if hasattr(type_obj, 'get_object'):
                        type_obj = type_obj.get_object()
                    field_type = str(type_obj)
                    type_mapping = {
                        '/Tx': 'text',
                        '/Ch': 'choice',
                        '/Btn': 'button',
                        '/Sig': 'signature',
                    }
                    field_info['type'] = type_mapping.get(field_type, 'unknown')
            except Exception as type_error:
                self.logger.debug(f"解析字段类型失败: {type_error}")
                field_info['type'] = 'unknown'
            
            # 字段标志
            try:
                if hasattr(field_obj, '__contains__') and '/Ff' in field_obj:
                    flags_obj = field_obj['/Ff']
                    if hasattr(flags_obj, 'get_object'):
                        flags_obj = flags_obj.get_object()
                    flags = int(flags_obj)
                    field_info['required'] = bool(flags & 2)
                    field_info['readonly'] = bool(flags & 1)
            except Exception as flags_error:
                self.logger.debug(f"解析字段标志失败: {flags_error}")
                field_info['required'] = False
                field_info['readonly'] = False
            
            # 选择字段的选项
            try:
                if hasattr(field_obj, '__contains__') and '/Opt' in field_obj:
                    opt_obj = field_obj['/Opt']
                    # 如果是IndirectObject，需要先解引用
                    if hasattr(opt_obj, 'get_object'):
                        opt_obj = opt_obj.get_object()
                    
                    # 确保opt_obj是可迭代的
                    if hasattr(opt_obj, '__iter__') and not isinstance(opt_obj, str):
                        options = []
                        for opt in opt_obj:
                            try:
                                # 每个选项也可能是IndirectObject
                                if hasattr(opt, 'get_object'):
                                    opt = opt.get_object()
                                options.append(str(opt))
                            except Exception as single_opt_error:
                                self.logger.debug(f"解析单个选项失败: {single_opt_error}")
                                options.append(str(opt))
                        field_info['options'] = options
                    else:
                        # 如果不是可迭代的，将其作为单一选项
                        field_info['options'] = [str(opt_obj)]
            except Exception as opt_error:
                self.logger.debug(f"解析选项字段失败: {opt_error}")
                field_info['options'] = []
            
            return field_info
            
        except Exception as e:
            self.logger.warning(f"解析表单字段失败: {e}")
            return None
    
    def _detect_form_patterns(self, text: str) -> List[Dict[str, Any]]:
        """检测文本中的表单模式"""
        patterns = []
        
        # 常见表单字段模式
        import re
        
        # 姓名字段
        name_patterns = [
            r'姓名[：:]\s*[_\s]*',
            r'Name[：:]\s*[_\s]*',
            r'名称[：:]\s*[_\s]*',
        ]
        
        # 身份证号字段
        id_patterns = [
            r'身份证号[：:]\s*[_\s]*',
            r'ID[：:]\s*[_\s]*',
            r'证件号码[：:]\s*[_\s]*',
        ]
        
        # 电话字段
        phone_patterns = [
            r'电话[：:]\s*[_\s]*',
            r'手机[：:]\s*[_\s]*',
            r'Phone[：:]\s*[_\s]*',
        ]
        
        # 邮箱字段
        email_patterns = [
            r'邮箱[：:]\s*[_\s]*',
            r'Email[：:]\s*[_\s]*',
            r'电子邮件[：:]\s*[_\s]*',
        ]
        
        pattern_groups = [
            ('name', name_patterns),
            ('id_card', id_patterns),
            ('phone', phone_patterns),
            ('email', email_patterns),
        ]
        
        for field_type, type_patterns in pattern_groups:
            for pattern in type_patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    patterns.append({
                        'type': field_type,
                        'pattern': pattern,
                        'position': match.span(),
                        'matched_text': match.group(),
                    })
        
        return patterns
    
    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名"""
        return ['.pdf']
    
    def get_status(self) -> ProcessingStatus:
        """获取处理状态"""
        return self.status 