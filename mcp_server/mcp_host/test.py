import requests

def ask_mcp(query, allow_servers=None, dry_run=False, timeout_ms=60000, base_url="http://127.0.0.1:50066", session_id=None):
    payload = {
        "query": query,
        "timeout_ms": timeout_ms,
        "dry_run": dry_run,
    }
    if allow_servers is not None:
        payload["allow_servers"] = allow_servers
    if session_id is not None:
        payload["session_id"] = session_id  # 建议 int 或 "123"

    r = requests.post(f"{base_url}/agent/ask", json=payload, timeout=timeout_ms/1000)
    print(r.text)
    r.raise_for_status()

    return r.json()

print(ask_mcp("打开蓝牙", allow_servers=["kylin_server"], session_id="1"))
