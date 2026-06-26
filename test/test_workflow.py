# test_workflow.py
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, START, END
import time
from src.agent.graph import create_state_graph

from src.agent.types import State
from src.config import TEAM_MEMBERS
from langchain_core.messages import HumanMessage
from typing import Dict, Any, Literal
from src.utils.db_manager import db_manager
# class State(TypedDict):
#     messages: Annotated[list, operator.add]

# def test_node(state: State):
#     return {"messages": [{"role": "assistant", "content": "Hello from test node"}]}

def test_workflow():
    """最简单的测试工作流"""
    
    start_node = "planner"
    builder = create_state_graph(start_node)
    # 测试无检查点
    graph1 = builder.compile()
    print("✓ 无检查点编译成功")
    session_id = 1
    # 测试内存检查点
    # 
    # graph2 = builder.compile(checkpointer=MemorySaver())
    start_time = time.time()
    with SqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
        graph2 = builder.compile(checkpointer=checkpointer)
        print("✓ 内存检查点编译成功")

        thread_id = f"session_{session_id}"
        config_for_checkpoint = {
            "configurable": {
                "thread_id": thread_id
            }
        }
        existing_checkpoint = checkpointer.get_tuple(config_for_checkpoint)

        if existing_checkpoint:
            print(f"从检查点恢复会话 {session_id}")
            # 恢复执行：使用最小状态或空状态
            workflow_state = {
                # "session_id": session_id,  # 只需要会话ID用于日志等
                # 其他字段会自动从检查点恢复
                "messages": [HumanMessage(content="根本就没有生产该文件，你个老6")],
            }
        else:
            print(f"创建新会话 {session_id}")
            workflow_state = {
                "session_id": session_id,
                "TEAM_MEMBERS": TEAM_MEMBERS,
                "messages": [HumanMessage(content="我在备考雅思写作，需要一篇教育类高分英文范文，主题“是否该强制学生穿校服”，要求结构清晰（观点+案例+结论），用下划线标出高级词汇，避开模板化句子,最后添加批注说明段落衔接技巧,并且把输出文档以txt格式保存至本地")],
                # "history": [HumanMessage(content="")],
                "deep_thinking_mode": True,
                "search_before_planning": False,
                "waiting_for_review": False,
                # "user_feedback": "",
                "next": "",
                "full_plan": ""
            }

        config = {
                "configurable": {
                    "thread_id": thread_id
                },
                "recursion_limit": 100
            }
        
        checkpoints = list(checkpointer.list(config))
        print(checkpointer)
        index = 0
        print("=== 工作流开始 ===")
        for event in graph2.stream(workflow_state, config=config):
            key, value = next(iter(event.items()))
            index += 1
            next_role = value.get("next")
            print(f"step {index}: cur:{key} next: {next_role}")
            if value.get("waiting_for_review", False):
                print("\n=== PLAN REVIEW REQUIRED ===")
                db_manager.set_user_feedback(session_id, "ACCEPT")
                print("✓ 已确认接受计划")
                continue
            
            # 检查工作流是否结束
            if next_role == END: 
                end_time = time.time()
                elapsed_time = end_time - start_time
                elapsed_minutes = int(elapsed_time // 60)
                elapsed_seconds = int(elapsed_time % 60)
                completion_message = f"任务已完成，用时{elapsed_minutes}分{elapsed_seconds}秒，有任何问题请向我反馈。"
                print(f"\n=== WORKFLOW COMPLETED ===\n{completion_message}")
                break
    
    print("✓ 测试执行成功")

if __name__ == "__main__":
    test_workflow()