#!/usr/bin/env bash
# webchat 直连启动（监听 0.0.0.0 + token 鉴权）
export WEBCHAT_HOST=0.0.0.0
export WEBCHAT_TOKEN=$(cat /tmp/webchat_token.txt)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
exec .venv/bin/python webchat.py 8080 >> webchat.log 2>&1
