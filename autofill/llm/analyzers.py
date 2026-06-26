"""
LLM分析器模块

使用大语言模型进行智能分析，包括：
- 表单结构分析
- 信息提取
- 字段匹配
- 内容分析
"""

import json
import re
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass

from .base import BaseLLMClient, LLMMessage, LLMRequest, MessageRole, ProcessingStatus
from .prompt_manager import get_prompt_manager, PromptType
from ..core import BaseAnalyzer
from ..utils.logger import get_logger, performance_monitor
from src.utils.db_manager import node_state

@dataclass
class AnalysisResult:
    """分析结果数据结构"""
    success: bool
    data: Dict[str, Any]
    confidence: float = 0.0
    error_message: Optional[str] = None
    raw_response: Optional[str] = None
    processing_time: float = 0.0


class FormLLMAnalyzer(BaseAnalyzer):
    """表单分析器"""
    
    def __init__(self, llm_client: BaseLLMClient, config: Dict[str, Any] = None):
        """
        初始化表单分析器
        
        Args:
            llm_client: LLM客户端
            config: 配置信息
        """
        super().__init__(config)
        self.llm_client = llm_client
        self.prompt_manager = get_prompt_manager()
        self.logger = get_logger(self.__class__.__name__)
    
    def process(self, input_data: Any) -> Dict[str, Any]:
        """处理输入数据并返回结果（实现抽象方法）"""
        if isinstance(input_data, dict):
            return self.analyze(input_data)
        else:
            return self.analyze({'form_content': input_data})
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性（实现抽象方法）"""
        return input_data is not None
    
    @performance_monitor()
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析表单结构
        
        Args:
            data: 包含表单内容的数据
            
        Returns:
            Dict[str, Any]: 分析结果
        """
        form_content = data.get('form_content', '')
        if not form_content:
            return self._create_error_result("表单内容不能为空")
        
        try:
            # 使用提示词模板
            prompt = self.prompt_manager.format_prompt(
                'form_structure_analysis',
                form_content=form_content
            )
            
            print(prompt)
            # 发送请求到LLM
            response = self.llm_client.simple_chat(prompt)
            
            if response:
                # 解析JSON响应
                analysis_result = self._parse_json_response(response)
                
                return {
                    'success': True,
                    'form_structure': analysis_result,
                    'confidence': self._calculate_confidence(analysis_result),
                    'raw_response': response
                }
            else:
                return self._create_error_result("LLM响应为空")
                
        except Exception as e:
            self.logger.error(f"表单分析失败: {e}", exc_info=True)
            return self._create_error_result(f"分析失败: {e}")
    
    def analyze_form(self, form_content: str) -> Dict[str, Any]:
        """
        分析表单内容（analyze方法的别名）
        
        Args:
            form_content: 表单内容
            
        Returns:
            Dict[str, Any]: 分析结果
        """
        return self.analyze({'form_content': form_content})
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据"""
        if not isinstance(input_data, dict):
            return False
        return 'form_content' in input_data and input_data['form_content'].strip()
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        try:
            # 尝试直接解析JSON
            return json.loads(response)
        except json.JSONDecodeError:
            # 如果直接解析失败，尝试提取JSON部分
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            
            # 如果都失败了，返回原始响应
            return {"raw_text": response, "parsed": False}
    
    def _calculate_confidence(self, result: Dict[str, Any]) -> float:
        """计算分析结果的置信度"""
        if not isinstance(result, dict) or result.get('parsed') is False:
            return 0.1
        
        confidence = 0.5  # 基础置信度
        
        # 如果有字段信息，增加置信度
        if 'fields' in result and isinstance(result['fields'], list):
            field_count = len(result['fields'])
            confidence += min(0.3, field_count * 0.1)
        
        # 如果有表单标题，增加置信度
        if 'form_title' in result and result['form_title']:
            confidence += 0.1
        
        # 如果有表单类型，增加置信度
        if 'form_type' in result and result['form_type']:
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _create_error_result(self, error_message: str) -> Dict[str, Any]:
        """创建错误结果"""
        return {
            'success': False,
            'error_message': error_message,
            'form_structure': {},
            'confidence': 0.0
        }


class InfoExtractor(BaseAnalyzer):
    """信息提取器"""
    
    def __init__(self, llm_client: BaseLLMClient, config: Dict[str, Any] = None):
        """
        初始化信息提取器
        
        Args:
            llm_client: LLM客户端
            config: 配置信息
        """
        super().__init__(config)
        self.llm_client = llm_client
        self.prompt_manager = get_prompt_manager()
        self.logger = get_logger(self.__class__.__name__)
    
    def process(self, input_data: Any) -> Dict[str, Any]:
        """处理输入数据并返回结果（实现抽象方法）"""
        if isinstance(input_data, dict):
            return self.analyze(input_data)
        else:
            return self.analyze({'content': input_data})
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性（实现抽象方法）"""
        return input_data is not None
    
    @performance_monitor()
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从文档中提取用户信息
        
        Args:
            data: 包含文档内容的数据
            
        Returns:
            Dict[str, Any]: 提取结果
        """
        document_content = data.get('document_content', '')
        if not document_content:
            return self._create_error_result("文档内容不能为空")
        
        try:
            # 使用提示词模板
            prompt = self.prompt_manager.format_prompt(
                'user_info_extraction',
                document_content=document_content
            )
            
            # 发送请求到LLM
            response = self.llm_client.simple_chat(prompt)
            
            if response:
                # 解析JSON响应
                extraction_result = self._parse_json_response(response)
                
                return {
                    'success': True,
                    'extracted_info': extraction_result,
                    'overall_confidence': self._calculate_extraction_confidence(extraction_result),
                    'raw_response': response
                }
            else:
                return self._create_error_result("LLM响应为空")
                
        except Exception as e:
            self.logger.error(f"信息提取失败: {e}", exc_info=True)
            return self._create_error_result(f"提取失败: {e}")
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据"""
        if not isinstance(input_data, dict):
            return False
        return 'document_content' in input_data and input_data['document_content'].strip()
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取JSON部分
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            
            return {"raw_text": response, "parsed": False}
    
    def _calculate_extraction_confidence(self, result: Dict[str, Any]) -> float:
        """计算提取结果的整体置信度"""
        if not isinstance(result, dict) or result.get('parsed') is False:
            return 0.1
        
        personal_info = result.get('personal_info', {})
        confidence_scores = result.get('confidence', {})
        
        if not personal_info:
            return 0.1
        
        # 计算有效信息的数量和平均置信度
        valid_info_count = 0
        total_confidence = 0.0
        
        for key, value in personal_info.items():
            if value and value != "null":
                valid_info_count += 1
                field_confidence = confidence_scores.get(key, 0.5)
                total_confidence += field_confidence
        
        if valid_info_count == 0:
            return 0.1
        
        avg_confidence = total_confidence / valid_info_count
        
        # 根据信息完整度调整置信度
        completeness_bonus = min(0.2, valid_info_count * 0.05)
        
        return min(avg_confidence + completeness_bonus, 1.0)
    
    def _create_error_result(self, error_message: str) -> Dict[str, Any]:
        """创建错误结果"""
        return {
            'success': False,
            'error_message': error_message,
            'extracted_info': {},
            'overall_confidence': 0.0
        }


class FieldMatcher(BaseAnalyzer):
    """字段匹配器"""
    
    def __init__(self, llm_client: BaseLLMClient, config: Dict[str, Any] = None):
        """
        初始化字段匹配器
        
        Args:
            llm_client: LLM客户端
            config: 配置信息
        """
        super().__init__(config)
        self.llm_client = llm_client
        self.prompt_manager = get_prompt_manager()
        self.logger = get_logger(self.__class__.__name__)
        self.relevance_scorer = InfoRelevanceScorer()
        self.context_analyzer = FormContextAnalyzer()

    def process(self, input_data: Any) -> Dict[str, Any]:
        """处理输入数据并返回结果（实现抽象方法）"""
        if isinstance(input_data, dict):
            return self.analyze(input_data)
        else:
            return self.analyze({'data': input_data})
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性（实现抽象方法）"""
        return input_data is not None
    
    @performance_monitor()
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        匹配用户信息到表单字段
        
        Args:
            data: 包含用户信息和表单字段的数据
            
        Returns:
            Dict[str, Any]: 匹配结果
        """
        user_info = data.get('user_info', {})
        form_fields = data.get('form_fields', [])
        form_context = data.get('form_context', {})
        
        if not user_info or not form_fields:
            return self._create_error_result("用户信息或表单字段不能为空")
        
        # 记录输入的用户数据，确保LLM只使用这些数据
        self.logger.info(f"{node_state}-=-填表员===开始字段匹配 - 用户数据项数: {len(user_info)}, 表单字段数: {len(form_fields)}")
        
        try:
            # 1. 分析表单上下文和结构
            form_analysis = self.context_analyzer.analyze_form_context(form_fields, form_context)
            
            # 2. 为每个字段筛选最相关的用户信息
            optimized_matches = []
            for field in form_fields:
                relevant_info = self.relevance_scorer.get_relevant_info(
                    field, user_info, form_analysis
                )
                optimized_matches.append({
                    'field': field,
                    'relevant_info': relevant_info,
                    'context_hints': form_analysis.get(field.get('id', ''), {})
                })
            
            # 3. 构建明确的提示词，强调只使用提供的数据
            prompt = self.prompt_manager.format_prompt(
                'data_driven_field_matching',  # 使用新的提示词模板
                form_type=form_analysis.get('form_type', 'unknown'),
                form_structure=form_analysis.get('structure', {}),
                available_user_data=user_info,  # 明确传递可用的用户数据
                field_matches=optimized_matches,
                confidence_threshold=0.7
            )
            
            # 发送请求到LLM - 强调LLM的角色是匹配而不是生成
            self.logger.info(f"{node_state}-=-填表员===发送字段匹配请求到LLM - 仅基于提供的用户数据进行匹配")
            response = self.llm_client.simple_chat(prompt)
            
            if response:
                # 解析JSON响应
                matching_result = self._parse_json_response(response)
                
                # 检查解析是否成功
                if matching_result.get('parsed') is False:
                    self.logger.error("LLM响应JSON解析失败，尝试手动提取信息")
                    # 尝试从原始文本中提取有用信息
                    matching_result = self._extract_matches_from_text(matching_result.get('raw_text', ''))
                
                # 4. 验证匹配结果，确保所有值都来自于输入的用户数据
                validated_result = self._validate_matches_against_source_data(
                    matching_result, user_info, form_analysis
                )
                
                return {
                    'success': True,
                    'matching_result': validated_result,
                    'form_analysis': form_analysis,
                    'source_user_data': user_info,  # 保留原始用户数据供验证
                    'optimization_stats': self.relevance_scorer.get_stats(),
                    'overall_confidence': self._calculate_matching_confidence(validated_result),
                    'raw_response': response
                }
            else:
                return self._create_error_result("LLM响应为空")
                
        except Exception as e:
            self.logger.error(f"字段匹配失败: {e}", exc_info=True)
            return self._create_error_result(f"匹配失败: {e}")
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据"""
        if not isinstance(input_data, dict):
            return False
        
        user_info = input_data.get('user_info')
        form_fields = input_data.get('form_fields')
        
        return (isinstance(user_info, dict) and user_info and
                isinstance(form_fields, list) and form_fields)
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        if not response:
            return {"raw_text": "", "parsed": False}
        
        # 记录原始响应用于调试
        self.logger.debug(f"原始LLM响应: {response[:500]}")
        
        # 尝试直接解析
        try:
            result = json.loads(response)
            self.logger.info(f"{node_state}-=-填表员===JSON直接解析成功")
            return result
        except json.JSONDecodeError as e:
            self.logger.warning(f"JSON直接解析失败: {e}")
        
        # 尝试提取JSON代码块
        json_patterns = [
            r'```json\s*(.*?)\s*```',  # ```json ... ```
            r'```\s*(.*?)\s*```',      # ``` ... ```
            r'\{.*\}',                 # { ... }
        ]
        
        for pattern in json_patterns:
            json_match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
            if json_match:
                json_str = json_match.group(1) if pattern.startswith(r'```') else json_match.group()
                try:
                    result = json.loads(json_str)
                    self.logger.info(f"{node_state}-=-填表员===JSON通过模式 '{pattern}' 解析成功")
                    return result
                except json.JSONDecodeError as e:
                    self.logger.warning(f"模式 '{pattern}' 解析失败: {e}")
                    continue
        
        # 如果所有解析都失败，返回原始文本
        self.logger.error("所有JSON解析尝试都失败，返回原始文本")
        return {"raw_text": response, "parsed": False}
    
    def _calculate_matching_confidence(self, result: Dict[str, Any]) -> float:
        """计算匹配结果的置信度"""
        if not isinstance(result, dict) or result.get('parsed') is False:
            return 0.1
        
        matches = result.get('matches', [])
        if not matches:
            return 0.1
        
        # 计算匹配的平均置信度
        total_confidence = 0.0
        exact_matches = 0
        
        for match in matches:
            if isinstance(match, dict):
                confidence = match.get('confidence', 0.5)
                total_confidence += confidence
                
                if match.get('match_type') == 'exact':
                    exact_matches += 1
        
        if len(matches) == 0:
            return 0.1
        
        avg_confidence = total_confidence / len(matches)
        
        # 精确匹配奖励
        exact_bonus = min(0.2, exact_matches * 0.1)
        
        return min(avg_confidence + exact_bonus, 1.0)
    
    def _create_error_result(self, error_message: str) -> Dict[str, Any]:
        """创建错误结果"""
        return {
            'success': False,
            'error_message': error_message,
            'matching_result': {},
            'overall_confidence': 0.0
        }

    def _extract_matches_from_text(self, text: str) -> Dict[str, Any]:
        """从原始文本中手动提取匹配信息"""
        matches = []
        
        # 查找字段匹配模式
        patterns = [
            r'"field_id":\s*"([^"]+)".*?"matched_value":\s*"([^"]+)"',
            r'"field_name":\s*"([^"]+)".*?"matched_value":\s*"([^"]+)"',
            r'字段:\s*([^\n,]+).*?值:\s*([^\n,]+)',
            r'匹配:\s*([^\n:]+):\s*([^\n,]+)',
        ]
        
        for pattern in patterns:
            pattern_matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
            for match in pattern_matches:
                if len(match) >= 2:
                    field_name = match[0].strip()
                    matched_value = match[1].strip()
                    
                    if field_name and matched_value:
                        matches.append({
                            'field_name': field_name,
                            'matched_value': matched_value,
                            'match_type': 'text_extracted',
                            'confidence': 0.6,  # 降低置信度因为是文本提取
                            'reasoning': '从LLM文本响应中提取'
                        })
        
        # 移除重复项
        unique_matches = []
        seen_fields = set()
        for match in matches:
            field_name = match['field_name']
            if field_name not in seen_fields:
                unique_matches.append(match)
                seen_fields.add(field_name)
        
        self.logger.info(f"{node_state}-=-填表员===从文本中提取到 {len(unique_matches)} 个匹配")
        
        return {
            'matches': unique_matches,
            'unmatched_fields': [],
            'data_coverage': {
                'total_fields': len(unique_matches),
                'matched_fields': len(unique_matches),
                'coverage_rate': '100%' if unique_matches else '0%'
            },
            'extraction_method': 'text_parsing'
        }

    def _validate_and_enhance_matches(self, matching_result: Dict[str, Any], 
                                     form_analysis: Dict[str, Any],
                                     user_info: Dict[str, Any]) -> Dict[str, Any]:
        """验证和增强匹配结果"""
        if not matching_result or 'matches' not in matching_result:
            return matching_result
            
        enhanced_matches = []
        for match in matching_result.get('matches', []):
            # 添加字段位置信息
            if 'position_context' in form_analysis:
                field_id = match.get('field_name', '')
                match['position_info'] = form_analysis['position_context'].get(field_id, {})
            
            # 重新评估置信度
            enhanced_confidence = self.relevance_scorer.calculate_match_confidence(
                match, form_analysis, user_info
            )
            match['enhanced_confidence'] = enhanced_confidence
            
            enhanced_matches.append(match)
        
        matching_result['matches'] = enhanced_matches
        return matching_result

    def _validate_matches_against_source_data(self, matching_result: Dict[str, Any], 
                                              user_info: Dict[str, Any],
                                              form_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """验证匹配结果是否仅包含来自输入用户数据的信息"""
        if not matching_result or 'matches' not in matching_result:
            return matching_result

        validated_matches = []
        invalid_matches = []
        
        for match in matching_result.get('matches', []):
            field_name = match.get('field_name', '')
            match_value = match.get('matched_value', match.get('value', ''))
            
            # 如果值为空或None，标记为需要数据
            if not match_value:
                invalid_matches.append({
                    'field_name': field_name,
                    'reason': '用户数据中无对应信息',
                    'status': 'no_data_available'
                })
                continue

            # 验证值是否来自用户数据
            if not self._is_value_from_user_data(match_value, user_info):
                self.logger.warning(f"字段 '{field_name}' 的匹配值 '{match_value}' 不是来自用户数据，疑似LLM生成")
                invalid_matches.append({
                    'field_name': field_name,
                    'rejected_value': match_value,
                    'reason': '值不存在于用户数据中，疑似AI生成',
                    'status': 'data_validation_failed'
                })
                continue

            # 添加源路径追踪
            source_path = self._find_source_path(match_value, user_info)
            if source_path:
                match['source_path'] = source_path
                match['data_verification'] = 'verified_from_source'
            else:
                match['data_verification'] = 'verification_uncertain'

            # 记录验证通过的匹配
            self.logger.info(f"{node_state}-=-填表员===字段 '{field_name}' 验证通过: '{match_value}' 来源于 {source_path}")
            validated_matches.append(match)

        # 更新匹配结果
        matching_result['matches'] = validated_matches
        matching_result['invalid_matches'] = invalid_matches
        matching_result['validation_summary'] = {
            'total_attempted': len(matching_result.get('matches', [])),
            'validated_matches': len(validated_matches),
            'invalid_matches': len(invalid_matches),
            'validation_rate': len(validated_matches) / max(len(matching_result.get('matches', [])), 1) * 100
        }
        
        return matching_result

    def _is_value_from_user_data(self, value: Any, user_info: Dict[str, Any]) -> bool:
        """检查值是否来自用户数据"""
        if not value or not isinstance(value, str):
            return False
        
        value = str(value).strip()
        if not value:
            return False
            
        # 递归搜索用户数据中的所有值
        def search_in_data(data, search_value):
            if isinstance(data, dict):
                for key, val in data.items():
                    if isinstance(val, str) and val.strip() == search_value:
                        return True
                    elif isinstance(val, (dict, list)):
                        if search_in_data(val, search_value):
                            return True
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, str) and item.strip() == search_value:
                        return True
                    elif isinstance(item, (dict, list)):
                        if search_in_data(item, search_value):
                            return True
            elif isinstance(data, str) and data.strip() == search_value:
                return True
            return False
        
        return search_in_data(user_info, value)
    
    def _find_source_path(self, value: Any, user_info: Dict[str, Any], path: str = "") -> Optional[str]:
        """找到用户数据中值的路径"""
        if not value or not isinstance(value, str):
            return None
            
        value = str(value).strip()
        if not value:
            return None
            
        def find_path(data, search_value, current_path=""):
            if isinstance(data, dict):
                for key, val in data.items():
                    new_path = f"{current_path}.{key}" if current_path else key
                    if isinstance(val, str) and val.strip() == search_value:
                        return new_path
                    elif isinstance(val, (dict, list)):
                        result = find_path(val, search_value, new_path)
                        if result:
                            return result
            elif isinstance(data, list):
                for i, item in enumerate(data):
                    new_path = f"{current_path}[{i}]" if current_path else f"[{i}]"
                    if isinstance(item, str) and item.strip() == search_value:
                        return new_path
                    elif isinstance(item, (dict, list)):
                        result = find_path(item, search_value, new_path)
                        if result:
                            return result
            return None
        
        return find_path(user_info, value)


class InfoRelevanceScorer:
    """信息相关性评分器"""
    
    def __init__(self):
        self.field_importance_weights = {
            'name': 1.0,
            'phone': 0.9,
            'email': 0.9,
            'id_card': 0.8,
            'address': 0.7,
            'company': 0.6,
            'position': 0.5
        }
        self.stats = {'filtered_info_count': 0, 'relevance_scores': []}
    
    def get_relevant_info(self, field: Dict[str, Any], 
                         user_info: Dict[str, Any],
                         form_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """为特定字段获取最相关的用户信息"""
        field_type = field.get('type', 'text')
        field_label = field.get('label', '').lower()
        
        relevant_info = {}
        
        # 根据字段类型筛选相关信息
        if 'name' in field_label or field_type == 'name':
            relevant_info.update(self._extract_name_related_info(user_info))
        elif 'phone' in field_label or field_type == 'phone':
            relevant_info.update(self._extract_contact_related_info(user_info, 'phone'))
        elif 'email' in field_label or field_type == 'email':
            relevant_info.update(self._extract_contact_related_info(user_info, 'email'))
        elif 'address' in field_label or field_type == 'address':
            relevant_info.update(self._extract_address_related_info(user_info))
        elif 'company' in field_label or 'work' in field_label:
            relevant_info.update(self._extract_work_related_info(user_info))
        else:
            # 对于未知字段，使用语义相似度
            relevant_info.update(self._extract_semantic_related_info(field, user_info))
        
        # 添加相关性评分
        for key, value in relevant_info.items():
            if isinstance(value, dict) and 'value' in value:
                score = self._calculate_relevance_score(field, key, value['value'])
                value['relevance_score'] = score
                self.stats['relevance_scores'].append(score)
        
        self.stats['filtered_info_count'] += len(relevant_info)
        return relevant_info
    
    def _extract_name_related_info(self, user_info: Dict[str, Any]) -> Dict[str, Any]:
        """提取姓名相关信息"""
        relevant = {}
        personal_info = user_info.get('personal', {})
        
        if 'name' in personal_info:
            relevant['name'] = personal_info['name']
        if 'full_name' in personal_info:
            relevant['full_name'] = personal_info['full_name']
        if 'first_name' in personal_info and 'last_name' in personal_info:
            relevant['combined_name'] = {
                'first': personal_info['first_name'],
                'last': personal_info['last_name']
            }
        
        return relevant
    
    def _extract_contact_related_info(self, user_info: Dict[str, Any], contact_type: str) -> Dict[str, Any]:
        """提取联系方式相关信息"""
        relevant = {}
        personal_info = user_info.get('personal', {})
        contact_info = user_info.get('contact_info', {})
        
        if contact_type == 'phone':
            if 'phone' in personal_info:
                relevant['phone'] = personal_info['phone']
            if 'mobile' in contact_info:
                relevant['mobile'] = contact_info['mobile']
            if 'work_phone' in contact_info:
                relevant['work_phone'] = contact_info['work_phone']
        elif contact_type == 'email':
            if 'email' in personal_info:
                relevant['email'] = personal_info['email']
            if 'work_email' in contact_info:
                relevant['work_email'] = contact_info['work_email']
            if 'personal_email' in contact_info:
                relevant['personal_email'] = contact_info['personal_email']
        
        return relevant
    
    def _extract_address_related_info(self, user_info: Dict[str, Any]) -> Dict[str, Any]:
        """提取地址相关信息"""
        relevant = {}
        address_info = user_info.get('address', {})
        personal_info = user_info.get('personal', {})
        
        if 'address' in personal_info:
            relevant['address'] = personal_info['address']
        if 'home_address' in address_info:
            relevant['home_address'] = address_info['home_address']
        if 'work_address' in address_info:
            relevant['work_address'] = address_info['work_address']
        if 'city' in address_info and 'province' in address_info:
            relevant['location'] = f"{address_info['province']} {address_info['city']}"
        
        return relevant
    
    def _extract_work_related_info(self, user_info: Dict[str, Any]) -> Dict[str, Any]:
        """提取工作相关信息"""
        relevant = {}
        work_info = user_info.get('work', {})
        
        if 'company' in work_info:
            relevant['company'] = work_info['company']
        if 'position' in work_info:
            relevant['position'] = work_info['position']
        if 'department' in work_info:
            relevant['department'] = work_info['department']
        if 'industry' in work_info:
            relevant['industry'] = work_info['industry']
        
        return relevant
    
    def _extract_semantic_related_info(self, field: Dict[str, Any], user_info: Dict[str, Any]) -> Dict[str, Any]:
        """基于语义相似度提取相关信息"""
        relevant = {}
        field_label = field.get('label', '').lower()
        
        # 遍历所有用户信息，寻找语义相关的内容
        for category, info_dict in user_info.items():
            if isinstance(info_dict, dict):
                for key, value in info_dict.items():
                    # 简单的语义匹配（可以后续用更复杂的NLP模型替换）
                    if self._is_semantically_related(field_label, key, value):
                        relevant[f"{category}_{key}"] = {
                            'value': value,
                            'category': category,
                            'confidence': 0.6  # 语义匹配的默认置信度较低
                        }
        
        return relevant
    
    def _is_semantically_related(self, field_label: str, info_key: str, info_value: Any) -> bool:
        """判断信息是否与字段语义相关"""
        # 关键词映射
        semantic_keywords = {
            '学历': ['education', 'degree', 'school', 'university'],
            '专业': ['major', 'field', 'study', 'subject'],
            '年龄': ['age', 'birth', 'born'],
            '性别': ['gender', 'sex'],
            '婚姻': ['marriage', 'marital', 'spouse'],
            '收入': ['salary', 'income', 'wage'],
            '技能': ['skill', 'ability', 'competency']
        }
        
        # 检查字段标签和信息键的语义关联
        for chinese_term, english_terms in semantic_keywords.items():
            if chinese_term in field_label:
                if any(term in info_key.lower() for term in english_terms):
                    return True
            if any(term in field_label for term in english_terms):
                if chinese_term in str(info_value).lower():
                    return True
        
        return False
    
    def calculate_match_confidence(self, match: Dict[str, Any], 
                                  form_analysis: Dict[str, Any],
                                  user_info: Dict[str, Any]) -> float:
        """重新计算匹配置信度"""
        base_confidence = match.get('confidence', 0.5)
        
        # 基于表单类型的调整
        form_type = form_analysis.get('form_type', 'general')
        if form_type in ['resume', 'application']:
            if match.get('field_name', '').lower() in ['name', 'phone', 'email']:
                base_confidence += 0.2
        
        # 基于字段重要性的调整
        field_name = match.get('field_name', '').lower()
        if field_name in self.field_importance_weights:
            weight = self.field_importance_weights[field_name]
            base_confidence = base_confidence * weight + (1 - weight) * 0.3
        
        # 基于信息来源可靠性的调整
        source_field = match.get('source_field', '')
        if 'document' in source_field:
            base_confidence += 0.1  # 来自文档的信息更可靠
        elif 'config' in source_field:
            base_confidence += 0.05  # 来自配置的信息次之
        
        return min(1.0, base_confidence)
    
    def _calculate_relevance_score(self, field: Dict[str, Any], 
                                   info_key: str, info_value: Any) -> float:
         """计算信息与字段的相关性分数"""
         base_score = 0.5
         
         # 基于字段类型的权重
         field_type = field.get('type', 'text')
         if field_type in self.field_importance_weights:
             base_score = self.field_importance_weights[field_type]
         
         # 基于标签相似度的调整
         field_label = field.get('label', '').lower()
         if info_key.lower() in field_label:
             base_score += 0.3
         
         # 基于信息质量的调整
         if info_value and str(info_value).strip():
             base_score += 0.1
         
         return min(1.0, base_score)
     
    def get_stats(self) -> Dict[str, Any]:
        """获取筛选统计信息"""
        avg_score = sum(self.stats['relevance_scores']) / len(self.stats['relevance_scores']) if self.stats['relevance_scores'] else 0
        return {
            'filtered_info_count': self.stats['filtered_info_count'],
            'average_relevance_score': avg_score,
            'total_scores': len(self.stats['relevance_scores'])
        }


class FormContextAnalyzer:
    """表单上下文分析器"""
    
    def analyze_form_context(self, form_fields: List[Dict[str, Any]], 
                           form_context: Dict[str, Any]) -> Dict[str, Any]:
        """分析表单上下文和结构"""
        analysis = {
            'form_type': self._detect_form_type(form_fields, form_context),
            'structure': self._analyze_field_structure(form_fields),
            'field_groups': self._group_related_fields(form_fields),
            'position_context': self._analyze_field_positions(form_fields),
            'completion_hints': self._generate_completion_hints(form_fields)
        }
        
        return analysis
    
    def _detect_form_type(self, form_fields: List[Dict[str, Any]], 
                         form_context: Dict[str, Any]) -> str:
        """检测表单类型"""
        field_labels = [f.get('label', '').lower() for f in form_fields]
        field_text = ' '.join(field_labels)
        
        # 基于字段内容判断表单类型
        if any(keyword in field_text for keyword in ['resume', '简历', 'cv', '求职']):
            return 'resume'
        elif any(keyword in field_text for keyword in ['application', '申请', '报名']):
            return 'application'
        elif any(keyword in field_text for keyword in ['registration', '注册', '登记']):
            return 'registration'
        elif any(keyword in field_text for keyword in ['survey', '调查', '问卷']):
            return 'survey'
        else:
            return 'general'
    
    def _analyze_field_structure(self, form_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """分析字段结构"""
        structure = {
            'total_fields': len(form_fields),
            'required_fields': len([f for f in form_fields if f.get('required', False)]),
            'field_types': {},
            'complexity_score': 0
        }
        
        # 统计字段类型
        for field in form_fields:
            field_type = field.get('type', 'text')
            structure['field_types'][field_type] = structure['field_types'].get(field_type, 0) + 1
        
        # 计算复杂度分数
        structure['complexity_score'] = self._calculate_complexity_score(form_fields)
        
        return structure
    
    def _calculate_complexity_score(self, form_fields: List[Dict[str, Any]]) -> float:
        """计算表单复杂度分数"""
        base_score = len(form_fields) * 0.1
        
        # 基于字段类型的复杂度调整
        for field in form_fields:
            field_type = field.get('type', 'text')
            if field_type in ['select', 'checkbox', 'radio']:
                base_score += 0.2
            elif field_type in ['date', 'file', 'signature']:
                base_score += 0.3
        
        return min(10.0, base_score)

    def _group_related_fields(self, form_fields: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """将相关字段分组"""
        groups = {
            'personal_info': [],
            'contact_info': [],
            'work_info': [],
            'education_info': [],
            'other': []
        }
        
        for field in form_fields:
            label = field.get('label', '').lower()
            field_id = field.get('id', '')
            
            if any(keyword in label for keyword in ['name', '姓名', 'first', 'last']):
                groups['personal_info'].append(field_id)
            elif any(keyword in label for keyword in ['phone', 'email', 'address', '电话', '邮箱', '地址']):
                groups['contact_info'].append(field_id)
            elif any(keyword in label for keyword in ['company', 'position', 'work', '公司', '职位', '工作']):
                groups['work_info'].append(field_id)
            elif any(keyword in label for keyword in ['education', 'school', 'degree', '学历', '学校', '专业']):
                groups['education_info'].append(field_id)
            else:
                groups['other'].append(field_id)
        
        return groups
    
    def _analyze_field_positions(self, form_fields: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """分析字段位置信息"""
        position_context = {}
        
        for i, field in enumerate(form_fields):
            field_id = field.get('id', f'field_{i}')
            position = field.get('position', (0, 0))
            
            # 分析字段的相对位置
            context = {
                'index': i,
                'position': position,
                'is_first': i == 0,
                'is_last': i == len(form_fields) - 1,
                'nearby_fields': []
            }
            
            # 查找邻近字段
            for j, other_field in enumerate(form_fields):
                if i != j and abs(i - j) <= 2:  # 前后2个字段内
                    context['nearby_fields'].append({
                        'id': other_field.get('id', f'field_{j}'),
                        'label': other_field.get('label', ''),
                        'distance': abs(i - j)
                    })
            
            position_context[field_id] = context
        
        return position_context
    
    def _generate_completion_hints(self, form_fields: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """生成填写提示"""
        hints = {}
        
        for field in form_fields:
            field_id = field.get('id', '')
            field_type = field.get('type', 'text')
            label = field.get('label', '').lower()
            
            field_hints = []
            
            # 基于字段类型的提示
            if field_type == 'email':
                field_hints.append('请输入有效的邮箱地址格式')
            elif field_type == 'phone':
                field_hints.append('请输入11位手机号码')
            elif field_type == 'date':
                field_hints.append('请注意日期格式要求')
            
            # 基于字段标签的提示
            if 'required' in label or '*' in label:
                field_hints.append('这是必填字段')
            if '身份证' in label or 'id' in label:
                field_hints.append('请输入18位身份证号码')
            
            if field_hints:
                hints[field_id] = field_hints
        
        return hints


class ContentAnalyzer(BaseAnalyzer):
    """内容分析器"""
    
    def __init__(self, llm_client: BaseLLMClient, config: Dict[str, Any] = None):
        """
        初始化内容分析器
        
        Args:
            llm_client: LLM客户端
            config: 配置信息
        """
        super().__init__(config)
        self.llm_client = llm_client
        self.prompt_manager = get_prompt_manager()
        self.logger = get_logger(self.__class__.__name__)
    
    def process(self, input_data: Any) -> Dict[str, Any]:
        """处理输入数据并返回结果（实现抽象方法）"""
        if isinstance(input_data, dict):
            return self.analyze(input_data)
        else:
            return self.analyze({'content': input_data})
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性（实现抽象方法）"""
        return input_data is not None
    
    @performance_monitor()
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析文档内容
        
        Args:
            data: 包含文档内容的数据
            
        Returns:
            Dict[str, Any]: 分析结果
        """
        document_content = data.get('document_content', '')
        summary_length = data.get('summary_length', '200')
        focus_areas = data.get('focus_areas', '文档关键信息')
        summary_style = data.get('summary_style', '简洁明了')
        
        if not document_content:
            return self._create_error_result("文档内容不能为空")
        
        try:
            # 使用提示词模板
            prompt = self.prompt_manager.format_prompt(
                'document_summary',
                document_content=document_content,
                summary_length=summary_length,
                focus_areas=focus_areas,
                summary_style=summary_style
            )
            
            # 发送请求到LLM
            response = self.llm_client.simple_chat(prompt)
            
            if response:
                # 解析JSON响应
                analysis_result = self._parse_json_response(response)
                
                return {
                    'success': True,
                    'content_analysis': analysis_result,
                    'confidence': self._calculate_analysis_confidence(analysis_result),
                    'raw_response': response
                }
            else:
                return self._create_error_result("LLM响应为空")
                
        except Exception as e:
            self.logger.error(f"内容分析失败: {e}", exc_info=True)
            return self._create_error_result(f"分析失败: {e}")
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据"""
        if not isinstance(input_data, dict):
            return False
        return 'document_content' in input_data and input_data['document_content'].strip()
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            
            return {"raw_text": response, "parsed": False}
    
    def _calculate_analysis_confidence(self, result: Dict[str, Any]) -> float:
        """计算分析结果的置信度"""
        if not isinstance(result, dict) or result.get('parsed') is False:
            return 0.1
        
        confidence = 0.5  # 基础置信度
        
        # 如果有摘要，增加置信度
        if 'summary' in result and result['summary']:
            confidence += 0.2
        
        # 如果有关键点，增加置信度
        if 'key_points' in result and isinstance(result['key_points'], list):
            confidence += min(0.2, len(result['key_points']) * 0.05)
        
        # 如果有文档类型识别，增加置信度
        if 'document_type' in result and result['document_type']:
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _create_error_result(self, error_message: str) -> Dict[str, Any]:
        """创建错误结果"""
        return {
            'success': False,
            'error_message': error_message,
            'content_analysis': {},
            'confidence': 0.0
        }


# 导出类
__all__ = [
    "AnalysisResult",
    "FormAnalyzer",
    "InfoExtractor", 
    "FieldMatcher",
    "ContentAnalyzer"
] 