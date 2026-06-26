import logging
from langchain_community.tools.tavily_search import TavilySearchResults
from src.config import TAVILY_MAX_RESULTS
from .decorators import create_logged_tool
from src.utils.db_manager import log_handler, node_state

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)




# Initialize Tavily search tool with logging
LoggedTavilySearch = create_logged_tool(TavilySearchResults)
tavily_tool = LoggedTavilySearch(name="tavily_search", max_results=TAVILY_MAX_RESULTS)

if __name__ == "__main__":
    from src.agent.types import State

    # Example usage of the tavily_tool
    # state = State(messages=[{"content": "What is the latest in AI research?"}])
    searched_content = tavily_tool.invoke({"query": "What is the latest in AI research?"})
    print(searched_content)
    print("-" * 80)
    for elem in searched_content:
        print(elem['title'], "----", elem['content'])
        print("-" * 80)