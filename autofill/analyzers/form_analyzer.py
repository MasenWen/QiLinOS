"""
表单分析器

分析表单文档，识别表单结构、字段类型、验证规则等
"""

from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import re

from ..core import BaseAnalyzer, ProcessingStatus
from ..config import get_settings
from ..utils.logger import get_logger, performance_monitor, error_handler
from ..parsers.document_factory import DocumentParserFactory
from ..llm.local_llm_client import LocalLLMClientAdapter
from ..llm.analyzers import FormLLMAnalyzer
from src.utils.db_manager import node_state


class FormAnalyzer(BaseAnalyzer):
    """表单分析器"""
    
    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        self.settings = get_settings()
        self.parser_factory = DocumentParserFactory()
        # 延迟初始化LLM分析器
        self.llm_analyzer = None
        
        # 表单字段类型映射
        self.field_type_mapping = {
            'text': ['姓名', '名称', '单位', '地址', '备注', '说明'],
            'number': ['年龄', '数量', '金额', '价格', '工资', '收入'],
            'phone': ['电话', '手机', '联系方式'],
            'email': ['邮箱', '电子邮件'],
            'id_card': ['身份证', '证件号'],
            'date': ['日期', '时间', '生日', '出生'],
            'select': ['性别', '学历', '职业', '状态'],
            'checkbox': ['是否', '选择', '确认'],
            'signature': ['签名', '签字'],
            'file': ['上传', '附件', '文件'],
        }
        
        # 验证规则模式
        self.validation_patterns = {
            'required': [r'必填', r'必须', r'必选', r'\*', r'required'],
            'optional': [r'可选', r'选填', r'optional'],
            'format': [r'格式', r'format'],
            'length': [r'长度', r'字符', r'length'],
            'range': [r'范围', r'区间', r'range'],
        }
    
    def process(self, input_data: Any) -> Dict[str, Any]:
        """处理输入数据并返回结果（实现抽象方法）"""
        if isinstance(input_data, (str, Path)):
            return self.analyze(Path(input_data))
        elif isinstance(input_data, dict) and 'document_path' in input_data:
            return self.analyze(Path(input_data['document_path']))
        else:
            raise ValueError("输入数据必须是文档路径或包含document_path的字典")
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性（实现抽象方法）"""
        if isinstance(input_data, (str, Path)):
            return Path(input_data).exists()
        elif isinstance(input_data, dict) and 'document_path' in input_data:
            return Path(input_data['document_path']).exists()
        return False
    
    def _get_llm_analyzer(self):
        """延迟初始化LLM分析器"""
        if self.llm_analyzer is None:
            
            llm_client = LocalLLMClientAdapter()
            self.llm_analyzer = FormLLMAnalyzer(llm_client)
        return self.llm_analyzer
    
    @error_handler()
    @performance_monitor
    def analyze(self, document_path: Path) -> Dict[str, Any]:
        """
        分析表单文档
        
        Args:
            document_path: 表单文档路径
            
        Returns:
            表单分析结果
        """
        self.logger.info(f"{node_state}-=-填表员===开始分析表单文档: {document_path}")
        
        try:
            result = {
                'document_path': str(document_path),
                'document_type': '',
                'form_structure': {},
                'fields': [],
                'field_groups': [],
                'validation_rules': {},
                'layout_info': {},
                'confidence': 0.0,
                'suggestions': [],
            }
            
            # 解析文档
            parsed_document = self._parse_document(document_path)
            if not parsed_document:
                raise ValueError(f"无法解析文档: {document_path}")
            
            result['document_type'] = parsed_document.get('document_type', '')
            
            # 分析表单结构
            form_structure = self._analyze_form_structure(parsed_document)
            result['form_structure'] = form_structure
            
            # 提取表单字段
            fields = self._extract_form_fields(parsed_document)
            result['fields'] = fields
            
            # 分组相关字段
            field_groups = self._group_related_fields(fields)
            result['field_groups'] = field_groups
            
            # 分析验证规则
            validation_rules = self._analyze_validation_rules(parsed_document, fields)
            result['validation_rules'] = validation_rules
            
            # 分析布局信息
            layout_info = self._analyze_layout(parsed_document)
            result['layout_info'] = layout_info
            
            # 使用LLM增强分析
            llm_analysis = self._enhance_with_llm(parsed_document)
            result = self._merge_llm_analysis(result, llm_analysis)
            
            # 计算置信度
            result['confidence'] = self._calculate_confidence(result)
            
            # 生成改进建议
            result['suggestions'] = self._generate_suggestions(result)
            
            self.status = ProcessingStatus.SUCCESS
            self.logger.info(f"{node_state}-=-填表员===表单分析完成: {document_path}")
            
            return result
            
        except Exception as e:
            self.status = ProcessingStatus.FAILED
            self.logger.error(f"表单分析失败 {document_path}: {e}")
            raise
    
    def _parse_document(self, document_path: Path) -> Optional[Dict[str, Any]]:
        """解析文档"""
        try:
            parser = self.parser_factory.create_parser(document_path)
            if not parser:
                return None
            
            return parser.parse(document_path)
            
        except Exception as e:
            self.logger.error(f"文档解析失败: {e}")
            return None
    
    def _analyze_form_structure(self, parsed_document: Dict[str, Any]) -> Dict[str, Any]:
        """分析表单结构"""
        structure = {
            'type': 'unknown',
            'sections': [],
            'tables': [],
            'total_fields': 0,
            'layout_type': 'unknown',
        }
        
        try:
            # 检测表单类型
            text_content = parsed_document.get('text_content', '')
            structure['type'] = self._detect_form_type(text_content)
            
            # 分析表格结构
            tables = parsed_document.get('tables', [])
            structure['tables'] = self._analyze_table_structure(tables)
            
            # 检测章节
            sections = self._detect_sections(text_content)
            structure['sections'] = sections
            
            # 统计字段数量
            forms = parsed_document.get('forms', [])
            structure['total_fields'] = len(forms)
            
            # 确定布局类型
            structure['layout_type'] = self._determine_layout_type(parsed_document)
            
        except Exception as e:
            self.logger.warning(f"分析表单结构失败: {e}")
        
        return structure
    
    def _detect_form_type(self, text_content: str) -> str:
        """检测表单类型"""
        form_type_patterns = {
            'application': [r'申请', r'application'],
            'registration': [r'注册', r'登记', r'registration'],
            'survey': [r'调查', r'问卷', r'survey'],
            'contact': [r'联系', r'contact'],
            'order': [r'订单', r'order'],
            'invoice': [r'发票', r'invoice'],
            'contract': [r'合同', r'contract'],
            'report': [r'报告', r'report'],
            'feedback': [r'反馈', r'feedback'],
        }
        
        for form_type, patterns in form_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_content, re.IGNORECASE):
                    return form_type
        
        return 'general'
    
    def _analyze_table_structure(self, tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """分析表格结构"""
        analyzed_tables = []
        
        for table in tables:
            table_analysis = {
                'index': table.get('index', 0),
                'rows': table.get('rows', 0),
                'columns': table.get('columns', 0),
                'has_headers': False,
                'is_form_table': False,
                'field_columns': [],
                'data_columns': [],
            }
            
            # 分析表格数据
            data = table.get('data', [])
            if data:
                # 检测是否有表头
                if len(data) > 1:
                    first_row = data[0]
                    second_row = data[1]
                    
                    # 简单启发式：如果第一行包含较多文字，第二行包含更多空白或特殊字符
                    header_score = sum(1 for cell in first_row if cell and len(cell.strip()) > 2)
                    data_score = sum(1 for cell in second_row if cell and ('_' in cell or len(cell.strip()) < 3))
                    
                    table_analysis['has_headers'] = header_score > data_score
                
                # 检测是否为表单表格
                table_analysis['is_form_table'] = self._is_form_table(data)
                
                # 分析列类型
                if table_analysis['has_headers']:
                    headers = data[0]
                    for col_idx, header in enumerate(headers):
                        col_type = self._classify_column_type(header)
                        if col_type in ['field', 'label']:
                            table_analysis['field_columns'].append(col_idx)
                        else:
                            table_analysis['data_columns'].append(col_idx)
            
            analyzed_tables.append(table_analysis)
        
        return analyzed_tables
    
    def _is_form_table(self, data: List[List[str]]) -> bool:
        """判断表格是否为表单表格"""
        if not data or len(data) < 2:
            return False
        
        # 检查是否包含表单字段指示符
        form_indicators = ['姓名', '电话', '地址', '日期', '签名', '___', '____']
        
        for row in data:
            for cell in row:
                if cell:
                    for indicator in form_indicators:
                        if indicator in cell:
                            return True
        
        return False
    
    def _classify_column_type(self, header: str) -> str:
        """分类列类型"""
        if not header:
            return 'unknown'
        
        header_lower = header.lower().strip()
        
        # 字段标签列
        if any(keyword in header_lower for keyword in ['项目', '字段', '内容', '标签']):
            return 'label'
        
        # 值列
        if any(keyword in header_lower for keyword in ['值', '内容', '填写', '输入']):
            return 'value'
        
        # 说明列
        if any(keyword in header_lower for keyword in ['说明', '备注', '描述', '要求']):
            return 'description'
        
        return 'field'
    
    def _detect_sections(self, text_content: str) -> List[Dict[str, Any]]:
        """检测表单章节"""
        sections = []
        
        # 常见章节标题模式
        section_patterns = [
            r'第[一二三四五六七八九十\d]+[部分章节]',
            r'[一二三四五六七八九十\d]+[、．.]',
            r'^\d+\.',
            r'^[A-Z]\.',
            r'【.*?】',
            r'■.*?■',
        ]
        
        lines = text_content.split('\n')
        
        for line_idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            for pattern in section_patterns:
                if re.match(pattern, line):
                    sections.append({
                        'title': line,
                        'line_number': line_idx + 1,
                        'pattern': pattern,
                        'level': self._determine_section_level(line),
                    })
                    break
        
        return sections
    
    def _determine_section_level(self, title: str) -> int:
        """确定章节级别"""
        if re.match(r'第[一二三四五六七八九十\d]+部分', title):
            return 1
        elif re.match(r'第[一二三四五六七八九十\d]+章', title):
            return 2
        elif re.match(r'第[一二三四五六七八九十\d]+节', title):
            return 3
        elif re.match(r'[一二三四五六七八九十\d]+[、．.]', title):
            return 2
        elif re.match(r'^\d+\.', title):
            return 3
        else:
            return 4
    
    def _determine_layout_type(self, parsed_document: Dict[str, Any]) -> str:
        """确定表单布局类型"""
        tables = parsed_document.get('tables', [])
        forms = parsed_document.get('forms', [])
        
        if tables and len(tables) > 0:
            # 检查是否主要基于表格
            table_cells = sum(table.get('rows', 0) * table.get('columns', 0) for table in tables)
            if table_cells > len(forms) * 2:
                return 'table_based'
        
        # 检查字段分布
        if len(forms) > 10:
            return 'multi_section'
        elif len(forms) > 5:
            return 'standard'
        else:
            return 'simple'
    
    def _extract_form_fields(self, parsed_document: Dict[str, Any]) -> List[Dict[str, Any]]:
        """提取表单字段"""
        fields = []
        
        try:
            # 从解析结果中获取表单字段
            parsed_forms = parsed_document.get('forms', [])
            
            for form_field in parsed_forms:
                # 使用真实字段标签，而不是抽象的field_X
                field_label = form_field.get('label', '').strip()
                if not field_label:
                    field_label = f"field_{len(fields)}"  # 只有在没有标签时才用field_X
                
                # 清理字段名，移除特殊字符，保留中文和英文
                import re
                clean_label = re.sub(r'[^\w\u4e00-\u9fa5]', '_', field_label)
                if not clean_label or clean_label == '_':
                    clean_label = f"field_{len(fields)}"
                
                field_info = {
                    'id': clean_label,  # 直接使用真实字段名
                    'name': clean_label,  # 添加name字段保持兼容性
                    'label': field_label,  # 保留原始标签
                    'type': self._classify_field_type(form_field),
                    'position': form_field.get('position', (0, 0)),
                    'required': form_field.get('required', False),
                    'value': form_field.get('value', ''),
                    'options': form_field.get('options', []),
                    'validation': {},
                    'source': 'parsed',
                }
                
                # 增强字段信息
                field_info = self._enhance_field_info(field_info, parsed_document)
                fields.append(field_info)
            
            # 从文本模式中检测额外字段
            additional_fields = self._detect_additional_fields(parsed_document)
            fields.extend(additional_fields)
            
        except Exception as e:
            self.logger.warning(f"提取表单字段失败: {e}")
        
        return fields
    
    def _classify_field_type(self, form_field: Dict[str, Any]) -> str:
        """分类字段类型"""
        field_type = form_field.get('type', 'text')
        label = form_field.get('label', '').lower()
        
        # 基于标签推断类型
        for field_type_key, keywords in self.field_type_mapping.items():
            for keyword in keywords:
                if keyword in label:
                    return field_type_key
        
        return field_type
    
    def _enhance_field_info(self, field_info: Dict[str, Any], parsed_document: Dict[str, Any]) -> Dict[str, Any]:
        """增强字段信息"""
        try:
            label = field_info['label']
            
            # 检测验证规则
            validation = {}
            
            # 必填检测
            if any(pattern in label for pattern in ['*', '必填', '必须', 'required']):
                validation['required'] = True
                field_info['required'] = True
            
            # 格式检测
            if '格式' in label or 'format' in label.lower():
                validation['format'] = True
            
            # 长度检测
            length_match = re.search(r'(\d+)[字符位]', label)
            if length_match:
                validation['max_length'] = int(length_match.group(1))
            
            field_info['validation'] = validation
            
            # 检测选项
            if field_info['type'] in ['select', 'checkbox', 'radio']:
                options = self._extract_field_options(label, parsed_document)
                if options:
                    field_info['options'] = options
            
        except Exception as e:
            self.logger.warning(f"增强字段信息失败: {e}")
        
        return field_info
    
    def _extract_field_options(self, label: str, parsed_document: Dict[str, Any]) -> List[str]:
        """提取字段选项"""
        options = []
        
        try:
            # 从标签中提取选项
            if '：' in label or ':' in label:
                parts = re.split('[：:]', label)
                if len(parts) > 1:
                    option_text = parts[1]
                    # 常见选项分隔符
                    separators = ['/', '｜', '|', '、', '，', ',']
                    for sep in separators:
                        if sep in option_text:
                            options = [opt.strip() for opt in option_text.split(sep)]
                            break
            
            # 性别字段的默认选项
            if '性别' in label.lower():
                options = ['男', '女']
            
            # 学历字段的默认选项
            elif '学历' in label.lower():
                options = ['小学', '初中', '高中', '大专', '本科', '硕士', '博士']
            
        except Exception as e:
            self.logger.warning(f"提取字段选项失败: {e}")
        
        return options
    
    def _detect_additional_fields(self, parsed_document: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检测额外的表单字段"""
        additional_fields = []
        
        try:
            text_content = parsed_document.get('text_content', '')
            
            # 使用更复杂的模式检测字段
            field_patterns = [
                r'(\w+)[：:]\s*[_\s\-]{3,}',  # 标签后跟下划线
                r'(\w+)\s*[\(（][^）)]*[\)）]\s*[：:]',  # 带括号说明的标签
                r'(\w+)\s*[：:]\s*\[\s*\]',  # 标签后跟方括号
                r'□\s*(\w+)',  # 复选框字段
            ]
            
            for pattern in field_patterns:
                matches = re.finditer(pattern, text_content)
                for match in matches:
                    label = match.group(1)
                    
                    # 避免重复
                    if not any(field['label'] == label for field in additional_fields):
                        # 清理字段名，移除特殊字符
                        clean_label = re.sub(r'[^\w\u4e00-\u9fa5]', '_', label)
                        if not clean_label or clean_label == '_':
                            clean_label = f"detected_field_{len(additional_fields)}"
                        
                        field_info = {
                            'id': clean_label,  # 直接使用真实字段名
                            'name': clean_label,  # 添加name字段保持兼容性
                            'label': label,  # 保留原始标签
                            'type': self._classify_field_type({'label': label}),
                            'position': match.span(),
                            'required': False,
                            'value': '',
                            'options': [],
                            'validation': {},
                            'source': 'pattern_detection',
                        }
                        additional_fields.append(field_info)
            
        except Exception as e:
            self.logger.warning(f"检测额外字段失败: {e}")
        
        return additional_fields
    
    def _group_related_fields(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """分组相关字段"""
        groups = []
        
        try:
            # 预定义字段组
            predefined_groups = {
                'personal_info': ['姓名', '性别', '年龄', '生日', '身份证'],
                'contact_info': ['电话', '手机', '邮箱', '地址'],
                'work_info': ['公司', '职位', '部门', '工作地址'],
                'education_info': ['学校', '专业', '学历', '毕业时间'],
                'family_info': ['配偶', '子女', '父母', '家庭成员'],
            }
            
            # 为每个预定义组查找匹配的字段
            for group_name, keywords in predefined_groups.items():
                group_fields = []
                
                for field in fields:
                    field_label = field['label'].lower()
                    if any(keyword in field_label for keyword in keywords):
                        group_fields.append(field['id'])
                
                if group_fields:
                    groups.append({
                        'id': group_name,
                        'name': group_name,
                        'fields': group_fields,
                        'type': 'predefined',
                    })
            
            # 基于位置的字段分组（简单实现）
            position_groups = self._group_by_position(fields)
            groups.extend(position_groups)
            
        except Exception as e:
            self.logger.warning(f"分组相关字段失败: {e}")
        
        return groups
    
    def _group_by_position(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """基于位置分组字段"""
        position_groups = []
        
        try:
            # 按Y坐标排序字段
            sorted_fields = sorted(fields, key=lambda f: f['position'][0] if isinstance(f['position'], tuple) else 0)
            
            # 简单的行分组
            current_group = []
            current_y = None
            threshold = 50  # 像素阈值
            
            for field in sorted_fields:
                if isinstance(field['position'], tuple) and len(field['position']) >= 2:
                    y_pos = field['position'][0]
                    
                    if current_y is None or abs(y_pos - current_y) <= threshold:
                        current_group.append(field['id'])
                        current_y = y_pos
                    else:
                        # 开始新组
                        if len(current_group) > 1:
                            position_groups.append({
                                'id': f"position_group_{len(position_groups)}",
                                'name': f"位置组 {len(position_groups) + 1}",
                                'fields': current_group,
                                'type': 'position',
                            })
                        current_group = [field['id']]
                        current_y = y_pos
            
            # 处理最后一组
            if len(current_group) > 1:
                position_groups.append({
                    'id': f"position_group_{len(position_groups)}",
                    'name': f"位置组 {len(position_groups) + 1}",
                    'fields': current_group,
                    'type': 'position',
                })
                
        except Exception as e:
            self.logger.warning(f"基于位置分组失败: {e}")
        
        return position_groups
    
    def _analyze_validation_rules(self, parsed_document: Dict[str, Any], fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """分析验证规则"""
        validation_rules = {}
        
        try:
            text_content = parsed_document.get('text_content', '')
            
            # 全局验证规则
            global_rules = {}
            
            for rule_type, patterns in self.validation_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, text_content, re.IGNORECASE):
                        global_rules[rule_type] = True
            
            validation_rules['global'] = global_rules
            
            # 字段级验证规则
            field_rules = {}
            for field in fields:
                field_id = field['id']
                field_validation = field.get('validation', {})
                if field_validation:
                    field_rules[field_id] = field_validation
            
            validation_rules['fields'] = field_rules
            
        except Exception as e:
            self.logger.warning(f"分析验证规则失败: {e}")
        
        return validation_rules
    
    def _analyze_layout(self, parsed_document: Dict[str, Any]) -> Dict[str, Any]:
        """分析表单布局"""
        layout_info = {
            'page_count': 1,
            'columns': 1,
            'orientation': 'portrait',
            'margins': {},
            'sections': [],
        }
        
        try:
            # 从文档元数据中获取布局信息
            if 'pages' in parsed_document:
                pages = parsed_document['pages']
                layout_info['page_count'] = len(pages)
                
                if pages:
                    first_page = pages[0]
                    if 'width' in first_page and 'height' in first_page:
                        width = first_page['width']
                        height = first_page['height']
                        layout_info['orientation'] = 'landscape' if width > height else 'portrait'
            
            # 分析列数（基于字段位置）
            forms = parsed_document.get('forms', [])
            if forms:
                x_positions = []
                for form in forms:
                    if isinstance(form.get('position'), tuple) and len(form['position']) >= 2:
                        x_positions.append(form['position'][1])
                
                if x_positions:
                    # 简单的列数估算
                    unique_x = sorted(set(x_positions))
                    if len(unique_x) > 1:
                        # 检查是否有明显的列分隔
                        gaps = [unique_x[i+1] - unique_x[i] for i in range(len(unique_x)-1)]
                        avg_gap = sum(gaps) / len(gaps)
                        large_gaps = [gap for gap in gaps if gap > avg_gap * 1.5]
                        layout_info['columns'] = len(large_gaps) + 1
            
        except Exception as e:
            self.logger.warning(f"分析布局失败: {e}")
        
        return layout_info
    
    def _enhance_with_llm(self, parsed_document: Dict[str, Any]) -> Dict[str, Any]:
        """使用LLM增强分析"""
        try:
            text_content = parsed_document.get('text_content', '')
            if text_content:
                return self._get_llm_analyzer().analyze_form(text_content)
        except Exception as e:
            self.logger.warning(f"LLM增强分析失败: {e}")
        
        return {}
    
    def _merge_llm_analysis(self, result: Dict[str, Any], llm_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """合并LLM分析结果"""
        try:
            if llm_analysis and llm_analysis.get('confidence', 0) > 0.7:
                # 合并字段信息
                llm_fields = llm_analysis.get('fields', [])
                for llm_field in llm_fields:
                    # 查找匹配的字段
                    matching_field = None
                    for field in result['fields']:
                        if field['label'] == llm_field.get('name', ''):
                            matching_field = field
                            break
                    
                    if matching_field:
                        # 更新字段信息
                        if 'type' in llm_field:
                            matching_field['type'] = llm_field['type']
                        if 'required' in llm_field:
                            matching_field['required'] = llm_field['required']
                
                # 更新整体置信度
                original_confidence = result.get('confidence', 0)
                llm_confidence = llm_analysis.get('confidence', 0)
                result['confidence'] = (original_confidence + llm_confidence) / 2
        
        except Exception as e:
            self.logger.warning(f"合并LLM分析结果失败: {e}")
        
        return result
    
    def _calculate_confidence(self, result: Dict[str, Any]) -> float:
        """计算分析置信度"""
        try:
            confidence_factors = []
            
            # 字段数量因子
            field_count = len(result.get('fields', []))
            if field_count > 0:
                confidence_factors.append(min(field_count / 10, 1.0))
            
            # 字段类型识别因子
            typed_fields = sum(1 for field in result.get('fields', []) if field.get('type') != 'text')
            if field_count > 0:
                confidence_factors.append(typed_fields / field_count)
            
            # 结构分析因子
            structure = result.get('form_structure', {})
            if structure.get('type') != 'unknown':
                confidence_factors.append(0.8)
            
            # 验证规则因子
            validation_rules = result.get('validation_rules', {})
            if validation_rules.get('fields'):
                confidence_factors.append(0.7)
            
            # 计算平均置信度
            if confidence_factors:
                return sum(confidence_factors) / len(confidence_factors)
            else:
                return 0.5
                
        except Exception as e:
            self.logger.warning(f"计算置信度失败: {e}")
            return 0.5
    
    def _generate_suggestions(self, result: Dict[str, Any]) -> List[str]:
        """生成改进建议"""
        suggestions = []
        
        try:
            # 基于分析结果生成建议
            fields = result.get('fields', [])
            
            # 字段相关建议
            if len(fields) == 0:
                suggestions.append("未检测到任何表单字段，请检查文档格式或内容")
            elif len(fields) < 3:
                suggestions.append("检测到的字段较少，可能存在漏检，建议手动验证")
            
            # 类型识别建议
            untyped_fields = [f for f in fields if f.get('type') == 'text']
            if len(untyped_fields) > len(fields) * 0.5:
                suggestions.append("大部分字段类型未能准确识别，建议手动指定字段类型")
            
            # 验证规则建议
            validation_rules = result.get('validation_rules', {})
            if not validation_rules.get('fields'):
                suggestions.append("未检测到字段验证规则，建议添加必要的验证约束")
            
            # 置信度建议
            confidence = result.get('confidence', 0)
            if confidence < 0.6:
                suggestions.append("分析置信度较低，建议人工审核分析结果")
            elif confidence < 0.8:
                suggestions.append("分析置信度中等，建议验证关键字段信息")
            
        except Exception as e:
            self.logger.warning(f"生成建议失败: {e}")
        
        return suggestions
    
    def get_status(self) -> ProcessingStatus:
        """获取处理状态"""
        return self.status 