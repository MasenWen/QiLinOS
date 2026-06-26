"""
基于LightRAG问答的智能表单填写器

将传统的表单填写转换为智能问答模式，通过LightRAG的知识图谱和问答能力
来更准确地填充表单字段。
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Callable
from datetime import datetime
import re
import json
from lightrag import QueryParam
# 添加项目根目录和LightRAG路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.append(str(Path(__file__).parent.parent.parent / "LightRAG-main" / "age_rag_demo"))

from ..utils.logger import get_logger, performance_monitor, error_handler
from ..core import BaseFiller


from src.rag.ps_rag import RAG_PS

from src.utils.db_manager import node_state
# try:
#     from lightrag_age_demo import insert_document_for_form_filling, query_user_info, extract_user_info_from_document
#     from lightrag_singleton import get_lightrag_instance, is_lightrag_available, is_lightrag_initialized
#     LIGHTRAG_AVAILABLE = is_lightrag_available()
# except ImportError as e:
#     print(f"LightRAG模块导入失败: {e}")
#     get_lightrag_instance = None
#     is_lightrag_available = lambda: False
#     is_lightrag_initialized = lambda: False
#     LIGHTRAG_AVAILABLE = False

class LightRAGFormFiller:
    """基于LightRAG问答的表单填写器"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.rag_ps = RAG_PS()
        self._initialized = False
        
        # 字段类型识别关键词（用于智能分析字段类型）
        self.field_type_keywords = {
            'name': ['姓名', 'name', '名字', '称呼', '全名', '真实姓名'],
            'phone': ['电话', '手机', '联系方式', 'phone', 'mobile', 'tel', '联系电话', '手机号', '电话号码'],
            'email': ['邮箱', '邮件', 'email', 'mail', '电子邮件', '邮件地址', '电子邮箱'],
            'address': ['地址', '住址', 'address', 'addr', '详细地址', '居住地址', '家庭住址', '现住址'],
            'company': ['公司', '单位', 'employer', 'company', '工作单位', '所在公司', '雇主'],
            'id_number': ['身份证', '证件号', 'id', 'identity', '身份证号', '证件号码'],
            'birth_date': ['出生', '生日', 'birth', 'birthday', '生年月日', '出生日期', '生日日期'],
            'education': ['学历', '教育', 'education', 'degree', '教育背景', '学位'],
            'salary': ['薪资', '工资', '收入', 'salary', 'income', '月薪', '年薪'],
            'gender': ['性别', 'gender', 'sex', '男女'],
            'age': ['年龄', 'age', '岁数'],
            'position': ['职位', '职务', 'position', 'job', 'title', '岗位', '工作'],
            'school': ['学校', '院校', 'school', 'university', '大学', '毕业院校'],
            'major': ['专业', 'major', '所学专业', '学科'],
            'marital': ['婚姻', 'marital', '婚姻状况', '婚否'],
            'nationality': ['国籍', 'nationality', '民族'],
            'department': ['部门', 'department', '科室', '处室']
        }

    async def _execute_with_retry(self, operation_name: str, operation_func: Callable, 
                                 max_retries: int = 5) -> Dict[str, Any]:
        """
        通用重试机制，用于所有可能失败的LightRAG操作
        
        Args:
            operation_name: 操作名称（用于日志）
            operation_func: 要执行的异步操作函数
            max_retries: 最大重试次数
            
        Returns:
            Dict[str, Any]: 操作结果
        """
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                self.logger.debug(f"🔄 {operation_name} 尝试 {attempt + 1}/{max_retries + 1}")
                
                result = await operation_func()
                
                if result is not None and result != "":
                    self.logger.debug(f"✅ {operation_name} 第 {attempt + 1} 次尝试成功")
                    return {'success': True, 'result': result, 'attempts': attempt + 1}
                else:
                    if attempt < max_retries:
                        self.logger.warning(f"⚠️ {operation_name} 第 {attempt + 1} 次尝试返回空结果，将重试")
                        await asyncio.sleep(1.0 * (attempt + 1))  # 递增延迟
                        continue
                    else:
                        self.logger.error(f"{node_state}-=-填表员===❌ {operation_name} 所有尝试均返回空结果")
                        return {'success': False, 'error': '所有尝试均返回空结果', 'attempts': max_retries + 1}
                
            except Exception as e:
                last_exception = e
                self.logger.warning(f"⚠️ {operation_name} 第 {attempt + 1} 次尝试失败: {str(e)}")
                
                if attempt < max_retries:
                    # 递增延迟重试
                    delay = 2.0 * (attempt + 1)
                    self.logger.debug(f"🔄 {operation_name} 将在 {delay} 秒后进行第 {attempt + 2} 次尝试")
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(f"❌ {operation_name} 所有 {max_retries + 1} 次尝试均失败")
                    return {'success': False, 'error': str(last_exception), 'attempts': max_retries + 1}
        
        # 理论上不应该到达这里
        return {'success': False, 'error': str(last_exception) if last_exception else '未知错误', 'attempts': max_retries + 1}

   
    
    async def initialize(self):
        """使用单例管理器初始化LightRAG，避免事件循环冲突"""
        if self._initialized and self.rag_ps:
            return True
            
        try:
            
            
            # 使用单例管理器获取实例，它会自动处理事件循环兼容性
            await self.rag_ps.initialize()
           
            
            if self.rag_ps:
                self._initialized = True
                self.logger.info(f"{node_state}-=-填表员===✅ 通过单例管理器获取LightRAG实例成功")
                return True
            else:
                self.logger.error(f"{node_state}-=-填表员===单例管理器返回空实例")
                return False
                
        except Exception as e:
            self.logger.error(f"{node_state}-=-填表员===通过单例管理器初始化LightRAG失败: {e}")
            self._initialized = False
            return False
    
    async def insert_document_content(self, document_content: str, document_path: str = None) -> bool:
        """将文档内容插入到LightRAG知识图谱中"""
        try:
            if not self._initialized:
                await self.initialize()
                
            if not self.rag_ps:
                self.logger.error("LightRAG未初始化，无法插入文档")
                return False
            
            result = await self.rag_ps.insert_document(document_content, 
                document_path
            )
            
            if result.get('success'):
                self.logger.info(f"{node_state}-=-填表员===文档内容已成功插入知识图谱: {document_path or 'content'}")
                return True
            else:
                self.logger.warning(f"文档插入失败: {result.get('error', '未知错误')}")
                return False
                
        except Exception as e:
            self.logger.error(f"插入文档内容时发生异常: {e}")
            return False
    
    def identify_field_type(self, field_name: str, field_label: str = None) -> str:
        """智能识别字段类型"""
        field_text = f"{field_name} {field_label or ''}".lower()
        
        best_match = 'unknown'
        max_score = 0
        
        # 使用关键词匹配计算相似度分数
        for field_type, keywords in self.field_type_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword.lower() in field_text:
                    # 完全匹配得分更高
                    if keyword.lower() == field_text.strip():
                        score += 10
                    else:
                        score += 1
            
            if score > max_score:
                max_score = score
                best_match = field_type
        
        return best_match
    
    def generate_questions_for_field(self, field_name: str, field_label: str = None) -> List[str]:
        """动态生成字段问题"""
        # 获取字段显示名称
        display_name = field_label or field_name
        
        # 识别字段类型
        field_type = self.identify_field_type(field_name, field_label)
        
        questions = []
        
        # 根据字段类型生成特定问题
        if field_type == 'name':
            questions = [
                f"{display_name}是什么？",
                "姓名是什么？",
                "叫什么名字？",
                "个人姓名信息"
            ]
        elif field_type == 'phone':
            questions = [
                f"{display_name}是多少？",
                "手机号码是什么？",
                "电话号码是多少？",
                "联系电话信息"
            ]
        elif field_type == 'email':
            questions = [
                f"{display_name}是什么？",
                "邮箱地址是什么？",
                "电子邮件地址",
                "邮件地址信息"
            ]
        elif field_type == 'address':
            questions = [
                f"{display_name}是什么？",
                "地址在哪里？",
                "住址是什么？",
                "详细地址信息"
            ]
        elif field_type == 'company':
            questions = [
                f"{display_name}是什么？",
                "工作单位是什么？",
                "公司名称是什么？",
                "所在公司信息"
            ]
        elif field_type == 'id_number':
            questions = [
                f"{display_name}是什么？",
                "身份证号码是什么？",
                "证件号码是多少？"
            ]
        elif field_type == 'birth_date':
            questions = [
                f"{display_name}是什么时候？",
                "出生日期是什么？",
                "生日是哪天？",
                "出生年月日信息"
            ]
        elif field_type == 'education':
            questions = [
                f"{display_name}是什么？",
                "学历是什么？",
                "教育背景如何？"
            ]
        elif field_type == 'position':
            questions = [
                f"{display_name}是什么？",
                "职位是什么？",
                "工作职务是什么？",
                "担任什么职位？"
            ]
        elif field_type == 'salary':
            questions = [
                f"{display_name}是多少？",
                "薪资是多少？",
                "工资收入多少？"
            ]
        else:
            # 通用问题生成
            questions = [
                f"{display_name}是什么？",
                f"关于{display_name}的信息是什么？",
                f"{display_name}的具体内容",
                f"文档中{display_name}相关的信息"
            ]
        
        return questions
    
    def build_field_query_prompt(self, field_name: str, field_label: str = None) -> str:
        """构建字段查询的综合prompt"""
        display_name = field_label or field_name
        field_type = self.identify_field_type(field_name, field_label)
        
        # 构建结构化的查询prompt
        prompt = f"""请根据已有的文档内容，回答关于"{display_name}"的问题。

字段信息：
- 字段名称：{field_name}
- 显示名称：{display_name}
- 字段类型：{field_type}

请提供准确、简洁的答案，如果文档中没有相关信息，请回答"未找到相关信息"。

问题：{display_name}是什么？"""

        # 根据字段类型添加特定的查询指导
        if field_type == 'phone':
            prompt += "\n\n注意：请提供完整的电话号码，包括区号（如果有）。"
        elif field_type == 'email':
            prompt += "\n\n注意：请提供完整的邮箱地址。"
        elif field_type == 'address':
            prompt += "\n\n注意：请提供完整的地址信息，包括省市区县街道。"
        elif field_type == 'birth_date':
            prompt += "\n\n注意：请提供具体的日期，格式如：YYYY-MM-DD 或 YYYY年MM月DD日。"
        elif field_type == 'id_number':
            prompt += "\n\n注意：请提供完整的身份证号码或其他证件号码。"
        elif field_type == 'name':
            prompt += "\n\n注意：请提供完整的姓名。"
        
        return prompt
    
    def build_complete_form_prompt(self, form_fields: List[Dict[str, Any]], document_content: str = None) -> str:
        """构建完整的表单填写prompt，让LightRAG一次性填写所有字段"""
        
        # 构建表单字段列表
        field_list = []
        for i, field in enumerate(form_fields):
            if not isinstance(field, dict):
                self.logger.warning(f"跳过无效字段项: {field}")
                continue
                
            field_name = field.get('name', f'field_{i}')
            field_label = field.get('label', field.get('text', ''))
            field_type = field.get('type', 'text')
            
            field_list.append({
                'name': field_name,
                'label': field_label.strip(),
                'type': field_type,
                'required': field.get('required', False)
            })
        
        # 构建prompt
        prompt = f"""你是一个专业的表单填写助手。请根据已有的知识图谱信息，智能填写以下表单的所有字段。

## 📋 需要填写的表单字段：

"""
        
        # 添加字段详情
        for field in field_list:
            prompt += f"**{field['name']}** ({field['type']})：{field['label']}\n"
        
        prompt += f"""

## 🎯 填写要求：

1. **信息来源**：请基于知识图谱中的用户信息进行填写
2. **准确性优先**：只填写确实存在的信息，不要猜测或编造
3. **格式规范**：
   - 手机号：11位数字格式
   - 身份证号：18位标准格式
   - 邮箱：标准邮箱格式
   - 日期：YYYY-MM-DD格式
   - 姓名：完整中文姓名

4. **处理原则**：
   - 如果知识图谱中有相关信息，请准确填写
   - 如果信息不完整或不确定，标记为"未知"
   - 保持答案简洁，直接给出字段值

## 📤 请严格按照以下JSON格式返回填写结果：

```json
{{
    "filled_fields": {{
        "字段名": "字段值",
        "姓名": "姓名", 
        "手机号码": "手机号码",
        "电子邮箱": "电子邮箱"
    }},
    "unfilled_fields": [
        "身份证号",
        "工作单位"
    ],
    "confidence": {{
        "字段名": 0.95,
        "姓名": 0.9,
        "手机号码": 0.85
    }},
    "notes": "基于知识图谱填写，部分字段信息不完整"
}}
```

请开始填写表单，确保返回有效的JSON格式："""
        
        return prompt
    
    def parse_lightrag_response(self, lightrag_result: str, form_fields: List[Dict[str, Any]]) -> tuple:
        """解析LightRAG的回答，提取字段值"""
        filled_fields = {}
        skipped_fields = []
        failed_fields = []
        
        try:
            if not lightrag_result or not str(lightrag_result).strip():
                self.logger.warning("LightRAG返回空结果")
                skipped_fields = [field.get('name', f'field_{i}') for i, field in enumerate(form_fields) if isinstance(field, dict)]
                return filled_fields, skipped_fields, failed_fields
            
            result_text = str(lightrag_result).strip()
            
            # 尝试解析JSON格式的回答
            import json
            import re
            
            # 查找JSON块
            json_pattern = r'```json\s*(.*?)\s*```'
            json_match = re.search(json_pattern, result_text, re.DOTALL)
            
            if json_match:
                json_text = json_match.group(1)
            else:
                # 尝试直接解析整个文本
                json_text = result_text
            
            # 清理可能的额外文本
            json_text = re.sub(r'^[^{]*', '', json_text)  # 移除开头非JSON内容
            json_text = re.sub(r'}[^}]*$', '}', json_text)  # 移除结尾非JSON内容
            
            try:
                parsed_result = json.loads(json_text)
                self.logger.debug(f"成功解析JSON，包含键: {list(parsed_result.keys())}")
                
                # 提取填写的字段
                if 'filled_fields' in parsed_result:
                    filled_data = parsed_result['filled_fields']
                    self.logger.debug(f"找到填写字段: {list(filled_data.keys())}")
                    
                    for field_name, field_value in filled_data.items():
                        if field_value and str(field_value).strip() and str(field_value).strip().lower() not in ['未知', 'unknown', '', '需用户提供', '需用户补充']:
                            # 查找对应的字段信息
                            field_info = None
                            for field in form_fields:
                                if isinstance(field, dict) and field.get('name') == field_name:
                                    field_info = field
                                    break
                            
                            # 获取推理信息
                            reasoning = ""
                            if 'reasoning' in parsed_result and field_name in parsed_result['reasoning']:
                                reasoning = parsed_result['reasoning'][field_name]
                            
                            filled_fields[field_name] = {
                                'value': str(field_value).strip(),
                                'label': field_info.get('label', '') if field_info else '',
                                'type': field_info.get('type', 'text') if field_info else 'text',
                                'method': 'lightrag_two_stage',
                                'confidence': parsed_result.get('confidence', {}).get(field_name, 0.9),
                                'reasoning': reasoning
                            }
                            self.logger.debug(f"成功提取字段: {field_name} = {field_value}")
                
                # 处理跳过的字段
                if 'skipped_fields' in parsed_result:
                    skipped_list = parsed_result['skipped_fields']
                    if isinstance(skipped_list, list):
                        skipped_fields.extend(skipped_list)
                        self.logger.debug(f"找到跳过字段: {skipped_list}")
                
                # 处理兼容性：旧版本的unfilled_fields
                if 'unfilled_fields' in parsed_result:
                    skipped_fields.extend(parsed_result['unfilled_fields'])
                
                # 标记所有未处理的字段为跳过
                processed_fields = set(filled_fields.keys()) | set(skipped_fields)
                for field in form_fields:
                    if not isinstance(field, dict):
                        continue
                    field_name = field.get('name', '')
                    if field_name and field_name not in processed_fields:
                        skipped_fields.append(field_name)
                        self.logger.debug(f"自动跳过未处理字段: {field_name}")
                
                self.logger.info(f"{node_state}-=-填表员===JSON解析成功: 填写 {len(filled_fields)} 个字段, 跳过 {len(skipped_fields)} 个字段")
                
            except json.JSONDecodeError as e:
                self.logger.warning(f"JSON解析失败: {e}, 尝试文本解析")
                # 尝试文本解析作为备选方案
                filled_fields, skipped_fields = self._parse_text_response(result_text, form_fields)
                
        except Exception as e:
            self.logger.error(f"解析LightRAG回答失败: {e}")
            # 将所有字段标记为失败
            failed_fields = [field.get('name', f'field_{i}') for i, field in enumerate(form_fields) if isinstance(field, dict) and field.get('name')]
        
        return filled_fields, skipped_fields, failed_fields
    
    def _parse_text_response(self, text: str, form_fields: List[Dict[str, Any]]) -> tuple:
        """文本解析备选方案"""
        filled_fields = {}
        skipped_fields = []
        
        # 简单的文本解析逻辑
        lines = text.split('\n')
        
        for field in form_fields:
            if not isinstance(field, dict):
                continue
                
            field_name = field.get('name', '')
            field_label = field.get('label', '')
            
            if not field_name:
                continue
                
            # 在文本中查找字段值
            for line in lines:
                if field_name in line or field_label in line:
                    # 尝试提取值（简单的冒号分割）
                    if ':' in line:
                        value = line.split(':', 1)[1].strip()
                        if value and value.lower() not in ['未知', 'unknown', '']:
                            filled_fields[field_name] = {
                                'value': value,
                                'label': field_label,
                                'type': field.get('type', 'text'),
                                'method': 'lightrag_text_parse',
                                'confidence': 0.6
                            }
                            break
            
            if field_name not in filled_fields:
                skipped_fields.append(field_name)
        
        return filled_fields, skipped_fields
    
    async def query_for_field_value(self, field_name: str, field_label: str = None, 
                                  query_mode: str = "hybrid") -> Optional[str]:
        """通过智能问答查询字段值"""
        try:
            self.logger.info(f"{node_state}-=-填表员===调试: 开始查询字段 {field_name}, _initialized={self._initialized}, lightrag={self.rag_ps is not None}")
            
            if not self._initialized or not self.rag_ps:
                self.logger.warning("LightRAG未初始化，无法进行问答查询")
                return None
            
            # 构建智能prompt
            query_prompt = self.build_field_query_prompt(field_name, field_label)
            
            self.logger.info(f"{node_state}-=-填表员===向LightRAG发送查询: {field_name} -> {query_prompt[:100]}...")
            
            try:
                
                # self.logger.info(调用lightrag.aquery开始...")
                result = await self.rag_ps.rag.aquery(
                    query_prompt,
                    param=QueryParam(
                        mode=query_mode,
                        response_type="中文回答",
                        enable_rerank=False
                    )
                )
                
                if result and len(str(result).strip()) > 0:
                    answer = str(result).strip()
                    
                    # 检查是否是有效答案
                    if self._is_valid_answer(answer, query_prompt):
                        extracted_value = self._extract_field_value(answer, field_name)
                        self.logger.info(f"{node_state}-=-填表员===字段 {field_name} 获得答案: {extracted_value}")
                        return extracted_value
                    else:
                        self.logger.debug(f"字段 {field_name} 获得无效答案: {answer[:100]}")
                else:
                    self.logger.debug(f"字段 {field_name} 查询无结果")
                
            except Exception as e:
                self.logger.debug(f"查询失败 {field_name}: {e}")
            
            # 如果主要查询失败，尝试备用问题
            fallback_questions = self.generate_questions_for_field(field_name, field_label)
            for question in fallback_questions[:2]:  # 只尝试前两个问题
                try:
                    self.logger.debug(f"尝试备用问题: {question}")
                    
                    result = await self.rag_ps.rag.aquery(
                        question,
                        param=QueryParam(
                            mode="local",  # 使用更快的本地模式
                            response_type="中文回答",
                            enable_rerank=False
                        )
                    )
                    
                    if result and len(str(result).strip()) > 0:
                        answer = str(result).strip()
                        if self._is_valid_answer(answer, question):
                            extracted_value = self._extract_field_value(answer, field_name)
                            self.logger.info(f"{node_state}-=-填表员===字段 {field_name} 通过备用问题获得答案: {extracted_value}")
                            return extracted_value
                    
                except Exception as e:
                    self.logger.debug(f"备用问题查询失败: {e}")
                    continue
            
            self.logger.debug(f"字段 {field_name} 所有查询方式均未找到有效答案")
            return None
            
        except Exception as e:
            self.logger.error(f"查询字段值时发生异常: {e}")
            return None
    
    def _is_valid_answer(self, answer: str, question: str) -> bool:
        """判断答案是否有效"""
        if len(answer) < 2:
            return False
            
        # 过滤掉常见的无效回答
        invalid_responses = [
            "我不知道", "不清楚", "没有信息", "无法回答", "未提及", 
            "文档中没有", "没有相关信息", "无", "不详", "暂无",
            "未找到相关信息", "无相关信息", "找不到", "不存在"
        ]
        
        answer_lower = answer.lower()
        for invalid in invalid_responses:
            if invalid.lower() in answer_lower:
                return False
        
        # 检查是否只是重复问题
        if question and len(question) > 10:
            question_lower = question.lower()
            if question_lower in answer_lower or answer_lower in question_lower:
                return False
        
        # 检查答案长度是否合理（太短或太长都可能有问题）
        if len(answer) > 200:
            return False
        
        return True
    
    def _extract_field_value(self, answer: str, field_name: str) -> str:
        """从答案中提取字段值"""
        # 根据字段类型进行特定的值提取
        field_type = self.identify_field_type(field_name)
        
        if field_type == 'phone':
            return self._extract_phone_number(answer)
        elif field_type == 'email':
            return self._extract_email(answer)
        elif field_type == 'id_number':
            return self._extract_id_number(answer)
        elif field_type == 'birth_date':
            return self._extract_date(answer)
        elif field_type == 'name':
            return self._extract_name(answer)
        else:
            # 通用提取：返回简洁的答案
            return self._clean_answer(answer)
    
    def _extract_phone_number(self, text: str) -> str:
        """提取电话号码"""
        phone_pattern = r'1[3-9]\d{9}|0\d{2,3}-?\d{7,8}|\d{3,4}-\d{7,8}'
        match = re.search(phone_pattern, text)
        return match.group() if match else self._clean_answer(text)
    
    def _extract_email(self, text: str) -> str:
        """提取邮箱地址"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, text)
        return match.group() if match else self._clean_answer(text)
    
    def _extract_id_number(self, text: str) -> str:
        """提取身份证号"""
        id_pattern = r'\d{17}[\dXx]|\d{15}'
        match = re.search(id_pattern, text)
        return match.group() if match else self._clean_answer(text)
    
    def _extract_date(self, text: str) -> str:
        """提取日期"""
        date_patterns = [
            r'\d{4}[-年]\d{1,2}[-月]\d{1,2}[日]?',
            r'\d{4}/\d{1,2}/\d{1,2}',
            r'\d{1,2}/\d{1,2}/\d{4}'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group()
        
        return self._clean_answer(text)
    
    def _extract_name(self, text: str) -> str:
        """提取姓名"""
        # 查找中文姓名（2-4个汉字）
        name_pattern = r'[\u4e00-\u9fa5]{2,4}'
        matches = re.findall(name_pattern, text)
        
        if matches:
            # 返回最可能的姓名（通常是最短的匹配）
            return min(matches, key=len)
        
        return self._clean_answer(text)
    
    def _clean_answer(self, answer: str) -> str:
        """清理答案，提取核心信息"""
        # 移除常见的前缀和后缀
        prefixes = [
            '根据文档', '文档显示', '文档中提到', '根据信息', '信息显示',
            '根据提供的信息', '从文档中可以看出', '文档内容显示',
            '根据上下文', '从内容中可以知道', '据了解', '根据资料'
        ]
        suffixes = [
            '等信息', '等内容', '相关信息', '具体信息', '的信息',
            '等等', '之类的', '相关内容', '详细信息'
        ]
        
        cleaned = answer.strip()
        
        # 移除前缀
        for prefix in prefixes:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip('，。：、').strip()
                break
        
        # 移除后缀
        for suffix in suffixes:
            if cleaned.endswith(suffix):
                cleaned = cleaned[:-len(suffix)].strip('，。：、').strip()
                break
        
        # 移除冗余的标点符号
        cleaned = re.sub(r'^[，。：、]+', '', cleaned)
        cleaned = re.sub(r'[，。：、]+$', '', cleaned)
        
        # 如果答案包含冒号，可能格式是"字段名: 值"，提取值的部分
        if '：' in cleaned:
            parts = cleaned.split('：', 1)
            if len(parts) == 2 and len(parts[1].strip()) > 0:
                cleaned = parts[1].strip()
        elif ':' in cleaned:
            parts = cleaned.split(':', 1)
            if len(parts) == 2 and len(parts[1].strip()) > 0:
                cleaned = parts[1].strip()
        
        # 限制长度，避免过长的答案
        if len(cleaned) > 100:
            # 尝试在句号处截断
            sentences = cleaned.split('。')
            if len(sentences) > 1 and len(sentences[0]) <= 100:
                cleaned = sentences[0]
            else:
                cleaned = cleaned[:100] + "..."
        
        return cleaned

    async def _multi_modal_exploration(self, form_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        阶段1：多模态信息探索
        使用不同的查询模式收集相关信息
        """
        self.logger.info(f"{node_state}-=-填表员===🔍 阶段1：多模态信息探索")
        
        
        exploration_results = {}
        
        # 1.1 全局图谱探索 - 获取高层次实体和关系
        global_query = f"根据以下表单字段类型，总结相关的个人信息、组织信息和关键数据：{', '.join([f.get('name', '') for f in form_fields[:10]])}"
        
        async def global_exploration_operation():
            return await self.rag_ps.rag.aquery(
                global_query,
                param=QueryParam(mode="global", response_type="结构化总结", enable_rerank=False)
            )
        
        global_result_data = await self._execute_with_retry("全局图谱探索", global_exploration_operation)
        
        if global_result_data['success']:
            exploration_results['global_context'] = global_result_data['result']
            self.logger.info(f"{node_state}-=-填表员===✅ 全局图谱探索完成")
        else:
            self.logger.warning(f"{node_state}-=-填表员===⚠️ 全局图谱探索失败: {global_result_data['error']}")
            exploration_results['global_context'] = ""
        
        # 1.2 局部实体探索 - 查找具体的个人数据
        local_query = f"查找与这些字段相关的具体个人信息：姓名、联系方式、地址、工作信息、教育背景等"
        
        async def local_exploration_operation():
            return await self.rag_ps.rag.aquery(
                local_query,
                param=QueryParam(mode="local", response_type="详细信息", enable_rerank=True)
            )
        
        local_result_data = await self._execute_with_retry("局部实体探索", local_exploration_operation)
        
        if local_result_data['success']:
            exploration_results['local_details'] = local_result_data['result']
            self.logger.info(f"{node_state}-=-填表员===✅ 局部实体探索完成")
        else:
            self.logger.warning(f"⚠️ 局部实体探索失败: {local_result_data['error']}")
            exploration_results['local_details'] = ""
        
        # 1.3 原始文档探索 - 查找文档中的原始信息
        naive_query = f"从原始文档中查找可以填写表单的具体数据和信息"
        
        async def naive_exploration_operation():
            return await self.rag_ps.rag.aquery(
                naive_query,
                param=QueryParam(mode="naive", response_type="原始数据", enable_rerank=True)
            )
        
        naive_result_data = await self._execute_with_retry("原始文档探索", naive_exploration_operation)
        
        if naive_result_data['success']:
            exploration_results['document_content'] = naive_result_data['result']
            self.logger.info(f"{node_state}-=-填表员===✅ 原始文档探索完成")
        else:
            self.logger.warning(f"⚠️ 原始文档探索失败: {naive_result_data['error']}")
            exploration_results['document_content'] = ""
        
        return exploration_results
    
    async def _comprehensive_analysis(self, form_fields: List[Dict[str, Any]], 
                                    exploration_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段2：综合信息分析
        整合多种查询结果，分析表单填写策略
        """
        self.logger.info(f"{node_state}-=-填表员===🧠 阶段2：综合信息分析")
        
        
        
        # 构建综合分析prompt
        analysis_prompt = f"""
请基于以下多源信息，分析如何填写表单：

**全局上下文信息：**
{exploration_results.get('global_context', '无')}

**局部详细信息：**
{exploration_results.get('local_details', '无')}

**原始文档信息：**
{exploration_results.get('document_content', '无')}

**表单字段清单：**
{self._format_fields_for_analysis(form_fields)}

请分析：
1. 哪些字段可以直接填写，以及对应的数据源
2. 哪些字段需要推理计算
3. 哪些字段缺乏信息无法填写
4. 推荐的填写策略和优先级
"""

        async def comprehensive_analysis_operation():
            return await self.rag_ps.rag.aquery(
                analysis_prompt,
                param=QueryParam(
                    mode="hybrid",  # 混合模式进行综合分析
                    response_type="策略分析",
                    enable_rerank=True
                )
            )
        
        analysis_result_data = await self._execute_with_retry("综合信息分析", comprehensive_analysis_operation)
        
        if analysis_result_data['success']:
            self.logger.info(f"{node_state}-=-填表员===✅ 综合信息分析完成")
            return {
                'analysis_result': analysis_result_data['result'],
                'strategy': 'multi_source_integration'
            }
        else:
            self.logger.error(f"❌ 综合信息分析失败: {analysis_result_data['error']}")
            return {
                'analysis_result': "",
                'strategy': 'fallback'
            }
    
    async def _analyze_field_semantics(self, name:str, basic_info:str,
                                     form_fields: List[Dict[str, Any]], 
                                     document_content: str = None) -> Dict[str, Any]:
        """
        阶段2.5：深度字段语义分析
        在填写前先分析每个字段的真实含义
        """
        self.logger.info(f"{node_state}-=-填表员===🔍 阶段2.5：深度字段语义分析")
        
        try:

            
            # 构建字段分析提示
            analysis_prompt = f"""
你是一个专业的表单字段分析专家。请深度分析以下表单的字段结构和含义。

**🎯 重要身份信息：当前用户是{name}，所有涉及姓名的字段都应该填写"{name}"。**
用户{name}的基本信息：{basic_info}

**📋 原始表单内容：**
{document_content if document_content else '无原始内容'}

**📝 字段列表：**
{self._format_raw_fields_for_analysis(form_fields)}

**🎯 分析任务：**
1. 基于原始表单内容，确定每个field_X对应的真实含义
2. 分析字段的数据类型要求
3. 理解字段的位置和上下文关系
4. 识别容易混淆的字段

**📤 请按以下格式返回分析结果：**
```json
{{
    "field_semantics": {{
        "姓名": {{
            "meaning": "用户姓名",
            "data_type": "人名文本",
            "position": "基本信息第1项",
            "validation": "非空文本，2-10字符"
        }},
        "性别": {{
            "meaning": "用户性别", 
            "data_type": "性别选项",
            "position": "基本信息第2项",
            "validation": "男/女"
        }}
    }},
    "confusion_risks": [
        "年龄和手机号容易混淆（数字vs电话）",
        "身份证和学校容易混淆（长文本识别）"
    ],
    "confidence": "高"
}}
```
请开始分析：
"""
            
            # 调用LightRAG进行分析（使用重试机制）
            async def field_semantics_analysis_operation():
                return await self.rag_ps.rag.aquery(
                    analysis_prompt,
                    param=QueryParam(
                        mode="bypass",  # 使用bypass模式，纯LLM分析
                        response_type="字段语义分析"
                    )
                )
            
            analysis_result_data = await self._execute_with_retry("字段语义分析", field_semantics_analysis_operation)
            
            if analysis_result_data['success']:
                self.logger.info(f"{node_state}-=-填表员===✅ 字段语义分析完成")
                return {
                    'stage': 'field_semantic_analysis',
                    'success': True,
                    'raw_result': analysis_result_data['result']
                }
            else:
                self.logger.error(f"❌ 字段语义分析失败: {analysis_result_data['error']}")
                return {
                    'stage': 'field_semantic_analysis',
                    'success': False,
                    'error': analysis_result_data['error'],
                    'raw_result': None
                }
            
        except Exception as e:
            self.logger.error(f"❌ 字段语义分析异常: {e}")
            return {
                'stage': 'field_semantic_analysis',
                'success': False,
                'error': str(e),
                'raw_result': None
            }

    async def _intelligent_form_filling(self, name:str, basic_info:str, form_fields: List[Dict[str, Any]], 
                                      analysis_results: Dict[str, Any],
                                      document_content: str = None,
                                      field_semantics: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        阶段3：智能表单填写
        基于综合分析结果进行精确填写
        """
        self.logger.info(f"{node_state}-=-填表员===✍️ 阶段3：智能表单填写")
        
        
        
        # 获取语义分析结果用于更精确的填写
        semantic_info = ""
        if field_semantics and field_semantics.get('success'):
            semantic_info = f"""
**🔍 字段语义分析结果：**
{field_semantics.get('raw_result', '暂无语义分析结果')}
"""
        
        # 构建最终填写prompt
        filling_prompt = f"""
你是一个专业的表单填写专家。请基于字段语义分析结果和知识库信息进行**高精度**填写。

**🎯 重要身份信息：当前用户是{name}，所有涉及姓名的字段都必须填写"{name}"，不要使用任何示例中的假名。**

当前用户的基本信息：{basic_info}

**📋 原始表单内容：**
{document_content if document_content else ''}

{semantic_info}

**📊 表单字段结构：**
{self._format_fields_for_filling(form_fields)}

**📖 可用的知识库信息：**
{analysis_results.get('analysis_result', '')}

**🎯 精确填写策略：**

1. **严格按照语义分析结果理解字段含义**
2. **验证每个填写内容的数据类型和格式**
3. **避免字段内容错位和混淆**
4. **确保逻辑一致性和合理性**

**❌ 严禁以下错误行为：**
- 将姓名填入年龄字段
- 将手机号填入身份证字段  
- 将学校名称填入身份证字段
- 将工作年限填入年龄字段
- 将地址信息填入学历字段
- 混淆不同字段的语义含义

**✅ 正确填写原则：**
- 姓名字段 → 只填人名（如"李明"）
- 年龄字段 → 只填数字（如"25"）
- 手机号字段 → 只填11位数字（如"13800138001"）
- 身份证字段 → 只填18位身份证号（如"110101199001011234"）
- 根据字段的真实标签和语义来确定要填写的内容类型

**📤 请按严格的JSON格式返回：**
```json
{{
    "filled_fields": {{
        "姓名": "XXX",
        "年龄": "XX", 
        "手机号码": "xxxxxxxxxxx"
    }},
    "skipped_fields": ["联系地址"],
    "validation_check": {{
        "姓名": "人名格式正确",
        "年龄": "数字格式正确",
        "手机号码": "11位数字格式正确"
    }},
    "confidence_level": "高/中/低"
}}
```

请基于语义分析结果进行高精度填写："""
        
        try:
            # 第一步：获取LLM的详细分析和填写结果（使用重试机制）
            self.logger.info(f"{node_state}-=-填表员===🧠 第一步：获取LLM详细分析...")
            
            async def intelligent_filling_operation():
                return await self.rag_ps.rag.aquery(
                    filling_prompt,
                    param=QueryParam(
                        mode="hybrid",  # 使用混合模式获得最佳填写效果
                        response_type="详细分析",
                        enable_rerank=True
                    )
                )
            
            filling_result_data = await self._execute_with_retry("智能表单填写", intelligent_filling_operation)
            
            if not filling_result_data['success']:
                self.logger.error(f"❌ 智能表单填写失败: {filling_result_data['error']}")
                return {
                    'filled_fields': {},
                    'skipped_fields': [f.get('name', 'unknown') for f in form_fields],
                    'failed_fields': [],
                    'error': filling_result_data['error']
                }
                
            filling_result = filling_result_data['result']
            self.logger.info(f"{node_state}-=-填表员===📝 获得LLM分析结果，长度: {len(str(filling_result)) if filling_result else 0}字符")
            
            # 第二步：让LLM将分析结果转换为标准JSON格式
            self.logger.info(f"{node_state}-=-填表员===🔄 第二步：转换为标准JSON格式...")
            json_result = await self._convert_to_json_format(filling_result, form_fields)
            
            # 解析最终的JSON结果
            filled_fields, skipped_fields, failed_fields = self.parse_lightrag_response(json_result, form_fields)
            
            self.logger.info(f"{node_state}-=-填表员===✅ 智能表单填写完成")
            return {
                'filled_fields': filled_fields,
                'skipped_fields': skipped_fields,
                'failed_fields': failed_fields,
                'raw_response': filling_result,
                'json_response': json_result
            }
            
        except Exception as e:
            self.logger.error(f"❌ 智能表单填写异常: {e}")
            return {
                'filled_fields': {},
                'skipped_fields': [f.get('name', 'unknown') for f in form_fields],
                'failed_fields': [],
                'error': str(e)
            }
    
    def _format_fields_for_analysis(self, form_fields: List[Dict[str, Any]]) -> str:
        """格式化字段用于分析阶段"""
        formatted = []
        for i, field in enumerate(form_fields, 1):
            if not isinstance(field, dict):
                continue
            name = field.get('name', f'field_{i}')
            type_info = field.get('type', 'unknown')
            description = field.get('description', '')
            formatted.append(f"{i}. {name} ({type_info}) - {description}")
        return "\n".join(formatted)
    
    def _format_raw_fields_for_analysis(self, form_fields: List[Dict[str, Any]]) -> str:
        """格式化原始字段列表用于语义分析"""
        formatted = []
        for field in form_fields:
            if not isinstance(field, dict):
                continue
            field_name = field.get('name', '')
            field_type = field.get('type', 'text')
            field_desc = field.get('description', '')
            field_required = '必填' if field.get('required', False) else '可选'
            
            formatted.append(f"- {field_name} ({field_type}) [{field_required}] - {field_desc}")
        
        return "\n".join(formatted)

    def _format_fields_for_filling(self, form_fields: List[Dict[str, Any]]) -> str:
        """格式化字段用于填写阶段，直接使用真实字段名和语义"""
        formatted = []
        for field in form_fields:
            if not isinstance(field, dict):
                continue
            # 优先使用真实字段名，而不是抽象代号
            field_id = field.get('id', 'unknown')
            field_name = field.get('name', field_id)
            field_label = field.get('label', '')
            type_info = field.get('type', 'text')
            description = field.get('description', '')
            required = field.get('required', False)
            
            # 使用真实的字段标签作为主要信息
            display_name = field_label if field_label else field_name
            
            field_info = f"- **{field_name}** ({display_name})"
            if type_info != 'text':
                field_info += f" [类型: {type_info}]"
            if required:
                field_info += " [必填]"
            if description:
                field_info += f" - {description}"
            
            formatted.append(field_info)
        return "\n".join(formatted)
    
    def _infer_field_semantic(self, field_name: str, description: str, label: str, field_type: str) -> str:
        """智能推断字段的语义含义"""
        # 合并所有可用信息
        all_text = f"{field_name} {description} {label}".lower().strip()
        
        # 字段语义映射（基于关键词匹配）
        semantic_mapping = {
            '姓名': ['姓名', 'name', '名字', '称呼', '全名', '真实姓名', '用户名'],
            '性别': ['性别', 'gender', 'sex', '男女'],
            '年龄': ['年龄', 'age', '岁数', '岁'],
            '出生日期': ['出生', '生日', 'birth', 'birthday', '生年月日', '出生日期'],
            '身份证号': ['身份证', '证件号', 'id', 'identity', '身份证号', '证件号码'],
            '手机号码': ['电话', '手机', '联系方式', 'phone', 'mobile', 'tel', '联系电话', '手机号', '电话号码'],
            '电子邮箱': ['邮箱', '邮件', 'email', 'mail', '电子邮件', '邮件地址', '电子邮箱'],
            '联系地址': ['地址', '住址', 'address', 'addr', '详细地址', '居住地址', '家庭住址', '现住址'],
            '工作单位': ['公司', '单位', 'employer', 'company', '工作单位', '所在公司', '雇主', '企业'],
            '职位职务': ['职位', '职务', 'position', 'job', 'title', '岗位', '工作', '职业'],
            '部门': ['部门', 'department', '科室', '处室', '所属部门'],
            '工作年限': ['工作年限', '年限', '工作经验', '工作时间', '从业年限'],
            '最高学历': ['学历', '教育', 'education', 'degree', '教育背景', '学位', '最高学历'],
            '毕业院校': ['学校', '院校', 'school', 'university', '大学', '毕业院校', '就读学校'],
            '所学专业': ['专业', 'major', '所学专业', '学科', '专业方向'],
            '毕业时间': ['毕业时间', '毕业日期', 'graduation', '完成学业时间'],
            '紧急联系人': ['紧急联系人', '联系人', '紧急联系', '应急联系人'],
            '联系人电话': ['联系人电话', '紧急电话', '联系人手机'],
            '特殊说明': ['特殊说明', '备注', '说明', '其他', '补充信息', '附加说明'],
            '申请人签名': ['签名', '签字', 'signature', '申请人签名'],
            '申请日期': ['申请日期', '日期', 'date', '填写日期', '提交日期']
        }
        
        # 尝试匹配最佳语义
        best_match = None
        max_score = 0
        
        for semantic, keywords in semantic_mapping.items():
            score = 0
            for keyword in keywords:
                if keyword in all_text:
                    score += len(keyword)  # 更长的匹配得分更高
                    
            if score > max_score:
                max_score = score
                best_match = semantic
        
        # 如果有匹配，返回语义含义
        if best_match and max_score > 0:
            return best_match
        
        # 没有匹配时的处理策略
        # 如果是老式的field_X格式，尝试根据位置推断（向后兼容）
        if field_name.startswith('field_') and '_' in field_name:
            try:
                field_num = int(field_name.split('_')[1])
                # 提供位置推断作为备选方案，但优先使用真实标签
                position_mapping = {
                    1: '姓名', 2: '性别', 3: '年龄', 4: '出生日期', 5: '身份证号',
                    6: '手机号码', 7: '电子邮箱', 8: '联系地址', 9: '工作单位', 10: '职位职务',
                    11: '部门', 12: '工作年限', 13: '最高学历', 14: '毕业院校', 15: '所学专业',
                    16: '毕业时间', 17: '紧急联系人', 18: '联系人电话', 19: '特殊说明',
                    20: '申请人签名', 21: '申请日期'
                }
                if field_num in position_mapping:
                    return f"{position_mapping[field_num]}(位置推断)"
            except (ValueError, IndexError):
                pass
        
        # 最后的后备方案：使用description或label
        if description and description.strip():
            return description.strip()
        elif label and label.strip():
            return label.strip()
        else:
            return f"未知字段 ({field_name})"

    async def _convert_to_json_format(self, analysis_result: str, form_fields: List[Dict[str, Any]]) -> str:
        """
        第二阶段：将LLM的分析结果转换为标准JSON格式
        这是专门的格式转换步骤，确保输出符合要求
        """
        self.logger.info(f"{node_state}-=-填表员===🔄 开始JSON格式转换...")
        
        
        
        # 构建专门的JSON转换prompt
        conversion_prompt = f"""
你需要将分析结果转换为严格的JSON格式。重点关注字段的语义含义映射。

**原始分析结果：**
{analysis_result}

**🎯 字段含义映射（关键）：**
{self._format_fields_for_filling(form_fields)}

**🔧 转换指导原则：**
1. **字段理解**：根据"字段名 -> 含义"映射来理解要填写的内容
2. **值提取**：从分析结果中提取与字段含义匹配的精确值
3. **质量控制**：
   - 姓名字段只填名字，不填职业描述
   - 手机号只填11位数字
   - 工作年限填数字，不填年份
   - 地址填具体地址，不填公司描述

**📋 严格JSON格式（只返回此JSON，无其他文字）：**
{{
    "filled_fields": {{
        "姓名": "XXX",
        "手机号码": "xxxxxxxx"
    }},
    "skipped_fields": ["联系地址", "紧急联系人"],
    "reasoning": {{
        "姓名": "从知识库中提取的用户姓名：用户名",
        "手机号码": "文档中明确的联系电话"
    }}
}}

现在请直接输出JSON：
"""
        
        try:
            # 使用bypass模式进行简单的格式转换，避免额外的知识检索
            json_result = await self.rag_ps.rag.aquery(
                conversion_prompt,
                param=QueryParam(
                    mode="bypass",  # 直接使用LLM，不做知识检索
                    response_type="JSON",
                    enable_rerank=False
                )
            )
            
            self.logger.info(f"{node_state}-=-填表员===✅ JSON转换完成，结果长度: {len(str(json_result)) if json_result else 0}字符")
            self.logger.debug(f"{node_state}-=-填表员===JSON转换结果预览: {str(json_result)[:200]}...")
            
            return str(json_result) if json_result else "{}"
            
        except Exception as e:
            self.logger.error(f"❌ JSON格式转换失败: {e}")
            # 如果转换失败，返回一个基本的空JSON结构
            return '{"filled_fields": {}, "skipped_fields": [], "reasoning": {}}'
    
    def _format_fields_list_for_conversion(self, form_fields: List[Dict[str, Any]]) -> str:
        """为JSON转换格式化字段列表，使用语义理解"""
        formatted_fields = []
        for field in form_fields:
            if not isinstance(field, dict):
                continue
            name = field.get('name', 'unknown')
            field_type = field.get('type', 'text')
            description = field.get('description', '')
            label = field.get('label', '')
            
            # 使用语义分析
            semantic_meaning = self._infer_field_semantic(name, description, label, field_type)
            formatted_fields.append(f"- {name} -> {semantic_meaning}")
        return "\n".join(formatted_fields)

    @performance_monitor
    @error_handler()
    async def fill_form_fields(self, name:str, basic_info:str, form_fields: List[Dict[str, Any]], 
                             document_content: str = None, 
                             document_path: str = None) -> Dict[str, Any]:
        """
        使用LightRAG问答填充表单字段
        
        Args:
            form_fields: 表单字段列表
            document_content: 文档内容（如果需要插入知识图谱）
            document_path: 文档路径
            
        Returns:
            Dict: 填充结果
        """
        start_time = datetime.now()
        self.logger.info(f"{node_state}-=-填表员===开始使用LightRAG问答方式填充 {len(form_fields)} 个表单字段")
        
        try:
            # 确保LightRAG已初始化（如果没有外部实例才会重新初始化）
            self.logger.info(f"{node_state}-=-填表员===调试: _initialized={self._initialized}, lightrag={self.rag_ps is not None}")
            
            # 确保LightRAG已初始化（单例管理器会处理事件循环兼容性）
            if not self._initialized:
                self.logger.info(f"{node_state}-=-填表员===LightRAG未初始化，通过单例管理器初始化...")
                if not await self.initialize():
                    return {
                        'success': False,
                        'error': 'LightRAG初始化失败',
                        'filled_fields': {},
                        'skipped_fields': [],
                        'failed_fields': []
                    }
            else:
                self.logger.info(f"{node_state}-=-填表员===LightRAG已通过单例管理器初始化，直接使用")
            
            # 🎯 三阶段综合推理流程
            self.logger.info(f"{node_state}-=-填表员===🎯 启动三阶段综合推理流程：探索 → 分析 → 填写")
            
            # 阶段1：多模态信息探索
            self.logger.info(f"{node_state}-=-填表员===🔍 阶段1：多模态信息探索开始...")
            exploration_results = await self._multi_modal_exploration(form_fields)
            
            # 阶段2：综合信息分析  
            self.logger.info(f"{node_state}-=-填表员===🧠 阶段2：综合信息分析开始...")
            analysis_results = await self._comprehensive_analysis(form_fields, exploration_results)
            
            # 阶段2.5：字段语义分析
            self.logger.info(f"{node_state}-=-填表员===🔍 阶段2.5：字段语义分析开始...")
            semantic_results = await self._analyze_field_semantics(name, basic_info, form_fields, document_content)
            
            # 阶段3：智能表单填写
            self.logger.info(f"{node_state}-=-填表员===✍️ 阶段3：智能表单填写开始...")
            filling_results = await self._intelligent_form_filling(name, basic_info, form_fields, analysis_results, document_content, semantic_results)
            
            # 获取综合推理的结果
            filled_fields = filling_results.get('filled_fields', {})
            skipped_fields = filling_results.get('skipped_fields', [])
            failed_fields = filling_results.get('failed_fields', [])
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(f"{node_state}-=-填表员===📥 LightRAG综合推理完成，处理结果: 成功{len(filled_fields)}个, 跳过{len(skipped_fields)}个, 失败{len(failed_fields)}个")
            
            # 构建最终结果，包含完整的推理过程信息
            # 成功标准：只要三阶段推理流程正常完成，就算成功（即使没有填充任何字段）
            # 因为知识图谱中可能确实没有相关信息，这是正常情况
            is_success = True  # 默认为成功，除非有明确的错误
            
            # 检查是否有明确的错误（不包括简单的字段未填写）
            if 'error' in filling_results and filling_results['error']:
                is_success = False
                self.logger.warning(f"{node_state}-=-填表员===填写阶段出现错误: {filling_results['error']}")
            
            # 无需后处理，在填写阶段已经进行了充分的思考和验证
            self.logger.info(f"{node_state}-=-填表员===✅ 智能填写完成，已在填写阶段进行充分思考")
            
            # 记录成功标准
            if len(filled_fields) == 0:
                self.logger.info(f"{node_state}-=-填表员===📝 虽然没有填写字段，但推理流程正常完成，标记为成功")
            else:
                self.logger.info(f"{node_state}-=-填表员===📝 推理流程完成且成功填写{len(filled_fields)}个字段")
            
            final_result = {
                'success': is_success,
                'filled_fields': filled_fields,
                'skipped_fields': skipped_fields,
                'failed_fields': failed_fields,
                'processing_time': processing_time,
                'method': 'lightrag_comprehensive_reasoning_with_context',
                'reasoning_stages': {
                    'exploration': exploration_results,
                    'analysis': analysis_results,
                    'semantic_analysis': semantic_results,
                    'filling': filling_results
                },
                'statistics': {
                    'total_fields': len(form_fields),
                    'filled_count': len(filled_fields),
                    'skipped_count': len(skipped_fields),
                    'failed_count': len(failed_fields),
                    'success_rate': len(filled_fields) / len(form_fields) if form_fields else 0
                },
                'timestamp': datetime.now().isoformat(),
                'warnings': []
            }
            
            # 添加调试信息
            self.logger.info(f"{node_state}-=-填表员===🔍 最终结果构建完成: success={is_success}, filled_count={len(filled_fields)}")
            self.logger.debug(f"{node_state}-=-填表员===🔍 完整结果键值: {list(final_result.keys())}")
            
            # 添加警告信息
            if len(failed_fields) > 0:
                final_result['warnings'].append(f"有 {len(failed_fields)} 个字段填写失败")
            if len(skipped_fields) > 0:
                final_result['warnings'].append(f"有 {len(skipped_fields)} 个字段被跳过")
            
            self.logger.info(
                f"{node_state}-=-填表员===✅ LightRAG综合推理表单填充完成: {len(filled_fields)}/{len(form_fields)} 字段成功填充 "
                f"(耗时 {processing_time:.2f}s, 成功率 {final_result['statistics']['success_rate']:.1%})"
            )
            
            return final_result
            
        except Exception as e:
            import traceback
            error_msg = f"LightRAG问答填充过程异常: {e}"
            self.logger.error(error_msg)
            self.logger.error(f"详细错误堆栈: {traceback.format_exc()}")
            
            return {
                'success': False,
                'error': error_msg,
                'filled_fields': {},
                'skipped_fields': [],
                'failed_fields': [],
                'processing_time': (datetime.now() - start_time).total_seconds(),
                'method': 'lightrag_comprehensive_reasoning',
                'exception_details': str(e)
            }
    
 