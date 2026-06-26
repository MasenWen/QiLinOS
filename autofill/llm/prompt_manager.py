"""
提示词管理模块

管理用于表单分析、信息提取和智能填写的提示词模板。
"""

import json
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..config.settings import get_config
from ..utils.logger import get_logger
from src.utils.db_manager import node_state


class PromptType(Enum):
    """提示词类型枚举"""
    FORM_ANALYSIS = "form_analysis"
    INFO_EXTRACTION = "info_extraction"
    FIELD_MATCHING = "field_matching"
    DATA_VALIDATION = "data_validation"
    CONTENT_SUMMARY = "content_summary"
    CLASSIFICATION = "classification"


@dataclass
class PromptTemplate:
    """提示词模板数据结构"""
    name: str
    type: PromptType
    template: str
    description: str = ""
    variables: List[str] = field(default_factory=list)
    examples: List[Dict[str, str]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    version: str = "1.0"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    def format(self, **kwargs) -> str:
        """
        格式化提示词模板
        
        Args:
            **kwargs: 模板变量
            
        Returns:
            str: 格式化后的提示词
        """
        try:
            return self.template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"缺少必需的模板变量: {e}")
    
    def validate_variables(self, variables: Dict[str, Any]) -> List[str]:
        """
        验证模板变量
        
        Args:
            variables: 要验证的变量
            
        Returns:
            List[str]: 缺失的变量列表
        """
        missing = []
        for var in self.variables:
            if var not in variables:
                missing.append(var)
        return missing
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "type": self.type.value,
            "template": self.template,
            "description": self.description,
            "variables": self.variables,
            "examples": self.examples,
            "tags": self.tags,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PromptTemplate':
        """从字典创建实例"""
        return cls(
            name=data["name"],
            type=PromptType(data["type"]),
            template=data["template"],
            description=data.get("description", ""),
            variables=data.get("variables", []),
            examples=data.get("examples", []),
            tags=data.get("tags", []),
            version=data.get("version", "1.0"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at")
        )


class PromptManager:
    """提示词管理器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化提示词管理器
        
        Args:
            config: 配置信息
        """
        self.config = config or {}
        self.logger = get_logger(self.__class__.__name__)
        
        # 配置文件路径
        app_config = get_config()
        self.prompts_dir = Path(self.config.get(
            'prompts_dir', 
            app_config.system.data_dir
        )) / "prompts"
        
        # 确保目录存在
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存中的提示词缓存
        self._templates: Dict[str, PromptTemplate] = {}
        
        # 加载默认提示词
        self._load_default_templates()
        
        # 从文件加载自定义提示词
        self._load_templates_from_files()
    
    def _load_default_templates(self):
        """加载默认提示词模板"""
        default_templates = [
            # 表单分析提示词
            PromptTemplate(
                name="form_structure_analysis",
                type=PromptType.FORM_ANALYSIS,
                template="""请分析以下表单内容，识别表单的结构和字段信息：

表单内容：
{form_content}

请按照以下JSON格式返回分析结果：
{{
    "form_title": "表单标题",
    "form_type": "表单类型（如：身份登记、申请表等）",
    "fields": [
        {{
            "field_name": "字段名称",
            "field_label": "字段标签",
            "field_type": "字段类型（text/number/date/select/checkbox等）",
            "required": true/false,
            "description": "字段描述",
            "position": "在表单中的位置"
        }}
    ],
    "sections": [
        {{
            "section_name": "章节名称",
            "fields": ["字段名称列表"]
        }}
    ]
}}

请确保分析准确且完整。""",
                description="分析表单结构和字段信息",
                variables=["form_content"],
                examples=[
                    {
                        "input": "姓名：___ 年龄：___ 电话：___",
                        "output": "识别出姓名、年龄、电话三个字段"
                    }
                ],
                tags=["表单分析", "结构识别"]
            ),
            
            # 信息提取提示词 - 重点关注用户相关信息的知识图谱构建
            PromptTemplate(
                name="user_info_extraction",
                type=PromptType.INFO_EXTRACTION,
                template="""请从以下文档内容中提取与用户相关的实体和关系信息，用于构建知识图谱：

文档内容：
{document_content}

请识别以下类型的实体和关系：

实体类型：
1. Person: 人员信息（姓名、身份、职位等）
2. Organization: 组织机构（公司、学校、政府部门等）
3. Location: 地理位置（地址、城市、区域等）
4. Contact: 联系方式（电话、邮箱、地址等）
5. Document: 文档信息（证件、合同、表单等）
6. Event: 事件信息（工作经历、教育经历、项目等）
7. Financial: 财务信息（银行、账户、收入等）

关系类型：
- WORKS_AT: 工作关系
- LIVES_IN: 居住关系
- GRADUATED_FROM: 毕业关系
- HAS_CONTACT: 联系方式关系
- OWNS: 拥有关系
- PARTICIPATES_IN: 参与关系

请按照以下JSON格式返回结果：
{{
    "entities": [
        {{
            "name": "实体名称",
            "type": "实体类型",
            "description": "实体描述",
            "attributes": {{
                "key1": "value1",
                "key2": "value2"
            }},
            "confidence": 0.9
        }}
    ],
    "relationships": [
        {{
            "source": "源实体",
            "target": "目标实体",
            "type": "关系类型",
            "description": "关系描述",
            "confidence": 0.8
        }}
    ],
    "user_profile": {{
        "primary_person": "主要人员实体名称",
        "key_attributes": {{
            "name": "姓名",
            "phone": "电话",
            "email": "邮箱",
            "address": "地址",
            "organization": "工作单位",
            "position": "职位"
        }}
    }}
}}

注意：
1. 重点识别与用户个人相关的实体和关系
2. 为每个实体和关系提供置信度评分（0-1）
3. 确保提取的信息准确可用于知识图谱构建
4. 识别主要用户实体及其关键属性""",
                description="提取用户相关实体和关系信息用于知识图谱构建",
                variables=["document_content"],
                examples=[
                    {
                        "input": "张三，男，在北京科技公司工作，电话13800138000",
                        "output": "提取人员实体张三、组织实体北京科技公司、工作关系"
                    }
                ],
                tags=["知识提取", "用户信息", "知识图谱"]
            ),
            
            # 知识图谱提取提示词 - 用于PostgreSQL AGE数据库
            PromptTemplate(
                name="knowledge_graph_extraction",
                type=PromptType.INFO_EXTRACTION,
                template="""请从以下文档中提取知识图谱信息，用于存储到PostgreSQL AGE图数据库中：

文档内容：
{document_content}

请识别实体和关系，并按照AGE图数据库的格式要求返回：

实体类型（标签）：
- Person: 个人实体
- Organization: 组织机构
- Location: 地理位置
- Document: 文档类型
- Contact: 联系方式
- Event: 事件活动

关系类型：
- WORKS_AT: 工作于
- LIVES_IN: 居住在
- GRADUATED_FROM: 毕业于
- HAS_CONTACT: 拥有联系方式
- CREATED: 创建了
- PARTICIPATED_IN: 参与了

请返回Cypher查询语句格式：
{{
    "nodes": [
        {{
            "labels": ["Person"],
            "properties": {{
                "entity_name": "张三",
                "entity_type": "Person",
                "name": "张三",
                "age": "30",
                "confidence": 0.9
            }}
        }}
    ],
    "relationships": [
        {{
            "source": "张三",
            "target": "北京公司",
            "type": "WORKS_AT",
            "properties": {{
                "start_date": "2020-01-01",
                "confidence": 0.8
            }}
        }}
    ],
    "cypher_statements": [
        "MERGE (p:Person {{entity_name: '张三', name: '张三', age: '30'}});",
        "MERGE (o:Organization {{entity_name: '北京公司', name: '北京公司'}});",
        "MATCH (p:Person {{entity_name: '张三'}}), (o:Organization {{entity_name: '北京公司'}}) MERGE (p)-[:WORKS_AT {{start_date: '2020-01-01'}}]->(o);"
    ]
}}

注意：
1. 确保实体名称唯一且准确
2. 为每个实体和关系生成对应的Cypher语句
3. 包含confidence评分用于质量控制
4. 优化图结构便于查询和分析""",
                description="提取知识图谱信息并生成AGE数据库Cypher语句",
                variables=["document_content"],
                examples=[
                    {
                        "input": "张三在北京科技有限公司担任工程师",
                        "output": "生成Person和Organization节点及WORKS_AT关系的Cypher语句"
                    }
                ],
                tags=["知识图谱", "AGE数据库", "Cypher"]
            ),
            
            # 字段匹配提示词
            PromptTemplate(
                name="field_value_matching",
                type=PromptType.FIELD_MATCHING,
                template="""请根据用户信息为表单字段匹配合适的值：

用户信息：
{user_info}

表单字段：
{form_fields}

匹配规则：
1. 精确匹配：字段名称完全对应
2. 语义匹配：根据字段含义匹配相关信息
3. 格式转换：根据字段要求调整格式
4. 默认值：对于没有匹配信息的可选字段，提供合理默认值

请按照以下JSON格式返回匹配结果：
{{
    "matches": [
        {{
            "field_name": "字段名称",
            "field_label": "字段标签",
            "matched_value": "匹配的值",
            "source_field": "来源字段",
            "match_type": "匹配类型（exact/semantic/format/default）",
            "confidence": 0.95,
            "notes": "匹配说明"
        }}
    ],
    "unmatched_fields": [
        {{
            "field_name": "未匹配字段",
            "reason": "未匹配原因"
        }}
    ],
    "suggestions": [
        "改进建议"
    ]
}}

请确保匹配准确且合理。""",
                description="为表单字段匹配用户信息",
                variables=["user_info", "form_fields"],
                examples=[
                    {
                        "input": "用户姓名：张三，表单字段：姓名",
                        "output": "精确匹配，值为张三"
                    }
                ],
                tags=["字段匹配", "智能填写"]
            ),
            
            # 增强字段匹配提示词
            PromptTemplate(
                name="enhanced_field_matching",
                type=PromptType.FIELD_MATCHING,
                template="""你是一个专业的表单填写助手。请根据表单分析结果和经过筛选的用户信息，为表单字段提供最佳匹配。
 
 ## 表单分析结果：
 **表单类型**: {form_type}
 **表单结构**: {form_structure}
 **置信度阈值**: {confidence_threshold}
 
 ## 字段匹配任务：
 {field_matches}
 
 ## 匹配规则：
 1. **精确匹配** (置信度 0.9+): 字段名称和用户信息完全对应
 2. **语义匹配** (置信度 0.7-0.9): 基于字段含义匹配相关信息
 3. **类型匹配** (置信度 0.5-0.7): 基于数据类型进行合理推断
 4. **上下文匹配** (置信度 0.6-0.8): 考虑字段在表单中的位置和相邻字段
 5. **智能推断** (置信度 0.3-0.6): 基于表单类型进行合理补充
 
 ## 质量要求：
 - 优先选择置信度高的匹配
 - 考虑字段的重要性和必填要求
 - 保持数据格式的一致性
 - 避免信息重复或冲突
 
 ## 输出格式：
 ```json
 {{
     "matches": [
         {{
             "field_id": "字段ID",
             "field_name": "字段名称",
             "field_label": "字段标签",
             "matched_value": "匹配的值",
             "source_info": "信息来源",
             "match_type": "exact|semantic|type|context|inference",
             "confidence": 0.95,
             "reasoning": "匹配理由说明",
             "format_notes": "格式说明（如有特殊要求）",
             "alternatives": ["备选值1", "备选值2"]
         }}
     ],
     "unmatched_fields": [
         {{
             "field_id": "未匹配字段ID",
             "field_name": "字段名称",
             "reason": "未匹配原因",
             "suggestions": ["建议的信息收集方向"]
         }}
     ],
     "quality_assessment": {{
         "overall_confidence": 0.85,
         "completion_rate": "85%",
         "critical_fields_filled": true,
         "recommendations": ["改进建议"]
     }},
     "context_analysis": {{
         "form_complexity": "medium",
         "missing_info_impact": "low",
         "field_relationships": ["相关字段分析"]
     }}
 }}
 ```
 
 请确保：
 1. 所有匹配都有明确的置信度评分
 2. 提供详细的匹配理由
 3. 考虑表单的整体完整性
 4. 识别关键信息缺失
 5. 给出实用的改进建议""",
                description="增强的字段匹配，提供上下文感知和质量评估",
                variables=["form_type", "form_structure", "field_matches", "confidence_threshold"],
                examples=[
                    {
                        "input": "表单类型：政府申请表，字段：姓名、电话",
                        "output": "基于用户信息智能匹配字段值"
                    }
                ],
                tags=["字段匹配", "智能填写", "上下文感知"]
            ),
            
            # 基于数据驱动的字段匹配提示词 - 确保只使用提供的数据
            PromptTemplate(
                name="data_driven_field_matching",
                type=PromptType.FIELD_MATCHING,
                template="""你是一个专业的表单填写助手。你的任务是**仅仅基于提供的用户数据**来匹配表单字段，绝对不能生成、推测或创造任何新的信息。

## 🔍 可用的用户数据：
{available_user_data}

## 📋 表单分析结果：
**表单类型**: {form_type}
**表单结构**: {form_structure}
**置信度阈值**: {confidence_threshold}

## 🎯 字段匹配任务：
{field_matches}

## ⚠️ 重要约束条件：
1. **数据来源限制**：你只能使用上述"可用的用户数据"中明确存在的信息
2. **禁止数据生成**：严禁创造、推测、生成任何不在用户数据中的信息
3. **空值处理**：如果用户数据中没有对应信息，必须标记为"无数据可用"
4. **数据溯源**：每个匹配的值都必须能追溯到用户数据的具体位置

## 📏 匹配规则（仅限现有数据）：
1. **精确匹配** (置信度 0.9+): 字段名称与用户数据中的键完全对应
2. **语义匹配** (置信度 0.7-0.9): 基于字段含义在用户数据中找到语义相关的信息
3. **格式转换** (置信度 0.6-0.8): 将用户数据中的信息转换为表单要求的格式
4. **部分匹配** (置信度 0.4-0.6): 用户数据中包含部分相关信息

## 📤 输出格式：
```json
{{
    "matches": [
        {{
            "field_id": "字段ID",
            "field_name": "字段名称", 
            "field_label": "字段标签",
            "matched_value": "来自用户数据的值",
            "source_path": "用户数据中的具体路径，如：personal_info.name",
            "source_value": "用户数据中的原始值",
            "match_type": "exact|semantic|format|partial",
            "confidence": 0.95,
            "reasoning": "为什么这个用户数据与该字段匹配",
            "data_transformation": "如果有格式转换，说明转换过程"
        }}
    ],
    "unmatched_fields": [
        {{
            "field_id": "未匹配字段ID",
            "field_name": "字段名称",
            "reason": "用户数据中无对应信息",
            "missing_data_type": "缺少什么类型的数据"
        }}
    ],
    "data_coverage": {{
        "total_fields": 10,
        "matched_fields": 7,
        "coverage_rate": "70%",
        "missing_critical_data": ["身份证号", "手机号"]
    }},
    "data_verification": {{
        "all_values_from_source": true,
        "no_generated_data": true,
        "data_integrity_check": "passed"
    }}
}}
```

## ✅ 质量检查清单：
- [ ] 所有matched_value都能在available_user_data中找到
- [ ] 没有生成任何新的个人信息
- [ ] 每个匹配都有明确的source_path
- [ ] 置信度评分反映数据匹配的准确性
- [ ] 未匹配字段明确标注原因

请严格按照以上要求执行匹配，确保数据的完整性和可追溯性。""",
                description="基于数据驱动的字段匹配，确保只使用提供的用户数据",
                variables=["available_user_data", "form_type", "form_structure", "field_matches", "confidence_threshold"],
                examples=[
                    {
                        "input": "用户数据：{name: '张三', phone: '13800138000'}，表单字段：姓名",
                        "output": "精确匹配姓名字段到张三，来源：用户数据.name"
                    }
                ],
                tags=["字段匹配", "数据驱动", "源数据验证"]
            ),
            
            # 数据验证提示词
            PromptTemplate(
                name="data_validation",
                type=PromptType.DATA_VALIDATION,
                template="""请验证以下表单数据的准确性和完整性：

表单数据：
{form_data}

验证规则：
{validation_rules}

请检查：
1. 数据格式是否正确
2. 必填字段是否完整
3. 数据之间是否一致
4. 是否符合业务逻辑

请按照以下JSON格式返回验证结果：
{{
    "validation_result": {{
        "is_valid": true/false,
        "overall_score": 0.95,
        "completion_rate": 0.90
    }},
    "field_validations": [
        {{
            "field_name": "字段名称",
            "is_valid": true/false,
            "error_type": "错误类型",
            "error_message": "错误描述",
            "suggestions": ["修正建议"]
        }}
    ],
    "missing_required_fields": ["缺失的必填字段"],
    "data_inconsistencies": [
        {{
            "fields": ["字段1", "字段2"],
            "issue": "不一致问题描述"
        }}
    ],
    "recommendations": ["整体建议"]
}}""",
                description="验证表单数据的准确性和完整性",
                variables=["form_data", "validation_rules"],
                examples=[
                    {
                        "input": "身份证号：123456，电话：abc",
                        "output": "身份证号格式错误，电话格式错误"
                    }
                ],
                tags=["数据验证", "质量检查"]
            ),
            
            # 内容摘要提示词
            PromptTemplate(
                name="document_summary",
                type=PromptType.CONTENT_SUMMARY,
                template="""请对以下文档内容进行摘要：

文档内容：
{document_content}

摘要要求：
- 长度：{summary_length}字以内
- 重点：{focus_areas}
- 风格：{summary_style}

请按照以下JSON格式返回摘要结果：
{{
    "summary": "文档摘要",
    "key_points": [
        "关键点1",
        "关键点2"
    ],
    "document_type": "文档类型",
    "main_topics": ["主要话题"],
    "word_count": 123,
    "relevance_score": 0.85
}}""",
                description="生成文档内容摘要",
                variables=["document_content", "summary_length", "focus_areas", "summary_style"],
                examples=[
                    {
                        "input": "一份3页的身份证明文档",
                        "output": "摘要：包含个人基本信息的身份证明"
                    }
                ],
                tags=["内容摘要", "文档分析"]
            )
        ]
        
        # 添加到缓存
        for template in default_templates:
            self._templates[template.name] = template
            
        self.logger.info(f"{node_state}-=-填表员===加载了 {len(default_templates)} 个默认提示词模板")
    
    def _load_templates_from_files(self):
        """从文件加载提示词模板"""
        try:
            for file_path in self.prompts_dir.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if isinstance(data, list):
                        # 多个模板的文件
                        for template_data in data:
                            template = PromptTemplate.from_dict(template_data)
                            self._templates[template.name] = template
                    else:
                        # 单个模板的文件
                        template = PromptTemplate.from_dict(data)
                        self._templates[template.name] = template
                        
                except Exception as e:
                    self.logger.warning(f"加载提示词文件失败 {file_path}: {e}")
            
            self.logger.info(f"{node_state}-=-填表员===从文件加载了额外的提示词模板，总计 {len(self._templates)} 个")
            
        except Exception as e:
            self.logger.error(f"加载提示词文件时出错: {e}")
    
    def get_template(self, name: str) -> Optional[PromptTemplate]:
        """
        获取提示词模板
        
        Args:
            name: 模板名称
            
        Returns:
            PromptTemplate: 提示词模板，不存在时返回None
        """
        return self._templates.get(name)
    
    def get_templates_by_type(self, prompt_type: PromptType) -> List[PromptTemplate]:
        """
        根据类型获取提示词模板
        
        Args:
            prompt_type: 提示词类型
            
        Returns:
            List[PromptTemplate]: 提示词模板列表
        """
        return [
            template for template in self._templates.values()
            if template.type == prompt_type
        ]
    
    def get_templates_by_tags(self, tags: List[str]) -> List[PromptTemplate]:
        """
        根据标签获取提示词模板
        
        Args:
            tags: 标签列表
            
        Returns:
            List[PromptTemplate]: 匹配的模板列表
        """
        matching_templates = []
        for template in self._templates.values():
            if any(tag in template.tags for tag in tags):
                matching_templates.append(template)
        return matching_templates
    
    def list_templates(self) -> List[str]:
        """
        列出所有模板名称
        
        Returns:
            List[str]: 模板名称列表
        """
        return list(self._templates.keys())
    
    def add_template(self, template: PromptTemplate) -> bool:
        """
        添加新的提示词模板
        
        Args:
            template: 提示词模板
            
        Returns:
            bool: 添加是否成功
        """
        try:
            self._templates[template.name] = template
            self.logger.info(f"添加新提示词模板: {template.name}")
            return True
        except Exception as e:
            self.logger.error(f"添加提示词模板失败: {e}")
            return False
    
    def save_template(self, template: PromptTemplate, file_name: str = None) -> bool:
        """
        保存提示词模板到文件
        
        Args:
            template: 提示词模板
            file_name: 文件名，默认使用模板名称
            
        Returns:
            bool: 保存是否成功
        """
        try:
            if not file_name:
                file_name = f"{template.name}.json"
            
            file_path = self.prompts_dir / file_name
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(template.to_dict(), f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"提示词模板已保存到: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"保存提示词模板失败: {e}")
            return False
    
    def format_prompt(self, template_name: str, **kwargs) -> str:
        """
        格式化提示词
        
        Args:
            template_name: 模板名称
            **kwargs: 模板变量
            
        Returns:
            str: 格式化后的提示词
            
        Raises:
            ValueError: 模板不存在或变量缺失
        """
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"提示词模板不存在: {template_name}")
        
        missing_vars = template.validate_variables(kwargs)
        if missing_vars:
            raise ValueError(f"缺少必需的模板变量: {missing_vars}")
        
        return template.format(**kwargs)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取提示词管理器统计信息"""
        type_counts = {}
        for template in self._templates.values():
            type_name = template.type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        return {
            "total_templates": len(self._templates),
            "types": type_counts,
            "prompts_directory": str(self.prompts_dir)
        }


# 全局提示词管理器实例
_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager(config: Dict[str, Any] = None) -> PromptManager:
    """
    获取全局提示词管理器实例
    
    Args:
        config: 配置信息
        
    Returns:
        PromptManager: 提示词管理器实例
    """
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager(config)
    return _prompt_manager


# 导出类和函数
__all__ = [
    "PromptType",
    "PromptTemplate", 
    "PromptManager",
    "get_prompt_manager"
] 