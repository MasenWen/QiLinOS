import signal
import threading

class CustomInterrupt(Exception):
    """自定义中断异常"""
    pass

class InterruptibleAgent:
    def __init__(self):
        self.interrupted = False
        self.original_handler = None
        self.lock = threading.Lock()
    
    def signal_handler(self, signum, frame):
        with self.lock:
            self.interrupted = True
        print("Received interrupt signal, aborting...")
    
    def manual_interrupt(self):
        """手动触发中断"""
        with self.lock:
            self.interrupted = True
        print("Manual interrupt triggered")
        raise CustomInterrupt("Manual interrupt triggered")
        # 也可以模拟发送信号
        # os.kill(os.getpid(), signal.SIGINT)
    
    def check_interrupted(self):
        """检查是否被中断"""
        print("Checking interrupt status")
        with self.lock:
            return self.interrupted
    
    def reset(self):
        """重置中断状态"""
        print("Resetting interrupt status")
        with self.lock:
            self.interrupted = False
    
    def __enter__(self):
        print("Entering interruptible context")
        self.reset()
        self.original_handler = signal.signal(signal.SIGINT, self.signal_handler)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        print("Exiting interruptible context")
        if self.original_handler:
            signal.signal(signal.SIGINT, self.original_handler)

intr = InterruptibleAgent()