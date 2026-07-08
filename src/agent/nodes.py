import logging
import json
from copy import deepcopy
from typing import Literal
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from langgraph.graph import END

from .llm import get_llm_by_type
from src.config import TEAM_MEMBERS
from src.config.agents import AGENT_LLM_MAP
from src.prompts.template import apply_prompt_template
from src.tools.search import tavily_tool
from .types import State, Router
from src.utils.msg_process import get_plan_json
from src.utils.db_manager import log_handler
from src.utils.interupt import intr, CustomInterrupt, InterruptibleAgent
from langgraph.prebuilt import create_react_agent
# from langchain.agents import create_agent
from src.prompts import apply_prompt_template
from src.utils.db_manager import node_state, ppt_state
import threading
import queue



from src.tools.bash_tool import bash_tool
from src.tools.browser import browser_tool
from src.tools.crawl import crawl_tool
from src.tools.python_repl import python_repl_tool
from src.tools.web_search import web_search
from src.tools.search import tavily_tool
from src.utils.db_manager import db_manager
from src.tools.autoppt import ppt_generator
from src.tools.UI_assistant import ui_automator
from src.tools.km import km_add_content, km_add_link, km_add_file
from src.tools.ocr_tool import ocr_tool
from src.tools.formfiller import parse_document, km_list_people, smartformfill
from src.utils.msg_process import get_first_json
import requests
import json
from src.tools.text2image import gen_image_tool
from src.utils.msg_process import get_first_json
# (
#     bash_tool,
#     browser_tool,
#     web_search,
#     crawl_tool,
#     python_repl_tool,
#     tavily_tool,
# )

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)


RESPONSE_FORMAT = "{}回复:\n\n<response>\n{}\n</response>\n\n*请执行下一步*"






# Create agents using configured LLM types
research_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["researcher"]),
    # tools=[tavily_tool, crawl_tool],
    tools=[web_search],
    prompt=lambda state: apply_prompt_template("researcher", state),
)

km_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["knowledge_manager"]),
    # tools=[tavily_tool, crawl_tool],
    tools=[km_add_content, km_add_link, km_add_file],
    prompt=lambda state: apply_prompt_template("knowledge_manager", state),
)

ocr_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["ocr_tool"]),
    # tools=[tavily_tool, crawl_tool],
    tools=[ocr_tool],
    prompt=lambda state: apply_prompt_template("ocr_tool", state),
)

pic_maker_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["pic_maker"]),
    # tools=[tavily_tool, crawl_tool],
    tools=[gen_image_tool],
    prompt=lambda state: apply_prompt_template("pic_maker", state),
)

filler_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["form_filler"]),
    # tools=[tavily_tool, crawl_tool],
    tools=[parse_document, km_list_people, smartformfill],
    prompt=lambda state: apply_prompt_template("form_filler", state),
)

coder_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["coder"]),
    tools=[python_repl_tool, bash_tool],
    prompt=lambda state: apply_prompt_template("coder", state),
)

browser_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["browser"]),
    tools=[browser_tool],
    prompt=lambda state: apply_prompt_template("browser", state),
)

ppt_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["ppt_generator"]),
    tools=[ppt_generator],
    prompt=lambda state: apply_prompt_template("ppt_generator", state),
)
ui_agent = create_react_agent(
    get_llm_by_type(AGENT_LLM_MAP["ui_automator"]),
    tools=[ui_automator],
    prompt=lambda state: apply_prompt_template("ui_automator", state),
)

def en_name(name):
    # 英文名到中文名的映射字典
    name_dict = {
        "用户": "user",
        "系统": "system",
        "监督员": "supervisor",
        "审核员": "reviewer",
        "复审核员": "review_processor",
        "规划员": "planner",
        "对话员": "conversationalist",
        "知识管理员": "knowledge_manager",
        "文本识别员": "ocr_tool",
        "图片制作员": "pic_maker",
        "填表员": "form_filler",
        "研究员": "researcher", 
        "程序员": "coder",
        "操作员": "operator", 
        "MCP服务": "mcp_server", 
        "网页浏览员": "browser", 
        "汇报员": "reporter", 
        "PPT专员": "ppt_generator",
        "UI专员": "ui_automator"
    }
    
    # 将输入的名字去除首尾空格，并处理大小写（保持原样查找，但可以增加灵活性）
    clean_name = name.strip()

    # 直接查找字典，如果找到则返回中文名，否则返回"未命名"
    return name_dict.get(clean_name, name.strip())

def zh_name(name):
    # 英文名到中文名的映射字典
    name_dict = {
        "user": "用户",
        "system": "系统",
        "supervisor": "监督员",
        "reviewer": "审核员",
        "review_processor": "复审核员",
        "planner": "规划员",
        "conversationalist": "对话员",
        "knowledge_manager": "知识管理员",
        "ocr_tool": "文本识别员",
        "pic_maker": "图片制作员",
        "form_filler": "填表员",
        "researcher": "研究员", 
        "coder": "程序员", 
        "operator": "操作员", 
        "mcp_server": "MCP服务", 
        "browser": "网页浏览员", 
        "reporter": "汇报员", 
        "ppt_generator": "PPT专员",
        "ui_automator": "UI专员"
    }
    
    # 将输入的名字去除首尾空格，并处理大小写（保持原样查找，但可以增加灵活性）
    clean_name = name.strip()

    # 直接查找字典，如果找到则返回中文名，否则返回"未命名"
    return name_dict.get(clean_name, name.strip())


class ResearchAgentRunner:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()
    
    def run_research_agent(self, state):
        def target():
            try:
                result = research_agent.invoke(state)
                logger.info(f"{self.session_id}-=-研究员===已完成任务")
                print(result)
                logger.info(f"{self.session_id}-=-研究员===结果：{result['messages'][-1].content}")

                output =  {
                    "messages": [
                        HumanMessage(
                            content=RESPONSE_FORMAT.format(
                                zh_name("researcher"), result["messages"][-1].content
                            ),
                            name=zh_name("researcher"),
                        )
                    ],
                    "cur": "researcher",
                    "next": "supervisor"
                }
                self.result_queue.put(("success", output))
            except Exception as e:
                print(str(e))
                self.result_queue.put(("error", str(e)))
        
        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()
    
    def _wait_for_result(self):
        # 原有的等待逻辑，但现在是实例方法，不会与其他实例混淆
        result_data = None
        try:
            while self.thread.is_alive():
                # 检查队列中是否有结果（非阻塞）
                try:
                    result_data = self.result_queue.get(block=False)
                    # 如果取到结果，立即终止进程
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    break
                except queue.Empty:
                    # 队列为空，继续等待
                    pass

                # 检查停止信号
                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-研究员===收到终止信号，结束工作")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，研究员工作中止")

                # 等待一小段时间
                self.thread.join(timeout=0.1)

            if result_data is None:
                # 进程已经结束，我们尝试取一次结果
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    # 如果队列仍然为空，说明子进程没有返回结果，可能是异常退出
                    raise CustomInterrupt("异常：研究员未反馈结果")

        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：研究员未反馈结果")
        
        return result_data
    
def research_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the researcher agent that performs research tasks."""
    
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-研究员===开始工作...")
    db_manager.set_session_node(session_id, "researcher")
    ppt_state.set_session_id(session_id)

    runner = ResearchAgentRunner(session_id)
    result_data = runner.run_research_agent(state)
    # 处理结果
    if result_data is not None:
        status, result = result_data
        if status == "success":
            return result
    raise CustomInterrupt("异常：研究员未反馈结果")
  
class PPTAgentRunner:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()

    def run_ppt_agent(self, state):
        def target():
            try:
                result = ppt_agent.invoke(state)
                logger.info(f"{self.session_id}-=-PPT专员===任务已完成")
                logger.info(f"{self.session_id}-=-PPT专员===结果：{result['messages'][-1].content}")

                output = {
                    "messages": [
                        HumanMessage(
                            content=RESPONSE_FORMAT.format(
                                zh_name("ppt_generator"), result["messages"][-1].content
                            ),
                            name=zh_name("ppt_generator"),
                        )
                    ],
                    "cur": "ppt_generator",
                    "next": "supervisor"
                }
                self.result_queue.put(("success", output))
            except Exception as e:
                print(str(e))
                self.result_queue.put(("error", str(e)))

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()

    def _wait_for_result(self):
        # 原有的等待逻辑，但现在是实例方法，不会与其他实例混淆
        result_data = None
        try:
            while self.thread.is_alive():
                # 检查队列中是否有结果（非阻塞）
                try:
                    result_data = self.result_queue.get(block=False)
                    # 如果取到结果，立即终止进程
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    break
                except queue.Empty:
                    # 队列为空，继续等待
                    pass

                # 检查停止信号
                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-PPT专员===收到终止信号，结束任务")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，PPT专员工作中止")

                # 等待一小段时间
                self.thread.join(timeout=0.1)

            if result_data is None:
                # 进程已经结束，我们尝试取一次结果
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    # 如果队列仍然为空，说明子进程没有返回结果，可能是异常退出
                    raise CustomInterrupt("异常：PPT专员未反馈结果")

        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：PPT专员未反馈结果")
        
        return result_data


def ppt_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the PPT agent that creates PowerPoint presentations."""

    session_id = state["session_id"]
    logger.info("-" * 50)
    logger.info(f"{session_id}-=-PPT专员===开始工作...")
    
    db_manager.set_session_node(session_id, "ppt_generator")
    ppt_state.set_session_id(session_id)

    runner = PPTAgentRunner(session_id)
    result_data = runner.run_ppt_agent(state)

    if result_data is not None:
        status, result = result_data
        if status == "success":
            return result
    raise CustomInterrupt("异常：PPT专员未反馈结果")


class UIAgentRunner:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()

    def run_ui_agent(self, state):
        def target():
            try:
                logger.info(f"{self.session_id}-=-UI专员========")
                result = ui_agent.invoke(state)
                logger.info(f"{self.session_id}-=-UI专员===任务已完成")
                logger.info(f"{self.session_id}-=-UI专员===结果：{result['messages'][-1].content}")

                output = {
                    "messages": [
                        HumanMessage(
                            content=RESPONSE_FORMAT.format(
                                zh_name("ui_automator"), result["messages"][-1].content
                            ),
                            name=zh_name("ui_automator"),
                        )
                    ],
                    "cur": "ui_automator",
                    "next": "supervisor"
                }
                self.result_queue.put(("success", output))
            except Exception as e:
                print(str(e))
                self.result_queue.put(("error", str(e)))

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()

    def _wait_for_result(self):
        # 原有的等待逻辑，但现在是实例方法，不会与其他实例混淆
        result_data = None
        try:
            while self.thread.is_alive():
                # 检查队列中是否有结果（非阻塞）
                try:
                    result_data = self.result_queue.get(block=False)
                    # 如果取到结果，立即终止进程
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    break
                except queue.Empty:
                    # 队列为空，继续等待
                    pass

                # 检查停止信号
                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-UI专员===收到终止信号，结束任务")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，UI专员工作中止")

                # 等待一小段时间
                self.thread.join(timeout=0.1)

            if result_data is None:
                # 进程已经结束，我们尝试取一次结果
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    # 如果队列仍然为空，说明子进程没有返回结果，可能是异常退出
                    raise CustomInterrupt("异常：UI专员未反馈结果")

        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：UI专员未反馈结果")

        return result_data


def ui_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the PPT agent that creates PowerPoint presentations."""

    session_id = state["session_id"]
    logger.info("-" * 50)
    logger.info(f"{session_id}-=-UI专员===开始工作...")

    db_manager.set_session_node(session_id, "ui_automator")
    # ppt_state.set_session_id(session_id)
    logger.info(f"{session_id}-=-UI专员===开始运行1")
    runner = UIAgentRunner(session_id)
    logger.info(f"{session_id}-=-UI专员===开始运行2")
    result_data = runner.run_ui_agent(state)
    logger.info(f"{session_id}-=-UI专员===开始运行3")
    if result_data is not None:
        status, result = result_data
        if status == "success":
            return result
    raise CustomInterrupt("异常：UI专员未反馈结果")


class CodeAgentRunner:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()

    def run_coder_agent(self, state):
        def target():
            try:
                result = coder_agent.invoke(state)
                if self._stop_event.is_set():
                    return
                logger.info(f"{self.session_id}-=-程序员===任务已完成")
                logger.info(f"{self.session_id}-=-程序员===结果：{result['messages'][-1].content}")

                output = {
                        "messages": [
                            HumanMessage(
                                content=RESPONSE_FORMAT.format(
                                    zh_name("coder"), result["messages"][-1].content
                                ),
                                name=zh_name("coder"),
                            )
                        ],
                        "cur": "coder",
                        "next": "supervisor"
                    }
                self.result_queue.put(("success", output))
            except Exception as e:
                print(str(e))
                self.result_queue.put(("error", str(e)))

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()

    def _wait_for_result(self):
        result_data = None
        try:
            while self.thread.is_alive():
                try:
                    result_data = self.result_queue.get(block=True, timeout=0.1)
                    break
                except queue.Empty:
                    pass

                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-程序员===收到终止信号，结束任务")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，程序员工作中止")

            if result_data is None:
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    raise CustomInterrupt("异常：程序员未反馈结果")

        except CustomInterrupt:
            raise
        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：程序员未反馈结果")
        
        return result_data
    

def code_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the coder agent that executes Python code."""
    session_id = state["session_id"]
    logger.info("-" * 50)
    logger.info(f"{session_id}-=-程序员===开始工作...")
    db_manager.set_session_node(session_id, "coder")
    # logger.debug(f"Current state: {state}")

    runner = CodeAgentRunner(session_id)
    result_data = runner.run_coder_agent(state)

    # 处理结果
    if result_data is not None:
        status, result = result_data
        if status == "success":
            return result

    raise CustomInterrupt("异常：程序员未反馈结果")


class BrowserAgentRunner:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()
    
    def run_browser_agent(self, state):
        def target():
            try:
                print(f"run_browser_agent...")
                result = browser_agent.invoke(state)
                logger.info(f"{self.session_id}-=-网页浏览员===任务已完成")
                logger.info(f"{self.session_id}-=-网页浏览员===结果：{result['messages'][-1].content}")
                print(f"{self.session_id}-=-{result['messages'][-1].content}")
                output = {
                    "messages": [
                        HumanMessage(
                            content=RESPONSE_FORMAT.format(
                                zh_name("browser"), result["messages"][-1].content
                            ),
                            name=zh_name("browser"),
                        )
                    ],
                    "cur": "browser",
                    "next": "supervisor"
                }
                self.result_queue.put(("success", output))
            except Exception as e:
                print(str(e))
                self.result_queue.put(("error", str(e)))
        
        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()
    
    def _wait_for_result(self):
        # 原有的等待逻辑，但现在是实例方法，不会与其他实例混淆
        result_data = None
        try:
            while self.thread.is_alive():
                # 检查队列中是否有结果（非阻塞）
                try:
                    result_data = self.result_queue.get(block=False)
                    # 如果取到结果，立即终止进程
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    break
                except queue.Empty:
                    # 队列为空，继续等待
                    pass

                # 检查停止信号
                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-网页浏览员===收到终止信号，结束任务")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，网页浏览员工作中止")

                # 等待一小段时间
                self.thread.join(timeout=0.1)

            if result_data is None:
                # 进程已经结束，我们尝试取一次结果
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    # 如果队列仍然为空，说明子进程没有返回结果，可能是异常退出
                    raise CustomInterrupt("异常：网页浏览员未反馈结果")

        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：网页浏览员未反馈结果")
        
        return result_data
    
def browser_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the browser agent that performs web browsing tasks."""
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-网页浏览员===开始工作...")
    db_manager.set_session_node(session_id, "browser")

    runner = BrowserAgentRunner(session_id)
    result_data = runner.run_browser_agent(state)
    if result_data is not None:
        status, result = result_data
        if status == "success":
        #    logger.info(f"{session_id}-=-Browser agent end task")
           return result
     
    raise CustomInterrupt("异常：网页浏览员未反馈结果")




class SupervisorAgentRunner:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()
    
    def run_supervisor_agent(self, state):
        def target():
            try:
                # valid_next_nodes = ["researcher", "coder", "operator", "mcp_server", "browser", "reporter", "ppt_generator", "pic_maker","__end__"]
                valid_next_nodes = ["研究员", "程序员", "操作员", "网页浏览员", "汇报员", "PPT专员", "UI专员","图片制作员", "MCP服务", "结束", "__end__"]
                max_retries = 3
                
                for retry_count in range(max_retries):
                    # 在重试时提供更明确的指示
                    if retry_count > 0:
                        # 在state中添加明确的指令
                        enhanced_state = state.copy()
                        enhanced_state["explicit_instruction"] = f"请从以下选项中选择: {', '.join(valid_next_nodes)}。不要返回其他值。"
                        messages = apply_prompt_template("supervisor", enhanced_state)
                    else:
                        messages = apply_prompt_template("supervisor", state)
                    # print('='*50)
                    # for content in messages:
                    #     print(content)
                    # print('='*50)
                    # result = (
                    #     get_llm_by_type(AGENT_LLM_MAP["supervisor"])
                    #     # .with_structured_output(Router)
                    #     .invoke(messages)
                    # )
                    stream = get_llm_by_type(AGENT_LLM_MAP["supervisor"]).stream(messages)
                    full_response = ""
                    for chunk in stream:
                        if db_manager.get_session_stop(self.session_id):
                            raise CustomInterrupt("收到终止信号，协调员工作中止")
                        full_response += chunk.content
                    # content= result['messages'][-1].content
                    response = get_first_json(full_response)
                    print(response)
                    goto = response["next"]
                    stepIndex = response.get("step", 1)
                    stepNum = response.get("all_step", 1)
                    # if goto not in valid_next_nodes:
                    #     b = goto.encode('latin-1')  # 得到原本的 UTF-8 字节
                    #     goto = b.decode('utf-8')
                    # print(goto)
                    reasoning = response.get("reasoning", "")
                    task = response.get("task", "")
                    # 处理 FINISH 情况
                    # if stepIndex == stepNum:
                    #     goto = END
                    if goto == "结束":
                        goto = END
                    
                    # 验证并可能的映射
                    if goto in valid_next_nodes:
                        name = en_name(goto)
                        logger.info(f"{self.session_id}-=-监督员===指派任务给: {goto}\n任务要求:{task}\n原因: {reasoning}")
                        if goto == END and "任务已完成" not in task:
                            task = "任务已完成"
                        self.result_queue.put(("success",  
                                               {"cur": "supervisor",             
                                                "messages": [
                                                        HumanMessage(
                                                            content=RESPONSE_FORMAT.format(zh_name("supervisor"), f"@{goto}，{task}"),
                                                            name=zh_name("supervisor"),
                                                                )
                                                            ],
                                                "next": name}
                                                ))
                        return
                    else:
                        logger.warning(f"{self.session_id}-=-监督员===无效的反馈: '{goto}'。 重试 {retry_count + 1}/{max_retries}")
            except Exception as e:
                print(str(e))
                pass
            logger.error(f"{self.session_id}-=-监督员===已重试多次，默认指派给汇报员")
            self.result_queue.put(("success",  {
                    "cur": "supervisor",
                    "next": "reporter"
                }))
        
        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()
    
    def _wait_for_result(self):
        result_data = None
        try:
            while self.thread.is_alive():
                try:
                    result_data = self.result_queue.get(block=False)
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    break
                except queue.Empty:
                    pass

                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-监督员===收到终止信号，结束任务")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，监督员工作中止")

                self.thread.join(timeout=0.1)

            if result_data is None:
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    raise CustomInterrupt("异常：监督员未反馈结果")

        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：监督员未反馈结果")
        
        return result_data
    
def supervisor_node(state: State) -> Command[Literal["researcher", "coder", "operator","ui_automator", "mcp_server", "browser", "reporter", "ppt_generator", "pic_maker","__end__"]]:
    """Supervisor node that decides which agent should act next."""
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-监督员===正在评估将任务指派给谁")
    db_manager.set_session_node(session_id, "supervisor")

    runner = SupervisorAgentRunner(session_id)
    result_data = runner.run_supervisor_agent(state)
    # 处理结果
    if result_data is not None:
        status, result = result_data
        if status == "success":
            # logger.info(f"{session_id}-=-Supervisor agent completed task")
            return result

    raise CustomInterrupt("异常：监督员未反馈结果")

class KMAgentRunner:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()
    
    def run_km_agent(self, state):
        def target():
            try:
                # result = filler_agent.invoke(state)
                result = km_agent.invoke(state)
                logger.info(f"{self.session_id}-=-知识管理员===任务已完成")
                # logger.info(f"{self.session_id}-=-知识管理员===结果：{result["messages"][-1].content}")
                output =  { 
                    "messages": [
                        HumanMessage(
                            content=RESPONSE_FORMAT.format(
                                zh_name("knowledge_manager"), result["messages"][-1].content
                            ),
                            name=zh_name("knowledge_manager"),
                        )
                    ],
                    "cur": "knowledge_manager",
                    "next": "__end__"
                }
                
                self.result_queue.put(("success", output))
            except Exception as e:
                print(str(e))
                self.result_queue.put(("error", str(e)))
        
        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()
    
    def _wait_for_result(self):
        # 原有的等待逻辑，但现在是实例方法，不会与其他实例混淆
        result_data = None
        try:
            while self.thread.is_alive():
                # 检查队列中是否有结果（非阻塞）
                try:
                    result_data = self.result_queue.get(block=False)
                    # 如果取到结果，立即终止进程
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    break
                except queue.Empty:
                    # 队列为空，继续等待
                    pass

                # 检查停止信号
                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-知识管理员===收到终止信号，结束任务")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，知识管理员工作中止")

                # 等待一小段时间
                self.thread.join(timeout=0.1)

            if result_data is None:
                # 进程已经结束，我们尝试取一次结果
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    # 如果队列仍然为空，说明子进程没有返回结果，可能是异常退出
                    raise CustomInterrupt("异常：文本员未反馈结果")

        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：文本识别员未反馈结果")
        
        return result_data
    
def km_node(state: State) -> Command[Literal["__end__"]]:
    """Node for the knowledge manager agent"""
    session_id = state["session_id"]
    logger.info("-" * 50)
    logger.info(f"{session_id}-=-知识管理员===开始工作...")
    db_manager.set_session_node(session_id, "knowledge_manager")

    runner = KMAgentRunner(session_id)
    result_data = runner.run_km_agent(state)
    # 处理结果
    if result_data is not None:
        status, result = result_data
        if status == "success":
            return result
    raise CustomInterrupt("异常：知识管理员未反馈结果")



class FormFillAgentRunner:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()
    
    def run_formfill_agent(self, state):
        def target():
            try:
                # result = filler_agent.invoke(state)
                result = filler_agent.invoke(state)
                logger.info(f"{self.session_id}-=-填表员===任务已完成")
                
                print(result["messages"][-1].content)
                content = result["messages"][-1].content
                json_data = {}

                json_data = get_first_json(content)
                if "结果" in content:
                    json_data = json_data.get("结果", {})
                if "Result" in content:
                    json_data = json_data.get("Result", {})
                # logger.info(f"{self.session_id}-=-填表员===结果：{json_data["response"]}")
                if json_data.get("ask_user", False) == True:
                    db_manager.set_wait_feedback_node(self.session_id, "form_filler")
                    output =  {
                        "messages": [
                            HumanMessage(
                                content=RESPONSE_FORMAT.format(
                                    zh_name("form_filler"), json_data["response"]
                                ),
                                name=zh_name("form_filler"),
                            )
                        ],
                        "cur": "form_filler",
                        "next": "reviewer",
                        "last": "from_filler",
                    }
                else:
                    output =  {
                        "messages": [
                            HumanMessage(
                                content=RESPONSE_FORMAT.format(
                                    zh_name("form_filler"), json_data["response"]
                                ),
                                name=zh_name("form_filler"),
                            )
                        ],
                        "cur": "form_filler",
                        "next": "__end__",
                        "last": "from_filler",
                    }
                self.result_queue.put(("success", output))
            except Exception as e:
                print(str(e))
                self.result_queue.put(("error", str(e)))
        
        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()
    
    def _wait_for_result(self):
        # 原有的等待逻辑，但现在是实例方法，不会与其他实例混淆
        result_data = None
        try:
            while self.thread.is_alive():
                # 检查队列中是否有结果（非阻塞）
                try:
                    result_data = self.result_queue.get(block=False)
                    # 如果取到结果，立即终止进程
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    break
                except queue.Empty:
                    # 队列为空，继续等待
                    pass

                # 检查停止信号
                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-填表员===收到终止信号，结束任务")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，填表员工作中止")

                # 等待一小段时间
                self.thread.join(timeout=0.1)

            if result_data is None:
                # 进程已经结束，我们尝试取一次结果
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    # 如果队列仍然为空，说明子进程没有返回结果，可能是异常退出
                    raise CustomInterrupt("异常：填表员未反馈结果")

        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：填表员未反馈结果")
        
        return result_data
    
def filler_node(state: State) -> Command[Literal["reviewer", "__end__"]]:
    """Node for the knowledge manager agent"""
    session_id = state["session_id"]
    logger.info("-" * 50)
    logger.info(f"{session_id}-=-填表员===开始工作...")
    db_manager.set_session_node(session_id, "form_filler")
    node_state.set_session_id(session_id)
    runner = FormFillAgentRunner(session_id)

    
    # enhanced_state = dict(state)
    # enhanced_state["messages"][-1].content +=  "待填入人为刘晴楠"

    result_data = runner.run_formfill_agent(state)
    # 处理结果
    if result_data is not None:
        status, result = result_data
        if status == "success":
            return result
    raise CustomInterrupt("异常：填表员未反馈结果")



def social_node(state: State) -> Command[Literal["planner", "__end__"]]:
    """Social node process user's query"""
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-对话员===开始工作...")
    db_manager.set_session_node(session_id, "conversationalist")
    if db_manager.get_session_stop(session_id):
        raise CustomInterrupt("-=-对话员===收到终止信号，结束任务")
    

    
    # logger.debug(f"Current state: {state}")
    messages = apply_prompt_template("conversationalist", state)
    # whether to enable deep thinking mode
    llm = get_llm_by_type("basic")
    
    stream = llm.stream(messages)
    full_response = ""
    print("conversationalist:\n", end="", flush=True)
    for chunk in stream:
        if db_manager.get_session_stop(session_id):
            raise CustomInterrupt("=-对话员===收到终止信号，结束对话")
        full_response += chunk.content
        db_manager.publish(
                    session_id,
                    {
                        "type": "chat_stream",
                        "payload": {
                            "role": "对话员",
                            "content": full_response,
                        },
                    },
                )

        print(chunk.content, end="", flush=True)

    if "planner" in full_response:
        goto = "planner"
    else:
        goto = END


    logger.info(f"{session_id}-=-对话员===回复：{full_response}")
    return {
            "messages": [HumanMessage(content=full_response, name=zh_name("conversationalist"))],
            "cur": "conversationalist",
            "next": goto,
        }



def ask_mcp(messages, session_id, allow_servers=None, dry_run=False, timeout_ms=180000, base_url="http://127.0.0.1:50066"):
    """
    向MCP代理发送查询请求
    
    参数:
    - query: 要执行的查询字符串
    - allow_servers: 允许使用的服务器列表，None表示不限制
    - dry_run: 是否只计划不执行
    - timeout_ms: 超时时间（毫秒）
    - base_url: MCP服务的基础URL
    
    返回:
    - 执行结果或错误信息
    """
    new_messages = deepcopy(messages)
    query = new_messages[-1].content

    # 提取最近几轮对话上下文，作为独立字段传给 MCP
    # 解决多轮对话时 hermes_ask 丢失上一轮信息的问题
    context_parts = []
    for msg in new_messages[-5:]:
        role = getattr(msg, 'name', None) or getattr(msg, 'type', 'unknown')
        content = str(msg.content)[:300] if hasattr(msg, 'content') else ''
        if role and role not in ('unknown',) and content:
            context_parts.append(f"[{role}]: {content}")
    context_messages = "\n".join(context_parts) if context_parts else None

    # 构建请求负载
    count = 1
    while count < 6:
        logger.info(f"{session_id}-=-操作员===尝试调用MCP服务第{count}次")
        count += 1 
        payload = {
            "query": query,
            "timeout_ms": timeout_ms,
            "session_id": session_id,
            "dry_run": dry_run
        }

        # 多轮对话上下文
        if context_messages:
            payload["context_messages"] = context_messages
        
        # 如果指定了允许的服务器，添加到payload中
        if allow_servers is not None:
            payload["allow_servers"] = allow_servers
        
        headers = {"Content-Type": "application/json"}
        
        try:
            response = requests.post(
                f"{base_url}/agent/ask",
                headers=headers,
                json=payload,
                timeout=timeout_ms/1000  # 转换为秒
            )
            
            response.raise_for_status()
            result = response.json()
            
            
            print("响应状态:", response.status_code)
            # print("响应内容:")
            # print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # 解析结果
            if result.get("executed"):
                print("\n执行成功！")
                logger.info(f"{session_id}-=-操作员===使用的服务器: {result.get('plan', {}).get('server', '未知')}")
                logger.info(f"{session_id}-=-操作员===使用的工具: {result.get('plan', {}).get('tool', '未知')}")
                print(f"最终答案: {result.get('answer', '无')}")
                return result.get("answer", "执行出错，请检查MCP服务是否启动")
            else:
                print("\n执行失败或未执行")
                if result.get("clarification_needed"):
                    print("需要更多信息:", result.get("clarification", {}))
                    messages.append(
                        HumanMessage(
                            content=result.get("clarification").get("question"),name=zh_name("MCP服务")
                        ))
                    messages.append(
                        HumanMessage(
                            content="请根据上下文信息，生成一句简明扼要的完整任务要求。",
                            name=zh_name("操作员"),
                        ))
                    print(messages[-1].content)
                    llm_response = get_llm_by_type("basic").invoke(messages)
                    query = llm_response.content
                    print(query)
            
            
            
        except requests.exceptions.RequestException as e:
            print(f"请求失败: {e}")
            return "执行出错，请检查MCP服务是否启动，以及kylin-actuator是否安装"
        except Exception as e:
            print(f"异常: {e}")


def operator_node(state: State) -> Command[Literal["__end__"]]:
    """Operator node process user's query"""
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-操作员===开始工作...")
    last_node = db_manager.get_last_session_node(session_id)
    db_manager.set_session_node(session_id, "operator")
    if db_manager.get_session_stop(session_id):
        raise CustomInterrupt("收到终止信号，操作员工作中止")
    # logger.debug(f"Current state: {state}")
        
    full_response = ask_mcp(state["messages"], session_id, allow_servers=["kylin_sdk_server", "kylin_desktop_control_server", "hermes_bridge"])
    if full_response:
        logger.info(f"{session_id}-=-操作员==={full_response}")
    next_role = END
    if last_node == "supervisor":
        next_role = "supervisor"
    return {
            "messages": [HumanMessage(content=full_response, name=zh_name("operator"))],
            "cur": "operator",
            "next": next_role,
        }



class OCRAgentRunner:
    def __init__(self, session_id):
        self.session_id = session_id
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()

    def run_ocr_agent(self, state):
        def target():
            try:
                # result = filler_agent.invoke(state)
                result = ocr_agent.invoke(state)
                logger.info(f"{self.session_id}-=-文本识别员===任务已完成")
                # logger.info(f"{self.session_id}-=-文本识别员==={result["messages"][-1].content}")
                output =  {
                    "messages": [
                        HumanMessage(
                            content=RESPONSE_FORMAT.format(
                                zh_name("ocr_tool"), result["messages"][-1].content
                            ),
                            name=zh_name("ocr_tool"),
                        )
                    ],
                    "cur": "ocr_tool",
                    "next": END
                }

                self.result_queue.put(("success", output))
            except Exception as e:
                print(str(e))
                self.result_queue.put(("error", str(e)))

        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()

    def _wait_for_result(self):
        # 原有的等待逻辑，但现在是实例方法，不会与其他实例混淆
        result_data = None
        try:
            while self.thread.is_alive():
                # 检查队列中是否有结果（非阻塞）
                try:
                    result_data = self.result_queue.get(block=False)
                    # 如果取到结果，立即终止进程
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    break
                except queue.Empty:
                    # 队列为空，继续等待
                    pass

                # 检查停止信号
                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-文本识别员===收到终止信号，结束任务")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，文本识别员工作中止")

                # 等待一小段时间
                self.thread.join(timeout=0.1)

            if result_data is None:
                # 进程已经结束，我们尝试取一次结果
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    # 如果队列仍然为空，说明子进程没有返回结果，可能是异常退出
                    raise CustomInterrupt("异常：文本识别员未反馈结果")

        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：文本识别员未反馈结果")

        return result_data
    
def ocr_node(state: State) -> Command[Literal["__end__"]]:
    """Node for the ocr agent"""
    session_id = state["session_id"]
    logger.info("-" * 50)
    logger.info(f"{session_id}-=-文本识别员===开始工作...")
    db_manager.set_session_node(session_id, "ocr_tool")

    runner = OCRAgentRunner(session_id)
    result_data = runner.run_ocr_agent(state)
    # 处理结果
    if result_data is not None:
        status, result = result_data
        if status == "success":
            return result
    raise CustomInterrupt("异常：文本识别员未反馈结果")


def get_string_before(text, spliter):
    """返回'==='之前的字符串，如果没有则返回原字符串"""
    return text.split(spliter)[0] if spliter in text else text

class PicMakerAgentRunner:
    def __init__(self, session_id, last_node):
        self.session_id = session_id
        self.last_node = last_node
        self.result_queue = queue.Queue()
        self.thread = None
        self._stop_event = threading.Event()
    
    def run_pic_maker_agent(self, state):
        def target():
            try:
                # result = filler_agent.invoke(state)
                result = pic_maker_agent.invoke(state)
                logger.info(f"{self.session_id}-=-图片制作员===任务已完成")
                content = result["messages"][-1].content
                content = get_string_before(content, "<img class=\"chat-image\"")
                logger.info(f"{self.session_id}-=-图片制作员==={content}")
                next_role = END
                if self.last_node == "supervisor":
                    next_role = "supervisor"
                
                output =  { 
                    "messages": [
                        HumanMessage(
                            content=RESPONSE_FORMAT.format(
                                zh_name("pic_maker"), result["messages"][-1].content
                            ),
                            name=zh_name("pic_maker"),
                        )
                    ],
                    "cur": "pic_maker",
                    "next": next_role
                }
                
                self.result_queue.put(("success", output))
            except Exception as e:
                print(str(e))
                self.result_queue.put(("error", str(e)))
        
        self.thread = threading.Thread(target=target, daemon=True)
        self.thread.start()
        return self._wait_for_result()
    
    def _wait_for_result(self):
        # 原有的等待逻辑，但现在是实例方法，不会与其他实例混淆
        result_data = None
        try:
            while self.thread.is_alive():
                # 检查队列中是否有结果（非阻塞）
                try:
                    result_data = self.result_queue.get(block=False)
                    # 如果取到结果，立即终止进程
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    break
                except queue.Empty:
                    # 队列为空，继续等待
                    pass

                # 检查停止信号
                if db_manager.get_session_stop(self.session_id):
                    logger.info(f"{self.session_id}-=-图片制作员===收到终止信号，结束任务")
                    self._stop_event.set()
                    self.thread.join(timeout=2)
                    raise CustomInterrupt("收到终止信号，图片制作员工作中止")

                # 等待一小段时间
                self.thread.join(timeout=0.1)

            if result_data is None:
                # 进程已经结束，我们尝试取一次结果
                try:
                    result_data = self.result_queue.get(block=False)
                except queue.Empty:
                    # 如果队列仍然为空，说明子进程没有返回结果，可能是异常退出
                    raise CustomInterrupt("异常：图片制作员未反馈结果")

        except Exception as e:
            print(str(e))
            self._stop_event.set()  # 通知线程停止
            self.thread.join(timeout=2)
            raise CustomInterrupt("异常：图片制作员未反馈结果")
        
        return result_data
    
def gen_image_node(state: State) -> Command[Literal["supervisor", "__end__"]]:
    """Node for the ocr agent"""
    session_id = state["session_id"]
    logger.info("-" * 50)
    logger.info(f"{session_id}-=-图片制作员===开始工作...")
    last_node = db_manager.get_last_session_node(session_id)
    db_manager.set_session_node(session_id, "pic_maker")

    runner = PicMakerAgentRunner(session_id, last_node)
    result_data = runner.run_pic_maker_agent(state)
    # 处理结果
    if result_data is not None:
        status, result = result_data
        if status == "success":
            return result
    raise CustomInterrupt("异常：图片制作员未反馈结果")



# def ocr_node(state: State) -> Command[Literal["__end__"]]:
#     """Operator node process user's query"""
#     session_id = state["session_id"]
#     logger.info("-"*50)
#     logger.info(f"{session_id}-=-文本识别员===开始工作...")
#     db_manager.set_session_node(session_id, "ocr_tool")
#     if db_manager.get_session_stop(session_id):
#         raise CustomInterrupt("Interrupted during Operator")
#     # logger.debug(f"Current state: {state}")
    
#     full_response = ask_mcp(state["messages"][-1].content, allow_servers=["kylin_server"])

#     logger.info(f"{session_id}-=-{full_response}")
#     return {
#             "messages": [HumanMessage(content=full_response, name="operator")],
#             "cur": "operator",
#             "next": END,
#         }


def mcp_node(state: State) -> Command[Literal["supervisor"]]:
    """Operator node process user's query"""
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-MCP服务===开始工作...")
    db_manager.set_session_node(session_id, "mcp_server")
    if db_manager.get_session_stop(session_id):
        raise CustomInterrupt("收到终止信号，MCP服务工作中止")
    # logger.debug(f"Current state: {state}")
    
    full_response = ask_mcp(state["messages"][-1].content, session_id)

    logger.info(f"{session_id}-=-MCP服务==={full_response}")
    return {
            "messages": [HumanMessage(content=full_response, name=zh_name("operator"))],
            "cur": "mcp_server",
            "next": "supervisor",
        }

def planner_node(state: State) -> Command[Literal["reviewer", "__end__"]]:
    """Planner node that generate the full plan."""
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-规划员===开始规划...")
    db_manager.set_session_node(session_id, "planner")
    if db_manager.get_session_stop(session_id):
        raise CustomInterrupt("收到终止信号，规划中止")
   

    messages = apply_prompt_template("planner", state)
    print(messages[0])
    # whether to enable deep thinking mode
    llm = get_llm_by_type("basic")
    if state.get("deep_thinking_mode"):
        llm = get_llm_by_type("reasoning")
    if state.get("search_before_planning"):
        searched_content = tavily_tool.invoke({"query": state["messages"][-1].content})
        if "HTTPError" in searched_content:
            logger.error(f"Search error: {searched_content}")
        else:
            messages = deepcopy(messages)
            messages[
                -1
            ].content += f"\n\n# Relative Search Results\n\n{json.dumps([{'titile': elem['title'], 'content': elem['content']} for elem in searched_content], ensure_ascii=False)}"
    
    # for idx, content in enumerate(messages):
    #     print(f"{idx}:{content}")


    stream = llm.stream(messages)
    full_response = ""
    print("Full Plan:\n", end="", flush=True)
    for chunk in stream:
        if db_manager.get_session_stop(session_id):
            raise CustomInterrupt("收到终止信号，中止规划")
        full_response += chunk.content
        db_manager.publish(
                    session_id,
                    {
                        "type": "chat_stream",
                        "payload": {
                            "role": "规划员",
                            "content": full_response,
                        },
                    },
                )

        print(chunk.content, end="", flush=True)


    goto = "reviewer"
    full_plan = get_plan_json(full_response)
    db_manager.set_wait_feedback_node(session_id, "planner")
    db_manager.set_full_plan(session_id, full_plan)
    logger.info(f"{session_id}-=-规划员==={full_response}")
    return {
            "messages": [HumanMessage(content=full_plan, name=zh_name("planner"))],
            "full_plan": full_plan,
            "cur": "planner",
            "next": goto,
            "last": "planner",
        }
        

def coordinator_node(state: State) -> Command[Literal["planner", "conversationalist", "knowledge_manager", "operator", "form_filler", "__end__"]]:
    """Coordinator node that communicate with customers."""
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-协调员===开始工作...")
    node_state.set_session_id(session_id)
    db_manager.set_session_node(session_id, "coordinator")
    if db_manager.get_session_stop(session_id):
        raise CustomInterrupt("收到终止信号，协调员工作中止")

    messages = apply_prompt_template("coordinator", state)

    stream = get_llm_by_type(AGENT_LLM_MAP["coordinator"]).stream(messages)
    full_response = ""
    for chunk in stream:
        if db_manager.get_session_stop(session_id):
            raise CustomInterrupt("收到终止信号，协调员工作中止")
        full_response += chunk.content


    goto = "__end__"
    if "handoff_to_planner" in full_response:
        goto = "planner"
    elif "handoff_to_conversationalist" in full_response:
        goto = "conversationalist"
    elif "handoff_to_operator" in full_response:
        goto = "operator"
    elif "handoff_to_ocr_tool" in full_response:
        goto = "ocr_tool"
    elif "handoff_to_pic_maker" in full_response:
        goto = "pic_maker"
    elif "handoff_to_knowledge_manager" in full_response:
        goto = "knowledge_manager"
    elif "handoff_to_form_filler" in full_response:
        goto = "form_filler"
    # 兜底：LLM 没输出路由指令时，非空输入转交谈者处理
    elif goto == "__end__" and full_response.strip():
        goto = "conversationalist"
    name = zh_name(goto)
    logger.info(f"{session_id}-=-协调员===协调 {name} 完成该任务")
    if goto == END:
        return {
            "cur": "coordinator",
            "next": goto,
            "messages": [
                    HumanMessage(
                        content=RESPONSE_FORMAT.format(zh_name("coordinator"), full_response),
                        name=zh_name("coordinator"),
                    )
                ],
            }
    else:
        return {
                "cur": "coordinator",
                "next": goto,
                }




def reporter_node(state: State) -> Command[Literal["supervisor"]]:
    """Reporter node that write a final report."""
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-汇报员===开始工作...")
    db_manager.set_session_node(session_id, "reporter")

    messages = apply_prompt_template("reporter", state)
    stream = get_llm_by_type(AGENT_LLM_MAP["reporter"]).stream(messages)
    response = ""
   
    for chunk in stream:
        if db_manager.get_session_stop(session_id):
            raise CustomInterrupt("Interrupted during planner generating full plan")
        response += chunk.content
        db_manager.publish(
                    session_id,
                    {
                        "type": "chat_stream",
                        "payload": {
                            "role": "汇报员",
                            "content": response,
                        },
                    },
                )

    logger.debug(f"{session_id}-=-汇报员===结果：{response}")
    return {
            "messages": [
                HumanMessage(
                    content=RESPONSE_FORMAT.format(zh_name("reporter"), response),
                    name=zh_name("reporter"),
                )
            ],
            "cur": "reporter",
            "next": "supervisor",
        }

def reviewer_node(state: State) -> Command[Literal["review_processor"]]:
    """Node for user to review and approve/modify/reject the plan."""
    session_id = state["session_id"]
    logger.info("-"*50)
    
    db_manager.set_session_node(session_id, "reviewer")
    wait_feedback_node = db_manager.get_wait_feedback_node(session_id)
    if wait_feedback_node == "planner":
        logger.info(f"{session_id}-=-审核员===等待用户审查计划")
        return {
                "waiting_for_review": True,
                "messages": [
                    HumanMessage(
                        content="请审查以上计划，并回复：\n1.同意：确认计划\n2.拒绝：拒绝计划并重新生成\n3.修改：你的修改意见",
                        name=zh_name("reviewer")
                    )
                ],
                "cur": "reviewer",
                "next": "review_processor",
            }
    else:
        logger.info(f"{session_id}-=-审核员===正在询问用户，希望提供更多信息")
        return {
                "waiting_for_review": True,
                "messages": [
                    HumanMessage(
                        content="请根据要求提供相关信息",
                        name=zh_name("reviewer")
                    )
                ],
                "cur": "reviewer",
                "next": "review_processor",
            }
         # 直接进入决策处理节点
    

# 修改 process_review_decision_node
def review_processor_node(state: State) -> Command[Literal["supervisor", "planner", "review_processor", "form_filler"]]:
    """Process user's review decision"""
    session_id = state["session_id"]
    logger.info("-"*50)
    logger.info(f"{session_id}-=-复审核员===处理用户反馈")
    db_manager.set_session_node(session_id, "review_processor")

    user_input = db_manager.get_user_feedback(session_id).strip().upper()
    wait_feedback_node = db_manager.get_wait_feedback_node(session_id)
    if wait_feedback_node == "planner":
        if user_input == "":
            logger.info(f"{session_id}-=-复审核员===等待用户反馈")
            return {
                    "waiting_for_review": True,
                    # "user_feedback": "",  # 清除无效反馈
                    "messages": [
                        *state["messages"],
                        HumanMessage(
                            content="无效的输入，请使用 '同意', '拒绝' 或 '修改：你的修改' 格式",
                            name=zh_name("system")
                        )
                    ],
                    "cur": "review_processor",
                    "next": "review_processor"  # 返回决策处理节点
                }
        
        logger.info(f"{session_id}-=-复审核员===处理用户的反馈: {user_input}")
        
        # 提取用户决策
        if "同意" in user_input:
            logger.info(f"{session_id}-=-复审核员===用户同意计划")
            return {
                    "waiting_for_review": False,
                    # "user_feedback": "",  # 清除反馈
                    "messages": [
                        HumanMessage(
                            content=f"好，按这个计划来", name=zh_name("user")
                        )
                    ],
                    "cur": "review_processor",
                    "next": "supervisor"
                }
        
        elif '拒绝' in user_input:
            logger.info(f"{session_id}-=-复审核员===用户拒绝计划，重新规划...")
            # 清除现有计划并重新生成
            return {
                    "full_plan": "",
                    "waiting_for_review": False,
                    # "user_feedback": "",  # 清除反馈
                    "messages": [
                        HumanMessage(
                            content=f"不好，请重新生成计划，并按原来的格式输出。", name=zh_name("user")
                        )
                    ],
                    "cur": "review_processor",
                    "next": "planner"
                }
        
        elif user_input.startswith("修改后的计划："):
            logger.info(f"{session_id}-=-复审核员===用户修改了计划")
            # 提取修改内容
            modified_plan = user_input.split("修改后的计划：", 1)[1].strip()
            return {
                    "full_plan": modified_plan,
                    "waiting_for_review": False,
                    # "user_feedback": "",  # 清除反馈
                    "messages": [
                        HumanMessage(
                            content=user_input, name=zh_name("user")
                        )
                    ],
                    "cur": "review_processor",
                    "next": "planner"
                }
        
        else:
            logger.warning(f"{session_id}-=-复审核员===无效的反馈: {user_input}")
            # 重新请求审查
            return {
                    "waiting_for_review": True,
                    # "user_feedback": "",  # 清除无效反馈
                    "messages": [
                        *state["messages"],
                        HumanMessage(
                            content="无效的输入，请使用 '同意', '拒绝' 或 '修改：你的修改' 格式",
                            name=zh_name("system")
                        )
                    ],
                    "next": "review_processor"  # 返回决策处理节点
                }
    elif wait_feedback_node == "form_filler":
        logger.warning(f"{session_id}-=-复审核员===用户反馈: {user_input}")
            # 重新请求审查
        return {
                "waiting_for_review": False,
                "messages": [
                    HumanMessage(
                        content=f"待填入的人员信息如下：\n{user_input}", name=zh_name("user")
                    )
                ],
                "cur": "review_processor",
                "next": "form_filler"
            }
    else:
        raise CustomInterrupt("复审核异常退出")
