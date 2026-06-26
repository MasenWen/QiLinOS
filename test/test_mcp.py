import requests
import json


BASE_URL = "http://127.0.0.1:50066"

def ask_kylin_server(query):
    """指定使用kylin_server打开蓝牙"""

    payload = {
        "query": query,
        "allow_servers": ["kylin_server"],
        "timeout_ms": 10000,
        "dry_run": False
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(
            f"{BASE_URL}/agent/ask",
            headers=headers,
            json=payload,
            timeout=10  # 请求超时时间
        )
        
        response.raise_for_status()
        result = response.json()
        
        print("响应状态:", response.status_code)
        print("响应内容:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        # 解析结果
        if result.get("executed"):
            print("\n执行成功！")
            print(f"使用的服务器: {result.get('plan', {}).get('server', '未知')}")
            print(f"使用的工具: {result.get('plan', {}).get('tool', '未知')}")
            print(f"最终答案: {result.get('answer', '无')}")
        else:
            print("\n执行失败或未执行")
            if result.get("clarification_needed"):
                print("需要更多信息:", result.get("clarification", {}))
        
        return result
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return None
    
def ask_plan(query):
    """指定使用kylin_server打开蓝牙"""
    
    payload = {
        "query": query,
        "timeout_ms": 10000,
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(
            f"{BASE_URL}/agent/plan",
            headers=headers,
            json=payload,
            timeout=10  # 请求超时时间
        )
        
        response.raise_for_status()
        result = response.json()
        
        print("响应状态:", response.status_code)
        print("响应内容:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        # 解析结果
        if result.get("executed"):
            print("\n执行成功！")
            print(f"使用的服务器: {result.get('plan', {}).get('server', '未知')}")
            print(f"使用的工具: {result.get('plan', {}).get('tool', '未知')}")
            print(f"最终答案: {result.get('answer', '无')}")
        else:
            print("\n执行失败或未执行")
            if result.get("clarification_needed"):
                print("需要更多信息:", result.get("clarification", {}))
        
        return result
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return None

def check_kylin_server_status():
    """检查kylin_server状态"""
    BASE_URL = "http://127.0.0.1:50066"
    
    try:
        # 检查kylin_server是否存在
        response = requests.get(f"{BASE_URL}/servers")
        servers = response.json().get("servers", [])
        
        if "kylin_server" in servers:
            print("✓ kylin_server 已连接")
            
            # 获取详细状态
            response = requests.get(f"{BASE_URL}/servers/kylin_server")
            status = response.json()
            print(f"  状态: {status}")
        else:
            print("✗ kylin_server 未连接")
            print("  请先连接服务器:")
            print(f"  curl -X POST {BASE_URL}/servers/kylin_server/connect")
            
    except Exception as e:
        print(f"检查服务器状态时出错: {e}")

# 执行示例
if __name__ == "__main__":
    BASE_URL = "http://127.0.0.1:50066"
    # 1. 检查服务器状态
    # print("=" * 50)
    # print("检查服务器状态")
    # print("=" * 50)
    # check_kylin_server_status()
    
    # 2. 打开蓝牙
    print("\n" + "=" * 50)
    print("尝试打开蓝牙（指定kylin_server）")
    print("=" * 50)
    result = ask_plan("今天天气怎么样？然后打开蓝牙")
    