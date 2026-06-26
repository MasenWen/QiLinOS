import multiprocessing
import time
import threading

def long_blocking_operation(worker_id):
    """在独立进程中运行的长时间操作"""
    print(f"工作进程 {worker_id} 开始执行长时间操作...")
    
    # 模拟长时间运行的单一操作
    start_time = time.time()
    i = 0
    while time.time() - start_time < worker_id+3: 
        i += 1
        print(f"工作线程 {worker_id} 步骤 {i}")
        time.sleep(0.5)

    end_time = time.time()
    print(f"工作进程 {worker_id} 完成长时间操作，耗时 {end_time - start_time} 秒")
    return f"工作进程 {worker_id} 的结果"

class ProcessManager:
    def __init__(self):
        self.processes = {}
        self.results = {}
    
    def start_process(self, worker_id, func, *args):
        """启动一个进程"""
        pipe_parent, pipe_child = multiprocessing.Pipe()
        
        def wrapped_func(conn, worker_id, *args):
            try:
                result = func(worker_id, *args)
                conn.send(('success', result))
            except Exception as e:
                conn.send(('error', str(e)))
        
        process = multiprocessing.Process(
            target=wrapped_func,
            args=(pipe_child, worker_id) + args
        )
        
        self.processes[worker_id] = (process, pipe_parent)
        process.start()
        return process
    
    def stop_process(self, worker_id, timeout=1):
        """停止一个进程"""
        if worker_id in self.processes:
            process, pipe = self.processes[worker_id]
            
            # 先尝试正常终止
            process.terminate()
            process.join(timeout=timeout)
            
            # 如果还在运行，强制杀死
            if process.is_alive():
                process.kill()
                process.join()
            
            del self.processes[worker_id]
            return True
        return False
    
    def stop_all(self, timeout=1):
        """停止所有进程"""
        for worker_id in list(self.processes.keys()):
            self.stop_process(worker_id, timeout)
    
    def get_result(self, worker_id, timeout=None):
        """获取进程结果"""
        if worker_id in self.processes:
            process, pipe = self.processes[worker_id]
            
            if pipe.poll(timeout):
                status, result = pipe.recv()
                return status, result
            else:
                return 'timeout', None
        return 'not_found', None

if __name__ == "__main__":
    manager = ProcessManager()
    
    # 启动多个进程
    for i in range(6):
        manager.start_process(i, long_blocking_operation)
        print(f"启动工作进程 {i}")
    
    def external_interrupt():
        """外部中断触发器"""
        time.sleep(2)
        print("-" * 50)
        print("发送中断信号给进程 1")
        manager.stop_process(1)
        
        time.sleep(4)
        print("-" * 50)
        print("发送中断信号给所有进程")
        manager.stop_all()
    
    # 启动外部中断
    interrupt_thread = threading.Thread(target=external_interrupt)
    interrupt_thread.start()
    
    # 等待所有进程完成或被中断
    interrupt_thread.join()
    
    # 检查结果
    for i in range(6):
        status, result = manager.get_result(i)
        print(f"进程 {i}: {status}, 结果: {result}")
    
    print("所有进程处理完成")