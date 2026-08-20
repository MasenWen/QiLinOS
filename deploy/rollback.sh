#!/bin/bash
# OS-Agent 回滚脚本: 回退到指定/上一个版本并重启
# 用法: bash deploy/rollback.sh [提交号]   （缺省回退到上一个提交）
set -e
cd "$(dirname "$0")/.."

CURRENT=$(git rev-parse HEAD)
if [ -n "$1" ]; then
    TARGET=$1
else
    TARGET=$(git rev-parse HEAD~1 2>/dev/null || echo "")
fi
if [ -z "$TARGET" ]; then
    echo "❌ 没有可回退的历史版本"
    exit 1
fi

echo "=== 回滚: ${CURRENT:0:8} → ${TARGET:0:8} ==="
git reset --hard "$TARGET"

echo "--- 重启 webchat ---"
if systemctl list-unit-files 2>/dev/null | grep -q webchat; then
    sudo systemctl restart webchat
else
    pkill -f "webchat.py 8080" 2>/dev/null || true
    sleep 1
    nohup .venv/bin/python webchat.py 8080 > webchat.log 2>&1 &
fi
sleep 5
curl -s -o /dev/null -w "网页状态: %{http_code}\n" --max-time 5 http://127.0.0.1:8080/ || echo "网页未响应"
echo "=== 回滚完成，当前版本: ${TARGET:0:8} ==="
