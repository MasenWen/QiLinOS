import asyncio

from pydantic import BaseModel, Field
from typing import Optional, ClassVar, Type
from langchain.tools import BaseTool
from browser_use import AgentHistoryList, Browser, ChatOpenAI
from browser_use import Agent as BrowserAgent
# from src.agent.llm import vl_llm
from src.tools.decorators import create_logged_tool
from src.config import CHROME_INSTANCE_PATH, VL_MODEL, VL_API_KEY, VL_BASE_URL

expected_browser = None



vl_llm = ChatOpenAI(
    model=VL_MODEL,  # 替换为你想要使用的具体千问模型
    api_key=VL_API_KEY, # 直接传递字符串即可，无需SecretStr包装[citation:9]
    base_url=VL_BASE_URL, # 核心：OpenAI兼容接口地址[citation:3]
    temperature=0  # 可选，控制随机性
)

# Use Chrome instance if specified
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


class BrowserUseInput(BaseModel):
    """Input for WriteFileTool."""

    instruction: str = Field(..., description="The instruction to use browser")


class BrowserTool(BaseTool):
    name: ClassVar[str] = "browser"
    args_schema: Type[BaseModel] = BrowserUseInput
    description: ClassVar[str] = (
        "Use this tool to interact with web browsers. Input should be a natural language description of what you want to do with the browser, such as 'Go to google.com and search for browser-use', or 'Navigate to Reddit and find the top post about AI'."
    )

    _agent: Optional[BrowserAgent] = None

    def _run(self, instruction: str) -> str:
        """Run the browser task synchronously."""
        print("Run the browser task synchronously...")
        print(instruction)
        if expected_browser:
            print("Browser instance found")
        else:
            print("Using default browser instance")
        self._agent = BrowserAgent(
            task=instruction,  # Will be set per request
            llm=vl_llm,
            browser=expected_browser,
            step_timeout = 60
        )
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self._agent.run())
                return (
                    str(result)
                    if not isinstance(result, AgentHistoryList)
                    else result.final_result
                )
            finally:
                loop.close()
        except Exception as e:
            return f"Error executing browser task: {str(e)}"

    async def _arun(self, instruction: str) -> str:
        """Run the browser task asynchronously."""
        self._agent = BrowserAgent(
            task=instruction, llm=vl_llm  # Will be set per request
        )
        try:
            result = await self._agent.run()
            return (
                str(result)
                if not isinstance(result, AgentHistoryList)
                else result.final_result
            )
        except Exception as e:
            return f"Error executing browser task: {str(e)}"


BrowserTool = create_logged_tool(BrowserTool)
browser_tool = BrowserTool()
