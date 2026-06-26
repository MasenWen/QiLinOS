"""
文本文档解析器

解析纯文本文档内容，提取文本信息和表单字段
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import chardet
import re

from ..core import BaseParser, DocumentType, ProcessingStatus
from ..config import get_settings
from ..utils.logger import get_logger, performance_monitor, error_handler
from src.utils.db_manager import node_state

class TextParser(BaseParser):
    """文本文档解析器"""
    
    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        self.settings = get_settings()
    
    def get_supported_formats(self) -> List[DocumentType]:
        """返回支持的文档格式列表"""
        return [DocumentType.TXT, DocumentType.RTF]
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性"""
        if isinstance(input_data, (str, Path)):
            file_path = Path(input_data)
            return (file_path.exists() and 
                    file_path.suffix.lower() in ['.txt', '.rtf', '.text'])
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
        解析文本文档
        
        Args:
            file_path: 文本文件路径
            
        Returns:
            解析结果字典
        """

        self.logger.info(f"{node_state}-=-文档处理员===开始解析文本文档: {file_path}")
        
        try:
            result = {
                'file_path': str(file_path),
                'file_size': file_path.stat().st_size,
                'document_type': self._get_text_type(file_path).value,
                'metadata': {},
                'text_content': '',
                'lines': [],
                'paragraphs': [],
                'forms': [],
                'statistics': {},
            }
            
            # 检测文件编码
            encoding = self._detect_encoding(file_path)
            result['metadata']['encoding'] = encoding
            
            # 读取文件内容
            content = self._read_file_content(file_path, encoding)
            result['text_content'] = content
            
            # 分析文本结构
            self._analyze_text_structure(content, result)
            
            # 检测表单字段
            self._detect_form_fields(content, result)
            
            # 生成统计信息
            self._generate_statistics(content, result)
            
            self.status = ProcessingStatus.SUCCESS
            self.logger.info(f"{node_state}-=-文档处理员===文本文档解析完成: {file_path}")
            
            return result
            
        except Exception as e:
            self.status = ProcessingStatus.FAILED
            self.logger.error(f"文本文档解析失败 {file_path}: {e}")
            raise
    
    def _detect_encoding(self, file_path: Path) -> str:
        """检测文件编码"""
        try:
            with open(file_path, 'rb') as f:
                # 读取前1KB用于编码检测
                raw_data = f.read(1024)
                
            result = chardet.detect(raw_data)
            encoding = result['encoding']
            confidence = result['confidence']
            

            self.logger.info(f"{node_state}-=-文档处理员===检测到文件编码: {encoding} (置信度: {confidence:.2f})")
            
            # 如果置信度太低，使用默认编码
            if confidence < 0.7:
                encoding = 'utf-8'
                self.logger.warning(f"编码检测置信度较低，使用默认编码: {encoding}")
            
            return encoding
            
        except Exception as e:
            self.logger.warning(f"编码检测失败，使用默认编码 utf-8: {e}")
            return 'utf-8'
    
    def _read_file_content(self, file_path: Path, encoding: str) -> str:
        """读取文件内容"""
        try:
            with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                content = f.read()
            return content
            
        except UnicodeDecodeError:
            # 如果指定编码失败，尝试其他常见编码
            fallback_encodings = ['utf-8', 'gbk', 'gb2312', 'ascii', 'latin-1']
            
            for fallback_encoding in fallback_encodings:
                if fallback_encoding == encoding:
                    continue
                    
                try:
                    with open(file_path, 'r', encoding=fallback_encoding, errors='ignore') as f:
                        content = f.read()
                    self.logger.info(f"{node_state}-=-文档处理员===使用备用编码 {fallback_encoding} 成功读取文件")
                    return content
                except:
                    continue
            
            # 如果所有编码都失败，使用二进制模式读取
            self.logger.warning("所有编码都失败，使用二进制模式读取")
            with open(file_path, 'rb') as f:
                raw_content = f.read()
            return raw_content.decode('utf-8', errors='replace')
    
    def _analyze_text_structure(self, content: str, result: Dict[str, Any]):
        """分析文本结构"""
        try:
            # 按行分割
            lines = content.split('\n')
            result['lines'] = [
                {
                    'line_number': i + 1,
                    'content': line,
                    'char_count': len(line),
                    'is_empty': line.strip() == '',
                }
                for i, line in enumerate(lines)
            ]
            
            # 按段落分割（以空行为分隔符）
            paragraphs = []
            current_paragraph = []
            
            for line in lines:
                if line.strip() == '':
                    if current_paragraph:
                        paragraph_text = '\n'.join(current_paragraph)
                        paragraphs.append({
                            'text': paragraph_text,
                            'line_count': len(current_paragraph),
                            'char_count': len(paragraph_text),
                        })
                        current_paragraph = []
                else:
                    current_paragraph.append(line)
            
            # 处理最后一个段落
            if current_paragraph:
                paragraph_text = '\n'.join(current_paragraph)
                paragraphs.append({
                    'text': paragraph_text,
                    'line_count': len(current_paragraph),
                    'char_count': len(paragraph_text),
                })
            
            result['paragraphs'] = paragraphs
            
        except Exception as e:
            self.logger.warning(f"分析文本结构失败: {e}")
    
    def _detect_form_fields(self, content: str, result: Dict[str, Any]):
        """检测文本中的表单字段"""
        form_fields = []
        
        try:
            patterns = self._detect_form_patterns(content)
            
            for pattern in patterns:
                form_field = {
                    'type': pattern['type'],
                    'label': pattern['matched_text'],
                    'position': pattern['position'],
                    'line_number': self._get_line_number(content, pattern['position'][0]),
                    'required': False,
                    'value': '',
                }
                form_fields.append(form_field)
            
            result['forms'] = form_fields
            
        except Exception as e:
            self.logger.warning(f"检测表单字段失败: {e}")
    
    def _detect_form_patterns(self, text: str) -> List[Dict[str, Any]]:
        """检测文本中的表单模式"""
        patterns = []
        
        # 表单字段模式（更详细的匹配）
        field_patterns = {
            'name': [
                r'姓名[：:]\s*[_\s\-]*',
                r'Name[：:]\s*[_\s\-]*',
                r'名称[：:]\s*[_\s\-]*',
                r'真实姓名[：:]\s*[_\s\-]*',
            ],
            'id_card': [
                r'身份证号[码]?[：:]\s*[_\s\-]*',
                r'ID[：:]\s*[_\s\-]*',
                r'证件号码[：:]\s*[_\s\-]*',
                r'身份证[：:]\s*[_\s\-]*',
            ],
            'phone': [
                r'电话[号码]?[：:]\s*[_\s\-]*',
                r'手机[号码]?[：:]\s*[_\s\-]*',
                r'Phone[：:]\s*[_\s\-]*',
                r'联系电话[：:]\s*[_\s\-]*',
                r'移动电话[：:]\s*[_\s\-]*',
            ],
            'email': [
                r'邮箱[：:]\s*[_\s\-]*',
                r'Email[：:]\s*[_\s\-]*',
                r'电子邮件[：:]\s*[_\s\-]*',
                r'电子邮箱[：:]\s*[_\s\-]*',
            ],
            'address': [
                r'地址[：:]\s*[_\s\-]*',
                r'Address[：:]\s*[_\s\-]*',
                r'住址[：:]\s*[_\s\-]*',
                r'家庭住址[：:]\s*[_\s\-]*',
                r'联系地址[：:]\s*[_\s\-]*',
            ],
            'date': [
                r'日期[：:]\s*[_\s\-]*',
                r'Date[：:]\s*[_\s\-]*',
                r'时间[：:]\s*[_\s\-]*',
                r'出生日期[：:]\s*[_\s\-]*',
                r'生日[：:]\s*[_\s\-]*',
            ],
            'gender': [
                r'性别[：:]\s*[_\s\-]*',
                r'Gender[：:]\s*[_\s\-]*',
            ],
            'company': [
                r'公司[：:]\s*[_\s\-]*',
                r'Company[：:]\s*[_\s\-]*',
                r'工作单位[：:]\s*[_\s\-]*',
                r'单位[：:]\s*[_\s\-]*',
            ],
            'position': [
                r'职位[：:]\s*[_\s\-]*',
                r'Position[：:]\s*[_\s\-]*',
                r'职务[：:]\s*[_\s\-]*',
                r'岗位[：:]\s*[_\s\-]*',
            ],
            'education': [
                r'学历[：:]\s*[_\s\-]*',
                r'Education[：:]\s*[_\s\-]*',
                r'文化程度[：:]\s*[_\s\-]*',
            ],
            'school': [
                r'学校[：:]\s*[_\s\-]*',
                r'School[：:]\s*[_\s\-]*',
                r'毕业院校[：:]\s*[_\s\-]*',
            ],
            'signature': [
                r'签名[：:]\s*[_\s\-]*',
                r'Signature[：:]\s*[_\s\-]*',
                r'本人签字[：:]\s*[_\s\-]*',
            ],
        }
        
        for field_type, type_patterns in field_patterns.items():
            for pattern in type_patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    patterns.append({
                        'type': field_type,
                        'pattern': pattern,
                        'position': match.span(),
                        'matched_text': match.group().strip(),
                    })
        
        return patterns
    
    def _get_line_number(self, text: str, position: int) -> int:
        """根据字符位置获取行号"""
        try:
            return text[:position].count('\n') + 1
        except:
            return 1
    
    def _generate_statistics(self, content: str, result: Dict[str, Any]):
        """生成文本统计信息"""
        try:
            # 基本统计
            char_count = len(content)
            line_count = content.count('\n') + 1
            word_count = len(content.split())
            
            # 中文字符统计
            chinese_char_count = len(re.findall(r'[\u4e00-\u9fff]', content))
            
            # 英文字符统计
            english_char_count = len(re.findall(r'[a-zA-Z]', content))
            
            # 数字统计
            digit_count = len(re.findall(r'\d', content))
            
            # 空行统计
            empty_lines = content.count('\n\n') + content.count('\r\n\r\n')
            
            # 段落统计
            paragraph_count = len(result.get('paragraphs', []))
            
            statistics = {
                'total_characters': char_count,
                'total_lines': line_count,
                'total_words': word_count,
                'chinese_characters': chinese_char_count,
                'english_characters': english_char_count,
                'digits': digit_count,
                'empty_lines': empty_lines,
                'paragraphs': paragraph_count,
                'form_fields': len(result.get('forms', [])),
            }
            
            # 计算平均值
            if paragraph_count > 0:
                statistics['avg_chars_per_paragraph'] = char_count / paragraph_count
                statistics['avg_lines_per_paragraph'] = line_count / paragraph_count
            
            if line_count > 0:
                statistics['avg_chars_per_line'] = char_count / line_count
                statistics['avg_words_per_line'] = word_count / line_count
            
            result['statistics'] = statistics
            
        except Exception as e:
            self.logger.warning(f"生成统计信息失败: {e}")
    
    def _get_text_type(self, file_path: Path) -> DocumentType:
        """根据文件扩展名确定文本类型"""
        suffix = file_path.suffix.lower()
        if suffix == '.txt':
            return DocumentType.TXT
        elif suffix == '.rtf':
            return DocumentType.RTF
        else:
            return DocumentType.TXT  # 默认为TXT
    
    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名"""
        return ['.txt', '.rtf']
    
    def get_status(self) -> ProcessingStatus:
        """获取处理状态"""
        return self.status 