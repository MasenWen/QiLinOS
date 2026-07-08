import logging
from src.config import TEAM_MEMBERS
from src.agent.graph import create_state_graph

from langgraph.graph import END
from typing import Dict, Any, Literal
from src.agent.types import State
from langchain_core.messages import HumanMessage, SystemMessage


import threading
import time
import asyncio
from time import sleep
from src.utils.interupt import CustomInterrupt
import pickle
from datetime import datetime
import os
from mcp_server.client import EventBus
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional
from langgraph.checkpoint.sqlite import SqliteSaver
from src.utils.msg_process import extract_response_content, parse_planner_response, parse_coder_response, parse_user_feedback_with_llm, parse_filler_response
from src.utils.file_process import remove_uploads_prefix, make_safe_filename
from src.utils.db_manager import db_manager, log_handler
from src.agent.nodes import zh_name
from urllib.parse import quote
from src.tools.userprofile import UserAssistant #黄
from src.memory.mem0_store import mem0_store
import json
import concurrent.futures
import re
import shutil
# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Default level is INFO
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def enable_debug_logging():
    """Enable debug level logging for more detailed execution information."""
    logging.getLogger("src").setLevel(logging.DEBUG)


logger = logging.getLogger(__name__)
logger.addHandler(log_handler)


def _safe_rotation_and_curator():
    """后台线程安全执行流转 + 老化检查，吞掉所有异常防止 daemon 线程静默崩溃。"""
    try:
        from src.memory.memory_lifecycle import trigger_rotation, curator_check
        trigger_rotation()
    except Exception as e:
        logger.warning("[后台] trigger_rotation 异常: %s", e)
    try:
        from src.memory.memory_lifecycle import curator_check
        curator_check()
    except Exception as e:
        logger.warning("[后台] curator_check 异常: %s", e)


def extract_path_saved_to(text):
    """
    专门提取"保存路径为："后的路径
    
    参数:
    text (str): 包含"保存路径为："和路径的字符串
    
    返回:
    str: 提取到的文件路径，如果未找到则返回 None
    """
    # 匹配"保存路径为："或"保存路径为:"后的路径
    pattern = r'保存路径为[:：]\s*(/\S+)'
    match = re.search(pattern, text)
    
    return match.group(1) if match else None


def extract_image_src(html_string):
    """
    从HTML字符串中提取包含chat-image类的img标签的src路径
    
    参数:
    html_string (str): 包含img标签的HTML字符串
    
    返回:
    str or None: 如果找到匹配的img标签和src属性，返回src路径；否则返回None
    """
    # 检查字符串中是否包含指定类名的img标签
    if '<img class="chat-image"' not in html_string:
        return None
    
    try:
        # 使用正则表达式提取src属性的值
        # 模式解释：src="([^"]+)" 匹配 src="..." 中的内容
        pattern = r'alt="([^"]+)"'
        match = re.search(pattern, html_string)
        
        if match:
            return match.group(1)  # 返回第一个捕获组的内容（src值）
        else:
            return None
    except Exception as e:
        print(f"提取src时出错: {e}")
        return None
    
class NexAgent:
    """智能体：负责规划与协调各个子智能体的工作"""

    def __init__(self, event_bus: EventBus):
        self.bus = event_bus
        db_manager.set_bus(event_bus)
        self.user_input = ""
        self.is_resuming = False
        self.thread_executor = ThreadPoolExecutor(max_workers=10)  # 支持多个会话
        self.session_tasks: Dict[int, asyncio.Task] = {}
        self.is_inputting: Dict[int, bool] = {}
        self.is_user_feedback: Dict[int, bool] = {}
        self.uploaded_files: Dict[str, str] = {}
        #黄------------------------
        self.infoAssistant = UserAssistant(db_manager) #黄
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        #黄------------------------
        # self.session_cancel_events: Dict[int, threading.Event] = {}

    # def add_chat(self, sid: int, role: str, content: str, server_name=None):
    #     db_manager.save_chat_log(role, content, server_name, sid)
    #     self.bus.publish(sid, {"type": "chat", "payload": {"role": role, "content": content}})

    # def add_log(self, sid, action, detail, *, server_name=None, correlation_id=None, level="info"):
    #     db_manager.add_call_log(action, detail, session_id=sid, correlation_id=correlation_id,
    #                          server_name=server_name, level=level)
    #     if sid:
    #         self.bus.publish(sid, {"type": "log", "payload": {"action": action, "detail": detail}})
    def extract_user_info_async(self, user_input: str):
        """异步处理用户查询"""
        # 主线程立即返回，后台执行处理
        print("异步处理用户输入")
        future = self._executor.submit(self._extract_user_info_background, user_input)
        # 可选：添加回调处理异常
        future.add_done_callback(self._handle_process_result)
        
        return future
    
    def _extract_user_info_background(self, user_input: str):
        """后台处理函数"""
        try:
            result = self.infoAssistant.handle_query(user_input)
            # 提取特征并存入数据库
            return result
        except Exception as e:
            print(f"Background processing failed: {e}")
            return None
        
    def update_user_behavior_async(self, session_id):
        """异步处理用户查询"""
        # 主线程立即返回，后台执行处理
        print("异步处理用户输入")
        future = self._executor.submit(self._update_user_behavior_background, session_id)
        # 可选：添加回调处理异常
        future.add_done_callback(self._handle_process_result)
        
        return future
    
    def _update_user_behavior_background(self, session_id):
        """后台处理函数"""
        try:
            full_plan_json = db_manager.get_full_plan(session_id)
            full_plan = json.loads(full_plan_json)
            if "title" in full_plan:
                title = full_plan['title']
                print(f"获取主题-----：{title}")
            step_text = ''
            if "steps" in full_plan and isinstance(full_plan["steps"], list):
                for i, step in enumerate(full_plan["steps"], 1):
                    step_text += f"**步骤{i}**：{step.get('agent_name', '')}，{step.get('title', '')}。{step.get('description', '').replace('~/nex-agent-output', '$HOME/nex-agent-output')}"
                    # 添加注意信息
                    if step.get('note'):
                        step_text += f"  __注意__，{step['note']}"
                print(f"获取步骤-----：{step_text}")
            user_behavior = self.infoAssistant.get_plan_from_chat(title,step_text)
            # 黄------------------------
            print(f"提取到的用户行为：{user_behavior}")
            if user_behavior.get("need_add_or_update",True):
                behavior = user_behavior.get("behavior_pattern",[])
                print(f"用户行为：{behavior}")
                db_manager.add_behavior(behavior[0],behavior[1])
            # 提取特征并存入数据库
            return user_behavior
        except Exception as e:
            print(f"Background processing failed: {e}")
            return None
    
    def _handle_process_result(self, future: concurrent.futures.Future):
        """处理后台任务结果"""
        try:
            result = future.result()
            if result:
                # 处理成功结果（如果需要）
                pass
        except Exception as e:
            print(f"Background task error: {e}")
    
    def cleanup(self):
        """清理资源"""
        self._executor.shutdown(wait=False)

    def input_with_timeout(self, session_id, timeout=60, default="同意"):
        print(f"您有 {timeout} 秒时间进行输入，超时将自动选择 {default}")
        self.is_inputting[session_id] = True
        # 如果 msg_index == 1，则等待直到条件改变或超时
        start_time = time.time()
        while self.user_input == '':
            if db_manager.get_session_stop(session_id):
                db_manager.set_session_node(session_id, "user_review")
                self.is_inputting[session_id] = False
                raise CustomInterrupt("Function interrupted during workflow streaming")
            # 检查是否超时
            if time.time() - start_time > timeout:
                logger.info(f"{session_id}-=-审核员===等待超时，默认选择 {default}")
                self.is_inputting[session_id] = False
                return default
            # 短暂休眠避免过度占用CPU
            time.sleep(0.1)
        # 如果 msg_index != 1，直接返回默认值
        self.is_inputting[session_id] = False
        # logger.info(f"{session_id}-=-审核员===用户反馈： {self.user_input}")
        return self.user_input
    
    def process_user_feedback(self, session_id: int):
        # 获取用户输入
        self.user_input = ""
        
        node = db_manager.get_wait_feedback_node(session_id)
        if node == "planner":
            user_feedback = self.input_with_timeout(session_id)
            # 使用LLM解析用户反馈
            decision = parse_user_feedback_with_llm(user_feedback)
            action = decision.get("action", "同意")
            reasoning = decision.get("reasoning", "")
            modification_content = decision.get("modification_content", None)
            confidence = decision.get("confidence", 0.5)
            logger.info(f"{session_id}-=-审核员===解析结果: {action}")
            if reasoning:
                logger.info(f"{session_id}-=-审核员===解析理由: {reasoning}")
            if confidence < 0.7:
                logger.info(f"{session_id}-=-审核员===注意: 解析置信度较低 ({confidence:.2f})")
            
            # 根据解析结果设置反馈
            if action == "同意":
                db_manager.set_user_feedback(session_id, "同意")
                logger.info(f"{session_id}-=-审核员===✓ 已确认接受计划")
                # 黄------------------------
                self.update_user_behavior_async(session_id)
                # 黄------------------------
            elif action == "拒绝":
                db_manager.set_user_feedback(session_id, "拒绝")
                logger.info(f"{session_id}-=-审核员===✗ 已拒绝计划，将重新生成")
            elif action == "修改":
                modification = modification_content
                if not modification:
                    db_manager.set_user_feedback(session_id, "拒绝")
                else:
                    db_manager.set_user_feedback(session_id, f"修改后的计划：{modification}")
                logger.info(f"{session_id}-=-审核员===📝 已记录修改意见: {modification}")
        elif node == "form_filler":
            user_feedback = self.input_with_timeout(
                                session_id,
                                timeout=60, 
                                default="第一个"
                            )
            db_manager.set_user_feedback(session_id, user_feedback)

    def run_workflow_with_review(self, user_input: str, session_id: int, correlation_id: int, debug: bool = False):
        file_content = ""
        for file, num in self.uploaded_files.items():
            if num == session_id:
                file_content += f"文件路径: {file}\n"
                self.uploaded_files[file] = -1
        if file_content != "":
            user_input = "文件列表：\n" + file_content + user_input
        user_input = "" + user_input
        print(f"worlflow start：{user_input}")
        db_manager.update_session_state(session_id, "running")

        # === 记忆前置注入 ===
        # 检索相关记忆，注入为独立的系统消息（不污染 user_input 的路由判断）
        memory_context = ""
        original_user_input = user_input
        try:
            if user_input and user_input.strip():
                from src.memory.memory_lifecycle import search_both
                memory_context = search_both(user_input) or ""
        except Exception:
            pass

        #黄------------------------
        # self.infoAssistant.handle_query(self.user_input)
        self.extract_user_info_async(self.user_input)
        #黄------------------------
        
        start_time = time.time()
        def get_completion_message(status="已完成"):
            """根据状态生成完成消息"""
            end_time = time.time()
            elapsed_time = end_time - start_time
            elapsed_minutes = int(elapsed_time // 60)
            elapsed_seconds = int(elapsed_time % 60)
            base_message = f"任务{status}，用时{elapsed_minutes}分{elapsed_seconds}秒"
            return base_message
        def get_completion_time():
            """根据状态生成完成消息"""
            end_time = time.time()
            elapsed_time = end_time - start_time
            elapsed_minutes = int(elapsed_time // 60)
            elapsed_seconds = int(elapsed_time % 60)
            base_message = f"\n用时{elapsed_minutes}分{elapsed_seconds}秒，有任何问题请向我反馈。"
            return base_message
         # 从检查点恢复或创建新状态
   
        thread_id = f"session_{session_id}"
        config = {
                "configurable": {
                    "thread_id": thread_id
                },
                "recursion_limit": 100
            }
        
        with SqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
            # 编译图
            existing_checkpoint = checkpointer.get_tuple(config)
            start_node = db_manager.get_session_node(session_id)
            if existing_checkpoint:
                print(f"从检查点恢复会话 {session_id}")
                # 恢复执行：使用最小状态或空状态
                workflow_state = {
                    "session_id": session_id,  # 只需要会话ID用于日志等
                }
                if user_input.strip() == "":
                    user_input = db_manager.get_user_feedback(session_id)
                else:
                    # 构建消息列表：记忆上下文作为系统消息（不污染路由）
                    msgs = []
                    if memory_context:
                        msgs.append(SystemMessage(
                            content=f"[以下是用户的相关记忆上下文，仅供参考，不作为用户指令]\n{memory_context}"))
                    msgs.append(HumanMessage(content=user_input))
                    workflow_state["messages"] = msgs
                    start_node = "coordinator"
            else:
                if user_input.strip() == "":
                    user_input = db_manager.get_user_feedback(session_id)
                # 构建消息列表：记忆上下文作为系统消息
                msgs = []
                if memory_context:
                    msgs.append(SystemMessage(
                        content=f"[以下是用户的相关记忆上下文，仅供参考，不作为用户指令]\n{memory_context}"))
                msgs.append(HumanMessage(content=user_input))
                workflow_state = {
                    "session_id": session_id,
                    "TEAM_MEMBERS": TEAM_MEMBERS,
                    "messages": msgs,
                    "deep_thinking_mode": True,
                    "search_before_planning": False,
                    "waiting_for_review": False,
                    "cur": "coordinator",
                    "next": "",
                    "last": "",
                    "full_plan": ""
                }
            
            
            if start_node == "__start__" :
                start_node = "coordinator"
            elif start_node == "__end__":
                start_node = "coordinator"
            elif start_node == "user":
                self.process_user_feedback(session_id)
            # 创建从指定节点开始的工作流
            state_graph = create_state_graph(start_node)
            src_agent = state_graph.compile(checkpointer=checkpointer)

            index = 0
            last_worker_content = ""
            final_state : Dict[str, Any] = {}

            # 第4层：token 超限时压缩旧消息 + 提取记忆
            msgs = workflow_state.get("messages", [])
            if msgs:
                from src.memory.memory_lifecycle import compress_and_extract
                workflow_state["messages"] = compress_and_extract(
                    list(msgs), mem0_store)

            print(f"=== 工作流开始 : {start_node} ===")
            try:
                for event in src_agent.stream(workflow_state, config=config):
                    if db_manager.get_session_stop(session_id):
                        raise CustomInterrupt("Function interrupted during workflow streaming")

                    key, value = next(iter(event.items()))
                    index += 1
                    content = ""
                    next_role = value.get("next")

                    print(f"step {index}: cur:{key} next: {next_role}")

                    if 'messages' in value:
                        content = extract_response_content(value["messages"][-1].content)
                        if content == "ACCEPT":
                            content = "同意"
                        elif key == "planner":
                            content = parse_planner_response(content)
                        elif key == "coder":
                            content = parse_coder_response(content)
                        elif key == "pic_maker":
                            path = extract_image_src(content)
                            if path:
                                self.uploaded_files[path] = session_id
                                print(f"添加文件{path}到待处理组")
                        elif key == "form_filler" and next_role == END:
                            content = parse_filler_response(content)

                        if key not in ("supervisor", "coordinator", "planner"):
                            last_worker_content = content

                        if "保存路径为: " in content and "<img class=\"chat-image\"" not in content:
                            image_path = extract_path_saved_to(content)
                            if image_path:
                                if "/uploads/" in image_path:
                                    content += f"\n<img class=\"chat-image\" alt=\"{image_path}\"  src=\"/api/download/{remove_uploads_prefix(image_path)}\">"
                                else:
                                    save_path = os.path.join("./uploads", str(session_id))
                                    os.makedirs(save_path, exist_ok=True)
                                    original_filename = os.path.basename(image_path)
                                    # 核心修复：安全文件名由 “安全化后的主文件名 + 原扩展名/猜测扩展名” 组成
                                    stored_filename = make_safe_filename(original_filename, "", save_path)

                                    save_path = os.path.join(save_path, stored_filename)
                                    shutil.copy2(image_path, save_path)
                                    content += f"\n<img class=\"chat-image\" alt=\"{image_path}\" src=\"/api/download/{session_id}/{quote(stored_filename)}\">"
                    else:
                        content = extract_response_content(str(value))
                    
                     # 检查工作流是否结束
                    if next_role == END: 
                        if key == "knowledge_manager" or key == "operator" or key == "conversationalist" or key == "ocr_tool":
                            db_manager.add_chat(session_id, zh_name(key), content)
                            print("结束流程")
                        else:
                            completion_message = get_completion_time()
                            final_state = {key: value}
                            db_manager.add_chat(session_id, zh_name(key), content.replace("@__end__，",""))
                            db_manager.add_chat(session_id, zh_name("system"), completion_message)
                            db_manager.add_log(session_id, zh_name("system"), completion_message)
                        db_manager.set_session_node(session_id, "__end__")
                        db_manager.update_session_state(session_id, "none")

                        # === 记忆后置钩子 ===
                        # LLM 审查对话，提取持久信息存入 Mem0
                        try:
                            if original_user_input and original_user_input.strip():
                                asst_msg = last_worker_content or content
                                from src.memory.memory_lifecycle import review_and_save_memory
                                review_and_save_memory(
                                    original_user_input, str(asst_msg), mem0_store)
                                # 自动流转 + 时间老化（后台线程，不阻塞主流程）
                                threading.Thread(
                                    target=_safe_rotation_and_curator,
                                    daemon=True
                                ).start()
                        except Exception:
                            pass

                        break

                    if 'messages' in value:
                        print(content)
                        db_manager.add_chat(session_id, zh_name(key), content)
                    elif next_role != END:
                            # db_manager.add_chat(session_id, zh_name(key), f"@{next_role}")
                            pass
                    

                    # db_manager.add_log(zh_name(key), content, session_id, correlation_id)
                    db_manager.set_session_node(session_id, next_role)
                    # 检查是否需要暂停等待用户审查
                    if value.get("waiting_for_review", False):
                        print("\n=== PLAN REVIEW REQUIRED ===")
                        print(value["messages"])

                        self.process_user_feedback(session_id)
                    
                        continue
                    
                   
            except CustomInterrupt as e:
                # 清理资源并返回适当的命令
                logger.info(f"{session_id}-=-系统===任务已中止，原因: {e}")
                print(f"工作流被取消 (Session: {session_id}): {e}")
               
                completion_message = get_completion_message("已中止")
                if self.is_user_feedback.get(session_id, False) == False:
                    db_manager.add_chat(session_id, zh_name("system"), completion_message)
                    db_manager.add_log(session_id, zh_name("system"), completion_message)
                db_manager.set_session_stop(session_id, False)
                db_manager.update_session_state(session_id, "paused")
                return {"status": "cancelled"}
            except Exception as e:
                completion_message = get_completion_message("异常")
                db_manager.add_chat(session_id, zh_name("system"), completion_message)
                db_manager.add_log(session_id, zh_name("system"), completion_message)
                db_manager.set_session_stop(session_id, False)
                db_manager.update_session_state(session_id, "paused")
                return {"status": "exception", "message": str(e)}

        return final_state
    
    async def _run_workflow_async(self, query: str, session_id: int, correlation_id: str):
        """在异步任务中运行工作流"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.thread_executor, 
                self.run_workflow_with_review, 
                query, session_id, correlation_id, True
            )
            
            # 任务完成后清理资源

            return result
            
        except Exception as e:
            print(f"后台工作流执行出错 (Session: {session_id}): {e}")
            self._cleanup_session(session_id)
            return {"status": "error", "message": str(e)}
        
    def _cleanup_session(self, session_id: int):
        """清理会话资源"""
        if session_id in self.session_tasks:
            print(f"清理会话资源: {session_id}")
            del self.session_tasks[session_id]


    async def process_query(self, query: str,  session_id: int, correlation_id: str | None = None):
        correlation_id = correlation_id or uuid.uuid4().hex
        
        print(f"用户提问: {query}")
        db_manager.add_chat(session_id, "user", query)
        db_manager.add_log(session_id, "用户", f"{query}")
        self.user_input = query
        if self.is_inputting.get(session_id, False) == False:
            db_manager.set_user_feedback(session_id, query)
            self.is_user_feedback[session_id] = True
            await self.cancel_session_task(session_id)
            self.is_user_feedback[session_id] = False
            self.session_tasks[session_id] = asyncio.create_task(self._run_workflow_async(query, session_id, correlation_id))
        return "收到", correlation_id
    
    def update_session_state(self):
        
        sessions = db_manager.list_sessions()
        for session in sessions:
            session_id = session['id']
            node = db_manager.get_session_node(session_id)
            if node in ["__start__", "__end__"] :
                db_manager.update_session_state(session_id, "none")
            else:
                db_manager.update_session_state(session_id, "paused")
                
        # print(sessions)
        # 

    async def resume_session_task(self, session_id: int):
        correlation_id = uuid.uuid4().hex
        """继续指定会话的任务"""
        print("继续任务")
        self.is_user_feedback[session_id] = False
        self.session_tasks[session_id] = asyncio.create_task(self._run_workflow_async("", session_id, correlation_id))
        print("成功继续任务")



    async def cancel_session_task(self, session_id: int):
        """取消指定会话的任务"""

        if session_id in self.session_tasks:
            task = self.session_tasks[session_id]
            if not task.done():
                db_manager.set_session_stop(session_id, True)
                
                # 取消异步任务
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            
            while db_manager.get_session_stop(session_id):
                await asyncio.sleep(0.1)
            # 清理资源
            self._cleanup_session(session_id)
            db_manager.update_session_state(session_id, "paused")
            print("成功取消任务")
 
    def handle_file_upload(self, session_id: int, original_filename: str, stored_filename: str, path: str, size: int):
        db_manager.save_uploaded_file(session_id, stored_filename, path, size)
        self.uploaded_files[path] = session_id
        href = f"/api/download/{session_id}/{quote(stored_filename)}?original={quote(original_filename)}"
        size_str = f"{size / 1024:.1f} KB"
        content = f"📎 [**{original_filename}**]({href}) · {size_str}"
        db_manager.save_chat_log("user_file", content, None, session_id)
        db_manager.publish(session_id, {"event": "file_uploaded", "filename": original_filename,
                                      "stored": stored_filename, "path": path, "size": size})



if __name__ == "__main__":
    # graph = src_agent.get_graph()
  
    # print(graph.draw_mermaid())
   
    nex_agent = NexAgent(event_bus=EventBus())

    user_query = "我在备考雅思写作，需要一篇教育类高分英文范文，主题“是否该强制学生穿校服”，要求结构清晰（观点+案例+结论），用下划线标出高级词汇，避开模板化句子,最后添加批注说明段落衔接技巧,并且把输出文档以txt格式保存至本地"
    
    nex_agent.run_workflow_with_review(
        user_input=user_query, 
        session_id=123456, 
        correlation_id="test123",
        debug=True
    )