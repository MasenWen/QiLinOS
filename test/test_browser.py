import inspect
from browser_use import Agent, AgentHistoryList, Browser, ChatOpenAI
import sys
from pathlib import Path
import asyncio
sys.path.insert(0, str(Path(__file__).parent.parent))
# from src.agent.llm import vl_llm

from src.config import CHROME_INSTANCE_PATH, VL_MODEL, VL_API_KEY, VL_BASE_URL

# print(inspect.signature(Browser.__init__))
# Connect to your existing Chrome browser

vl_llm = ChatOpenAI(
        model=VL_MODEL,  # 替换为你想要使用的具体千问模型
        api_key=VL_API_KEY, # 直接传递字符串即可，无需SecretStr包装[citation:9]
        base_url=VL_BASE_URL, # 核心：OpenAI兼容接口地址[citation:3]
        temperature=0  # 可选，控制随机性
    )

if CHROME_INSTANCE_PATH:
    expected_browser = Browser(
        executable_path=CHROME_INSTANCE_PATH
    )
    if expected_browser:
        print("Browser instance found with path")
    else:
        print("Using default browser instance with path")
else:
    expected_browser = Browser()
    if expected_browser:
        print("Browser instance found without path")
    else:
        print("Using default browser instance without path")

agent = Agent(
    task='查找最近最火热的十大事件',
    browser=expected_browser,
    llm=vl_llm,
)

async def main():
    result = await agent.run()
    print(result)
    

if __name__ == '__main__':
    # 运行异步主函数
    asyncio.run(main())