"""
增强PDF解析器

专注于Qwen多模态解析方法：
1. Qwen多模态解析（使用AI模型识别PDF页面图像，准确率更高）
2. 文档节点化处理（为知识图谱优化）
3. 智能文档分类和实体提取

注意：使用Qwen2.5-VL多模态模型，提供最佳的PDF文本识别效果
"""

import io
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import hashlib
from datetime import datetime
from src.utils.db_manager import node_state
# 添加LightRAG路径
sys.path.append(str(Path(__file__).parent.parent.parent / "LightRAG-main"))

# 移除传统PDF解析库依赖
# 只保留增强的docling和OCR解析方法
HAS_PDF_LIBS = False
PyPDF2 = None
pdfplumber = None

# 使用Qwen多模态解析，移除其他依赖
HAS_DOCLING = False
DocumentConverter = None
HAS_OCR = False

try:
    # 导入Qwen PDF解析器
    from .qwen_pdf_parser import QwenPDFParser
    HAS_QWEN = True
except ImportError:
    QwenPDFParser = None
    HAS_QWEN = False

from ..core import BaseParser, DocumentType, ProcessingStatus
from ..config import get_settings
from ..utils.logger import get_logger, performance_monitor, error_handler


class EnhancedPDFParser(BaseParser):
    """增强PDF解析器"""
    
    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        self.settings = get_settings()
        
        # 检查可用的解析方法（只使用Qwen多模态）
        self.available_methods = []
        if HAS_QWEN:
            self.available_methods.append("qwen")
            # 初始化Qwen解析器
            self.qwen_parser = QwenPDFParser()
        else:
            raise ImportError("Qwen解析器未安装，请确保qwen_pdf_parser.py可用")
            
        self.logger.info(f"{node_state}-=-填表员===可用的PDF解析方法: {', '.join(self.available_methods)}")
        
        if not self.available_methods:
            raise ImportError("没有可用的PDF解析方法，请安装相关依赖")
    
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
        增强PDF解析
        
        Args:
            file_path: PDF文件路径
            
        Returns:
            解析结果字典，包含文档节点信息
        """
        self.logger.info(f"{node_state}-=-填表员===开始增强PDF解析: {file_path}")
        
        try:
            # 创建文档节点基础信息
            document_node = self._create_document_node(file_path)
            
            # 使用Qwen多模态解析方法
            content_results = []
            
            # Qwen多模态解析（处理所有PDF文档）
            if "qwen" in self.available_methods:
                try:
                    qwen_result = self.qwen_parser.parse(file_path)
                    if qwen_result and qwen_result.get('text_content'):
                        content_results.append(("qwen", qwen_result))
                        self.logger.info(f"{node_state}-=-填表员===Qwen多模态解析成功")
                except Exception as e:
                    self.logger.warning(f"{node_state}-=-填表员===Qwen多模态解析失败: {e}")
            
            # 合并解析结果
            if content_results:
                # 使用最佳解析结果
                best_method, best_result = content_results[0]
                document_node.update(best_result)
                document_node['parsing_method'] = best_method
                document_node['parsing_methods_tried'] = [method for method, _ in content_results]
                
                # 添加文档节点特有属性
                self._enhance_document_node(document_node, file_path)
                
                self.status = ProcessingStatus.SUCCESS
                self.logger.info(f"{node_state}-=-填表员===增强PDF解析完成: {file_path} (使用方法: {best_method})")
                
                return document_node
            else:
                raise Exception("所有解析方法都失败了")
                
        except Exception as e:
            self.status = ProcessingStatus.FAILED
            self.logger.error(f"增强PDF解析失败 {file_path}: {e}")
            raise
    
    def _create_document_node(self, file_path: Path) -> Dict[str, Any]:
        """创建文档节点基础信息"""
        file_stat = file_path.stat()
        
        # 计算文件哈希
        file_hash = self._calculate_file_hash(file_path)
        
        return {
            # 文档节点基础属性
            'node_type': 'Document',
            'document_id': file_hash,
            'file_path': str(file_path),
            'file_name': file_path.name,
            'file_stem': file_path.stem,
            'file_extension': file_path.suffix.lower(),
            'file_size': file_stat.st_size,
            'file_size_mb': round(file_stat.st_size / (1024 * 1024), 2),
            'creation_time': datetime.fromtimestamp(file_stat.st_ctime).isoformat(),
            'modification_time': datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
            'access_time': datetime.fromtimestamp(file_stat.st_atime).isoformat(),
            
            # 文档类型信息
            'document_type': DocumentType.PDF.value,
            'mime_type': 'application/pdf',
            
            # 解析相关信息
            'parsing_timestamp': datetime.now().isoformat(),
            'parsing_method': '',
            'parsing_methods_tried': [],
            
            # 内容信息（待填充）
            'text_content': '',
            'page_count': 0,
            'char_count': 0,
            'word_count': 0,
            'metadata': {},
            'pages': [],
            'tables': [],
            'images': [],
            'forms': [],
            
            # 文档质量评估
            'content_quality': 'unknown',
            'extraction_confidence': 0.0,
            'has_text': False,
            'has_images': False,
            'has_tables': False,
            'has_forms': False,
        }
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """计算文件哈希值作为唯一标识"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    # 所有解析方法现在都通过Qwen多模态解析器处理
    
    # 传统PDF解析方法已移除
    # 现在只使用docling和OCR两种增强解析方法
    
    def _enhance_document_node(self, document_node: Dict[str, Any], file_path: Path):
        """增强文档节点属性"""
        
        # 更新内容统计
        text_content = document_node.get('text_content', '')
        document_node['char_count'] = len(text_content)
        document_node['word_count'] = len(text_content.split())
        document_node['has_text'] = bool(text_content.strip())
        
        # 内容质量评估
        if document_node['char_count'] > 1000:
            if document_node.get('extraction_confidence', 0) > 0.8:
                document_node['content_quality'] = 'high'
            elif document_node.get('extraction_confidence', 0) > 0.6:
                document_node['content_quality'] = 'medium'
            else:
                document_node['content_quality'] = 'low'
        else:
            document_node['content_quality'] = 'poor'
        
        # 文档分类（基于内容特征）
        document_node['document_category'] = self._classify_document(text_content)
        
        # 提取关键信息
        document_node['key_entities'] = self._extract_key_entities(text_content)
        
        # 文档摘要（前200字符）
        document_node['content_preview'] = text_content[:200] + "..." if len(text_content) > 200 else text_content
        
        # 文档语言检测
        document_node['detected_language'] = self._detect_language(text_content)
        
        # 添加文档中心化的关键信息
        self._add_document_center_info(document_node, file_path, text_content)
    
    def _add_document_center_info(self, document_node: Dict[str, Any], file_path: Path, text_content: str):
        """添加文档作为中心节点的信息"""
        
        # 在文本内容前添加文档节点信息，让LightRAG识别文档作为实体
        document_entity_info = f"""
文档信息：
文档名称：{file_path.name}
文档类型：{document_node['document_category']}
文件大小：{document_node['file_size_mb']}MB
页数：{document_node['page_count']}页
创建时间：{document_node['creation_time']}
文件路径：{document_node['file_path']}
内容质量：{document_node['content_quality']}
解析方法：{document_node.get('parsing_method', 'unknown')}

文档内容：
{text_content}
"""
        
        # 更新文本内容，包含文档节点信息
        document_node['text_content'] = document_entity_info
        document_node['enhanced_for_kg'] = True
        
        # 为知识图谱准备的文档实体信息
        document_node['document_entity'] = {
            'entity_name': file_path.name,
            'entity_type': 'Document',
            'file_url': f"file://{document_node['file_path']}",
            'document_category': document_node['document_category'],
            'file_size_mb': document_node['file_size_mb'],
            'page_count': document_node['page_count'],
            'content_quality': document_node['content_quality'],
            'creation_time': document_node['creation_time'],
            'parsing_method': document_node.get('parsing_method', 'unknown'),
            'detected_language': document_node['detected_language'],
        }
    
    def _classify_document(self, text_content: str) -> str:
        """基于内容对文档进行分类"""
        text_lower = text_content.lower()
        
        # 简单的关键词分类
        if any(keyword in text_lower for keyword in ['简历', 'resume', '工作经历', '教育背景']):
            return 'resume'
        elif any(keyword in text_lower for keyword in ['合同', 'contract', '协议', 'agreement']):
            return 'contract'
        elif any(keyword in text_lower for keyword in ['报告', 'report', '分析', 'analysis']):
            return 'report'
        elif any(keyword in text_lower for keyword in ['申请', 'application', '表格', 'form']):
            return 'application'
        elif any(keyword in text_lower for keyword in ['发票', 'invoice', '收据', 'receipt']):
            return 'financial'
        else:
            return 'general'
    
    def _extract_key_entities(self, text_content: str) -> List[str]:
        """提取关键实体（简单版本）"""
        import re
        
        entities = []
        
        # 提取可能的姓名（中文姓名模式）
        chinese_names = re.findall(r'[\u4e00-\u9fff]{2,4}(?=\s|，|。|：)', text_content)
        entities.extend(chinese_names[:5])  # 最多5个
        
        # 提取电话号码
        phones = re.findall(r'1[3-9]\d{9}', text_content)
        entities.extend(phones[:3])  # 最多3个
        
        # 提取邮箱
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text_content)
        entities.extend(emails[:3])  # 最多3个
        
        return list(set(entities))  # 去重
    
    def _detect_language(self, text_content: str) -> str:
        """检测文档语言"""
        import re
        # 简单的语言检测
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text_content))
        english_chars = len(re.findall(r'[a-zA-Z]', text_content))
        
        if chinese_chars > english_chars:
            return 'chinese'
        elif english_chars > chinese_chars:
            return 'english'
        else:
            return 'mixed'
    
    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名"""
        return ['.pdf']
    
    def get_status(self) -> ProcessingStatus:
        """获取处理状态"""
        return self.status
