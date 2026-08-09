"""
Bash 执行工具 —— 优先使用 Toolkit/SDK，不可识别命令 fallback 到 shell。

之前: subprocess.run(cmd, shell=True)
现在: Toolkit Registry → SDK/DBus → shell fallback（闭环验证 + 日志记录）
"""
import logging
import subprocess
import re
from typing import Annotated, Optional
from langchain_core.tools import tool
from .decorators import log_io
from src.utils.db_manager import log_handler, node_state

logger = logging.getLogger(__name__)
logger.addHandler(log_handler)

# ---------------------------------------------------------------------------
# 命令 → Toolkit 路由表
# 将常见 shell 命令映射到 toolkit 工具名，享受闭环验证
# ---------------------------------------------------------------------------

_TOOLKIT_ROUTES: dict[str, tuple[str, dict]] = {
    # 时区类
    "timedatectl set-timezone": ("timezone", {"timezone": "{arg}"}),
    # 音量类
    "amixer set master": ("volume", {"action": "set", "value": "{arg}"}),
    "amixer set Master": ("volume", {"action": "set", "value": "{arg}"}),
    # 蓝牙 / WiFi / 触摸板
    "rfkill unblock bluetooth": ("bluetooth", {"action": "on"}),
    "rfkill block bluetooth": ("bluetooth", {"action": "off"}),
    "nmcli radio wifi on": ("wifi", {"action": "on"}),
    "nmcli radio wifi off": ("wifi", {"action": "off"}),
    # 音乐
    "playerctl play": ("music", {"action": "play"}),
    "playerctl pause": ("music", {"action": "pause"}),
    # 睡眠
    "systemctl suspend": ("sleep", {}),
    # 目录（部分）
    "xdg-open": ("directory", {"dir": "{arg}"}),
    # 电源 / 重启 / 关机（正则锚定开头处理，见 _try_resolve_toolkit）
    "systemctl poweroff": ("power", {"action": "shutdown"}),
    "systemctl reboot": ("power", {"action": "reboot"}),
}


# 危险命令前缀 → DSL 权限 key（shell fallback 前的最后一道防线）
# 锚定命令开头，避免子串误匹配（如 `echo reboot`）
_DANGEROUS_CMDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*systemctl\s+poweroff\b"), "shutdown"),
    (re.compile(r"^\s*systemctl\s+reboot\b"), "reboot"),
    (re.compile(r"^\s*poweroff\b"), "shutdown"),
    (re.compile(r"^\s*reboot\b"), "reboot"),
    (re.compile(r"^\s*shutdown\b"), "shutdown"),
    (re.compile(r"^\s*rm\s+-rf\s+/\s*($|[;&|])"), "rm_root"),
    (re.compile(r"^\s*mkfs\b"), "mkfs"),
    (re.compile(r"^\s*dd\s+if="), "dd_write"),
]


def _check_shell_permission(cmd: str) -> Optional[str]:
    """
    Shell fallback 前的权限检查（确定性防线）。

    Returns an error string if blocked, else None.
    - L2 (deny) → 直接拦截 + 审计 permission_deny
    - L1 (require_confirm) → shell 路径无法交互确认，拦截并提示走 toolkit
    """
    from security.permission import get_permission_engine, Permission

    for pattern, dsl_key in _DANGEROUS_CMDS:
        if pattern.match(cmd):
            result = get_permission_engine().check_action(dsl_key)
            if result.permission == Permission.DENY:
                try:
                    from security.audit import SecurityAuditLogger
                    SecurityAuditLogger().log_permission_deny(
                        "bash_tool", dsl_key, result.reason
                    )
                except Exception:
                    pass
                return (
                    f"命令被安全策略拦截 (L2: {dsl_key}): {cmd.strip()[:120]}。"
                    "如需执行，请改用 toolkit 工具或联系管理员。"
                )
            if result.permission == Permission.REQUIRE_CONFIRM:
                try:
                    from security.audit import SecurityAuditLogger
                    SecurityAuditLogger().log_permission_deny(
                        "bash_tool", dsl_key,
                        "shell 路径无法交互确认，请走 toolkit 闭环",
                    )
                except Exception:
                    pass
                return (
                    f"命令需要用户确认 (L1: {dsl_key}): 请通过 toolkit 工具执行。"
                )
    return None


def _ensure_toolkit() -> None:
    """确保 toolkit 已初始化（幂等），覆盖不走 FastAPI lifespan 的入口."""
    try:
        from src.toolkit import init_tools
        init_tools.init_all_tools()
    except Exception as e:
        logger.warning("toolkit 初始化失败: %s", e)


def _try_resolve_toolkit(cmd: str) -> Optional[tuple[str, dict]]:
    """
    尝试将 shell 命令解析为 toolkit 工具调用。

    Returns
    -------
    (tool_name, kwargs) | None
    """
    cmd_lower = cmd.strip().lower()

    # 精确匹配
    for pattern, (tool_name, kwargs_template) in _TOOLKIT_ROUTES.items():
        if pattern in cmd_lower:
            # 提取参数（简单处理：取命令最后一段作为 arg）
            resolved = {}
            for key, value in kwargs_template.items():
                if value == "{arg}":
                    parts = cmd.strip().split()
                    if parts:
                        resolved[key] = parts[-1].strip("\"'")
                else:
                    resolved[key] = value
            return tool_name, resolved

    # 智能匹配: timedatectl set-timezone <zone>
    m = re.match(r"timedatectl\s+set-timezone\s+(\S+)", cmd_lower)
    if m:
        return "timezone", {"timezone": m.group(1)}

    # amixer set Master <value>%
    m = re.match(r"amixer\s+set\s+master\s+(\d+)%?", cmd_lower)
    if m:
        return "volume", {"action": "set", "value": int(m.group(1))}

    # 电源/关机/重启: 锚定开头，避免子串误匹配
    m = re.match(r"\s*(?:systemctl\s+)?poweroff\b", cmd_lower)
    if m:
        return "power", {"action": "shutdown"}
    m = re.match(r"\s*(?:systemctl\s+)?reboot\b", cmd_lower)
    if m:
        return "power", {"action": "reboot"}
    m = re.match(r"\s*shutdown\s+(-[a-z]*[hrc][a-z]*)\b", cmd_lower)
    if m:
        flag = m.group(1)
        action = ("shutdown" if "h" in flag else
                  "reboot" if "r" in flag else
                  "cancel" if "c" in flag else None)
        if action:
            return "power", {"action": action}

    return None


@tool
@log_io
def bash_tool(
    cmd: Annotated[str, "The bash command to be executed."],
):
    """
    执行 Bash 命令。优先通过 Toolkit（SDK/DBus）执行已知命令，享受闭环验证。
    无法识别的命令 fallback 到 subprocess。

    支持的命令示例：
    - 时区: timedatectl set-timezone Asia/Shanghai
    - 音量: amixer set Master 75%
    - 蓝牙: rfkill unblock/block bluetooth
    - WiFi: nmcli radio wifi on/off
    - 睡眠: systemctl suspend
    """
    logger.info(f"{node_state}-=-程序员===执行命令: {cmd}")

    # 0a. 确保 toolkit 已初始化（幂等）
    _ensure_toolkit()

    # 0b. 威胁扫描（prompt/命令注入/凭据外泄）
    from security.threat import get_threat_scanner
    threat = get_threat_scanner().scan(cmd)
    if not threat.safe:
        try:
            from security.audit import SecurityAuditLogger
            SecurityAuditLogger().log_threat_block(
                cmd, threat.threat_ids, threat.severity
            )
        except Exception:
            pass
        logger.warning(
            "%s-=-程序员===威胁拦截: ids=%s severity=%s cmd=%s",
            node_state, threat.threat_ids, threat.severity, cmd[:200],
        )
        return (
            f"命令被安全策略拦截（命中威胁模式: {', '.join(threat.threat_ids)}，"
            f"severity={threat.severity}）。{threat.description}"
        )

    # 1. 尝试 Toolkit 路由
    toolkit = _try_resolve_toolkit(cmd)
    if toolkit is not None:
        tool_name, kwargs = toolkit
        logger.info(f"{node_state}-=-程序员===路由到 Toolkit: {tool_name} params={kwargs}")

        try:
            from src.toolkit.base import get_registry
            from src.toolkit.executor import ClosedLoopExecutor
            import asyncio

            registry = get_registry()
            tool_obj = registry.get(tool_name)

            if tool_obj is not None:
                executor = ClosedLoopExecutor(registry=registry, max_retries=1)
                result = asyncio.run(executor.run(tool_name, **kwargs))
                logger.info(f"{node_state}-=-程序员===Toolkit 结果: {result.to_log()}")
                return result.to_agent_summary()
            else:
                logger.warning(f"{node_state}-=-程序员===Toolkit 工具 '{tool_name}' 未注册，fallback 到 shell")
        except Exception as e:
            logger.warning(f"{node_state}-=-程序员===Toolkit 路由失败: {e}，fallback 到 shell")

    # 2. Shell fallback 前的权限检查（危险命令确定性拦截）
    blocked = _check_shell_permission(cmd)
    if blocked is not None:
        logger.warning("%s-=-程序员===权限拦截: %s", node_state, blocked)
        return blocked

    # 3. Shell fallback
    logger.info(f"{node_state}-=-程序员===Shell fallback: {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, check=True, text=True, capture_output=True, timeout=120
        )
        logger.info(f"{node_state}-=-程序员===Stdout: {result.stdout[:500]}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        error_message = (
            f"{node_state}-=-程序员===Bash 返回错误代码: {e.returncode}.\n"
            f"Stdout: {e.stdout}\nStderr: {e.stderr}"
        )
        logger.error(error_message)
        return error_message
    except Exception as e:
        error_message = f"{node_state}-=-程序员===执行命令出错: {str(e)}"
        logger.error(error_message)
        return error_message


if __name__ == "__main__":
    print(bash_tool.invoke("ls -all"))
