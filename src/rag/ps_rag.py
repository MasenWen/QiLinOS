#!/usr/bin/env python3
"""
LightRAG + PostgreSQL 完整方案演示脚本
使用PostgreSQL双扩展架构：
- 图数据: PostgreSQL AGE扩展（图数据库）
- 向量数据: PostgreSQL vector扩展（向量数据库）
- 统一存储: 所有数据存储在PostgreSQL中
- 实现完整的RAG + 图推理功能
"""
import asyncio
import os
import sys
import time
import random
import aiohttp
from dotenv import load_dotenv

from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache  # , openai_embed
from lightrag.utils import EmbeddingFunc
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.base import DocStatus
from lightrag import prompt as lightrag_prompt
import numpy as np

from lightrag.utils import setup_logger
import json
from pathlib import Path
from datetime import datetime  # 添加这个导入

# 麒麟 AI SDK 文本向量化 — 原生 C API (ctypes)
from src.rag.kylin_embedding_sdk import kylin_sdk_embedding_func, get_kylin_embedder

setup_logger("ps_rag", level="INFO")

WORKING_DIR = "./rag_storage"
if not os.path.exists(WORKING_DIR):
    os.mkdir(WORKING_DIR)




# # 工作目录
# WORKING_DIR = "./rag_storage"

# 设置PostgreSQL向量索引类型（现在vector扩展已安装）
# os.environ["POSTGRES_VECTOR_INDEX_TYPE"] = "HNSW"  # 使用HNSW向量索引

# 表单填写系统图数据库设计：自定义实体类型
FORM_FILLER_ENTITY_TYPES = [
    "Person",           # 个人信息
    "Organization",     # 组织机构  
    "Document",         # 文档信息
    "Contact",          # 联系方式
    "Location",         # 地理位置
    "Event",            # 事件活动
    "Financial",        # 财务信息
    "Education",        # 教育信息
    "Employment"        # 工作信息
]

# 表单填写系统关系类型
FORM_FILLER_RELATIONSHIPS = [
    "WORKS_AT",         # 工作于
    "LIVES_IN",         # 居住在
    "GRADUATED_FROM",   # 毕业于
    "HAS_CONTACT",      # 拥有联系方式
    "OWNS",             # 拥有
    "PARTICIPATES_IN",  # 参与
    "BELONGS_TO",       # 属于
    "CREATED",          # 创建
    "RELATED_TO"        # 相关
]

# 增强的开放式实体抽取prompt（支持更丰富的知识抽取）
FORM_FILLER_ENTITY_EXTRACTION_PROMPT = """---目标---
从提供的文档中全面识别实体和关系，构建丰富的知识图谱。请使用{language}进行输出。

---核心原则---
1. **开放性抽取**：不仅限于预定义类型，发现文档中所有有价值的实体和关系
2. **层次化理解**：识别个人、组织、事件、概念等不同层次的实体
3. **多维关系**：挖掘时间、空间、因果、从属等多种关系类型
4. **上下文理解**：基于完整语境理解实体的真实含义和重要性

---步骤---
1. **实体识别**：识别文档中的所有重要实体，包括但不限于：
- entity_name: 实体名称（保持原文语言）
- entity_type: 实体类型，可以是预定义类型[{entity_types}]，也可以是你认为更准确的类型
- entity_description: 实体的详细描述，包括其属性、特征、重要性等

**扩展实体类型**（在基础类型上可灵活扩展）：
- Person: 个人（包括姓名、角色、身份、特征等）
- Organization: 组织机构（公司、学校、部门、团队等）
- Location: 地理位置（国家、城市、地址、场所等）
- Event: 事件活动（工作经历、项目、会议、成就等）
- Concept: 概念技能（技术、方法、理论、专业知识等）
- Product: 产品服务（软件、系统、平台、工具等）
- Time: 时间信息（日期、时期、阶段等）
- Financial: 财务信息（薪资、投资、资产等）
- Education: 教育信息（学历、专业、课程等）
- Contact: 联系方式（电话、邮箱、地址等）
- Achievement: 成就荣誉（奖项、认证、专利等）
- Relationship: 社会关系（家庭、同事、朋友等）

格式: ("entity"{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>)

2. **关系抽取**：识别实体间的各种关系，包括：
- source_entity: 源实体名称
- target_entity: 目标实体名称  
- relationship_description: 关系的详细描述和上下文
- relationship_keywords: 关系类型关键词（可使用预定义类型或创新类型）
- relationship_strength: 关系强度(1-10)

**丰富的关系类型**（可灵活扩展）：
- WORKS_AT/EMPLOYED_BY: 工作雇佣关系
- GRADUATED_FROM/STUDIED_AT: 教育学习关系  
- LIVES_IN/LOCATED_IN: 居住位置关系
- FAMILY_OF/MARRIED_TO/PARENT_OF: 家庭关系
- COLLEAGUE_OF/TEAMMATE_OF: 同事合作关系
- MANAGES/LEADS/SUPERVISES: 管理领导关系
- DEVELOPS/CREATES/BUILDS: 开发创造关系
- USES/APPLIES/MASTERS: 使用掌握关系
- PARTICIPATES_IN/INVOLVED_IN: 参与关系
- OWNS/POSSESSES/HAS: 拥有关系
- ACHIEVES/WINS/RECEIVES: 获得成就关系
- INFLUENCES/IMPACTS/AFFECTS: 影响关系
- COLLABORATES_WITH/PARTNERS_WITH: 合作关系
- COMPETES_WITH/RIVALS: 竞争关系
- SUCCEEDS/FOLLOWS/PRECEDES: 时序关系
- SIMILAR_TO/RELATED_TO/CONNECTED_TO: 相似关联关系

格式: ("relationship"{tuple_delimiter}<source_entity>{tuple_delimiter}<target_entity>{tuple_delimiter}<relationship_description>{tuple_delimiter}<relationship_keywords>{tuple_delimiter}<relationship_strength>)

3. **概念主题识别**：提取文档的核心概念、主题和关键词
- 技术概念：编程语言、技术栈、方法论等
- 行业领域：互联网、人工智能、推荐系统等  
- 职业发展：技术专家、团队管理、创业等
- 生活方面：家庭、兴趣爱好、投资理财等

格式: ("content_keywords"{tuple_delimiter}<high_level_keywords>)

4. **创新抽取指导**：
- 发现隐含关系：从时间线、地理位置、共同经历中推断关系
- 识别影响因素：技术发展对职业的影响、家庭对决策的影响等
- 抽取价值信息：薪资变化趋势、技能发展路径、投资偏好等
- 构建知识网络：将分散信息连接成有意义的知识结构

5. **质量要求**：
- 准确性：基于文本明确信息，避免过度推断
- 完整性：尽可能全面抽取，不遗漏重要信息  
- 层次性：区分核心实体和次要实体，重要关系和一般关系
- 可用性：抽取的信息应对表单填写和知识问答有实际价值

6. 以{language}返回步骤1、2、3中识别的所有实体、关系和关键词的单一列表。使用**{record_delimiter}**作为列表分隔符。

7. 完成后，输出{completion_delimiter}

#############################
---示例---
#############################
{examples}

#############################
---实际数据---
#############################
实体类型: [{entity_types}]
文本:
{input_text}
#############################
输出:"""


async def llm_model_func(
        prompt, system_prompt=None, history_messages=[], keyword_extraction=False, **kwargs
    ) -> str:
        return await openai_complete_if_cache(
            "qwen3-max",  # 使用 Qwen3-Max 模型
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=os.getenv("QWEN_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            **kwargs
        )

# ================================================================
# 原代码：阿里云 DashScope Qwen text-embedding-v3 (1024维)
# ================================================================
# async def embedding_func(texts: list[str]) -> np.ndarray:
#     return await openai_embed(
#         texts,
#         model="text-embedding-v3",  # 推荐使用 Qwen 的 text-embedding-v3 模型
#         api_key=os.getenv("QWEN_API_KEY"),
#         base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
#     )
# ================================================================

# 麒麟 AI SDK 文本向量化
async def embedding_func(texts: list[str]) -> np.ndarray:
    return await kylin_sdk_embedding_func(texts)


# async def initialize_rag() -> LightRAG:
    # ================================================================
    # 原代码：PostgreSQL + Qwen text-embedding-v3 (1024维)
    # rag = LightRAG(
    #     working_dir=WORKING_DIR,
    #     llm_model_func=llm_model_func,
    #     embedding_func=EmbeddingFunc(
    #         embedding_dim=1024,
    #         func=embedding_func,
    #     ),
    # )
    # ================================================================

async def initialize_rag() -> LightRAG:
    # 麒麟向量数据库 — pymilvus 嵌入式模式
    os.environ["MILVUS_URI"] = os.path.expanduser(
        "~/.nex-agent/rag_vectordb.db")

    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=get_kylin_embedder().dim,  # GTE-base 768维
            func=embedding_func,
        ),
        vector_storage="MilvusVectorDBStorage",      # 麒麟向量数据库
        graph_storage="NetworkXStorage",              # 本地图存储
        kv_storage="JsonKVStorage",                   # 本地 KV
        doc_status_storage="JsonDocStatusStorage",    # 本地文档状态
    )
    return rag



    
# 为表单填写系统添加的专用函数
def compute_document_id(document_content: str) -> str:
    """根据文档内容计算文档ID（使用MD5哈希）"""
    import hashlib
    # 使用与LightRAG相同的方法计算文档ID
    content_hash = hashlib.md5(document_content.encode('utf-8')).hexdigest()
    return f"doc-{content_hash}"

def reset_storage_completely():
    """完全重置存储（最后手段）"""
    try:
        print("完全重置存储目录...")
        import shutil
        import time
        
        # 多次尝试删除，确保完全清理
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                if os.path.exists(WORKING_DIR):
                    # 首先尝试删除所有文件
                    for root, dirs, files in os.walk(WORKING_DIR):
                        for file in files:
                            try:
                                os.remove(os.path.join(root, file))
                            except:
                                pass
                    
                    # 然后删除目录
                    shutil.rmtree(WORKING_DIR, ignore_errors=True)
                    time.sleep(0.5)  # 等待文件系统完成删除
                    
                if not os.path.exists(WORKING_DIR):
                    print("   旧存储目录已完全删除")
                    break
            except Exception as e:
                if attempt < max_attempts - 1:
                    print(f"   删除尝试 {attempt + 1} 失败，重试中...")
                    time.sleep(1)
                else:
                    print(f"   删除失败: {e}")
        
        # 创建全新目录
        os.makedirs(WORKING_DIR, exist_ok=True)
        print("   全新存储目录已创建")
        
        # 验证目录是空的
        if os.path.exists(WORKING_DIR) and len(os.listdir(WORKING_DIR)) == 0:
            print("   确认存储目录为空")
            return True
        else:
            print("   存储目录可能仍有残留文件")
            return False
            
    except Exception as e:
        print(f"   重置存储失败: {e}")
        return False
    
class RAG_PS:
    def __init__(self, working_dir: str = "./rag_storage"):
        self.rag = None
        self.init = False
        self.working_dir = working_dir
        self.document_registry_file = os.path.join(working_dir, "document_registry.json")
        self.person_registry_file = os.path.join(working_dir, "person_registry.json")
        self.inserted_docs = set()
        self.inserted_persons = set() 
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.initialize()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.finalize()

    async def finalize(self):
        """异步清理资源"""
        if not self.rag:
            return
        try:
            await self.rag.finalize_storages()
            print("RAG_PS 资源已清理")
            print("del RAG_PS")
        except Exception as e:
            print(f"清理资源时出错: {e}")

    async def initialize(self):
        """异步初始化方法"""
        if not self.init:
            self.rag = await initialize_rag()
            await self.setup_lightrag()
            await self.load_document_registry()  # 从文件加载文档注册表
            self.init = True

        
    async def setup_lightrag(self) -> LightRAG:
        """设置和初始化LightRAG实例"""
        try:
            # Initialize RAG instance
            
            # IMPORTANT: Both initialization calls are required!
            # 添加事件循环兼容性检查和强制清理机制
            import asyncio
            try:
                current_loop = asyncio.get_running_loop()
                print(f"当前事件循环ID: {id(current_loop)}")
            except RuntimeError:
                print("没有运行中的事件循环")
            
            # 强制清理可能存在的旧连接
            try:
                import gc
                gc.collect()  # 强制垃圾回收
                print("已执行垃圾回收清理")
            except Exception as cleanup_e:
                print(f"垃圾回收清理失败: {cleanup_e}")
            
            # 初始化存储，添加重试机制
            max_init_retries = 3
            for init_attempt in range(max_init_retries):
                try:
                    print(f"尝试初始化存储 (第 {init_attempt + 1}/{max_init_retries} 次)...")
                    
                    # 等待一下确保旧连接完全释放
                    if init_attempt > 0:
                        await asyncio.sleep(2.0)
                    
                    await self.rag.initialize_storages()  # 初始化存储后端
                    print("✅ 存储初始化成功")
                    break
                    
                except Exception as init_e:
                    error_msg = str(init_e)
                    print(f"❌ 第 {init_attempt + 1} 次存储初始化失败: {error_msg}")
                    
                    if "attached to a different loop" in error_msg or "another operation is in progress" in error_msg:
                        if init_attempt < max_init_retries - 1:
                            print(f"检测到事件循环冲突，等待 {(init_attempt + 1) * 2} 秒后重试...")
                            await asyncio.sleep((init_attempt + 1) * 2)
                            continue
                        else:
                            print("事件循环冲突持续存在，初始化失败")
                            raise init_e
                    else:
                        if init_attempt < max_init_retries - 1:
                            print(f"其他初始化错误，等待 1 秒后重试...")
                            await asyncio.sleep(1.0)
                            continue
                        else:
                            raise init_e
            
            print("初始化处理管道...")
            await initialize_pipeline_status()  # 初始化处理管道（关键步骤！）
        except Exception as e:
            print(f"An error occurred: {e}")
        print("LightRAG初始化成功！")

    async def load_document_registry(self):
        """从文件加载文档注册表"""
        try:
            if os.path.exists(self.document_registry_file):
                with open(self.document_registry_file, 'r', encoding='utf-8') as f:
                    registry_data = json.load(f)
                    self.inserted_docs = set(registry_data.get('documents', []))
                print(f"📁 已加载 {len(self.inserted_docs)} 个已注册文档")
            else:
                self.inserted_docs = set()
                print("📁 无现有文档注册表，创建新的注册表")
        except Exception as e:
            print(f"❌ 加载文档注册表失败: {e}")
            self.inserted_docs = set()

        try:
            if os.path.exists(self.person_registry_file):
                with open(self.person_registry_file, 'r', encoding='utf-8') as f:
                    registry_data = json.load(f)
                    self.inserted_persons = set(registry_data.get('persons', []))
                print(f"📁 已加载 {len(self.inserted_persons)} 个已注册文档")
            else:
                self.inserted_persons = set()
                print("📁 无现有人物注册表，创建新的注册表")
        except Exception as e:
            print(f"❌ 加载人物注册表失败: {e}")
            self.inserted_persons = set()
    
    def save_document_registry(self):
        """保存文档注册表到文件"""
        try:
            os.makedirs(os.path.dirname(self.document_registry_file), exist_ok=True)
            registry_data = {
                'documents': list(self.inserted_docs),
                'total_count': len(self.inserted_docs),
                'updated_at': str(datetime.now())
            }
            with open(self.document_registry_file, 'w', encoding='utf-8') as f:
                json.dump(registry_data, f, ensure_ascii=False, indent=2)
            print(f"💾 文档注册表已保存，共 {len(self.inserted_docs)} 个文档")
        except Exception as e:
            print(f"❌ 保存文档注册表失败: {e}")
        
        try:
            os.makedirs(os.path.dirname(self.person_registry_file), exist_ok=True)
            registry_data = {
                'persons': list(self.inserted_persons),
                'total_count': len(self.inserted_persons),
                'updated_at': str(datetime.now())
            }
            with open(self.person_registry_file, 'w', encoding='utf-8') as f:
                json.dump(registry_data, f, ensure_ascii=False, indent=2)
            print(f"💾 人物注册表已保存，共 {len(self.inserted_persons)} 个文档")
        except Exception as e:
            print(f"❌ 保存人物注册表失败: {e}")

# 删除了复杂的存储清理函数，因为我们现在在开始时就完全重置存储目录

# 删除了create_safe_embedding_func，因为我们现在直接在embedding_func中处理错误
    def insert_persons(self, persons):
        flag = False
        for person in persons:
            if person in self.inserted_persons:
                continue
            flag = True
            self.inserted_persons.add(person)
        if flag:
            self.save_document_registry()  # 保存注册表

    async def insert_document(self, content, path = None):
        if not self.init:
            await self.initialize()
        if not self.rag:
            return False
        doc_id = compute_document_id(content)
        if doc_id in self.inserted_docs:
            print(f"⚠️  文档已存在，跳过插入: {path} (ID: {doc_id})")
            return True
        try:
            # 插入长段内容，创建虚拟文件路径用于追踪源文档
            if path:
                # 传递绝对路径到LightRAG，确保实体和关系能够溯源到源文档
                track_id = await self.rag.ainsert(content, file_paths=path)
            else:
                # 如果没有文档路径，仍然插入内容，但无法溯源
                track_id = await self.rag.ainsert(content)
        
            if track_id:
                self.inserted_docs.add(doc_id)
                self.save_document_registry()  # 保存注册表
                print(f"   插入{path}成功！跟踪ID: {track_id}")
                return True
            else:
                print(f"   插入{path}失败！返回空ID")
                
        except Exception as doc_error:
            print(f"   插入{path}失败: {doc_error}")
        
        return False
    
    async def aquery(self, question):
        if not self.init:
            await self.initialize()
        if not self.rag:
            return "None"
        try: 
            result = await self.rag.aquery(
                question, 
                param=QueryParam(
                    mode="hybrid", #query_modes = ["naive", "local", "global"]
                    response_type="中文回答",  # 明确要求中文回答
                    enable_rerank=False        # 禁用rerank避免警告
                )
            )
            
            # 显示结果
            if result and len(str(result).strip()) > 0:
                short_result = str(result)
                print(f"   结果: {short_result}")
                return short_result
            else:
                print(f"   空结果")
                return "None"
            
        except Exception as e:
            print(f"   查询失败: {e}")
            return "None"

    def get_statistics(rag):
        """获取LightRAG统计信息"""
        try:
            stats = {
                'working_dir': rag.working_dir if hasattr(rag, 'working_dir') else './rag_storage',
                'storage_types': {
                    'graph_storage': 'NetworkXStorage',
                    'kv_storage': 'JsonKVStorage',
                    'vector_storage': 'MilvusVectorDBStorage',
                    'doc_status_storage': 'JsonDocStatusStorage'
                },
                'vector_db_path': os.path.expanduser('~/.nex-agent/rag_vectordb.db'),
                'database_info': {
                },
                'entity_types': FORM_FILLER_ENTITY_TYPES,
                'relationship_types': FORM_FILLER_RELATIONSHIPS
            }
            
            return stats
            
        except Exception as e:
            print(f"获取统计信息失败: {e}")
            return {'error': str(e)}
        

# rag_gps = RAG_PS()

async def main():
    """主演示函数"""
    print("=" * 60)
    # print("完全重置存储，确保测试环境干净...")
    # if not reset_storage_completely():
    #     print("存储重置失败，无法继续")
    #     return
    rag_ps = RAG_PS()
    await rag_ps.initialize()

    rag_ps.get_statistics()
    print("=" * 60)
    # async with RAG_PS() as rag_ps:
    try:
        # 0. 首先完全重置存储（确保从零开始）

        
        content = '''姓  名	李汉华	身份证号	430422199004054657	照片
出生年月	1990-04-05	政治面貌	群众	籍贯	衡南	
文化程度	本科	性别	男	民族	汉	
军人证件号	无	军衔	无	职级	无	
单位	国防科技大学计算机学院国产基础软件工程研究中心	手机	13272026409
通讯地址	湖南省长沙市开福区德雅路1420金帆小区9栋	微信号	clxf-66
个人简历	2008.09-2012.06黑龙江科技大学电气与信息工程系自动化专业		学生
2012.07-2014.06长沙伟格软件有限公司文档研发组				软件工程师
2014.07-2019.01桂林飞宇科技有限公司软件软件部iOS研发组	软件工程师
2019.02-2022.10从事Windows，Mac及iOS应用开发				个人开发者
2022.11 至今	国防科技大学计算机学院国产基础软件工程研究中心 终端研发工程师
家庭成员基本情况
关系	姓名	身份证号	工作单位及职务
　父亲	李绍忠　	430422196210224633　	务农　
　妻子	刘群群　	430422198911117805　	自由职业　
　女儿	李芮清　	430422201502010227　	学生　
　女儿	李芮昕　	430422201903230060　	学生　'''
        # 2. 插入演示文档
        success = await rag_ps.insert_document(content, "/home/ubuntu/Videos/ps.docx")
        
        
        if success:
            # 3. 演示查询
            await rag_ps.query("李汉华的住在哪里？")

        
        print("\n" + "=" * 50)
        
        
    except Exception as e:
        print(f"演示过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await rag_ps.finalize()
        




async def query_user_info(rag, user_identifier: str, query_mode: str = "hybrid"):
    """
    查询用户相关信息
    
    Args:
        rag: LightRAG实例
        user_identifier: 用户标识符
        query_mode: 查询模式
        
    Returns:
        Dict: 查询结果
    """
    try:
        print(f"查询用户信息: {user_identifier} (模式: {query_mode})")
        
        # 构建用户相关查询
        query = f"关于{user_identifier}的个人信息、工作信息、教育背景、联系方式等详细信息是什么？"
        
        result = await rag.aquery(
            query, 
            param=QueryParam(
                mode=query_mode,
                response_type="中文回答",
                enable_rerank=False
            )
        )
        
        if result and len(str(result).strip()) > 0:
            print(f"查询成功，结果长度: {len(str(result))}")
            return {
                'success': True,
                'result': str(result),
                'query': query,
                'mode': query_mode
            }
        else:
            print("查询返回空结果")
            return {'success': False, 'error': '查询返回空结果'}
            
    except Exception as e:
        error_msg = f"用户信息查询失败: {e}"
        print(error_msg)
        return {'success': False, 'error': error_msg}


async def extract_user_info_from_document(rag, document_content: str):
    """
    从文档中提取用户相关信息
    
    注意：此函数假设文档已经通过insert_document_for_form_filling插入到知识图谱中
    
    Args:
        rag: LightRAG实例
        document_content: 文档内容（用于生成查询提示）
        
    Returns:
        Dict: 提取结果
    """
    try:
        # 直接查询用户相关信息，不重复插入文档
        # 假设文档已经通过insert_document_for_form_filling插入到知识图谱中
        
        # 查询用户相关信息
        user_queries = [
            "文档中提到的个人信息有哪些？包括姓名、联系方式、地址等",
            "文档中的工作和教育信息是什么？",
            "文档中涉及的组织机构有哪些？",
            "文档中的重要日期和事件有哪些？"
        ]
        
        extracted_info = {}
        for query in user_queries:
            try:
                result = await rag.aquery(
                    query, 
                    param=QueryParam(
                        mode="local",
                        response_type="中文回答",
                        enable_rerank=False
                    )
                )
                
                if result and len(str(result).strip()) > 0:
                    key = query.split('？')[0].replace('文档中', '').replace('的', '')
                    extracted_info[key] = str(result)
                    
            except Exception as e:
                print(f"查询失败: {query} - {e}")
        
        return {
            'success': True,
            'extracted_info': extracted_info
        }
        
    except Exception as e:
        error_msg = f"用户信息提取失败: {e}"
        print(error_msg)
        return {'success': False, 'error': error_msg}




if __name__ == "__main__":
    asyncio.run(main())
