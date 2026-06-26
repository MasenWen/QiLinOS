import os
import re
from datetime import datetime

from langchain_core.prompts import PromptTemplate
from langgraph.prebuilt.chat_agent_executor import AgentState
from src.utils.db_manager import db_manager
from src.config import ZH_TEAM_MEMBERS

def get_prompt_template(prompt_name: str) -> str:
    template = open(os.path.join(os.path.dirname(__file__), f"{prompt_name}.md")).read()
    # Escape curly braces using backslash
    template = template.replace("{", "{{").replace("}", "}}")
    # Replace `<<VAR>>` with `{VAR}`
    template = re.sub(r"<<([^>>]+)>>", r"{\1}", template)
    return template


def apply_prompt_template(prompt_name: str, state: AgentState) -> list:
    system_prompt = PromptTemplate(
        input_variables=["当前时间"],
        template=get_prompt_template(prompt_name+'_zh'),
    ).format(当前时间=datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"), **state)
    if prompt_name == "planner" or prompt_name == "conversationalist":
        userInfo = db_manager.get_info_simple()
        if userInfo:
            system_prompt += f"\n\n#用户基本信息（仅供参考，不相关则略过）：\n\n{userInfo}"
    if prompt_name == "planner":
        userBehavier = db_manager.get_behavior_simple()
        if userBehavier:
            system_prompt += f"\n\n#历史任务及规划情况（仅供参考，不相关则略过）：\n\n{userBehavier}"

    
    return [{"role": "system", "content": system_prompt}] + state["messages"]
