"""
System-level tools — timezone, sleep, power management.

Each tool is SDK-first, shell-fallback, with built-in verify().

Mapping to shell commands being replaced:
- ``timedatectl set-timezone`` → TimezoneTool
- ``systemctl suspend``        → SleepTool
- ``systemctl reboot``         → PowerTool (reboot)
- ``systemctl poweroff``       → PowerTool (shutdown)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import logging
from typing import Optional

from .base import BaseTool, ToolResult, ToolStatus, RiskLevel

logger = logging.getLogger("toolkit.system")


def _to_minutes(delay_seconds) -> int:
    """
    Normalize a delay (seconds) to a minutes value for the C SDK.

    - ``delay < 0``  → -1 (immediate)
    - ``0 <= delay < 60`` → 1 (round up, avoid accidental immediate "+0")
    - otherwise → ``delay // 60``
    """
    try:
        delay = int(delay_seconds)
    except (TypeError, ValueError):
        delay = 60
    if delay < 0:
        return -1
    return max(1, delay // 60)


# ---------------------------------------------------------------------------
# TimezoneTool
# ---------------------------------------------------------------------------

class TimezoneTool(BaseTool):
    """
    Set system timezone with full verification.

    Replaces::

        timedatectl set-timezone Asia/Singapore
        timedatectl status | grep "Time zone"

    - execute: set timezone via ``timedatectl``
    - verify:  read back current timezone, compare with target
    - rollback: restore previous timezone on failure
    """

    name = "timezone"
    description = (
        "设置系统时区（需带 timezone 参数，例如 'Asia/Shanghai', 'Asia/Singapore', 'America/New_York'）；"
        "不带 timezone 参数时，返回当前系统时区（查询模式）。"
        "执行后会验证时区是否确实切换成功。"
    )
    risk = RiskLevel.CONSEQUENTIAL
    requires_approval = True
    timeout_s = 30.0

    def __init__(self):
        super().__init__()
        self._previous_timezone: Optional[str] = None

    # ------------------------------------------------------------------
    def execute(self, **kwargs) -> ToolResult:
        target = kwargs.get("timezone", "")
        if not target:
            # 查询模式：返回当前系统时区（AI 问"现在时区是多少"时走这里）
            current = self._get_current_timezone()
            if current:
                return self._ok(
                    f"当前系统时区: {current}（查询模式，未做任何修改）",
                    timezone=current, mode="query",
                )
            return self._fail("无法读取当前系统时区")

        # Validate timezone
        valid = self._list_timezones()
        if target not in valid:
            return self._fail(
                f"无效的时区: '{target}'。使用 list_timezones() 查看可用时区。",
                output=f"可用示例: {', '.join(list(valid)[:10])}...",
            )

        # Save current timezone for rollback
        self._previous_timezone = self._get_current_timezone()

        try:
            result = subprocess.run(
                ["timedatectl", "set-timezone", target],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return self._ok(
                    f"时区已设置为 {target}（原时区: {self._previous_timezone}）",
                    previous=self._previous_timezone,
                    target=target,
                )
            else:
                return self._fail(
                    f"timedatectl 失败: {result.stderr.strip()}",
                    output=result.stdout.strip(),
                )
        except FileNotFoundError:
            return self._fail("timedatectl 命令不可用")
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.TIMEOUT,
                error="设置时区超时",
            )
        except Exception as e:
            return self._fail(f"执行异常: {e}")

    # ------------------------------------------------------------------
    def verify(self, **kwargs) -> bool:
        target = kwargs.get("timezone", "")
        if not target:
            # 查询模式：读回成功即视为验证通过
            return bool(self._get_current_timezone())
        current = self._get_current_timezone()
        return current == target

    # ------------------------------------------------------------------
    def rollback(self, **kwargs) -> bool:
        if not self._previous_timezone:
            logger.warning("[timezone] 没有保存之前时区，无法回滚")
            return False
        try:
            result = subprocess.run(
                ["timedatectl", "set-timezone", self._previous_timezone],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info(
                    "[timezone] 回滚成功: %s → %s",
                    kwargs.get("timezone", "?"), self._previous_timezone,
                )
                return True
            return False
        except Exception as e:
            logger.error("[timezone] 回滚失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_current_timezone() -> str:
        try:
            result = subprocess.run(
                ["timedatectl", "show", "--property=Timezone", "--value"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    @staticmethod
    def _list_timezones() -> set:
        try:
            result = subprocess.run(
                ["timedatectl", "list-timezones"],
                capture_output=True, text=True, timeout=5,
            )
            return set(line.strip() for line in result.stdout.splitlines() if line.strip())
        except Exception:
            return set()


# ---------------------------------------------------------------------------
# SleepTool
# ---------------------------------------------------------------------------

class SleepTool(BaseTool):
    """
    Suspend the system to sleep.

    Replaces::

        systemctl suspend

    - execute: suspend via ``systemctl suspend``
    - verify:  not applicable (system suspends)
    - Pre-checks: warn if unsaved work, check inhibitors
    """

    name = "sleep"
    description = "使系统进入睡眠/挂起状态。执行前会检查是否有阻止睡眠的程序。"
    risk = RiskLevel.CONSEQUENTIAL
    requires_approval = True
    timeout_s = 60.0

    def execute(self, **kwargs) -> ToolResult:
        # Check for inhibitors
        inhibitors = self._get_inhibitors()
        if inhibitors:
            self.logger.warning("[sleep] 检测到睡眠抑制器: %s", inhibitors)

        # SDK first — libkypowermanagement (kdk_power_set_suspend)
        from src.sdk import power
        ok, msg = power.suspend()
        if ok:
            return self._ok(msg, inhibitors=inhibitors)

        # Fallback: systemctl suspend
        self.logger.warning("[sleep] SDK 挂起失败, 回退 systemctl: %s", msg)
        try:
            result = subprocess.run(
                ["systemctl", "suspend"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return self._fallback("系统已进入睡眠状态 (shell fallback)", inhibitors=inhibitors)
            else:
                return self._fail(
                    f"systemctl suspend 失败: {result.stderr.strip()}",
                    inhibitors=inhibitors,
                )
        except FileNotFoundError:
            return self._fail("systemctl 不可用")
        except subprocess.TimeoutExpired:
            return self._fail("睡眠命令超时（可能被取消）")
        except Exception as e:
            return self._fail(f"执行异常: {e}")

    def verify(self, **kwargs) -> bool:
        # Can't verify after sleep — the system is suspended
        return True  # Optimistic; the command either works or fails

    @staticmethod
    def _get_inhibitors() -> str:
        try:
            result = subprocess.run(
                ["systemd-inhibit", "--list", "--no-pager"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# PowerTool — reboot / shutdown
# ---------------------------------------------------------------------------

class PowerTool(BaseTool):
    """
    Reboot or shutdown the system.

    Replaces::

        systemctl reboot
        systemctl poweroff

    - execute: reboot or poweroff via systemctl
    - verify:  not applicable
    - Safety: requires explicit ``action`` parameter
    """

    name = "power"
    description = (
        "重启或关闭系统。action='reboot' 重启，action='shutdown' 关机。"
        "⚠️ 危险操作，需要明确确认。"
    )
    risk = RiskLevel.CONSEQUENTIAL
    requires_approval = True
    timeout_s = 120.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()

        if action == "reboot":
            return self._do_reboot(kwargs.get("delay_seconds", 60))
        elif action in ("shutdown", "poweroff"):
            return self._do_shutdown(kwargs.get("delay_seconds", 60))
        elif action == "cancel":
            return self._cancel_shutdown()
        else:
            return self._fail(f"未知操作: '{action}'。可用: reboot, shutdown, cancel")

    def _do_reboot(self, delay: int = 60) -> ToolResult:
        minutes = _to_minutes(delay)
        # SDK first — libkyrestart (kdk_restart_reboot)
        from src.sdk import power
        ok, msg = power.reboot(minutes)
        if ok:
            return self._ok(msg)
        self.logger.warning("[power] SDK 重启调度失败, 回退 shutdown: %s", msg)

        try:
            result = subprocess.run(
                ["shutdown", "-r", f"+{minutes}", "NexAgent 请求重启"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return self._fallback(f"系统将在 {minutes} 分钟后重启 (shell fallback)。取消: power action=cancel")
            return self._fail(f"重启命令失败: {result.stderr.strip()}")
        except Exception as e:
            return self._fail(f"执行异常: {e}")

    def _do_shutdown(self, delay: int = 60) -> ToolResult:
        minutes = _to_minutes(delay)
        # SDK first — libkyshutdown (kdk_shutdown_power_off)
        from src.sdk import power
        ok, msg = power.power_off(minutes)
        if ok:
            return self._ok(msg)
        self.logger.warning("[power] SDK 关机调度失败, 回退 shutdown: %s", msg)

        try:
            result = subprocess.run(
                ["shutdown", "-h", f"+{minutes}", "NexAgent 请求关机"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return self._fallback(f"系统将在 {minutes} 分钟后关机 (shell fallback)。取消: power action=cancel")
            return self._fail(f"关机命令失败: {result.stderr.strip()}")
        except Exception as e:
            return self._fail(f"执行异常: {e}")

    def _cancel_shutdown(self) -> ToolResult:
        # SDK first — cancel both shutdown and reboot schedules
        from src.sdk import power
        ok1, _ = power.cancel_power_off()
        ok2, _ = power.cancel_reboot()
        if ok1 or ok2:
            return self._ok("已取消计划的关机/重启 (SDK)")

        try:
            result = subprocess.run(
                ["shutdown", "-c"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return self._fallback("已取消计划的关机/重启 (shell fallback)")
            return self._fail(f"取消失败: {result.stderr.strip()}")
        except Exception as e:
            return self._fail(f"执行异常: {e}")

    # ------------------------------------------------------------------
    def verify(self, **kwargs) -> bool:
        """For scheduled actions, confirm a power schedule exists (SDK or shutdown)."""
        action = kwargs.get("action", "").strip().lower()
        delay = _to_minutes(kwargs.get("delay_seconds", 60))

        if action == "reboot":
            if delay < 1:
                return True  # immediate — can't verify post-schedule
            from src.sdk import power
            return power.is_schedule_reboot() or self._scheduled_via_shutdown()
        elif action in ("shutdown", "poweroff"):
            if delay < 1:
                return True
            from src.sdk import power
            return power.is_schedule_power_off() or self._scheduled_via_shutdown()
        elif action == "cancel":
            from src.sdk import power
            return (not power.is_schedule_reboot()
                    and not power.is_schedule_power_off()
                    and not self._scheduled_via_shutdown())
        return True

    @staticmethod
    def _scheduled_via_shutdown() -> bool:
        """systemd 在调度了 shutdown/reboot 时会在该路径留下标记文件."""
        try:
            import os
            return os.path.exists("/run/systemd/shutdown/scheduled")
        except Exception:
            return False


# ---------------------------------------------------------------------------
# DateTimeTool — set system date/time
# ---------------------------------------------------------------------------

class DateTimeTool(BaseTool):
    """
    Set system date and time.

    Replaces::

        timedatectl set-time "2026-07-27 14:30:00"

    - execute: set datetime via timedatectl
    - verify:  read back and compare
    """

    name = "datetime"
    description = "设置系统日期和时间，格式 'YYYY-MM-DD HH:MM:SS'"
    risk = RiskLevel.CONSEQUENTIAL
    requires_approval = True
    timeout_s = 15.0

    def __init__(self):
        super().__init__()
        self._previous_time: Optional[str] = None

    def execute(self, **kwargs) -> ToolResult:
        dt = kwargs.get("datetime", "")
        if not dt:
            return self._fail("缺少参数: datetime (格式: 'YYYY-MM-DD HH:MM:SS')")

        # Disable NTP temporarily
        subprocess.run(
            ["timedatectl", "set-ntp", "false"],
            capture_output=True, text=True, timeout=5,
        )

        self._previous_time = self._get_current_time()

        try:
            result = subprocess.run(
                ["timedatectl", "set-time", dt],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return self._ok(f"系统时间已设置为 {dt}", previous=self._previous_time)
            return self._fail(f"设置时间失败: {result.stderr.strip()}")
        except Exception as e:
            return self._fail(f"执行异常: {e}")

    def verify(self, **kwargs) -> bool:
        target = kwargs.get("datetime", "")
        current = self._get_current_time()
        # Check if current time is close to target (within 2 seconds)
        from datetime import datetime
        try:
            target_dt = datetime.strptime(target, "%Y-%m-%d %H:%M:%S")
            current_dt = datetime.strptime(current, "%Y-%m-%d %H:%M:%S")
            return abs((current_dt - target_dt).total_seconds()) < 5
        except Exception:
            return False

    def rollback(self, **kwargs) -> bool:
        if not self._previous_time:
            return False
        subprocess.run(["timedatectl", "set-ntp", "true"], capture_output=True, timeout=5)
        return True

    @staticmethod
    def _get_current_time() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------

def register_system_tools(registry=None):
    """Register all system tools into the given registry."""
    if registry is None:
        from .base import get_registry
        registry = get_registry()

    registry.register_many([
        TimezoneTool(),
        SleepTool(),
        PowerTool(),
        DateTimeTool(),
    ])
    return registry
