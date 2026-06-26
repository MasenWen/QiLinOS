import threading
import time
import ctypes

class ThreadInterrupt:
    def __init__(self):
        self.thread_stop_events = {}
        self.lock = threading.Lock()
    
    def register_thread(self, thread_id=None):
        """为线程注册停止事件"""
        if thread_id is None:
            thread_id = threading.get_ident()
        
        with self.lock:
            if thread_id not in self.thread_stop_events:
                self.thread_stop_events[thread_id] = threading.Event()
            return self.thread_stop_events[thread_id]
    
    def interrupt_thread(self, thread_id):
        """中断特定线程"""
        with self.lock:
            if thread_id in self.thread_stop_events:
                self.thread_stop_events[thread_id].set()
                return True
            return False
    
    def interrupt_all(self):
        """中断所有注册的线程"""
        with self.lock:
            for event in self.thread_stop_events.values():
                event.set()
    
    def check_interrupted(self, thread_id=None):
        """检查线程是否被中断"""
        if thread_id is None:
            thread_id = threading.get_ident()
        
        with self.lock:
            if thread_id in self.thread_stop_events:
                return self.thread_stop_events[thread_id].is_set()
            return False
    
    def reset(self, thread_id=None):
        """重置线程的中断状态"""
        if thread_id is None:
            thread_id = threading.get_ident()
        
        with self.lock:
            if thread_id in self.thread_stop_events:
                self.thread_stop_events[thread_id].clear()

def long_blocking_operation(thread_interrupt, worker_id):
    """在子线程中运行的长时间阻塞操作"""
    stop_event = thread_interrupt.register_thread()
    print(f"工作线程 {worker_id} 开始...")
    
    try:
        for i in range(100):
            if stop_event.is_set():
                print(f"工作线程 {worker_id} 被中断")
                return
            print(f"工作线程 {worker_id} 步骤 {i}")
            time.sleep(0.5)
        print(f"工作线程 {worker_id} 完成")
    except Exception as e:
        print(f"工作线程 {worker_id} 异常: {e}")

if __name__ == "__main__":
    thread_interrupt = ThreadInterrupt()
    worker_threads = []
    
    # 创建并启动多个工作线程
    for i in range(4):
        thread = threading.Thread(
            target=long_blocking_operation,
            args=(thread_interrupt, i),
            name=f"WorkerThread-{i}"
        )
        worker_threads.append(thread)
        thread.start()
    
    def external_interrupt():
        """外部中断触发器"""
        time.sleep(3)
        print("-"*50)
        print("发送中断信号给所有工作线程1")
        thread_interrupt.interrupt_thread(worker_threads[1].ident)
        time.sleep(3)
        print("-"*50)
        print("发送中断信号给所有工作线程")
        thread_interrupt.interrupt_all()
    
    # 启动外部中断
    interrupt_thread = threading.Thread(target=external_interrupt, name="InterruptThread")
    interrupt_thread.start()
    
    # 等待所有工作线程完成
    for thread in worker_threads:
        thread.join()
    
    interrupt_thread.join()
    print("所有线程已完成")