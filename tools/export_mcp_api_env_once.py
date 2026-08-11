from __future__ import annotations

import argparse
import os
from pathlib import Path


ALLOWED_VARIABLES = ("DS_API_KEY", "DS_API_BASE", "DS_API_MODEL")
PROCESS_MARKERS = ("mcp_host.py", "uvicorn mcp_server.mcp_host")


def _authorized_values() -> dict[str, str]:
    for entry in sorted(
        (path for path in Path("/proc").iterdir() if path.name.isdigit()),
        key=lambda path: int(path.name),
        reverse=True,
    ):
        try:
            command = (entry / "cmdline").read_bytes().replace(
                b"\0", b" "
            ).decode("utf-8", errors="replace")
            if not any(marker in command for marker in PROCESS_MARKERS):
                continue
            values = {}
            for raw in (entry / "environ").read_bytes().split(b"\0"):
                if b"=" not in raw:
                    continue
                name, value = raw.split(b"=", 1)
                decoded = name.decode("utf-8", errors="ignore")
                if decoded not in ALLOWED_VARIABLES:
                    continue
                text = value.decode("utf-8", errors="strict")
                if not text or "\n" in text or "\r" in text or "\0" in text:
                    raise RuntimeError("invalid_authorized_environment_value")
                values[decoded] = text
            if values.get("DS_API_KEY"):
                return values
        except (OSError, UnicodeDecodeError):
            continue
    raise RuntimeError("authorized_mcp_api_environment_not_found")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    values = _authorized_values()
    payload = "".join(
        f"{name}={values[name]}\n"
        for name in ALLOWED_VARIABLES
        if values.get(name)
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(args.target, flags, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(
        "Protected API environment created with: "
        + ", ".join(name for name in ALLOWED_VARIABLES if values.get(name))
    )


if __name__ == "__main__":
    main()
