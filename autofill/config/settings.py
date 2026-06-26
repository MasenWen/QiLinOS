"""
配置管理模块

统一管理应用程序的所有配置信息，包括：
- 数据库连接配置（PostgreSQL + AGE扩展）
- 日志配置
- 大语言模型配置
- 文件处理配置
- 系统设置
"""

import os
import json
from typing import Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class DatabaseConfig:
    """PostgreSQL数据库配置（使用AGE扩展）"""
    host: str = "localhost"
    port: int = 5455
    username: str = "why"
    password: str = "123456789"
    database: str = "lightrag"
    connection_timeout: int = 30
    max_connection_pool_size: int = 100
    # AGE扩展相关配置
    graph_name: str = "form_filler_graph"
    workspace: str = "default"


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: str = "logs/app.log"
    max_file_size: str = "10MB"
    backup_count: int = 5
    console_output: bool = True


@dataclass
class LLMConfig:
    """大语言模型配置"""
    model_name: str = ""
    api_key: str = ""
    api_base: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 60
    # 控制是否在信息收集阶段使用LLM（默认禁用）
    enable_llm_analysis: bool = False
    retry_count: int = 3


@dataclass
class DocumentConfig:
    """文档处理配置"""
    supported_formats: list = None
    max_file_size: str = "100MB"
    temp_dir: str = "temp"
    ocr_enabled: bool = True
    ocr_language: str = "chi_sim"
    extract_images: bool = True


@dataclass
class MonitorsConfig:
    """监控器配置"""
    analysis_interval: int = 5  # 分析间隔（秒）
    monitor_paths: list = None  # 监控路径列表
    enable_file_watcher: bool = True  # 启用文件监控
    max_file_size: str = "10MB"  # 最大文件处理大小
    supported_extensions: list = None  # 支持的文件扩展名


@dataclass
class SystemConfig:
    """系统配置"""
    app_name: str = "表单自动填写软件"
    version: str = "1.0.0"
    data_dir: str = "data"
    cache_dir: str = "cache"
    max_concurrent_tasks: int = 5
    auto_backup: bool = True
    backup_interval_hours: int = 24


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_file: 配置文件路径，如果为None则使用默认配置
        """
        self.config_file = config_file or "config/settings.json"
        self._config_data = {}
        
        # 初始化默认配置
        self.database = DatabaseConfig()
        self.logging = LoggingConfig()
        self.llm = LLMConfig()
        self.document = DocumentConfig()
        self.monitors = MonitorsConfig()
        self.system = SystemConfig()
        
        # 设置文档支持格式默认值
        if self.document.supported_formats is None:
            self.document.supported_formats = ["pdf", "doc", "docx", "xls", "xlsx"]
        
        # 设置监控器默认值
        if self.monitors.monitor_paths is None:
            self.monitors.monitor_paths = []
        if self.monitors.supported_extensions is None:
            self.monitors.supported_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt']
        
        # 加载配置文件
        self._load_config()
        
        # 加载环境变量
        self._load_environment_variables()
    
    def _load_config(self):
        """从配置文件加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config_data = json.load(f)
                    
                # 更新配置对象
                if 'database' in self._config_data:
                    self.database = DatabaseConfig(**self._config_data['database'])
                    
                if 'logging' in self._config_data:
                    self.logging = LoggingConfig(**self._config_data['logging'])
                    
                if 'llm' in self._config_data:
                    self.llm = LLMConfig(**self._config_data['llm'])
                    
                if 'document' in self._config_data:
                    self.document = DocumentConfig(**self._config_data['document'])
                    
                if 'monitors' in self._config_data:
                    self.monitors = MonitorsConfig(**self._config_data['monitors'])
                    
                if 'system' in self._config_data:
                    self.system = SystemConfig(**self._config_data['system'])
                    
        except Exception as e:
            print(f"警告：无法加载配置文件 {self.config_file}: {e}")
            print("使用默认配置")
    
    def _load_environment_variables(self):
        """从环境变量加载配置"""
        # 数据库配置
        self.database.host = os.getenv("DB_HOST", self.database.host)
        self.database.port = int(os.getenv("DB_PORT", self.database.port))
        self.database.username = os.getenv("DB_USERNAME", self.database.username)
        self.database.password = os.getenv("DB_PASSWORD", self.database.password)
        self.database.database = os.getenv("DB_DATABASE", self.database.database)
        
        # 大语言模型配置
        self.llm.model_name = os.getenv("LLM_MODEL_NAME", self.llm.model_name)
        self.llm.api_key = os.getenv("LLM_API_KEY", self.llm.api_key)
        self.llm.api_base = os.getenv("LLM_API_BASE", self.llm.api_base)
        
        # 日志配置
        self.logging.level = os.getenv("LOG_LEVEL", self.logging.level)
        self.logging.file_path = os.getenv("LOG_FILE", self.logging.file_path)
    
    def save_config(self):
        """保存当前配置到文件"""
        try:
            # 确保配置目录存在
            config_dir = os.path.dirname(self.config_file)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)
            
            # 构建配置数据
            config_data = {
                'database': asdict(self.database),
                'logging': asdict(self.logging),
                'llm': asdict(self.llm),
                'document': asdict(self.document),
                'monitors': asdict(self.monitors),
                'system': asdict(self.system)
            }
            
            # 写入配置文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
                
            print(f"配置已保存到 {self.config_file}")
            
        except Exception as e:
            print(f"错误：无法保存配置文件: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        keys = key.split('.')
        value = self._config_data
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any):
        """设置配置值"""
        keys = key.split('.')
        config = self._config_data
        
        # 创建嵌套字典结构
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def validate_config(self) -> Dict[str, str]:
        """验证配置有效性"""
        errors = {}
        
        # 验证数据库配置
        if not self.database.host:
            errors['database.host'] = "数据库主机地址不能为空"
        
        if not (1 <= self.database.port <= 65535):
            errors['database.port'] = "数据库端口必须在1-65535之间"
        
        # 验证大语言模型配置
        if not self.llm.model_name:
            errors['llm.model_name'] = "大语言模型名称不能为空"
        
        # 验证文件路径
        try:
            log_dir = os.path.dirname(self.logging.file_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            errors['logging.file_path'] = f"无法创建日志目录: {e}"
        
        return errors
    
    def create_directories(self):
        """创建必要的目录"""
        directories = [
            self.system.data_dir,
            self.system.cache_dir,
            self.document.temp_dir,
            os.path.dirname(self.logging.file_path),
            os.path.dirname(self.config_file)
        ]
        
        for directory in directories:
            if directory:
                try:
                    os.makedirs(directory, exist_ok=True)
                except Exception as e:
                    print(f"警告：无法创建目录 {directory}: {e}")


# 全局配置实例
config = ConfigManager()


def get_config() -> ConfigManager:
    """获取全局配置实例"""
    return config


def reload_config(config_file: Optional[str] = None) -> ConfigManager:
    """重新加载配置"""
    global config
    config = ConfigManager(config_file)
    return config


# 导出配置类和函数
__all__ = [
    "DatabaseConfig",
    "LoggingConfig", 
    "LLMConfig",
    "DocumentConfig",
    "MonitorsConfig",
    "SystemConfig",
    "ConfigManager",
    "config",
    "get_config",
    "reload_config"
] 