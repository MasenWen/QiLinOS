"""
自动填写器

主要的自动填写器，负责协调整个表单填写过程。
集成字段匹配、内容生成、策略选择等功能。
"""

import json
import time
from typing import Dict, List, Any, Optional, Union, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
from enum import Enum

from ..core import BaseFiller, ProcessingStatus
from ..config.settings import ConfigManager
from ..utils.logger import get_logger, performance_monitor, error_handler
from ..llm.analyzers import FieldMatcher
from .types import FillMode, FillStrategy, FillRequest, FillResult
from .field_filler import FieldFiller
from src.utils.db_manager import node_state

class EnumEncoder(json.JSONEncoder):
    """自定义JSON编码器，用于处理枚举类型"""
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)


class AutoFiller(BaseFiller):
    """
    自动填写器
    
    主要功能:
    - 智能字段匹配和填写
    - 多种填写策略支持
    - 填写结果验证
    - 填写过程监控
    """
    
    def __init__(self, settings: ConfigManager):
        self.settings = settings
        self.logger = get_logger(__name__)
        
        # 初始化子组件
        self.field_filler = FieldFiller(settings)
        # 延迟导入以避免循环依赖
        self.strategy_filler = None
        self.template_filler = None
        
        # 初始化LLM客户端和字段匹配器
        self.llm_client = None
        self.field_matcher = None
        
        # 填写统计
        self.fill_stats = {
            'total_fills': 0,
            'successful_fills': 0,
            'failed_fills': 0,
            'average_confidence': 0.0,
            'processing_times': []
        }
        
        self.logger.info(f"{node_state}-=-填表员===初始化成功")
    
    def _get_llm_client(self):
        """延迟初始化LLM客户端"""
        if self.llm_client is None:
            from ..llm.local_llm_client import LocalLLMClientAdapter
            self.llm_client = LocalLLMClientAdapter()
        return self.llm_client
    
    def _get_field_matcher(self):
        """延迟初始化字段匹配器"""
        if self.field_matcher is None:
            from ..llm.analyzers import FieldMatcher
            llm_client = self._get_llm_client()
            self.field_matcher = FieldMatcher(llm_client)
        return self.field_matcher
    
    def _get_strategy_filler(self):
        """延迟初始化strategy_filler"""
        if self.strategy_filler is None:
            from .strategy_filler import StrategyFiller
            self.strategy_filler = StrategyFiller(self.settings)
        return self.strategy_filler
    
    def _get_template_filler(self):
        """延迟初始化template_filler"""
        if self.template_filler is None:
            from .template_filler import TemplateFiller
            self.template_filler = TemplateFiller(self.settings)
        return self.template_filler
    
    def process(self, input_data: Any) -> Dict[str, Any]:
        """处理输入数据并返回结果（实现抽象方法）"""
        if isinstance(input_data, FillRequest):
            # 同步包装异步方法
            import asyncio
            return asyncio.run(self.fill_form(input_data))
        else:
            raise ValueError("输入数据必须是FillRequest类型")
    
    def validate_input(self, input_data: Any) -> bool:
        """验证输入数据的有效性（实现抽象方法）"""
        return isinstance(input_data, FillRequest) and input_data.form_info and input_data.user_info
    
    def fill(self, form_data: Dict[str, Any], user_info: Dict[str, Any]) -> Dict[str, Any]:
        """填写表单并返回填写结果（实现抽象方法）"""
        # 创建填写请求
        request = FillRequest(
            form_info=form_data,
            user_info=user_info,
            mode=FillMode.AUTOMATIC,
            strategy=FillStrategy.BALANCED
        )
        # 同步包装异步方法
        import asyncio
        result = asyncio.run(self.fill_form(request))
        return asdict(result)
    
    @performance_monitor
    @error_handler()
    async def fill_form(self, request: FillRequest) -> FillResult:
        """
        填写表单
        
        Args:
            request: 填写请求
            
        Returns:
            填写结果
        """
        start_time = time.time()
        
        try:
            self.logger.info(f"{node_state}-=-填表员===开始填表模式: {request.mode.value}")
            
            # 预处理
            preprocessed_request = await self._preprocess_request(request)
            
            # 字段匹配
            matching_result = await self._match_fields(
                preprocessed_request.form_info,
                preprocessed_request.user_info
            )
            
            # 根据模式选择填写方法
            if request.mode == FillMode.TEMPLATE:
                fill_result = await self._fill_with_template(
                    preprocessed_request, matching_result
                )
            elif request.mode == FillMode.STRATEGY:
                fill_result = await self._fill_with_strategy(
                    preprocessed_request, matching_result
                )
            elif request.mode == FillMode.INTERACTIVE:
                fill_result = await self._fill_interactive(
                    preprocessed_request, matching_result
                )
            else:  # AUTOMATIC
                fill_result = await self._fill_automatic(
                    preprocessed_request, matching_result
                )
            
            # 后处理
            final_result = await self._postprocess_result(fill_result, request)
            
            # 更新统计
            self._update_statistics(final_result, time.time() - start_time)
            
            self.logger.info(f"{node_state}-=-填表员===填表完成，用时 {final_result.processing_time:.2f}s")
            return final_result
            
        except Exception as e:
            self.logger.error(f"Form fill failed: {str(e)}")
            return FillResult(
                success=False,
                filled_fields={},
                skipped_fields=[],
                failed_fields=[],
                confidence_scores={},
                validation_results={},
                processing_time=time.time() - start_time,
                errors=[str(e)],
                warnings=[]
            )
    
    async def _preprocess_request(self, request: FillRequest) -> FillRequest:
        """预处理填写请求"""
        # 验证请求数据
        if not request.form_info:
            raise ValueError("Form info is required")
        if not request.user_info:
            raise ValueError("User info is required")
        
        # 标准化字段名称
        normalized_form_info = self._normalize_field_names(request.form_info)
        normalized_user_info = self._normalize_user_info(request.user_info)
        
        return FillRequest(
            form_info=normalized_form_info,
            user_info=normalized_user_info,
            mode=request.mode,
            strategy=request.strategy,
            template_id=request.template_id,
            custom_rules=request.custom_rules or {},
            validate_before_fill=request.validate_before_fill,
            save_backup=request.save_backup
        )
    
    async def _match_fields(self, form_info: Dict[str, Any], 
                          user_info: Dict[str, Any]) -> Dict[str, Any]:
        """匹配表单字段与用户信息"""
        try:
            # 使用FieldMatcher的analyze方法
            analysis_data = {
                'form_fields': form_info.get('fields', []),
                'user_info': user_info,
                'form_analysis': form_info
            }
            
            # 获取字段匹配器并调用analyze方法
            field_matcher = self._get_field_matcher()
            result = field_matcher.analyze(analysis_data)
            
            # 转换结果格式
            if result.get('success', False):
                matching_result = result.get('matching_result', {})
                matches = matching_result.get('matches', [])
                
                # 转换匹配结果格式
                formatted_matches = []
                for match in matches:
                    if isinstance(match, dict):
                        formatted_match = {
                            'field_name': match.get('field_name', ''),
                            'user_field': match.get('user_field', ''),
                            'confidence': match.get('confidence', 0.0),
                            'match_type': match.get('match_type', 'unknown'),
                            'value': match.get('value', '')
                        }
                        formatted_matches.append(formatted_match)
                
                return {
                    'matches': formatted_matches,
                    'confidence': result.get('overall_confidence', 0.0),
                    'field_mappings': matching_result.get('field_mappings', {})
                }
            else:
                return {'matches': [], 'confidence': 0.0}
                
        except Exception as e:
            self.logger.error(f"Field matching failed: {str(e)}")
            return {'matches': [], 'confidence': 0.0}
    
    async def _fill_automatic(self, request: FillRequest, 
                            matching_result: Dict[str, Any]) -> FillResult:
        """自动填写模式"""
        filled_fields = {}
        skipped_fields = []
        failed_fields = []
        confidence_scores = {}
        warnings = []
        
        matches = matching_result.get('matches', [])
        
        for match in matches:
            field_name = match.get('field_name')
            user_field = match.get('user_field')
            confidence = match.get('confidence', 0.0)
            
            # 根据策略决定是否填写
            if self._should_fill_field(confidence, request.strategy):
                try:
                    fill_value = await self.field_filler.fill_field(
                        field_name, user_field, request.user_info, match
                    )
                    if fill_value is not None:
                        filled_fields[field_name] = fill_value
                        confidence_scores[field_name] = confidence
                    else:
                        failed_fields.append(field_name)
                        warnings.append(f"Failed to fill {field_name}: No value returned")
                    
                except Exception as e:
                    self.logger.warning(f"Failed to fill field {field_name}: {str(e)}")
                    failed_fields.append(field_name)
                    warnings.append(f"Failed to fill {field_name}: {str(e)}")
            else:
                skipped_fields.append(field_name)
                warnings.append(f"Skipped {field_name} due to low confidence: {confidence}")
        
        return FillResult(
            success=len(failed_fields) == 0,
            filled_fields=filled_fields,
            skipped_fields=skipped_fields,
            failed_fields=failed_fields,
            confidence_scores=confidence_scores,
            validation_results={},
            processing_time=0.0,
            errors=[],
            warnings=warnings
        )
    
    async def _fill_with_template(self, request: FillRequest, 
                                matching_result: Dict[str, Any]) -> FillResult:
        """模板填写模式"""
        if not request.template_id:
            raise ValueError("Template ID is required for template mode")
        
        return await self._get_template_filler().fill_with_template(
            request.template_id, request.form_info, request.user_info
        )
    
    async def _fill_with_strategy(self, request: FillRequest, 
                                matching_result: Dict[str, Any]) -> FillResult:
        """策略填写模式"""
        return await self._get_strategy_filler().fill_with_strategy(
            request.strategy, request.form_info, request.user_info, matching_result
        )
    
    async def _fill_interactive(self, request: FillRequest, 
                              matching_result: Dict[str, Any]) -> FillResult:
        """交互式填写模式"""
        # 这里可以实现交互式界面逻辑
        # 暂时回退到自动模式
        self.logger.warning("Interactive mode not fully implemented, falling back to automatic")
        return await self._fill_automatic(request, matching_result)
    
    def _should_fill_field(self, confidence: float, strategy: FillStrategy) -> bool:
        """根据策略决定是否填写字段"""
        thresholds = {
            FillStrategy.CONSERVATIVE: 0.8,
            FillStrategy.BALANCED: 0.6,
            FillStrategy.AGGRESSIVE: 0.3
        }
        
        return confidence >= thresholds.get(strategy, 0.6)
    
    async def _postprocess_result(self, result: FillResult, 
                                request: FillRequest) -> FillResult:
        """后处理填写结果"""
        # 保存备份
        if request.save_backup and result.success:
            await self._save_backup(result, request)
        
        # 验证结果
        if request.validate_before_fill and result.filled_fields:
            validation_results = await self._validate_filled_data(
                result.filled_fields, request.form_info
            )
            result.validation_results = validation_results
        
        return result
    
    async def _save_backup(self, result: FillResult, request: FillRequest):
        """保存填写备份"""
        try:
            backup_dir = Path(self.settings.system.data_dir) / "fill_backups"
            backup_dir.mkdir(exist_ok=True)
            
            timestamp = int(time.time())
            backup_file = backup_dir / f"fill_backup_{timestamp}.json"
            
            # 转换请求和结果为可序列化的字典
            request_dict = asdict(request)
            result_dict = asdict(result)
            
            backup_data = {
                'timestamp': timestamp,
                'request': request_dict,
                'result': result_dict
            }
            
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2, cls=EnumEncoder)
                
            self.logger.info(f"{node_state}-=-填表员===备份保存: {backup_file}")
            
        except Exception as e:
            self.logger.warning(f"Failed to save backup: {str(e)}")
    
    async def _validate_filled_data(self, filled_fields: Dict[str, Any], 
                                  form_info: Dict[str, Any]) -> Dict[str, Any]:
        """验证填写的数据"""
        # 这里可以集成验证器
        # 暂时返回简单验证结果
        validation_results = {
            'is_valid': True,
            'errors': [],
            'warnings': []
        }
        
        for field_name, value in filled_fields.items():
            if not value or (isinstance(value, str) and not value.strip()):
                validation_results['warnings'].append(f"Field {field_name} is empty")
        
        return validation_results
    
    def _normalize_field_names(self, form_info: Dict[str, Any]) -> Dict[str, Any]:
        """标准化字段名称"""
        # 实现字段名称标准化逻辑
        return form_info
    
    def _normalize_user_info(self, user_info: Dict[str, Any]) -> Dict[str, Any]:
        """标准化用户信息"""
        # 实现用户信息标准化逻辑
        return user_info
    
    def _update_statistics(self, result: FillResult, processing_time: float):
        """更新填写统计"""
        self.fill_stats['total_fills'] += 1
        if result.success:
            self.fill_stats['successful_fills'] += 1
        else:
            self.fill_stats['failed_fills'] += 1
        
        self.fill_stats['processing_times'].append(processing_time)
        result.processing_time = processing_time
        
        # 计算平均置信度
        if result.confidence_scores:
            avg_confidence = sum(result.confidence_scores.values()) / len(result.confidence_scores)
            self.fill_stats['average_confidence'] = avg_confidence
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取填写统计信息"""
        stats = self.fill_stats.copy()
        if stats['processing_times']:
            stats['average_processing_time'] = sum(stats['processing_times']) / len(stats['processing_times'])
        else:
            stats['average_processing_time'] = 0.0
        
        return stats
    
    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """实现基类的process方法"""
        request = FillRequest(**data)
        result = await self.fill_form(request)
        return asdict(result) 