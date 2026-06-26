"""
Qwen多模态PDF解析器

使用PyMuPDF将PDF转换为图像，然后使用Qwen2.5-VL多模态模型进行文本识别
- 无需外部依赖（如poppler）
- 纯Python解决方案
- 高精度AI识别
"""

import os
import sys
import requests
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional
import hashlib
from datetime import datetime

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    fitz = None
    HAS_PYMUPDF = False

from ..core import BaseParser, DocumentType, ProcessingStatus
from ..config import get_settings
from ..utils.logger import get_logger, performance_monitor, error_handler


class QwenPDFParser(BaseParser):
    """基于Qwen多模态模型的PDF解析器"""
    
    def __init__(self, api_url: Optional[str] = None):
        super().__init__()
        self.logger = get_logger(__name__)
        self.settings = get_settings()
        
        # 如果没有指定API URL，尝试从配置文件获取
        if api_url is None:
            try:
                import sys
                from pathlib import Path
                sys.path.append(str(Path(__file__).parent.parent.parent))
                # from api_config import get_api_url
                # self.api_url = get_api_url().rstrip('/')
                self.api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
                self.logger.info(f"{node_state}-=-填表员===使用配置文件中的API地址: {self.api_url}")
            except ImportError:
                self.api_url = "http://localhost:6666"
                self.logger.info("使用默认API地址: http://localhost:6666")
        else:
            self.api_url = api_url.rstrip('/')
        
        # 检查依赖
        if not HAS_PYMUPDF:
            raise ImportError("PyMuPDF未安装，请安装: pip install PyMuPDF")
        
        # 测试API连接
        self._test_api_connection()
        
        self.logger.info("Qwen PDF解析器初始化成功")
    
    def _test_api_connection(self):
        """测试API连接"""
        try:
            response = requests.get(f"{self.api_url}/health", timeout=5)
            if response.status_code == 200:
                self.logger.info("Qwen API连接正常")
            else:
                self.logger.warning(f"Qwen API响应异常: {response.status_code}")
        except Exception as e:
            self.logger.warning(f"无法连接到Qwen API: {e}")
    
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
        使用Qwen多模态模型解析PDF
        
        Args:
            file_path: PDF文件路径
            
        Returns:
            解析结果字典，包含文档节点信息
        """
        self.logger.info(f"{node_state}-=-填表员===开始Qwen PDF解析: {file_path}")
        
        try:
            # 创建文档节点基础信息
            document_node = self._create_document_node(file_path)
            
            # 使用PyMuPDF将PDF转换为图像
            images_info = self._pdf_to_images_with_pymupdf(file_path)
            if not images_info:
                raise Exception("PDF转换为图像失败")
            
            self.logger.info(f"{node_state}-=-填表员===PDF转换为 {len(images_info)} 页图像")
            
            # 使用Qwen模型识别每页内容
            pages_content = []
            all_text = []
            
            for image_info in images_info:
                page_num = image_info['page_num']
                image_path = image_info['image_path']
                
                try:
                    # 使用图像文件路径分析
                    page_text = self._analyze_page_with_qwen_file(image_path, page_num)
                    
                    pages_content.append({
                        'page_number': page_num,
                        'text': page_text,
                        'char_count': len(page_text),
                        'confidence': 'high',  # Qwen模型通常质量较高
                    })
                    all_text.append(page_text)
                    self.logger.info(f"{node_state}-=-填表员===第{page_num}页解析完成，字符数: {len(page_text)}")
                    
                except Exception as e:
                    self.logger.warning(f"第{page_num}页解析失败: {e}")
                    pages_content.append({
                        'page_number': page_num,
                        'text': '',
                        'char_count': 0,
                        'confidence': 'failed',
                    })
                finally:
                    # 清理临时文件
                    if image_path and os.path.exists(image_path):
                        try:
                            os.unlink(image_path)
                        except:
                            pass
            
            # 合并所有页面文本
            full_text = '\n\n'.join(all_text)
            
            # 更新文档节点
            document_node.update({
                'text_content': full_text,
                'page_count': len(images_info),
                'char_count': len(full_text),
                'word_count': len(full_text.split()),
                'pages': pages_content,
                'has_text': bool(full_text.strip()),
                'extraction_confidence': 0.9,  # Qwen模型置信度高
                'content_quality': 'high',
                'parsing_method': 'qwen_multimodal',
            })
            
            # 增强文档节点属性
            self._enhance_document_node(document_node, file_path)
            
            self.status = ProcessingStatus.SUCCESS
            self.logger.info(f"{node_state}-=-填表员===Qwen PDF解析完成: {file_path}")
            
            return document_node
            
        except Exception as e:
            self.status = ProcessingStatus.FAILED
            self.logger.error(f"Qwen PDF解析失败 {file_path}: {e}")
            raise
    
    # 移除pdf2image相关方法，专门使用PyMuPDF
    
    # 移除poppler相关方法，专门使用PyMuPDF
    
    def _pdf_to_images_with_pymupdf(self, file_path: Path) -> List[Dict[str, Any]]:
        """使用PyMuPDF将PDF转换为图像"""
        try:
            import io
            from PIL import Image
            
            # 打开PDF文档
            doc = fitz.open(file_path)
            images_info = []
            
            # 转换每一页为图像
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                
                # 设置缩放矩阵以提高分辨率
                mat = fitz.Matrix(2.0, 2.0)  # 2倍缩放，相当于200 DPI
                
                # 渲染页面为图像
                pix = page.get_pixmap(matrix=mat)
                
                # 转换为PIL图像
                img_data = pix.tobytes("png")
                pil_image = Image.open(io.BytesIO(img_data))
                
                # 保存到临时文件
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                    pil_image.save(temp_file.name, 'PNG')
                    
                    images_info.append({
                        'page_num': page_num + 1,
                        'image': None,  # 不保存PIL对象，使用文件路径
                        'image_path': temp_file.name
                    })
            
            doc.close()
            self.logger.info(f"{node_state}-=-填表员===PyMuPDF转换成功，共{len(images_info)}页")
            return images_info
            
        except Exception as e:
            self.logger.error(f"PyMuPDF转换失败: {e}")
            return []
    
    # 移除PIL图像处理方法，只使用文件路径方式
    
    def _analyze_page_with_qwen_file(self, image_path: str, page_num: int) -> str:
        """使用Qwen模型分析页面图像文件"""
        try:
            # 将图像转换为base64发送（支持远程API）
            import base64
            
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            # 调用Qwen API分析图像（使用base64格式）
            response = requests.post(
                f"{self.api_url}/image_base64",
                json={
                    "image_base64": base64_image,
                    "message": self._get_analysis_prompt(page_num)
                },
                timeout=30
            )
            
            # 如果base64接口不存在，尝试原来的文件路径接口
            if response.status_code == 404:
                self.logger.info("尝试使用文件路径接口...")
                response = requests.post(
                    f"{self.api_url}/image",
                    json={
                        "image_path": image_path,
                        "message": self._get_analysis_prompt(page_num)
                    },
                    timeout=30
                )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 'success':
                    return result.get('response', '')
                else:
                    self.logger.warning(f"Qwen API返回错误: {result}")
                    return ''
            else:
                self.logger.warning(f"Qwen API请求失败: {response.status_code}")
                # 打印详细错误信息
                try:
                    error_detail = response.json()
                    self.logger.warning(f"错误详情: {error_detail}")
                except:
                    self.logger.warning(f"响应内容: {response.text}")
                return ''
                    
        except Exception as e:
            self.logger.error(f"Qwen分析页面失败: {e}")
            return ''
    
    def _get_analysis_prompt(self, page_num: int) -> str:
        """获取页面分析提示词"""
        return f"""请仔细分析这个PDF页面图像（第{page_num}页），提取其中的所有文本内容。

要求：
1. 准确识别所有可见的文字，包括标题、正文、表格、图表说明等
2. 保持原有的文本结构和格式
3. 对于表格，请保持表格的行列结构
4. 对于列表，请保持列表的层级结构
5. 忽略页眉页脚的页码信息
6. 如果有图片或图表，请简要描述其内容

请直接返回提取的文本内容，不要添加额外的说明。"""
    
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
            'parsing_method': 'qwen_multimodal',
            
            # 内容信息（待填充）
            'text_content': '',
            'page_count': 0,
            'char_count': 0,
            'word_count': 0,
            'metadata': {},
            'pages': [],
            
            # 文档质量评估
            'content_quality': 'high',  # Qwen模型通常质量较高
            'extraction_confidence': 0.9,
            'has_text': False,
            'has_images': False,
            'has_tables': False,
        }
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """计算文件哈希值作为唯一标识"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def _enhance_document_node(self, document_node: Dict[str, Any], file_path: Path):
        """增强文档节点属性"""
        
        # 更新内容统计
        text_content = document_node.get('text_content', '')
        document_node['char_count'] = len(text_content)
        document_node['word_count'] = len(text_content.split())
        document_node['has_text'] = bool(text_content.strip())
        
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
解析方法：Qwen多模态识别

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
            'parsing_method': 'qwen_multimodal',
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
