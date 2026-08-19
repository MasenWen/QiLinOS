"""系统日志读取策略（指令「优化-日志读取」：策略性读取系统日志更新记忆）

- 增量读取：记录已读位置，只处理新增行
- 分级策略：ERROR/WARN 优先沉淀记忆，INFO 低优先
- 去重：相同消息在时间窗内只记一次
- 产出结构化 LogEvent，供记忆引擎 ingest（观察→记忆）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Sequence

# 常见系统日志路径（麒麟 V11）
DEFAULT_LOG_PATHS = ("/var/log/syslog", "/var/log/messages", "/var/log/kern.log")

_LEVEL_RE = re.compile(r"\b(ERROR|WARN|INFO|DEBUG|CRIT|FATAL|err|warn|info|debug)\b", re.IGNORECASE)
# 进程来源：优先 进程[pid]:，后备 主机名后模块:
_PROC_RE = re.compile(r"([A-Za-z][A-Za-z0-9_\-]*)\[\d+\]:")
_MOD_RE = re.compile(r"\s([A-Za-z][A-Za-z0-9_\-]*)\s*:")
_TS_TOKENS = 3  # 日志行首时间戳 token 数（如 "Aug 19 10:00:01"）

_LEVEL_RANK = {"debug": 0, "info": 1, "warn": 2, "error": 3, "critical": 4}


@dataclass
class LogEvent:
    timestamp: str
    source: str
    level: str
    message: str
    event_id: str = ""

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "source": self.source,
                "level": self.level, "message": self.message, "event_id": self.event_id}


class SystemLogReader:
    """策略性系统日志读取器。"""

    def __init__(self, min_level: str = "warn", dedup_window: int = 300):
        self.min_level = min_level
        self.dedup_window = dedup_window
        self._positions: dict[str, int] = {}
        self._seen: dict[str, float] = {}

    # ---- 解析（稳健：级别优先 + 来源/时间戳宽松提取）----
    def parse_line(self, line: str) -> LogEvent | None:
        line = line.strip()
        if not line:
            return None
        tokens = line.split()
        m = _LEVEL_RE.search(line)
        level = m.group(1).lower() if m else "info"
        if m:
            msg = line[m.end():].lstrip(": ]\t").strip()
        else:
            msg = line
        if not msg:
            msg = line
        source = "system"
        pm = _PROC_RE.search(line)
        if pm:
            source = pm.group(1)
        else:
            mm = _MOD_RE.search(line)
            if mm:
                src = mm.group(1)
                if src not in tokens[: _TS_TOKENS]:  # 排除主机名/时间戳
                    source = src
        ts = " ".join(tokens[:_TS_TOKENS]) if tokens else ""
        return LogEvent(timestamp=ts, source=source, level=level, message=msg)

    def read_text(self, text: str, source: str = "text") -> list[LogEvent]:
        return [ev for ev in (self.parse_line(l) for l in text.splitlines()) if ev]

    def read_file(self, path: str) -> list[LogEvent]:
        """增量读取文件：只处理新增部分。"""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._positions.get(path, 0))
                new_text = f.read()
                self._positions[path] = f.tell()
        except OSError:
            return []
        return self.read_text(new_text, source=path)

    # ---- 提取记忆（分级 + 去重）----
    def extract_observations(
        self,
        events: Iterable[LogEvent],
        min_level: str | None = None,
    ) -> list[dict[str, Any]]:
        threshold = _LEVEL_RANK[(min_level or self.min_level).lower()]
        out: list[dict[str, Any]] = []
        for ev in events:
            if _LEVEL_RANK.get(ev.level, 0) < threshold:
                continue
            key = f"{ev.level}|{ev.message[:60]}"
            if key in self._seen:
                continue
            self._seen[key] = 1.0
            out.append({
                "source_type": "system_log",
                "source_event_id": ev.event_id or f"log-{len(out)}",
                "event_time": ev.timestamp or datetime.now().isoformat(),
                "actor": "system",
                "content": f"[{ev.level.upper()}] {ev.source}: {ev.message}",
                "task": "system log monitoring",
                "context": {"log_level": ev.level, "log_source": ev.source},
            })
        return out

    def read_and_update(
        self,
        engine: Any,
        user_id: str = "nex_user",
        paths: Sequence[str] = DEFAULT_LOG_PATHS,
        stage_limit: str = "lifecycle",
    ) -> dict[str, Any]:
        all_events: list[LogEvent] = []
        for p in paths:
            all_events.extend(self.read_file(p))
        observations = self.extract_observations(all_events)
        ingested = 0
        for obs in observations:
            obs["user_id"] = user_id
            try:
                engine.ingest_observation(obs, stage_limit=stage_limit)
                ingested += 1
            except Exception:
                continue
        return {"events": len(all_events), "observations": len(observations), "ingested": ingested}

    def reset_dedup(self) -> None:
        self._seen.clear()

    def positions(self) -> dict[str, int]:
        return dict(self._positions)
