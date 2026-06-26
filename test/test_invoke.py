from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.agent.llm import get_llm_by_type

# 假设你已经创建了 llm 实例
# llm = create_openai_llm("gpt-4")  # 注意：模型名应该是 "gpt-4" 而不是 "gpt4"
nllm = get_llm_by_type("basic")

# 示例 1: 基本使用 - 单条消息
messages = [HumanMessage(content="你好，请介绍一下你自己。")]
response = nllm.invoke(messages)
print(response.content)

# 示例 2: 包含系统消息的对话
messages = [
    SystemMessage(content="你是一个专业的翻译助手，专门翻译中英文。"),
    HumanMessage(content="请将 'Hello, how are you?' 翻译成中文。")
]
response = nllm.invoke(messages)
print(f"AI回复: {response.content}")

# 示例 3: 多轮对话
messages = [
    SystemMessage(content="你是一个友好的聊天助手。"),
    HumanMessage(content="今天的天气真好！"),
    AIMessage(content="是的，阳光明媚，适合出去走走。"),
    HumanMessage(content="你有什么推荐的户外活动吗？")
]
response = nllm.invoke(messages)
print(f"AI推荐: {response.content}")