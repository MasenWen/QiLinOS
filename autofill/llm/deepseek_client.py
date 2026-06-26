"""
通用LLM客户端

支持连接到各种LLM模型服务，包括DeepSeek、Qwen等。
默认连接到本地部署的模型服务。
"""

import requests
import time
import uuid
from typing import Dict, Any, Optional
from urllib.parse import urljoin

from .base import (
    BaseLLMClient, 
    LLMProvider, 
    LLMRequest, 
    LLMResponse, 
    LLMUsage,
    ProcessingStatus
)
from ..config.settings import get_config
from ..utils.logger import performance_monitor, error_handler
import os

DS_API_KEY = os.environ.get('DEEPSEEK_API_KEY', "none")
class DeepSeekClient(BaseLLMClient):
    """通用LLM模型客户端，支持DeepSeek、Qwen等模型"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化通用LLM客户端
        
        Args:
            config: 客户端配置，包含服务器地址和端口
        """
        super().__init__(config)
        
        # 获取配置
        app_config = get_config()
        
        # 服务器配置 - 正确处理api_base
        api_base = None
        if self.config and 'api_base' in self.config:
            api_base = self.config['api_base']
        elif self.config and 'host' in self.config:
            # 如果直接指定host，构建简单的host:port格式
            self.host = self.config['host']
            self.port = self.config.get('port', 6666)
            self.base_url = f"http://{self.host}:{self.port}"
            self.base_url = "https://api.deepseek.com/v1"
        else:
            # 从app_config获取
            api_base = app_config.llm.api_base
        
        # 处理api_base
        if api_base:
            # 如果api_base是完整的URL
            if api_base.startswith('http://') or api_base.startswith('https://'):
                self.base_url = api_base.rstrip('/')
                # 解析出host和port用于日志
                from urllib.parse import urlparse
                parsed = urlparse(api_base)
                self.host = parsed.hostname or 'unknown'
                self.port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            else:
                # 如果api_base只是主机名或IP
                self.host = api_base
                self.port = self.config.get('port', 6666) if self.config else 6666
                self.base_url = f"http://{self.host}:{self.port}"
        else:
            # 默认值
            self.host = 'localhost'
            self.port = 6666
            self.base_url = f"http://{self.host}:{self.port}"
        
        # 检查LLM服务是否启用
        self.enabled = app_config.llm.enable_llm_analysis
        
        # 请求配置
        self.timeout = self.config.get('timeout', app_config.llm.timeout or 30)
        self.retry_count = self.config.get('retry_count', app_config.llm.retry_count or 3)
        self.retry_delay = self.config.get('retry_delay', 1.0)
        
        # HTTP会话
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'FormFiller-DeepSeekClient/1.0'
        })
        
        self.logger.info(
            "通用LLM客户端初始化完成",
            extra={
                "host": self.host,
                "port": self.port,
                "base_url": self.base_url,
                "timeout": self.timeout,
                "enabled": self.enabled,
                "model_type": "通用LLM（支持Qwen、DeepSeek等）"
            }
        )
        
        # 添加调试信息
        print(f"LLM客户端配置:")
        print(f"  - 服务地址: {self.base_url}")
        print(f"  - 超时时间: {self.timeout}秒")
        print(f"  - LLM分析: {'启用' if self.enabled else '禁用'}")
        print(f"  - 重试次数: {self.retry_count}")
    
    def _get_provider(self) -> LLMProvider:
        """获取LLM提供商"""
        return LLMProvider.DEEPSEEK
    
    @performance_monitor()
    def _send_request(self, request: LLMRequest) -> LLMResponse:
        """
        发送请求到DeepSeek服务
        
        Args:
            request: LLM请求对象
            
        Returns:
            LLMResponse: LLM响应对象
        """
        request_id = request.request_id or str(uuid.uuid4())
        
        # 如果LLM服务未启用，返回默认响应
        if not self.enabled:
            self.logger.info("LLM服务未启用，返回默认响应")
            return LLMResponse(
                content="LLM服务未启用，使用默认处理逻辑",
                status=ProcessingStatus.SUCCESS,
                request_id=request_id
            )
        
        try:
            # 构建请求数据
            payload = self._build_payload(request)
            
            # 发送请求（带重试机制）
            response_data = self._send_with_retry(payload, request_id)
            
            # 解析响应
            return self._parse_response(response_data, request_id)
            
        except requests.exceptions.ConnectionError as e:
            self.logger.error(
                f"连接到DeepSeek服务失败: {e}",
                extra={"request_id": request_id, "base_url": self.base_url}
            )
            return LLMResponse(
                content="",
                status=ProcessingStatus.FAILED,
                error_message=f"连接服务失败: {e}",
                request_id=request_id
            )
            
        except requests.exceptions.Timeout as e:
            self.logger.error(
                f"DeepSeek服务请求超时: {e}",
                extra={"request_id": request_id, "timeout": self.timeout}
            )
            return LLMResponse(
                content="",
                status=ProcessingStatus.FAILED,
                error_message=f"请求超时: {e}",
                request_id=request_id
            )
            
        except Exception as e:
            self.logger.error(
                f"DeepSeek请求处理失败: {e}",
                extra={"request_id": request_id},
                exc_info=True
            )
            return LLMResponse(
                content="",
                status=ProcessingStatus.FAILED,
                error_message=str(e),
                request_id=request_id
            )
    
    def _build_payload(self, request: LLMRequest) -> Dict[str, Any]:
        """
        构建请求负载
        
        Args:
            request: LLM请求对象
            
        Returns:
            Dict[str, Any]: 请求负载
        """
        # 合并所有消息内容（DeepSeek服务期望单个message字段）
        # combined_message = ""
        
        # for msg in request.messages:
        #     if msg.role.value == "system":
        #         combined_message += f"[系统]: {msg.content}\n"
        #     elif msg.role.value == "user":
        #         combined_message += f"[用户]: {msg.content}\n"
        #     elif msg.role.value == "assistant":
        #         combined_message += f"[助手]: {msg.content}\n"
        
        # 移除最后的换行符
        # combined_message = combined_message.rstrip('\n')
        
        combined_message = []
        for msg in request.messages:
            # if msg.role.value == "system":
            combined_message.append({"role": msg.role.value, "content": msg.content})
            # elif msg.role.value == "user":
            #     combined_message += f"[用户]: {msg.content}\n"
            # elif msg.role.value == "assistant":
            #     combined_message += f"[助手]: {msg.content}\n"

            # messages = [
        #     {"role": "user", "content": "请写一首关于春天的诗"}
        # ]
        # temperature=0.7
        # max_tokens=2048
        # stream=False
        # data = {
        #     "model": "deepseek-chat",
        #     "messages": messages,
        #     "temperature": temperature,
        #     "max_tokens": max_tokens,
        #     "stream": stream
        # }

        payload = {
            "model": "deepseek-chat",
            "messages": combined_message
        }
        
        # 添加可选参数（如果DeepSeek服务支持）
        if hasattr(request, 'temperature') and request.temperature != 0.7:
            payload["temperature"] = request.temperature
        
        if hasattr(request, 'max_tokens') and request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        
        return payload
    
    def _send_with_retry(self, payload: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        """
        带重试机制发送请求
        
        Args:
            payload: 请求负载
            request_id: 请求ID
            
        Returns:
            Dict[str, Any]: 响应数据
            
        Raises:
            Exception: 请求失败异常
        """
        last_exception = None
        
        for attempt in range(self.retry_count):
            try:
                self.logger.debug(
                    f"发送DeepSeek请求，尝试 {attempt + 1}/{self.retry_count}",
                    extra={
                        "request_id": request_id,
                        "payload_size": len(str(payload))
                    }
                )
                self.headers = {
                    "Authorization": f"Bearer {DS_API_KEY}",
                    "Content-Type": "application/json"
                }
                
                # messages = [
                #     {"role": "user", "content": "test"}
                # ]
                # # temperature=0.7
                # # max_tokens=2048
                # # stream=False
                # data = {
                #     "model": "deepseek-chat",
                #     "messages": messages,
                #     # "temperature": temperature,
                #     # "max_tokens": max_tokens,
                #     # "stream": stream
                # }
                # print('='*60)
                # print(data)
                # print('='*60)
                # print(payload)
                # response = self.session.post(
                #     urljoin(self.base_url, "/chat/completions"),
                #     json=data,
                #     # timeout=self.timeout
                # )
                response = requests.post(urljoin(self.base_url, "/chat/completions"), headers=self.headers, json=payload)
                response.raise_for_status()
                
                # 检查HTTP状态码
                if response.status_code == 200:
                    result = response.json()
                    
                    self.logger.debug(
                        "DeepSeek请求成功",
                        extra={
                            "request_id": request_id,
                            "status_code": response.status_code,
                            "response_size": len(response.text)
                        }
                    )
                    
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                    return {
                        "status": "success",
                        "success": True,
                        "content": content.strip(),
                        "usage": result.get("usage", {}),
                        "model": "deepseek-chat"
                    }
            
                    # return response_data
                
                elif response.status_code == 500:
                    # 服务器内部错误，可以重试
                    error_msg = f"服务器内部错误 (HTTP {response.status_code})"
                    if attempt < self.retry_count - 1:
                        self.logger.warning(
                            f"{error_msg}，{self.retry_delay}秒后重试",
                            extra={"request_id": request_id, "attempt": attempt + 1}
                        )
                        time.sleep(self.retry_delay)
                        continue
                    else:
                        raise requests.exceptions.HTTPError(error_msg)
                
                else:
                    # 其他HTTP错误，不重试
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('error', f'HTTP {response.status_code}')
                    except:
                        error_msg = f"HTTP {response.status_code}: {response.text}"
                    
                    raise requests.exceptions.HTTPError(error_msg)
                
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_exception = e
                if attempt < self.retry_count - 1:
                    self.logger.warning(
                        f"连接失败，{self.retry_delay}秒后重试: {e}",
                        extra={"request_id": request_id, "attempt": attempt + 1}
                    )
                    time.sleep(self.retry_delay * (attempt + 1))  # 指数退避
                else:
                    raise e
            
            except Exception as e:
                # 其他异常不重试
                raise e
        
        # 如果所有重试都失败了
        if last_exception:
            raise last_exception
        else:
            raise Exception("所有重试尝试都失败了")
    
    def _parse_response(self, response_data: Dict[str, Any], request_id: str) -> LLMResponse:
        """
        解析响应数据
        
        Args:
            response_data: 服务器响应数据
            request_id: 请求ID
            
        Returns:
            LLMResponse: LLM响应对象
        """
        try:
            # 检查响应状态
            if response_data.get("success") == True:
                content = response_data.get("content", "").strip()
                
                # 创建使用统计（DeepSeek服务没有返回token统计，估算）
                usage = LLMUsage(
                    prompt_tokens=self._estimate_tokens(response_data.get("user_message", "")),
                    completion_tokens=self._estimate_tokens(content),
                    total_tokens=0
                )
                usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
                
                return LLMResponse(
                    content=content,
                    status=ProcessingStatus.SUCCESS,
                    request_id=request_id,
                    model="deepseek-7b",
                    usage=usage,
                    metadata={
                        "user_message": response_data.get("user_message"),
                        "raw_response": response_data
                    }
                )
            else:
                # 处理错误响应
                error_message = response_data.get("error", "未知错误")
                
                return LLMResponse(
                    content="",
                    status=ProcessingStatus.FAILED,
                    request_id=request_id,
                    error_message=error_message,
                    metadata={"raw_response": response_data}
                )
                
        except Exception as e:
            self.logger.error(
                f"解析DeepSeek响应失败: {e}",
                extra={"request_id": request_id, "response_data": response_data},
                exc_info=True
            )
            
            return LLMResponse(
                content="",
                status=ProcessingStatus.FAILED,
                request_id=request_id,
                error_message=f"响应解析失败: {e}",
                metadata={"raw_response": response_data}
            )
    
    def _estimate_tokens(self, text: str) -> int:
        """
        估算文本的token数量
        
        Args:
            text: 输入文本
            
        Returns:
            int: 估算的token数量
        """
        if not text:
            return 0
        
        # 简单估算：中文字符按1个token计算，英文单词按平均1.3个token计算
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
        english_words = len(text.replace(' ', '').replace('\n', '')) - chinese_chars
        
        return chinese_chars + int(english_words * 1.3)
    
    @error_handler(reraise=False)
    def health_check(self) -> Dict[str, Any]:
        """
        健康检查
        
        Returns:
            Dict[str, Any]: 健康状态信息
        """
        try:
            # 检查服务可达性
            response = self.session.get(
                urljoin(self.base_url, "/health"),
                timeout=5
            )
            
            if response.status_code == 200:
                health_data = response.json()
                
                return {
                    "status": "healthy" if health_data.get("status") == "healthy" else "unhealthy",
                    "provider": self.provider.value,
                    "service_url": self.base_url,
                    "model_loaded": health_data.get("model_loaded", False),
                    "response_time": response.elapsed.total_seconds(),
                    "timestamp": time.time()
                }
            else:
                return {
                    "status": "unhealthy",
                    "provider": self.provider.value,
                    "service_url": self.base_url,
                    "error": f"HTTP {response.status_code}",
                    "timestamp": time.time()
                }
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": self.provider.value,
                "service_url": self.base_url,
                "error": str(e),
                "timestamp": time.time()
            }
    
    def close(self):
        """关闭客户端连接"""
        if self.session:
            self.session.close()
            self.logger.info("DeepSeek客户端连接已关闭")


# 全局客户端实例
_deepseek_client: Optional[DeepSeekClient] = None


def get_deepseek_client(config: Dict[str, Any] = None) -> DeepSeekClient:
    """
    获取全局DeepSeek客户端实例
    
    Args:
        config: 客户端配置
        
    Returns:
        DeepSeekClient: DeepSeek客户端实例
    """
    global _deepseek_client
    if _deepseek_client is None:
        _deepseek_client = DeepSeekClient(config)
    return _deepseek_client


def close_deepseek_client():
    """关闭全局DeepSeek客户端"""
    global _deepseek_client
    if _deepseek_client:
        _deepseek_client.close()
        _deepseek_client = None


# 导出类和函数
__all__ = [
    "DeepSeekClient",
    "get_deepseek_client", 
    "close_deepseek_client"
] 