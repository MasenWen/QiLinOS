"""
Entry point script for the LangGraph Demo.
"""
from agent import NexAgent
from src.utils.eventbus import EventBus
import sys
import random
import time

if __name__ == "__main__":
    
    nex_agent = NexAgent(event_bus=EventBus())
    if len(sys.argv) > 1:
        user_query = " ".join(sys.argv[1:])
    else:
        user_query = input("Enter your query: ")
    random.seed(int(time.time()))
    session_id = 100000 + random.randint(1, 100000)
    nex_agent.run_workflow_with_review(
        user_input=user_query,
        session_id=session_id,
        correlation_id=session_id,
        debug=True
    )