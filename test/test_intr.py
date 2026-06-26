from logging import exception
from src.utils.interupt import InterruptibleAgent, CustomInterrupt

from src.agent.types import State
import threading
import time
# def test_interruptible():
#     intr = InterruptibleAgent()
    
#     print("Before with block")
    
#     with intr as ia:
#         print("Starting research agent invocation", flush=True)
#         # 添加一个简单的测试，而不是直接调用 research_agent.invoke(state)
#         print("Simulating agent work...")
#         import time
#         time.sleep(100)  # 模拟工作
#         print("Agent work completed")
        
#         if ia.check_interrupted():
#             print("Interrupt detected")
#             if db_manager.get_session_stop(1):
#                 raise CustomInterrupt("Function interrupted during research_agent.invoke")
    
#     print("After with block")

# # 先运行测试
# test_interruptible()

# db_manager.set_session_stop(1, True)  # 设置中断标志


agent = InterruptibleAgent()

def external_interrupt_trigger():
    """外部中断触发器"""
    time.sleep(2)  # 等待2秒后触发中断
    print("外部线程：正在触发中断...")
    agent.manual_interrupt()


if __name__ == "__main__":
    print("主线程：启动中断测试")
    # 启动外部中断线程
    interrupt_thread = threading.Thread(target=external_interrupt_trigger)
    interrupt_thread.start()

    # 主线程中的 with 块
    try:
        with agent:
            print(f"进入上下文后状态: {agent.interrupted}")
            
            for i in range(100):
                print(f"正在工作... {i}")
                time.sleep(0.5)  # 模拟工作耗时
            if agent.check_interrupted():
                print("检测到中断，提前退出") 
                raise CustomInterrupt("Detected interrupt during work loop")
    except CustomInterrupt as e:
        print(f"主线程捕获到中断异常: {e}")
                
                
        print("循环结束")

    interrupt_thread.join()