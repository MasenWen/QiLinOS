from langgraph.graph import StateGraph, START, END


from .nodes import (
    coordinator_node,
    km_node,
    operator_node,
    ocr_node,
    gen_image_node,
    filler_node,
    social_node,
    planner_node,
    reviewer_node,
    review_processor_node,
    supervisor_node,
    research_node,
    ppt_node,
    ui_node,
    code_node,
    mcp_node,
    browser_node,
    reporter_node,
)
from .types import State


from src.config import TEAM_MEMBERS

def create_state_graph(start_node="coordinator"):
    builder = StateGraph(State)

    # Add all nodes
    builder.add_node("coordinator", coordinator_node)
    builder.add_node("conversationalist", social_node)
    builder.add_node("operator", operator_node)
    builder.add_node("knowledge_manager", km_node)
    builder.add_node("ocr_tool", ocr_node)
    builder.add_node("pic_maker", gen_image_node)
    builder.add_node("form_filler", filler_node)
    builder.add_node("planner", planner_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("review_processor", review_processor_node)
    
    builder.add_node("supervisor", supervisor_node)

    builder.add_node("researcher", research_node)
    builder.add_node("ppt_generator", ppt_node)
    builder.add_node("ui_automator", ui_node)
    builder.add_node("coder", code_node)
    builder.add_node("mcp_server", mcp_node)
    builder.add_node("browser", browser_node)
    builder.add_node("reporter", reporter_node)

    # 设置入口点
    builder.set_entry_point(start_node)

    # Add fixed edges

    
    builder.add_edge("planner", "reviewer")
    builder.add_edge("reviewer", "review_processor")
    builder.add_edge("knowledge_manager",  "__end__")
    builder.add_edge("ocr_tool",  "__end__")


    # Add conditional edges for review processor



    builder.add_conditional_edges(
        "coordinator",
        lambda state: state.get("next", "planner"),
        {
            "planner": "planner",
            "conversationalist": "conversationalist",
            "operator": "operator",
            "knowledge_manager": "knowledge_manager",
            "ocr_tool": "ocr_tool",
            "pic_maker": "pic_maker",
            "form_filler": "form_filler",
        }
    )
    

    builder.add_conditional_edges(
        "conversationalist",
        lambda state: state.get("next", "conversationalist"),
        {
            "planner": "planner",
            "__end__": "__end__",
        }
    )

    builder.add_conditional_edges(
        "form_filler",
        lambda state: state.get("next", "form_filler"),
        {
            "reviewer": "reviewer",
            "__end__": "__end__",
        }
    )

    builder.add_conditional_edges(
        "review_processor",
        lambda state: state.get("next", "review_processor"),
        {
            "supervisor": "supervisor",
            "planner": "planner",
            "form_filler": "form_filler",
            "review_processor": "review_processor",  # 添加这行
            "__end__": "__end__"
        }
    )

    builder.add_conditional_edges(
        "operator",
        lambda state: state.get("next", "__end__"),
        {
            "supervisor": "supervisor",
            "__end__": "__end__",
        }
    )

    builder.add_conditional_edges(
        "pic_maker",
        lambda state: state.get("next", "__end__"),
        {
            "supervisor": "supervisor",
            "__end__": "__end__",
        }
    )
    
    # Add conditional edges for supervisor
    builder.add_conditional_edges(
        "supervisor",
        lambda state: state.get("next", "__end__"),
        {
            "researcher": "researcher",
            "coder": "coder",
            "operator": "operator",
            "ppt_generator": "ppt_generator",
            "ui_automator": "ui_automator",
            "pic_maker": "pic_maker",
            "mcp_server": "mcp_server",
            "browser": "browser", 
            "reporter": "reporter",
            "__end__": "__end__",
        }
    )

    # Add edges from agent nodes back to supervisor
    for agent in TEAM_MEMBERS:
        builder.add_edge(agent, "supervisor")

    return builder





# Compile the workflow


