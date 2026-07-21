from langchain_openai import ChatOpenAI
from langchain_deepseek import ChatDeepSeek
from typing import Optional, Dict, Any, Union
from langchain_openai import ChatOpenAI

# 修改导入
from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_cohere import ChatCohere
from langchain_huggingface import ChatHuggingFace
from langchain_openai import AzureChatOpenAI


from langchain_community.llms.llamacpp import LlamaCpp
from langchain_community.llms.vllm import VLLM

import os

from src.config import (
    REASONING_MODEL,
    REASONING_BASE_URL,
    REASONING_API_KEY,
    BASIC_MODEL,
    BASIC_BASE_URL,
    BASIC_API_KEY,
    VL_MODEL,
    VL_BASE_URL,
    VL_API_KEY,
)
from src.config.agents import LLMType


def create_llm(
    provider: str,
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    **kwargs,
) -> Union[ChatOpenAI, ChatOllama, Any]:
    """
    创建各种LLM实例的统一工厂函数
    
    Args:
        provider: LLM提供商，可选值：
            - "openai" (包括兼容OpenAI API的接口)
            - "deepseek"
            - "ollama"
            - "vllm"
            - "anthropic"
            - "azure_openai"
            - "huggingface"
            - "google_palm"
            - "cohere"
            - "gpt4all"
            - "llama_cpp"
            - "replicate"
            - "text_gen_inference" (HuggingFace Text Generation Inference)
        model: 模型名称
        base_url: API基础URL
        api_key: API密钥
        temperature: 温度参数
        max_tokens: 最大token数
        **kwargs: 其他特定于提供商的参数
        
    Returns:
        LLM实例
    """
    
    # 设置API密钥环境变量（如果提供）
    if api_key:
        # 根据provider设置不同的环境变量
        env_vars = {
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "azure_openai": "AZURE_OPENAI_API_KEY",
            "google_palm": "GOOGLE_PALM_API_KEY",
            "cohere": "COHERE_API_KEY",
            "huggingface": "HUGGINGFACEHUB_API_TOKEN",
            "replicate": "REPLICATE_API_TOKEN",
        }
        
        if provider in env_vars:
            os.environ[env_vars[provider]] = api_key
    
    # 通用配置
    llm_kwargs = {
        "model": model,
        "temperature": temperature,
        **kwargs
    }
    
    if max_tokens:
        llm_kwargs["max_tokens"] = max_tokens
    
    # 根据provider创建相应的LLM实例
    if provider == "openai":
        if base_url:
            llm_kwargs["base_url"] = base_url
        if api_key:
            llm_kwargs["api_key"] = api_key
        return ChatOpenAI(**llm_kwargs)
    
    elif provider == "deepseek":
        # DeepSeek通常使用OpenAI兼容的接口
        if base_url:
            llm_kwargs["base_url"] = base_url or "https://api.deepseek.com"
        if api_key:
            llm_kwargs["api_key"] = api_key
        # DeepSeek使用OpenAI兼容的API
        return ChatOpenAI(**llm_kwargs)
    
    elif provider == "ollama":
        if base_url:
            llm_kwargs["base_url"] = base_url
        # Ollama不需要API密钥
        return ChatOllama(**llm_kwargs)
    
    elif provider == "vllm":
        # VLLM通常使用OpenAI兼容的接口
        if base_url:
            llm_kwargs["base_url"] = base_url or "http://localhost:8000/v1"
        if api_key:
            llm_kwargs["api_key"] = api_key or "EMPTY"  # VLLM通常需要API密钥占位符
        # 使用OpenAI兼容接口
        return ChatOpenAI(**llm_kwargs)
    
    elif provider == "anthropic":
        if base_url:
            llm_kwargs["base_url"] = base_url
        if api_key:
            llm_kwargs["anthropic_api_key"] = api_key
        return ChatAnthropic(**llm_kwargs)
    
    elif provider == "azure_openai":
        # Azure OpenAI需要特定的参数
        if base_url:
            llm_kwargs["azure_endpoint"] = base_url
        if api_key:
            llm_kwargs["api_key"] = api_key
        
        # Azure OpenAI需要deployment_name参数
        if "deployment_name" not in llm_kwargs:
            llm_kwargs["deployment_name"] = model
        
        return AzureChatOpenAI(**llm_kwargs)
    
    elif provider == "huggingface":
        # HuggingFace聊天模型
        if api_key:
            llm_kwargs["huggingfacehub_api_token"] = api_key
        
        # 设置默认参数
        llm_kwargs.setdefault("task", "text-generation")
        
        return ChatHuggingFace(**llm_kwargs)
    
    elif provider == "google_palm":
        if api_key:
            llm_kwargs["google_api_key"] = api_key
        return ChatGooglePalm(**llm_kwargs)
    
    elif provider == "cohere":
        if api_key:
            llm_kwargs["cohere_api_key"] = api_key
        return ChatCohere(**llm_kwargs)
    
    elif provider == "llama_cpp":
        # Llama.cpp本地模型
        llm_kwargs.setdefault("n_ctx", 2048)
        llm_kwargs.setdefault("max_tokens", max_tokens or 512)
        
        # 模型路径
        if "model_path" not in llm_kwargs:
            llm_kwargs["model_path"] = model
        return LlamaCpp(**llm_kwargs)
    
    
    else:
        raise ValueError(f"不支持的LLM提供商: {provider}")
    

# 配置预设
LLM_CONFIGS = {
    # OpenAI
    "gpt-4": {"provider": "openai", "model": "gpt-4"},
    "gpt-3.5-turbo": {"provider": "openai", "model": "gpt-3.5-turbo"},
    "gpt-4o": {"provider": "openai", "model": "gpt-4o"},
    
    # DeepSeek
    "deepseek-chat": {"provider": "deepseek", "model": "deepseek-chat"},
    "deepseek-coder": {"provider": "deepseek", "model": "deepseek-coder"},
    
    # Ollama常用模型
    "llama2": {"provider": "ollama", "model": "llama2"},
    "llama3": {"provider": "ollama", "model": "llama3"},
    "mistral": {"provider": "ollama", "model": "mistral"},
    "mixtral": {"provider": "ollama", "model": "mixtral"},
    "qwen": {"provider": "ollama", "model": "qwen"},
    
    # Anthropic
    "claude-3-opus": {"provider": "anthropic", "model": "claude-3-opus-20240229"},
    "claude-3-sonnet": {"provider": "anthropic", "model": "claude-3-sonnet-20240229"},
    "claude-3-haiku": {"provider": "anthropic", "model": "claude-3-haiku-20240307"},
    
    # vLLM预设
    "vllm-llama2": {"provider": "vllm", "model": "meta-llama/Llama-2-7b-chat-hf"},
    "vllm-mistral": {"provider": "vllm", "model": "mistralai/Mistral-7B-Instruct-v0.1"},
    
    # 本地模型
    "llama-cpp": {"provider": "llama_cpp", "model": "models/llama-2-7b-chat.Q4_K_M.gguf"},
}


def create_llm_from_config(
    config_name: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.0,
    **kwargs,
) -> Any:
    """
    使用预设配置创建LLM实例
    
    Args:
        config_name: 预设配置名称
        base_url: 覆盖预设的基础URL
        api_key: API密钥
        temperature: 温度参数
        **kwargs: 其他参数
        
    Returns:
        LLM实例
    """
    if config_name not in LLM_CONFIGS:
        raise ValueError(f"未知的LLM配置: {config_name}")
    
    config = LLM_CONFIGS[config_name].copy()
    provider = config.pop("provider")
    model = config.pop("model")
    
    # 合并参数
    config.update(kwargs)
    
    return create_llm(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        **config,
    )
    
def create_openai_llm(
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.0,
    **kwargs,
) -> ChatOpenAI:
    """
    Create a ChatOpenAI instance with the specified configuration
    """
    # Only include base_url in the arguments if it's not None or empty
    llm_kwargs = {"model": model, "temperature": temperature, "request_timeout": 15, **kwargs}

    if base_url:  # This will handle None or empty string
        llm_kwargs["base_url"] = base_url

    if api_key:  # This will handle None or empty string
        llm_kwargs["api_key"] = api_key

    return ChatOpenAI(**llm_kwargs)


def create_deepseek_llm(
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.0,
    **kwargs,
) -> ChatDeepSeek:
    """
    Create a ChatDeepSeek instance with the specified configuration
    """
    # Only include base_url in the arguments if it's not None or empty
    llm_kwargs = {"model": model, "temperature": temperature, **kwargs}

    if base_url:  # This will handle None or empty string
        llm_kwargs["api_base"] = base_url

    if api_key:  # This will handle None or empty string
        llm_kwargs["api_key"] = api_key

    return ChatDeepSeek(**llm_kwargs)


# Cache for LLM instances
_llm_cache: dict[LLMType, ChatOpenAI | ChatDeepSeek] = {}


def get_llm_by_type(llm_type: LLMType) -> ChatOpenAI | ChatDeepSeek:
    """
    Get LLM instance by type. Returns cached instance if available.
    """
    if llm_type in _llm_cache:
        return _llm_cache[llm_type]

    if llm_type == "reasoning":
        llm = create_openai_llm(
            model=REASONING_MODEL,
            base_url=REASONING_BASE_URL,
            api_key=REASONING_API_KEY,
        )
    elif llm_type == "basic":
        llm = create_openai_llm(
            model=BASIC_MODEL,
            base_url=BASIC_BASE_URL,
            api_key=BASIC_API_KEY,
        )
    elif llm_type == "vision":
        llm = create_openai_llm(
            model=VL_MODEL,
            base_url=VL_BASE_URL,
            api_key=VL_API_KEY,
        )
    else:
        raise ValueError(f"Unknown LLM type: {llm_type}")

    _llm_cache[llm_type] = llm
    return llm


reasoning_llm = get_llm_by_type("reasoning")
basic_llm = get_llm_by_type("basic")
vl_llm = get_llm_by_type("vision")


if __name__ == "__main__":
    # Initialize LLMs for different purposes - now these will be cached

    stream = reasoning_llm.stream("what is mcp?")
    full_response = ""
    for chunk in stream:
        full_response += chunk.content
    print(full_response)

    basic_llm.invoke("Hello")
    vl_llm.invoke("Hello")


    llm1 = create_llm(
        provider="openai",
        model="gpt-3.5-turbo",
        base_url="https://api.openai.com/v1",
        api_key="your-api-key",
        temperature=0.7,
    )
    
    # 2. 使用Ollama
    llm2 = create_llm(
        provider="ollama",
        model="llama2",
        base_url="http://localhost:11434",
        temperature=0.7,
    )
    
    # 3. 使用vLLM
    llm3 = create_llm(
        provider="vllm",
        model="meta-llama/Llama-2-7b-chat-hf",
        base_url="http://localhost:8000/v1",
        api_key="EMPTY",  # vLLM通常需要API密钥占位符
        temperature=0.7,
    )
    
    # 4. 使用DeepSeek
    llm4 = create_llm(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key="your-deepseek-key",
        temperature=0.7,
    )
