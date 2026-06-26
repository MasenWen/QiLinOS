import json
from pathlib import Path

# 仓库根目录 = mcp_host 上一层
ROOT = Path(__file__).resolve().parents[1]

REGISTRY_PATH = ROOT / "mcp_server/servers_registry.json"
OUT_PATH = ROOT / "mcp_server/mcp_servers.config.json"


def _command_for_path(abs_path: str) -> str:
    if abs_path.endswith(".py"):
        return "python"
    # 默认按 Node（.js/.mjs/.cjs 等）
    return "node"


def main():
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    mcp_servers = {}

    for name, info in data.items():
        desc = info.get("description", "")
        abs_path = info.get("abs_path")
        filename = info.get("filename")

        if not abs_path and filename:
            abs_path = str((ROOT / "mcp_server/server" / filename).resolve())

        external_name = name.replace("_", "-")

        mcp_servers[external_name] = {
            "description": desc,
            "command": _command_for_path(abs_path),
            "args": [abs_path],
            "env": {"PYTHONUNBUFFERED": "1"},
        }

    out = {"mcpServers": mcp_servers}
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"生成完成: {OUT_PATH}")


if __name__ == "__main__":
    main()
