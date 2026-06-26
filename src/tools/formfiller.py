import logging
from typing import Annotated
from openai import OpenAI
import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from .decorators import log_io
from datetime import datetime
from src.tools.web_search import fetch_webpage_content
import trafilatura
import time
import random
from pathlib import Path
from typing import Dict, Type, Optional, Any
import asyncio
from autofill.parsers.document_factory import DocumentParserFactory
from autofill.analyzers.form_analyzer import FormAnalyzer
from autofill.fillers.lightrag_form_filler import LightRAGFormFiller
from autofill.fillers.document_writer import DocumentWriter
from src.utils.db_manager import db_manager, node_state
from src.rag.ps_rag import RAG_PS
import json
import hashlib

logger = logging.getLogger(__name__)
parser_factory = DocumentParserFactory()
form_analyzer = FormAnalyzer()
# lightrag_filler = LightRAGFormFiller()
document_writer = DocumentWriter()

def parse_the_document(document_path: Path) -> Optional[Dict[str, Any]]:
    """解析文档"""
    logger.info(f"{node_state}-=-填表员===开始解析文档: {document_path}")
    try:
        if not document_path.exists():
            logger.error(f"文档不存在: {document_path}")
            return None
        
        parser = parser_factory.create_parser(document_path)
        if not parser:
            logger.error(f"不支持的文档格式: {document_path}")
            return None
        
        parsed_doc = parser.parse(document_path)
        logger.info(f"{node_state}-=-填表员===文档解析完成: {document_path}")
        return parsed_doc
        
    except Exception as e:
        logger.error(f"文档解析失败: {e}")
        return None

def analyze_form(document_path: Path) -> Optional[Dict[str, Any]]:
    """分析表单"""
    logger.info(f"{node_state}-=-填表员===开始分析表单: {document_path}")
    try:
        form_analysis = form_analyzer.analyze(document_path)
        confidence = form_analysis.get('confidence', 0)
        field_count = len(form_analysis.get('fields', []))
        
        logger.info(f"{node_state}-=-填表员===表单分析完成: 字段数量={field_count}, 置信度={confidence:.2f}")
        return form_analysis
        
    except Exception as e:
        logger.error(f"表单分析失败: {e}")
        return None
    
def save_original_format(document_path: str, results: Dict[str, Any]) -> Dict[str, Any]:
        """保存为原始文档格式"""
        try:
            # 兼容不同的数据结构
            # LightRAG直接返回: {'filled_fields': {...}, 'success': ...}
            # 旧版本返回: {'fill_result': {'filled_fields': {...}}}
            if 'fill_result' in results:
                filled_data = results['fill_result']
            else:
                filled_data = results
            
            # 如果有校正数据，优先使用校正后的数据
            if 'corrected_fields' in filled_data:
                final_data = {**filled_data.get('filled_fields', {}), **filled_data['corrected_fields']}
            else:
                final_data = filled_data.get('filled_fields', {})
            
            # 调试信息
            logger.info(f"{node_state}-=-填表员===🔍 保存调试：原始结果keys: {list(results.keys())}")
            logger.info(f"{node_state}-=-填表员===🔍 保存调试：filled_data keys: {list(filled_data.keys()) if filled_data else 'None'}")
            logger.info(f"{node_state}-=-填表员===🔍 保存调试：final_data长度: {len(final_data) if final_data else 0}")
            if final_data:
                logger.info(f"{node_state}-=-填表员===🔍 保存调试：final_data前3个字段: {dict(list(final_data.items())[:3])}")
            
            # 即使没有填写数据，也尝试创建原始格式的副本
            if not final_data:
                logger.info("没有填写数据，创建原始文件副本")
                try:
                    import shutil
                    from pathlib import Path
                    
                    original_path = Path(document_path)
                    home_dir = Path.home()  # 自动获取当前用户的home目录
                    output_dir = home_dir / "nex-agent-output"
                  
                    output_dir.mkdir(exist_ok=True)
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_name = f"{original_path.stem}_copy_{timestamp}{original_path.suffix}"
                    output_path = output_dir / output_name
                    
                    shutil.copy2(original_path, output_path)
                    
                    return {
                        'success': True,
                        'output_file': str(output_path),
                        'method': 'simple_copy',
                        'filled_count': 0
                    }
                except Exception as e:
                    return {
                        'success': False,
                        'error': f'创建文件副本失败: {e}',
                        'output_file': None,
                        'method': 'simple_copy'
                    }
            
            # 使用文档写入器保存
            write_result = document_writer.write_filled_document(
                original_path=document_path,
                filled_data={'filled_fields': final_data}
            )
            
            if write_result['success']:
                logger.info(f"{node_state}-=-填表员===原始格式保存成功: {write_result['output_file']}")
                return write_result
            else:
                error_msg = write_result.get('error', write_result.get('reason', 'Unknown error'))
                logger.warning(f"原始格式保存失败: {error_msg}")
                
                # 返回失败信息，但包含详细错误
                return {
                    'success': False,
                    'error': error_msg,
                    'output_file': None,
                    'method': write_result.get('method', 'unknown'),
                    'details': write_result
                }
            
        except Exception as e:
            logger.error(f"原始格式保存异常: {e}")
            return {
                'success': False,
                'error': str(e),
                'output_file': None,
                'method': 'exception'
            }

def save_fill_results(document_path: str, results: Dict[str, Any]) -> str:
    """保存填写结果到文件"""
    try:
        # 生成输出文件名
        input_path = Path(document_path)
        home_dir = Path.home()  # 自动获取当前用户的home目录
        output_dir = home_dir / "nex-agent-output"
        output_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"fill_result_{input_path.stem}_{timestamp}.json"
        
        # 保存结果
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        
        logger.info(f"{node_state}-=-填表员===填写结果已保存到: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"保存填写结果失败: {e}")
        return ""

async def aquery(content):
    rag_gps = RAG_PS()
    result = await rag_gps.aquery(content)
    return result

async def afill_form_fields(name, basic_info, form_fields, content):
    lightrag_filler = LightRAGFormFiller()
    lightrag_fill_result = await lightrag_filler.fill_form_fields(
                                                                name = name,
                                                                basic_info = basic_info,
                                                                form_fields=form_fields,
                                                                document_content=content
                                                                )
    return lightrag_fill_result


def get_cache_key(path):
    """生成缓存键"""
    return f"cache_{hashlib.md5(path.encode()).hexdigest()}.json"


def get_cache_data(path):
    out_dir = Path("out-data")
    out_dir.mkdir(exist_ok=True)
    cache_dir = Path("out-data/form_cache")
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / get_cache_key(path)
    
    # 检查文件缓存
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            
            if cached_data.get('document_path', "") == path and cached_data.get('status', "") == "completed":
                print("==========================parse_document from file cache")
                return cached_data
                
        except Exception as e:
            print(f"读取缓存失败: {e}")
            return None
@tool
@log_io
def parse_document(path: Annotated[str, "document's path"]) -> HumanMessage:
    """pasre document """
    print(f"==========================parse_document: {path}")
    
   
    cache_data = get_cache_data(path)
    if cache_data:
        return HumanMessage(content=f"已解析文件并分析和处理其中的表格信息'''")


    document_path = Path(path)
    if not document_path.exists():
        raise FileNotFoundError(f"表单文件不存在: {document_path}")
    parsed_doc = parse_the_document(document_path)
    if not parsed_doc:
        raise Exception("表单文档解析失败")
    
    logger.info("正在分析表单结构...")
    form_analysis = analyze_form(document_path)
    if not form_analysis:
        raise Exception("表单结构分析失败")
    
    result_data = {
        'document_parsed': parsed_doc,
        'form_analysis': form_analysis,
        'document_path': path,
        'status': "completed"
    }
    
    # 保存到文件缓存
    cache_dir = Path("out-data/form_cache")
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / get_cache_key(path)
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存缓存失败: {e}")

    
    return HumanMessage(content=f"已解析文件并分析和处理其中的表格信息'''")


def km_list_people() -> HumanMessage:
    """list all people in the knowledge base"""
    print(f"==========================km_list_people")

    km_updated = db_manager.is_km_updated()
    if km_updated == True:
        people_info = asyncio.run(aquery("查找所有类型为'人员'或'Person'的实体，并列出他们的姓名及其基本信息"))
        db_manager.set_people_info(people_info)
    else:
        people_info = db_manager.get_people_info()
        print("==========================km_list_people skiped")

    
    return HumanMessage(content=f"以下为知识库中所有的人的姓名及其基本信息：{people_info}")

# def km_search_people_info(name: Annotated[str, "someone's name"]) -> HumanMessage:
#     """List the basic information of someone"""
#     print(f"km_search_people_info: {name}")

#     query = '''根据提供的姓名查找所有匹配的人员信息

# 姓名：====

# 查询要求：
# 1. 列出所有姓名包含"===="的人员
# 2. 每人必须包含姓名、性别、年龄信息
# 3. 如有描述信息请一并提供
# 4. 如果未找到任何匹配人员，返回空数组

# 输出必须包含`Information`，且必须严格遵守以下JSON格式：

# ```ts
# interface Person {
#   name: string;      // 人员姓名
#   gender: string;    // 性别：男/女/其他
#   age: string;       // 年龄或出生日期
#   description?: string;  // 可选：简要描述或备注
# }

# interface Information {
#   all: Person[];     // 所有匹配的人员列表
# }
# ```'''
#     try:
#         content = query.replace("====", name)
#     except Exception as e:
#         print(f"exception: {str(e)}")
#         # query = "刘晴楠多大吗？"
#     result = asyncio.run(aquery(content))
    
#     if result:
#         return HumanMessage(content=f"以下为{name}的相关信息：{result}")
#     else:
#         return HumanMessage(content="未查询到该用户的信息")
    

    
def smartformfill(name: Annotated[str, "Name to be filled in"], basic_info: Annotated[str, "Basic information of the person to be filled in"], path: Annotated[str, "document's path"]) -> HumanMessage:
    """Based on user information, basic details, file paths, and contextual information for intelligent form filling."""
    document_path = Path(path)
    results = {}
    parsed_info = get_cache_data(path)
    form_fields = parsed_info["form_analysis"].get('fields', [])
    document_content = parsed_info["document_parsed"].get('text_content', '')
    print("==========================smartformfill")
    # print('='*60)
    # print(form_fields)
    # print(document_content)
    # print('='*60)
    # 使用LightRAG单例管理器，避免事件循环冲突
    logger.info("表单填写将使用LightRAG单例管理器，自动处理事件循环兼容性")
    
    # 使用LightRAG问答填写器填充表单
    lightrag_fill_result = asyncio.run(afill_form_fields(name, basic_info, form_fields, document_content))

    results['fill_result'] = {
                'success': lightrag_fill_result.get('success', False),
                'filled_fields': lightrag_fill_result.get('filled_fields', {}),
                'skipped_fields': lightrag_fill_result.get('skipped_fields', []),
                'failed_fields': lightrag_fill_result.get('failed_fields', []),
                'confidence_scores': {},  # LightRAG问答方式暂不提供置信度分数
                'processing_time': lightrag_fill_result.get('processing_time', 0),
                'warnings': [],
                'method': 'lightrag_qa',  # 标记使用的方法
                'statistics': lightrag_fill_result.get('statistics', {})
            }
    
    original_format_result = save_original_format(document_path, results)
            
    # 保存为JSON格式作为备份
    json_output_file = save_fill_results(str(document_path), results)
    
    results['output_files'] = {
        'original_format': original_format_result.get('output_file'),
        'json_backup': json_output_file,
        'writing_success': original_format_result.get('success', False),
        'writing_method': original_format_result.get('method', 'unknown'),
        'error': original_format_result.get('error'),
        'details': original_format_result.get('details')
    }
        
    results['success'] = True
    results['stage'] = 'completed'
    return HumanMessage(content=f"填写结果:{results}")

