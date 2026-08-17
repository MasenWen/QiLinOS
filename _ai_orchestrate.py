"""AI 流程编排演示：让服务器上注册的 AI（ai_text SDK）决定工具与参数，
再由通用执行器执行。用户只给一句自然语言，其余全部由服务器 AI 完成。"""
import asyncio
import json
import re
import subprocess

from src.sdk import ai_text
from src.toolkit.init_tools import init_all_tools
from src.toolkit.base import get_registry
from src.toolkit.executor import ClosedLoopExecutor


def current_tz():
    return subprocess.run(
        ["timedatectl", "show", "--property=Timezone", "--value"],
        capture_output=True, text=True,
    ).stdout.strip()


def main():
    instruction = "修改当前时区到美国西海岸时区"

    init_all_tools()
    registry = get_registry()

    # 1) 把可用工具目录交给服务器 AI，让它做编排（选工具 + 填参数）
    catalog = "\n".join(
        f"- {name}: {registry.get(name).description}"
        for name in registry.list_all()
    )
    prompt = (
        "你是系统操作编排器。根据用户指令，从下面的工具列表中选择一个工具并给出参数。\n\n"
        f"可用工具：\n{catalog}\n\n"
        f"用户指令：{instruction}\n\n"
        '只输出一个 JSON，格式：{"tool": "工具名", "params": {"参数名": "参数值"}}，不要输出其它内容。'
    )

    with ai_text.TextSession() as t:
        raw = t.generate(prompt)
    print("AI 编排原始输出:", repr(raw))

    # 2) 解析 AI 返回的 JSON 计划
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    plan = json.loads(m.group(0))
    tool_name = plan["tool"]
    params = plan["params"]
    print("AI 选择工具:", tool_name, "| 参数:", params)

    # 3) 通用执行器按 AI 的计划执行（closed-loop execute -> verify）
    executor = ClosedLoopExecutor(registry=registry, max_retries=1)

    async def run():
        return await executor.run(tool_name, confirmed=True, **params)

    res = asyncio.run(run())
    after = current_tz()
    print("执行状态:", res.status.value)
    print("执行输出:", res.output)
    print("闭环验证:", res.verification, "| is_verified:", res.is_verified)
    print("实际时区:", after, "| MATCH:", after == params.get("timezone"))


if __name__ == "__main__":
    main()
