#!/usr/bin/env python3
"""
增强的LightRAG表单填写器 - 集成三元组跟踪

在原有LightRAG表单填写功能基础上，增加子图三元组跟踪功能。
"""

import asyncio
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

from ..processors.subgraph_tracker import (
    LightRAGSubgraphTracker,
    LightRAGTrackerAdapter,
    get_global_tracker,
    reset_global_tracker
)


class LightRAGTripletFiller:
    """增强的LightRAG表单填写器
    
    在原有表单填写功能基础上，增加：
    1. 子图三元组跟踪
    2. 查询过程记录
    3. 知识使用分析
    """
    
    def __init__(self, original_filler=None, enable_tracking: bool = True):
        """初始化增强填写器
        
        Args:
            original_filler: 原始的LightRAG填写器实例
            enable_tracking: 是否启用三元组跟踪
        """
        self.original_filler = original_filler
        self.enable_tracking = enable_tracking
        
        # 三元组跟踪器
        if enable_tracking:
            self.tracker = get_global_tracker()
            self.tracker_adapter = LightRAGTrackerAdapter(self.tracker)
        else:
            self.tracker = None
            self.tracker_adapter = None
        
        # 当前填写会话信息
        self.current_session = {
            'session_id': None,
            'form_path': None,
            'start_time': None,
            'field_queries': {},  # field_name -> query_info
        }
        
        self._initialized = False
    
    async def initialize(self):
        """初始化填写器"""
        if self.original_filler and hasattr(self.original_filler, 'initialize'):
            await self.original_filler.initialize()
        self._initialized = True
    
    def set_lightrag_instance(self, lightrag_instance):
        """设置LightRAG实例"""
        if self.original_filler and hasattr(self.original_filler, 'set_lightrag_instance'):
            self.original_filler.set_lightrag_instance(lightrag_instance)
        
        # 如果启用跟踪，可以在这里进行额外的设置
        if self.enable_tracking and lightrag_instance:
            # 这里可以hook LightRAG的查询方法来捕获三元组
            pass
    
    async def fill_form_fields(self, form_fields: List[Dict[str, Any]], 
                             document_content: Optional[str] = None,
                             document_path: Optional[str] = None) -> Dict[str, Any]:
        """填写表单字段（增强版）
        
        Args:
            form_fields: 表单字段列表
            document_content: 文档内容
            document_path: 文档路径
            
        Returns:
            填写结果，包含原始结果和三元组跟踪信息
        """
        # 开始新的填写会话
        self.start_filling_session(document_path)
        
        try:
            # 调用原始填写器
            if self.original_filler:
                original_result = await self._fill_with_tracking(
                    form_fields, document_content, document_path
                )
            else:
                # 如果没有原始填写器，返回模拟结果
                original_result = await self._mock_fill_form_fields(
                    form_fields, document_content, document_path
                )
            
            # 增强结果，添加三元组信息
            enhanced_result = self.enhance_result_with_triplets(original_result)
            
            return enhanced_result
            
        except Exception as e:
            # 即使填写失败，也要保存已收集的三元组信息
            if self.enable_tracking:
                self.tracker.finish_query_tracking(
                    self.current_session.get('session_id', 'unknown'), 
                    processing_time=(datetime.now() - self.current_session['start_time']).total_seconds()
                )
            raise
        
        finally:
            self.end_filling_session()
    
    def start_filling_session(self, document_path: Optional[str] = None):
        """开始填写会话"""
        self.current_session = {
            'session_id': datetime.now().strftime("%Y%m%d_%H%M%S"),
            'form_path': document_path,
            'start_time': datetime.now(),
            'field_queries': {}
        }
        
        # 重置跟踪器以开始新会话
        if self.enable_tracking:
            reset_global_tracker()
            self.tracker = get_global_tracker()
            self.tracker_adapter = LightRAGTrackerAdapter(self.tracker)
    
    def end_filling_session(self):
        """结束填写会话"""
        if self.enable_tracking and self.tracker:
            # 保存会话数据
            try:
                session_file = self.tracker.save_to_file()
                print(f"三元组会话数据已保存到: {session_file}")
            except Exception as e:
                print(f"保存三元组会话数据失败: {e}")
    
    async def _fill_with_tracking(self, form_fields: List[Dict[str, Any]], 
                                document_content: Optional[str] = None,
                                document_path: Optional[str] = None) -> Dict[str, Any]:
        """带跟踪的填写过程"""
        if not self.enable_tracking:
            # 直接调用原始填写器
            return await self.original_filler.fill_form_fields(
                form_fields, document_content, document_path
            )
        
        # 为每个字段执行填写并跟踪三元组
        filled_fields = {}
        skipped_fields = []
        failed_fields = []
        processing_times = []
        
        for field in form_fields:
            field_name = field.get('name', 'unknown_field')
            field_type = field.get('type', 'text')
            field_description = field.get('description', '')
            
            try:
                start_time = datetime.now()
                
                # 构建查询文本
                query_text = self._build_field_query(field)
                
                # 开始跟踪这个字段的查询
                query_id = self.tracker.start_query_tracking(
                    query_text=query_text,
                    form_field=field_name,
                    query_mode="form_filling"
                )
                
                # 记录字段查询信息
                self.current_session['field_queries'][field_name] = {
                    'query_id': query_id,
                    'query_text': query_text,
                    'field_type': field_type,
                    'start_time': start_time
                }
                
                # 执行单个字段填写
                field_result = await self._fill_single_field_with_tracking(
                    field, query_id, query_text
                )
                
                if field_result is not None:
                    filled_fields[field_name] = field_result
                    
                    # 添加推理三元组
                    self.tracker.add_custom_triple(
                        query_id=query_id,
                        subject=field_name,
                        predicate="填写值",
                        obj=str(field_result)[:100],  # 限制长度
                        confidence=0.9,
                        source_type="inference"
                    )
                else:
                    skipped_fields.append(field_name)
                
                # 完成字段查询跟踪
                processing_time = (datetime.now() - start_time).total_seconds()
                processing_times.append(processing_time)
                self.tracker.finish_query_tracking(query_id, processing_time)
                
            except Exception as e:
                failed_fields.append({
                    'field': field_name,
                    'error': str(e)
                })
                print(f"填写字段 {field_name} 失败: {e}")
        
        # 构建结果
        total_processing_time = sum(processing_times)
        
        return {
            'success': True,
            'filled_fields': filled_fields,
            'skipped_fields': skipped_fields,
            'failed_fields': failed_fields,
            'processing_time': total_processing_time,
            'timestamp': datetime.now().isoformat(),
            'method': 'lightrag_with_triplet_tracking'
        }
    
    async def _fill_single_field_with_tracking(self, field: Dict[str, Any], 
                                             query_id: str, query_text: str) -> Any:
        """填写单个字段并跟踪三元组"""
        try:
            # 如果有原始填写器，使用它的单字段填写方法
            if (self.original_filler and 
                hasattr(self.original_filler, '_fill_single_field')):
                result = await self.original_filler._fill_single_field(field)
                
                # 尝试捕获LightRAG查询过程中的实体和关系
                # 这里需要根据实际的LightRAG填写器接口进行调整
                await self._capture_lightrag_query_data(query_id, query_text, field)
                
                return result
            else:
                # 模拟填写
                return await self._mock_single_field_fill(field, query_id)
                
        except Exception as e:
            print(f"填写字段时出错: {e}")
            return None
    
    async def _capture_lightrag_query_data(self, query_id: str, query_text: str, field: Dict[str, Any]):
        """捕获LightRAG查询数据
        
        这个方法需要根据实际的LightRAG填写器实现进行调整，
        以捕获查询过程中使用的实体和关系。
        """
        try:
            # 这里应该集成到实际的LightRAG查询流程中
            # 由于需要深度集成，暂时使用模拟数据
            
            field_name = field.get('name', 'unknown')
            field_type = field.get('type', 'text')
            
            # 模拟实体数据
            mock_entities = [
                {
                    'entity_name': f"用户_{field_name}",
                    'entity_type': 'Person',
                    'description': f"与{field_name}字段相关的用户信息",
                    'confidence': 0.8
                }
            ]
            
            # 模拟关系数据
            mock_relations = [
                {
                    'src_id': f"用户_{field_name}",
                    'tgt_id': field_name,
                    'description': f"用户具有{field_name}属性",
                    'weight': 0.9,
                    'keywords': field_type
                }
            ]
            
            # 添加到跟踪器
            self.tracker.add_entity_data(query_id, mock_entities)
            self.tracker.add_relation_data(query_id, mock_relations)
            
        except Exception as e:
            print(f"捕获LightRAG查询数据失败: {e}")
    
    async def _mock_single_field_fill(self, field: Dict[str, Any], query_id: str) -> Any:
        """模拟单字段填写（用于测试）"""
        field_name = field.get('name', 'unknown')
        field_type = field.get('type', 'text')
        
        # 模拟不同类型字段的填写
        if field_type == 'text':
            result = f"填写的{field_name}文本值"
        elif field_type == 'number':
            result = 12345
        elif field_type == 'date':
            result = datetime.now().strftime('%Y-%m-%d')
        elif field_type == 'email':
            result = "user@example.com"
        else:
            result = f"默认值_{field_name}"
        
        # 添加模拟的推理三元组
        self.tracker.add_custom_triple(
            query_id=query_id,
            subject="知识图谱",
            predicate="推理得出",
            obj=f"{field_name}的值为{result}",
            confidence=0.8,
            source_type="inference"
        )
        
        return result
    
    async def _mock_fill_form_fields(self, form_fields: List[Dict[str, Any]], 
                                   document_content: Optional[str] = None,
                                   document_path: Optional[str] = None) -> Dict[str, Any]:
        """模拟表单填写（当没有原始填写器时）"""
        filled_fields = {}
        skipped_fields = []
        
        for field in form_fields:
            field_name = field.get('name', 'unknown_field')
            
            try:
                # 模拟填写
                if self.enable_tracking:
                    query_text = self._build_field_query(field)
                    query_id = self.tracker.start_query_tracking(
                        query_text=query_text,
                        form_field=field_name,
                        query_mode="mock_filling"
                    )
                    
                    result = await self._mock_single_field_fill(field, query_id)
                    self.tracker.finish_query_tracking(query_id, 0.1)
                else:
                    result = f"模拟填写_{field_name}"
                
                if result:
                    filled_fields[field_name] = result
                else:
                    skipped_fields.append(field_name)
                    
            except Exception as e:
                skipped_fields.append(field_name)
        
        return {
            'success': True,
            'filled_fields': filled_fields,
            'skipped_fields': skipped_fields,
            'failed_fields': [],
            'processing_time': len(form_fields) * 0.1,
            'timestamp': datetime.now().isoformat(),
            'method': 'mock_filling_with_tracking'
        }
    
    def _build_field_query(self, field: Dict[str, Any]) -> str:
        """构建字段查询文本"""
        field_name = field.get('name', 'unknown')
        field_type = field.get('type', 'text')
        field_description = field.get('description', '')
        field_label = field.get('label', field_name)
        
        # 构建查询
        query_parts = []
        
        if field_label and field_label != field_name:
            query_parts.append(f"用户的{field_label}")
        else:
            query_parts.append(f"用户的{field_name}")
        
        if field_description:
            query_parts.append(field_description)
        
        if field_type in ['email', 'phone', 'address', 'name']:
            query_parts.append(f"{field_type}信息")
        
        return " ".join(query_parts)
    
    def enhance_result_with_triplets(self, original_result: Dict[str, Any]) -> Dict[str, Any]:
        """增强结果，添加三元组信息"""
        if not self.enable_tracking or not self.tracker:
            return original_result
        
        # 获取三元组摘要
        triplet_summary = self.tracker.get_session_summary()
        all_triples = self.tracker.get_all_triples()
        
        # 增强结果
        enhanced_result = original_result.copy()
        enhanced_result.update({
            'triplet_tracking': {
                'enabled': True,
                'session_id': self.current_session['session_id'],
                'summary': triplet_summary,
                'total_triples': len(all_triples),
                'triples_by_confidence': {
                    'high': len([t for t in all_triples if t.confidence >= 0.8]),
                    'medium': len([t for t in all_triples if 0.5 <= t.confidence < 0.8]),
                    'low': len([t for t in all_triples if t.confidence < 0.5])
                },
                'field_queries': self.current_session['field_queries']
            }
        })
        
        return enhanced_result
    
    def get_tracker(self) -> Optional[LightRAGSubgraphTracker]:
        """获取三元组跟踪器"""
        return self.tracker
    
    def get_session_triplets(self) -> List[Dict[str, Any]]:
        """获取当前会话的三元组"""
        if not self.tracker:
            return []
        
        all_triples = self.tracker.get_all_triples()
        return [triple.to_dict() for triple in all_triples]
    
    def export_session_data(self, file_path: str = None) -> str:
        """导出会话数据"""
        if not self.tracker:
            raise ValueError("三元组跟踪未启用")
        
        return self.tracker.save_to_file(file_path)
