import requests
import json
from typing import List, Dict, Any
import os

def get_dashscope_models(api_key: str) -> List[Dict[str, Any]]:
    """
    获取阿里云百炼平台的所有模型列表
    
    Args:
        api_key: 阿里云API Key
        
    Returns:
        模型列表
    """
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/models"
    # url = "https://api.deepseek.com/v1/models"
    
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

# 使用示例
if __name__ == "__main__":
    # 替换为你的阿里云API Key
    API_KEY = os.environ.get('QWEN_API_KEY', "none")
    # API_KEY = os.environ.get('DEEPSEEK_API_KEY', "none")
    print(API_KEY)
    models = get_dashscope_models(API_KEY)
    
    # 保存到文件
    if models:
        with open("dashscope_models.json", "w", encoding="utf-8") as f:
            json.dump(models, f, ensure_ascii=False, indent=2)
        print(f"\n模型列表已保存到 dashscope_models.json")