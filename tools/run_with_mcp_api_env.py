from __future__ import annotations

import os
import sys
from pathlib import Path


ALLOWED_VARIABLES = ("DS_API_KEY", "DS_API_BASE", "DS_API_MODEL")
PROCESS_MARKERS = (
    "mcp_host.py",
    "uvicorn mcp_server.mcp_host",
)


def _mcp_environment() -> dict[str, str]:
    proc = Path("/proc")
    if not proc.exists():
        raise RuntimeError("/proc is not available")
    for entry in sorted(
        (path for path in proc.iterdir() if path.name.isdigit()),
        key=lambda path: int(path.name),
        reverse=True,
    ):
        try:
            command = (entry / "cmdline").read_bytes().replace(
                b"\0",
                b" ",
            ).decode("utf-8", errors="replace")
            if not any(marker in command for marker in PROCESS_MARKERS):
                continue
            values = {}
            for raw in (entry / "environ").read_bytes().split(b"\0"):
                if b"=" not in raw:
                    continue
                name, value = raw.split(b"=", 1)
                decoded_name = name.decode("utf-8", errors="ignore")
                if decoded_name in ALLOWED_VARIABLES:
                    values[decoded_name] = value.decode(
                        "utf-8",
                        errors="strict",
                    )
            if values.get("DS_API_KEY"):
                return values
        except (OSError, UnicodeDecodeError):
            continue
    raise RuntimeError("MCP Host DS_API_KEY environment was not found")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: run_with_mcp_api_env.py SCRIPT [SCRIPT_ARGS...]"
        )
    environment = dict(os.environ)
    values = _mcp_environment()
    environment.update(values)
    environment.setdefault("DS_API_BASE", "https://api.deepseek.com/v1")
    environment.setdefault("DS_API_MODEL", "deepseek-chat")
    print(
        "MCP API environment acquired: "
        + ", ".join(
            f"{name}=configured"
            for name in ALLOWED_VARIABLES
            if environment.get(name)
        ),
        flush=True,
    )
    script = str(Path(sys.argv[1]).resolve())
    os.execve(
        sys.executable,
        [sys.executable, script, *sys.argv[2:]],
        environment,
    )


if __name__ == "__main__":
    main()
