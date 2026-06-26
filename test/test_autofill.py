import sys
from pathlib import Path
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from autofill.config import get_settings, update_settings
from autofill.utils.logger import get_logger, setup_logging
from autofill.parsers.document_factory import DocumentParserFactory
from autofill.analyzers.form_analyzer import FormAnalyzer
from autofill.llm.local_llm_client import LocalLLMClientAdapter

from autofill.fillers.lightrag_form_filler import LightRAGFormFiller
from autofill.fillers.auto_filler import AutoFiller
from autofill.fillers.auto_filler import FillRequest, FillMode, FillStrategy
from autofill.validators.data_validator import DataValidator
from autofill.validators.data_validator import ValidationRequest, ValidationLevel
from autofill.fillers.document_writer import DocumentWriter
import asyncio
from src.rag.ps_rag import RAG_PS





class FormAutoFillerApp:
    """表单自动填写应用程序主类"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 初始化各模块
        # self.system_collector = SystemInfoCollector()
        # self.user_collector = UserInfoCollector()
        # self.activity_collector = ActivityInfoCollector()
        self.parser_factory = DocumentParserFactory()
        self.form_analyzer = FormAnalyzer()
        # 使用本地LLM客户端替代DeepSeek
        
        self.llm_client = LocalLLMClientAdapter()
        self.auto_filler = AutoFiller(self.settings)
        self.data_validator = DataValidator(self.settings)
        
        # 初始化LightRAG问答表单填写器
        self.lightrag_filler = LightRAGFormFiller()
        
        # 初始化LightRAG实例
        self.lightrag = None
        
        # 初始化系统域知识服务
    
         
        # 添加文档写入器
     
        self.document_writer = DocumentWriter()
        
        # 缓存收集的信息
        self._system_info_cache = None
        self._user_info_cache = None
        self._activity_info_cache = None
        self._knowledge_graph_cache = {}
        
        # 异步初始化标志
        self._lightrag_initialized = False
        self._lightrag_init_lock = None  # 异步锁，防止并发初始化
        
        
        self.logger.info("表单自动填写应用程序初始化完成")

    def parse_document(self, document_path: Path) -> Optional[Dict[str, Any]]:
        """解析文档"""
        self.logger.info(f"开始解析文档: {document_path}")
        try:
            if not document_path.exists():
                self.logger.error(f"文档不存在: {document_path}")
                return None
            
            parser = self.parser_factory.create_parser(document_path)
            if not parser:
                self.logger.error(f"不支持的文档格式: {document_path}")
                return None
            
            parsed_doc = parser.parse(document_path)
            self.logger.info(f"文档解析完成: {document_path}")
            return parsed_doc
            
        except Exception as e:
            self.logger.error(f"文档解析失败: {e}")
            return None
    
    def analyze_form(self, document_path: Path) -> Optional[Dict[str, Any]]:
        """分析表单"""
        self.logger.info(f"开始分析表单: {document_path}")
        try:
            form_analysis = self.form_analyzer.analyze(document_path)
            confidence = form_analysis.get('confidence', 0)
            field_count = len(form_analysis.get('fields', []))
            
            self.logger.info(f"表单分析完成: 字段数量={field_count}, 置信度={confidence:.2f}")
            return form_analysis
            
        except Exception as e:
            self.logger.error(f"表单分析失败: {e}")
            return None
        
    def _save_original_format(self, document_path: str, results: Dict[str, Any]) -> Dict[str, Any]:
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
            self.logger.info(f"🔍 保存调试：原始结果keys: {list(results.keys())}")
            self.logger.info(f"🔍 保存调试：filled_data keys: {list(filled_data.keys()) if filled_data else 'None'}")
            self.logger.info(f"🔍 保存调试：final_data长度: {len(final_data) if final_data else 0}")
            if final_data:
                self.logger.info(f"🔍 保存调试：final_data前3个字段: {dict(list(final_data.items())[:3])}")
            
            # 即使没有填写数据，也尝试创建原始格式的副本
            if not final_data:
                self.logger.info("没有填写数据，创建原始文件副本")
                try:
                    import shutil
                    from pathlib import Path
                    
                    original_path = Path(document_path)
                    output_dir = Path(self.settings.system.data_dir) / "output"
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
            write_result = self.document_writer.write_filled_document(
                original_path=document_path,
                filled_data={'filled_fields': final_data}
            )
            
            if write_result['success']:
                self.logger.info(f"原始格式保存成功: {write_result['output_file']}")
                return write_result
            else:
                error_msg = write_result.get('error', write_result.get('reason', 'Unknown error'))
                self.logger.warning(f"原始格式保存失败: {error_msg}")
                
                # 返回失败信息，但包含详细错误
                return {
                    'success': False,
                    'error': error_msg,
                    'output_file': None,
                    'method': write_result.get('method', 'unknown'),
                    'details': write_result
                }
            
        except Exception as e:
            self.logger.error(f"原始格式保存异常: {e}")
            return {
                'success': False,
                'error': str(e),
                'output_file': None,
                'method': 'exception'
            }

    def _save_fill_results(self, document_path: str, results: Dict[str, Any]) -> str:
        """保存填写结果到文件"""
        try:
            # 生成输出文件名
            input_path = Path(document_path)
            output_dir = Path(self.settings.system.data_dir) / "output"
            output_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = output_dir / f"fill_result_{input_path.stem}_{timestamp}.json"
            
            # 保存结果
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2, default=str)
            
            self.logger.info(f"填写结果已保存到: {output_file}")
            return str(output_file)
            
        except Exception as e:
            self.logger.error(f"保存填写结果失败: {e}")
            return ""
        
    async def test_autofill(self, path):
        fill_mode = "automatic"
        validate_data = True
        save_results = True
        results = {'success': False, 'errors': [], 'stage': 'initialization'}



        try:
            self.logger.info("开始智能表单填写流程...")
            document_path = Path(path)
            if not document_path.exists():
                raise FileNotFoundError(f"表单文件不存在: {document_path}")
            
            parsed_doc = self.parse_document(document_path)
            if not parsed_doc:
                raise Exception("表单文档解析失败")
            
            self.logger.info("正在分析表单结构...")
            form_analysis = self.analyze_form(document_path)
            if not form_analysis:
                raise Exception("表单结构分析失败")
            

            results['document_parsed'] = parsed_doc
            results['form_analysis'] = form_analysis
            results['stage'] = 'form_analyzed'
            
            # 跳过知识重复抽取，直接使用用户信息收集阶段已构建的知识图谱
            self.logger.info("表单填写阶段：直接使用已有知识图谱进行问答，无需重复抽取知识")
            
            # 步骤4: 使用LightRAG问答方式智能填写表单

            self.logger.info("步骤4: 执行基于LightRAG问答的智能填写")
            
            # 提取表单字段
            form_fields = form_analysis.get('fields', [])
            document_content = parsed_doc.get('text_content', '')
            
            # 使用LightRAG单例管理器，避免事件循环冲突
            self.logger.info("表单填写将使用LightRAG单例管理器，自动处理事件循环兼容性")
            
            # 使用LightRAG问答填写器填充表单
            lightrag_fill_result = await self.lightrag_filler.fill_form_fields(
                "李明", "男，出生于1996年",
                form_fields=form_fields,
                document_content=document_content,
                document_path=str(document_path)
            )

        # 转换结果格式以保持兼容性
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
            
            # 如果LightRAG填写失败，回退到传统方式
            if not lightrag_fill_result.get('success') and len(lightrag_fill_result.get('filled_fields', {})) == 0:
                self.logger.warning("LightRAG问答填写未获得结果，回退到传统填写方式")
                
                # fill_request = FillRequest(
                #     form_info=form_analysis,
                #     user_info=user_info,
                #     mode=FillMode(fill_mode),
                #     strategy=FillStrategy.BALANCED,
                #     validate_before_fill=validate_data,
                #     save_backup=save_results
                # )
                
                # fallback_fill_result = await self.auto_filler.fill_form(fill_request)
                # results['fill_result'] = {
                #     'success': fallback_fill_result.success,
                #     'filled_fields': fallback_fill_result.filled_fields,
                #     'skipped_fields': fallback_fill_result.skipped_fields,
                #     'failed_fields': fallback_fill_result.failed_fields,
                #     'confidence_scores': fallback_fill_result.confidence_scores,
                #     'processing_time': fallback_fill_result.processing_time,
                #     'warnings': fallback_fill_result.warnings,
                #     'method': 'traditional_fallback'  # 标记这是回退方式
                # }
            else:
                self.logger.info(f"LightRAG问答填写完成: {len(lightrag_fill_result.get('filled_fields', {}))} 个字段成功填写")
            results['stage'] = 'form_filled'
            
            # 步骤5: 数据验证
            # if validate_data and results['fill_result']['filled_fields']:
                
            #     self.logger.info("步骤5: 验证填写数据")
                
                
                
            #     validation_request = ValidationRequest(
            #         data=results['fill_result']['filled_fields'],
            #         form_info=form_analysis,
            #         validation_level=ValidationLevel.STANDARD,
            #         fix_errors=True
            #     )
                
            #     validation_result = await self.data_validator.validate_data(validation_request)
            #     results['validation_result'] = {
            #         'is_valid': validation_result.is_valid,
            #         'validation_score': validation_result.validation_score,
            #         'issues_count': len(validation_result.issues),
            #         'corrected_data': validation_result.corrected_data,
            #         'summary': validation_result.summary
            #     }
                
            #     if validation_result.corrected_data:
            #         results['fill_result']['corrected_fields'] = validation_result.corrected_data
            
            # results['stage'] = 'data_validated'
            
            # 步骤6: 保存结果
            if save_results:
                self.logger.info("步骤6: 保存填写结果")
                
                # 保存为原始格式（如果可能）
                original_format_result = self._save_original_format(document_path, results)
                
                # 保存为JSON格式作为备份
                json_output_file = self._save_fill_results(str(document_path), results)
                
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
            self.logger.info("智能表单填写流程完成")
            
            return results
            
        except Exception as e:
            self.logger.error(f"智能表单填写失败: {e}")
            results['errors'].append(str(e))
            return results
        

async def main():
    try:
        # Initialize RAG instance

        content1 = '''姓  名	李明	身份证号	430422199901075892
出生年月	1996-01-07	政治面貌	群众	籍贯	衡南	
文化程度	本科	性别	男	民族	汉
单位	湖南师范大学计算机学院	手机	13762027389
通讯地址	湖南省长沙市开福区德雅路1420金帆小区9栋
个人简历  2014.09-2017.06中南大学计算机系软件工程专业 学生
2017.07-2020.06   中南大学计算机系人工智能    学生
2020.07-2023.06   中南大学计算机系人工智能	学生
2023.07-至今  湖南师范大学计算机学院  教师
'''

        content2 = '''姓  名	刘晴楠	身份证号	430422200104054657
出生年月	2001-09-06	政治面貌	党员	籍贯	长沙
文化程度	本科	性别	女	民族	汉
单位	国防科技大学计算机学院	手机	13287764512
通讯地址	国防科技大学计算机学院	微信号	lqn-66
个人简历	2019.09-2023.06国防科技大学计算机系计算机专业   学生
2023.23-至今    国防科技大学计算机学院计算机专业 学生
'''

#         content3 = '''姓  名	刘晴楠	身份证号	430422200404054657	照片
# 出生年月	2004-01-06	政治面貌	群众	籍贯	衡阳	
# 文化程度	本科	性别	女	民族	汉	
# 军人证件号	无	军衔	无	职级	无	
# 单位	衡阳师范学院美术学院	手机	13203134152
# 通讯地址	湖南省长沙市开福区德雅路1420金帆小区9栋	微信号	lqn-66
# 个人简历	2019.09-2023.06中南大学美术系动漫专业		学生
# 2022.23 至今	衡阳师范学院美术学院 美术老师
# 家庭成员基本情况'''
        rag_gps = RAG_PS()
        await rag_gps.insert_document(content1, "/home/ubuntu/Videos/ps.docx")
        await rag_gps.insert_document(content2, "/home/ubuntu/Videos/ps2.docx")
#         await rag_gps.insert_document(content3, "/home/ubuntu/Videos/ps3.docx")

#         query = '''列出所有人名叫刘晴楠的基本信息

# 输出必须包含`Information`，且必须严格遵守以下 JSON 格式。

# ```ts
# interface Person {
#   name: string;
#   gender: string;
#   age: string;
#   description?: string;
# }

# interface Information {
#   all: Person[];
# }
# ```'''
        # query = "刘晴楠多大吗？"
        # await rag_gps.aquery(query)
    
        autofill = FormAutoFillerApp()
        
        await autofill.test_autofill("/home/ubuntu/Downloads/temp/nex_agent/test-data/demo_form.docx")

        # print(result)

    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(main())