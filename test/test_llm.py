import requests
import json
from typing import List, Dict, Any, Optional
import os
from openai import OpenAI

def get_llm_models(url: str, api_key: str) -> List[Dict[str, Any]]:
    """
    获取阿里云百炼平台的所有模型列表
    
    Args:
        api_key: 阿里云API Key
        
    Returns:
        模型列表
    """
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # 提取模型信息
        models = data.get("data", [])
        
        print(f"成功获取 {len(models)} 个模型")
        
        # 打印模型详情
        for i, model in enumerate(models, 1):
            print(f"{i}. 模型ID: {model.get('id', 'N/A')}")
            # print(f"   名称: {model.get('name', 'N/A')}")
            # print(f"   类型: {model.get('type', 'N/A')}")
            # print(f"   所有者: {model.get('owned_by', 'N/A')}")
            # if 'permission' in model:
            #     print(f"   权限: {model.get('permission', [])}")
        
        return models
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        return []
    except Exception as e:
        print(f"发生错误: {e}")
        return []


def test_model_chat(api_url: str, api_key: str, model_name: str, prompt: str, 
                   max_tokens: int = 500, temperature: float = 0.7) -> Optional[str]:
    """
    测试模型的基本问答功能
    
    Args:
        api_url: API端点URL
        api_key: API密钥
        model_name: 模型名称
        prompt: 输入的提示文本
        max_tokens: 最大生成token数
        temperature: 生成温度
        
    Returns:
        模型的回复文本
    """
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 根据不同平台调整请求格式
    if "dashscope" in api_url:
        # 阿里云百炼格式
        payload = {
            "model": model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            },
            "parameters": {
                "max_tokens": max_tokens,
                "temperature": temperature
            }
        }
    else:
        # DeepSeek格式 (OpenAI兼容格式)
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False
        }
    
    try:
        print(f"\n正在测试模型: {model_name}")
        print(f"问题: {prompt}")
        
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        
        # 根据不同平台解析响应
        if "dashscope" in api_url:
            # 阿里云百炼响应格式
            if "output" in result and "choices" in result["output"]:
                reply = result["output"]["choices"][0]["message"]["content"]
            else:
                reply = "无法解析响应格式"
        else:
            # DeepSeek响应格式
            if "choices" in result and len(result["choices"]) > 0:
                reply = result["choices"][0]["message"]["content"]
            else:
                reply = "无法解析响应格式"
        
        print(f"回答: {reply}")
        print("-" * 80)
        
        return reply
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"响应状态码: {e.response.status_code}")
            print(f"响应内容: {e.response.text}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        return None
    except Exception as e:
        print(f"发生错误: {e}")
        return None
    
def openai_llm_qwen():
    client = OpenAI(
        # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx",
        api_key=os.environ.get('QWEN_API_KEY', "none"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    completion = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "你是谁？"},
        ],
        stream=True
    )
    for chunk in completion:
        print(chunk.choices[0].delta.content, end="", flush=True)
    
# 使用示例
if __name__ == "__main__":
    # 替换为你的阿里云API Key
    QWEN_API_KEY = os.environ.get('QWEN_API_KEY', "none")
    print(f"QWEN_API_KEY: {QWEN_API_KEY}")
    


    model = get_llm_models("https://dashscope.aliyuncs.com/compatible-mode/v1/models", QWEN_API_KEY)
    

    DS_API_KEY = os.environ.get('DEEPSEEK_API_KEY', "none")

    print("="*60)
    print(f"DEEPSEEK_API_KEY: {DS_API_KEY}")
    # model = get_llm_models("https://api.deepseek.com/v1/models", DS_API_KEY)
    print("="*60)
    # test_model_chat("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", QWEN_API_KEY, "qwen3-max-2025-09-23", "请写一首七言律诗")
    openai_llm_qwen()
    # test_model_chat("https://api.deepseek.com/chat/completions", DS_API_KEY, "deepseek-chat", "请问如何克服晚睡的习惯?")
    # # 保存到文件
    # if models:
    #     with open("dashscope_models.json", "w", encoding="utf-8") as f:
    #         json.dump(models, f, ensure_ascii=False, indent=2)
    #     print(f"\n模型列表已保存到 dashscope_models.json")