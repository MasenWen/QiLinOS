"""
日志记录模块

提供统一的日志记录功能，支持：
- 多级别日志记录
- 文件和控制台输出
- 日志轮转
- 结构化日志
- 性能监控
"""

import logging
import logging.handlers
import sys
import os
import json
import time
import functools
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from contextlib import contextmanager

from ..config.settings import get_config
from src.utils.db_manager import node_state
from src.utils.db_manager import log_handler

class LoggerConfig:
    """日志配置类"""
    
    def __init__(self, level: str = "INFO", 
                 file_path: str = None,
                 console_output: bool = True,
                 json_format: bool = False,
                 max_file_size: int = 10*1024*1024,
                 backup_count: int = 5):
        self.level = level
        self.file_path = file_path
        self.console_output = console_output
        self.json_format = json_format
        self.max_file_size = max_file_size
        self.backup_count = backup_count


class JSONFormatter(logging.Formatter):
    """JSON格式的日志格式化器"""
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为JSON格式"""
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # 添加额外字段
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
        
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        
        if hasattr(record, 'execution_time'):
            log_entry['execution_time'] = record.execution_time
        
        # 添加异常信息
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    """带颜色的控制台日志格式化器"""
    
    # 颜色代码
    COLORS = {
        'DEBUG': '\033[36m',     # 青色
        'INFO': '\033[32m',      # 绿色
        'WARNING': '\033[33m',   # 黄色
        'ERROR': '\033[31m',     # 红色
        'CRITICAL': '\033[35m',  # 紫色
        'RESET': '\033[0m'       # 重置
    }
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录并添加颜色"""
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        
        # 格式化消息
        formatted = super().format(record)
        
        # 添加颜色
        return f"{color}{formatted}{reset}"


class LoggerManager:
    """日志管理器"""
    
    def __init__(self):
        self.config = get_config()
        self.loggers: Dict[str, logging.Logger] = {}
        self._setup_root_logger()
    
    def _setup_root_logger(self):
        """设置根日志记录器"""
        root_logger = logging.getLogger()
        
        # 🔧 修复：添加日志级别验证和错误处理
        try:
            level_name = self.config.logging.level.upper()
            
            # 验证logging模块是否正常
            if not hasattr(logging, 'INFO'):
                print(f"❌ 错误：logging模块状态异常，logging类型: {type(logging)}")
                print(f"❌ logging模块属性: {dir(logging)}")
                # 尝试重新导入logging
                import importlib
                importlib.reload(logging)
            
            # 验证级别名称是否有效
            valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
            if level_name not in valid_levels:
                print(f"⚠️ 警告：无效的日志级别 '{level_name}'，使用默认级别 INFO")
                level_name = 'INFO'
            
            # 获取级别值
            if hasattr(logging, level_name):
                level_value = getattr(logging, level_name)
            else:
                print(f"⚠️ 警告：logging模块缺少 {level_name} 属性，使用数值 20 (INFO)")
                level_value = 20  # INFO级别的数值
                
            root_logger.setLevel(level_value)
            
        except Exception as e:
            print(f"❌ 日志级别设置失败: {e}")
            # 使用数值形式的INFO级别作为回退
            root_logger.setLevel(20)  # INFO = 20
        
        # 清除现有处理器
        root_logger.handlers.clear()
        
        # 设置文件处理器
        self._setup_file_handler(root_logger)
        
        # 设置控制台处理器
        if self.config.logging.console_output:
            self._setup_console_handler(root_logger)
    
    def _setup_file_handler(self, logger: logging.Logger):
        """设置文件处理器"""
        try:
            # 确保日志目录存在
            log_dir = os.path.dirname(self.config.logging.file_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            
            # 创建轮转文件处理器
            file_handler = logging.handlers.RotatingFileHandler(
                filename=self.config.logging.file_path,
                maxBytes=self._parse_size(self.config.logging.max_file_size),
                backupCount=self.config.logging.backup_count,
                encoding='utf-8'
            )
            
            # 设置JSON格式化器
            json_formatter = JSONFormatter()
            file_handler.setFormatter(json_formatter)
            
            logger.addHandler(file_handler)
            
        except Exception as e:
            print(f"警告：无法设置文件日志处理器: {e}")
    
    def _setup_console_handler(self, logger: logging.Logger):
        """设置控制台处理器"""
        console_handler = logging.StreamHandler(sys.stdout)
        
        # 设置彩色格式化器
        colored_formatter = ColoredFormatter(
            fmt=self.config.logging.format,
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(colored_formatter)
        
        logger.addHandler(console_handler)
    
    def _parse_size(self, size_str: str) -> int:
        """解析文件大小字符串"""
        size_str = size_str.upper()
        
        if size_str.endswith('KB'):
            return int(size_str[:-2]) * 1024
        elif size_str.endswith('MB'):
            return int(size_str[:-2]) * 1024 * 1024
        elif size_str.endswith('GB'):
            return int(size_str[:-2]) * 1024 * 1024 * 1024
        else:
            return int(size_str)
    
    def get_logger(self, name: str) -> logging.Logger:
        """获取指定名称的日志记录器"""
        if name not in self.loggers:
            logger = logging.getLogger(name)
            logger.setLevel(logging.INFO)
            logger.addHandler(log_handler)
            self.loggers[name] = logger
        
        return self.loggers[name]
    
    def set_level(self, level: str):
        """设置日志级别"""
        level_obj = getattr(logging, level.upper())
        
        # 更新根日志记录器级别
        logging.getLogger().setLevel(level_obj)
        
        # 更新配置
        self.config.logging.level = level.upper()


class PerformanceLogger:
    """性能监控日志记录器"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    @contextmanager
    def timer(self, operation: str, **kwargs):
        """计时上下文管理器"""
        start_time = time.time()
        
        try:
            self.logger.info(f"{node_state}-=-填表员===开始执行: {operation}", extra=kwargs)
            yield
            
        finally:
            execution_time = time.time() - start_time
            self.logger.info(
                f"执行完成: {operation}",
                extra={
                    'execution_time': execution_time,
                    'operation': operation,
                    **kwargs
                }
            )
    
    def log_function_call(self, func: Callable, args: tuple, kwargs: dict, result: Any = None, error: Exception = None):
        """记录函数调用"""
        log_data = {
            'function': func.__name__,
            'func_module': func.__module__,  # 改名避免与内置字段冲突
            'args_count': len(args),
            'kwargs_keys': list(kwargs.keys())
        }
        
        if error:
            self.logger.error(f"{node_state}-=-填表员===函数调用失败: {func.__name__}", extra=log_data, exc_info=error)
        else:
            self.logger.debug(f"{node_state}-=-填表员===函数调用成功: {func.__name__}", extra=log_data)


def performance_monitor(logger_name: str = None):
    """性能监控装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 确定logger名称
            actual_logger_name = logger_name
            if actual_logger_name is None:
                actual_logger_name = func.__module__
            
            # 确保logger名称是字符串
            if not isinstance(actual_logger_name, str):
                actual_logger_name = str(actual_logger_name)
            
            logger = get_logger(actual_logger_name)
            perf_logger = PerformanceLogger(logger)
            
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                perf_logger.log_function_call(func, args, kwargs, result)
                
                # 记录执行时间
                logger.debug(
                    f"函数 {func.__name__} 执行时间: {execution_time:.3f}s",
                    extra={'execution_time': execution_time, 'function': func.__name__}
                )
                
                return result
                
            except Exception as e:
                execution_time = time.time() - start_time
                perf_logger.log_function_call(func, args, kwargs, error=e)
                
                logger.error(
                    f"函数 {func.__name__} 执行失败: {e}",
                    extra={'execution_time': execution_time, 'function': func.__name__},
                    exc_info=True
                )
                
                raise
        
        return wrapper
    
    # 处理不同的调用方式
    if callable(logger_name):
        # 如果直接传递了函数，说明是 @performance_monitor 的用法
        func = logger_name
        return decorator(func)
    else:
        # 否则返回装饰器函数
        return decorator


def error_handler(logger_name: str = None, reraise: bool = True):
    """错误处理装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name or func.__module__)
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"函数 {func.__name__} 发生错误: {e}",
                    extra={
                        'function': func.__name__,
                        'args_count': len(args),
                        'kwargs_keys': list(kwargs.keys())
                    },
                    exc_info=True
                )
                
                if reraise:
                    raise
                else:
                    return None
        
        return wrapper
    return decorator


# 全局日志管理器实例
_logger_manager = LoggerManager()


def setup_logging(level: str = "INFO", 
                 log_file: str = None,
                 console_output: bool = True,
                 json_format: bool = False):
    """
    设置日志配置
    
    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径，None表示不写入文件
        console_output: 是否输出到控制台
        json_format: 是否使用JSON格式
    """
    # 设置全局日志级别
    _logger_manager.set_level(level)
    
    # 获取根日志记录器
    root_logger = logging.getLogger()
    
    # 清除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 设置日志级别
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)
    
    # 添加控制台处理器
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        
        if json_format:
            console_handler.setFormatter(JSONFormatter())
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(formatter)
        
        root_logger.addHandler(console_handler)
    
    # 添加文件处理器
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(numeric_level)
        
        if json_format:
            file_handler.setFormatter(JSONFormatter())
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
            )
            file_handler.setFormatter(formatter)
        
        root_logger.addHandler(file_handler)


def get_logger(name: str = None) -> logging.Logger:
    """获取日志记录器"""
    if name is None:
        name = __name__
    
    # 确保name是字符串
    if not isinstance(name, str):
        name = str(name)
    
    return _logger_manager.get_logger(name)


def get_performance_logger(name: str = None) -> PerformanceLogger:
    """获取性能监控日志记录器"""
    logger = get_logger(name)
    return PerformanceLogger(logger)


def set_log_level(level: str):
    """设置全局日志级别"""
    _logger_manager.set_level(level)


def log_config_info():
    """记录配置信息"""
    logger = get_logger(__name__)
    config = get_config()
    
    logger.info("应用程序启动", extra={
        'app_name': config.system.app_name,
        'version': config.system.version,
        'log_level': config.logging.level
    })


# 导出函数和类
__all__ = [
    "get_logger",
    "setup_logging",
    "get_performance_logger", 
    "set_log_level",
    "log_config_info",
    "performance_monitor",
    "error_handler",
    "LoggerConfig",
    "PerformanceLogger",
    "LoggerManager"
] 