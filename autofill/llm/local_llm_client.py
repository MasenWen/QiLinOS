"""
本地LLM客户端
使用本地模型服务替代外部API
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any, Optional
from ..utils.logger import get_logger

class LocalLLMClient:
    """本地LLM客户端"""
    
    def __init__(self, base_url: str = None, model: str = None):
        import os
        self.base_url = base_url or os.getenv("LLM_BINDING_HOST", "http://localhost:8000/v1")
        self.model = model or os.getenv("LLM_MODEL", "Qwen2.5-VL-Instruct")#"/root/autodl-tmp/model"
        self.api_key = os.getenv("LLM_BINDING_API_KEY", "")
        self.logger = get_logger(__name__)
        self.session = None
        
        # self.logger.info(f"初始化本地LLM客户端: 服务地址={self.base_url}, 模型路径={self.model}")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.session:
            await self.session.close()
    
    def _get_session(self):
        """获取或创建会话"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def send_request(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """
        发送请求到本地LLM服务
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示（可选）
            max_tokens: 最大令牌数
            temperature: 温度参数
            **kwargs: 其他参数
            
        Returns:
            LLM响应结果
        """
        try:
            # 构建消息
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # 构建请求payload
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False
            }
            headers = {
                "Content-Type": "application/json",
            }
            if self.api_key:
                # 方式1: Bearer Token (OpenAI格式)
                # print(self.api_key)
                headers["Authorization"] = f"Bearer {self.api_key}"
            # 发送请求
            session = self._get_session()
            async with session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=180)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    return {
                        "success": True,
                        "content": content.strip(),
                        "usage": result.get("usage", {}),
                        "model": self.model
                    }
                else:
                    error_text = await response.text()
                    self.logger.error(f"本地LLM请求失败: HTTP {response.status}, {error_text}")
                    return {
                        "success": False,
                        "error": f"HTTP {response.status}: {error_text}",
                        "content": ""
                    }
                    
        except Exception as e:
            self.logger.error(f"本地LLM请求异常: {e}")
            return {
                "success": False,
                "error": str(e),
                "content": ""
            }
    
    def send_request_sync(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """
        同步版本的请求方法（兼容DeepSeek接口）
        使用requests库避免事件循环冲突
        """
        try:
            import requests
            
            # 构建消息
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # 构建请求payload
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False
            }
            
            headers = {
                "Content-Type": "application/json",
            }
            if self.api_key:
                # 方式1: Bearer Token (OpenAI格式)
                headers["Authorization"] = f"Bearer {self.api_key}"
            # 使用requests同步发送请求
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=180
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                return {
                    "success": True,
                    "content": content.strip(),
                    "usage": result.get("usage", {}),
                    "model": self.model
                }
            else:
                self.logger.error(f"本地LLM请求失败: HTTP {response.status_code}, {response.text}")
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}",
                    "content": ""
                }
                
        except Exception as e:
            self.logger.error(f"同步LLM请求异常: {e}")
            return {
                "success": False,
                "error": str(e),
                "content": ""
            }
    
    async def close(self):
        """关闭客户端连接"""
        if self.session:
            await self.session.close()
            self.session = None
    
    def __del__(self):
        """析构函数，确保连接被关闭"""
        if self.session and not self.session.closed:
            # 在同步析构函数中无法调用异步方法，只能记录警告
            self.logger.warning("LocalLLMClient连接未正确关闭，请使用async with或手动调用close()")


# 简化的本地LLM客户端适配器（完全同步实现）
class LocalLLMClientAdapter:
    """本地LLM客户端适配器，兼容DeepSeek接口"""
    
    def __init__(self):
        import os
        self.base_url = os.getenv("LLM_BINDING_HOST", "http://localhost:8000/v1")
        self.model = os.getenv("LLM_MODEL", "Qwen2.5-VL-Instruct")
        self.api_key = os.getenv("LLM_BINDING_API_KEY", "")
        self.logger = get_logger(__name__)
        
        self.logger.info(f"初始化本地LLM客户端: 服务地址={self.base_url}, 模型路径={self.model}")
    
    def _send_request_direct(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """直接发送请求，避免异步复杂性"""
        try:
            import requests
            
            # 构建消息
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # 构建请求payload
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": kwargs.get("max_tokens", 2000),
                "temperature": kwargs.get("temperature", 0.7),
                "stream": False
            }
            headers = {
                "Content-Type": "application/json",
            }
            if self.api_key:
                # 方式1: Bearer Token (OpenAI格式)
                # print(self.api_key)
                headers["Authorization"] = f"Bearer {self.api_key}"

            # 使用requests同步发送请求
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=180
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                return {
                    "success": True,
                    "content": content.strip(),
                    "usage": result.get("usage", {}),
                    "model": self.model
                }
            else:
                self.logger.error(f"本地LLM请求失败: HTTP {response.status_code}, {response.text}")
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}",
                    "content": ""
                }
                
        except Exception as e:
            self.logger.error(f"本地LLM请求异常: {e}")
            return {
                "success": False,
                "error": str(e),
                "content": ""
            }
    
    def send_request(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """发送请求（兼容DeepSeek接口）"""
        try:
            result = self._send_request_direct(prompt, system_prompt, **kwargs)
            
            if result.get("success"):
                return {
                    "success": True,
                    "response": result.get("content", ""),
                    "usage": result.get("usage", {}),
                    "model": result.get("model", "local")
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "未知错误"),
                    "response": ""
                }
                
        except Exception as e:
            self.logger.error(f"本地LLM适配器请求失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": ""
            }
    
    def simple_chat(self, prompt: str, **kwargs) -> str:
        """简单聊天接口（兼容FieldMatcher需求）"""
        try:
            result = self.send_request(prompt, **kwargs)
            if result.get("success"):
                return result.get("response", "")
            else:
                self.logger.error(f"简单聊天失败: {result.get('error', '未知错误')}")
                return ""
        except Exception as e:
            self.logger.error(f"简单聊天异常: {e}")
            return ""
    
    def chat(self, messages: list, **kwargs) -> Dict[str, Any]:
        """聊天接口（兼容其他组件）"""
        try:
            # 提取最后一条用户消息作为prompt
            user_message = ""
            system_message = None
            
            for msg in messages:
                if msg.get("role") == "user":
                    user_message = msg.get("content", "")
                elif msg.get("role") == "system":
                    system_message = msg.get("content")
            
            return self.send_request(user_message, system_message, **kwargs)
            
        except Exception as e:
            self.logger.error(f"聊天接口异常: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": ""
            }
