
import os
import sys
import subprocess


def main() -> int:
    cmd = [
        sys.executable, "-m", "uvicorn",
        "mcp_server.mcp_host:app",
        "--host", os.environ.get("UVICORN_HOST", "0.0.0.0"),
        "--port", os.environ.get("UVICORN_PORT", "50066"),
    ]
    print("Running:", " ".join(cmd))
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        print("Error: Python executable not found.", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
