#!/bin/bash
# OS-Agent 一键更新脚本
# 用法: bash deploy/update.sh
# 功能: git pull → 检测 requirements 变更并重装依赖 → 重启 webchat
# 安全: --ff-only 快进合并，冲突时中止不破坏现场

set -e
cd "$(dirname "$0")/.."

echo "=== OS-Agent 更新开始 ==="
OLD=$(git rev-parse HEAD 2>/dev/null || echo "无")

# 1. 拉取最新代码（只快进，避免合并破坏）
echo "--- 拉取最新代码 (origin/dev1) ---"
git fetch origin dev1
if git pull --ff-only origin dev1; then
    NEW=$(git rev-parse HEAD)
else
    echo "❌ 更新冲突。当前有本地改动，处理方式："
    echo "   git stash          # 暂存本地改动后重试"
    echo "   git checkout .     # 丢弃本地改动（谨慎）"
    exit 1
fi

if [ "$OLD" = "$NEW" ]; then
    echo "✅ 已是最新版本: ${NEW:0:8}"
    exit 0
fi
echo "更新: ${OLD:0:8} → ${NEW:0:8}"

# 2. 检测依赖变更 → 重装
if git diff "$OLD" "$NEW" -- requirements.txt | grep -qE "^[+-][a-zA-Z]"; then
    echo "--- requirements.txt 有变更，重装依赖 ---"
    .venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 30 --retries 2
else
    echo "--- 依赖无变更，跳过安装 ---"
fi

# 3. 重启服务
echo "--- 重启 webchat ---"
if systemctl list-unit-files 2>/dev/null | grep -q webchat; then
    sudo systemctl restart webchat
    sleep 5
    systemctl is-active webchat && echo "✅ webchat 已重启（新版 ${NEW:0:8}）"
else
    pkill -f "webchat.py 8080" 2>/dev/null || true
    sleep 1
    nohup .venv/bin/python webchat.py 8080 > webchat.log 2>&1 &
    echo "✅ webchat 已重启（手动模式，新版 ${NEW:0:8}）"
fi

echo "=== 更新完成 ==="
