"""
配置模块

提供统一的配置管理接口
"""

from .settings import (
    DatabaseConfig,
    LoggingConfig,
    LLMConfig,
    DocumentConfig,
    MonitorsConfig,
    SystemConfig,
    ConfigManager,
    config,
    get_config,
    reload_config
)

# 为了兼容性，提供别名函数
def get_settings():
    """获取配置设置（兼容函数）"""
    return get_config()


def update_settings(config_file=None):
    """更新配置设置（兼容函数）"""
    return reload_config(config_file)


# 导出所有接口
__all__ = [
    # 配置类
    "DatabaseConfig",
    "LoggingConfig", 
    "LLMConfig",
    "DocumentConfig",
    "MonitorsConfig",
    "SystemConfig",
    "ConfigManager",
    
    # 配置实例和函数
    "config",
    "get_config",
    "reload_config",
    
    # 兼容接口
    "get_settings",
    "update_settings",
] 