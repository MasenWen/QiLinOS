#!/usr/bin/env bash
# 一条命令把本机 webchat 更新到最新：拉 dev1 → 重启服务 → 自检 → 打印版本
#
# 用法：
#   bash deploy/update.sh                 # 默认分支 dev1、服务 webchat.service、端口 8080
#   BRANCH=dev1 SVC=webchat.service PORT=8080 bash deploy/update.sh
#   SKIP_PULL=1 bash deploy/update.sh     # 只重启+自检，不拉代码
#
# 退出码：0=更新成功且服务健康；1=拉取/重启/健康检查失败（会打印排查命令）
set -uo pipefail

PROJ_DIR="${PROJ_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BRANCH="${BRANCH:-dev1}"
SVC="${SVC:-webchat.service}"
PORT="${PORT:-8080}"
URL="http://127.0.0.1:${PORT}/"
WAIT_SECS="${WAIT_SECS:-40}"

say() { printf '[update] %s\n' "$*"; }
die() { printf '[update] ✗ %s\n' "$*" >&2; exit 1; }

cd "$PROJ_DIR" || die "项目目录不存在：$PROJ_DIR"
command -v git >/dev/null || die "缺少 git"

say "项目目录：$PROJ_DIR"

# ---------- 1) 拉取最新代码 ----------
if [ "${SKIP_PULL:-0}" = "1" ]; then
  say "跳过拉取（SKIP_PULL=1）"
else
  cur="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  say "当前分支：$cur"
  if [ "$cur" != "$BRANCH" ]; then
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git checkout "$BRANCH" || die "切到 $BRANCH 失败（本地有改动？先 git stash）"
    else
      git checkout -b "$BRANCH" "origin/$BRANCH" || die "创建 $BRANCH 失败"
    fi
  fi
  git fetch origin "$BRANCH" || die "git fetch 失败（网络/权限？）"
  before="$(git rev-parse --short HEAD)"
  if ! git pull --ff-only "origin" "$BRANCH"; then
    die "git pull 失败（本地有改动或历史分叉，先 git stash / 处理冲突）"
  fi
  after="$(git rev-parse --short HEAD)"
  [ "$before" = "$after" ] && say "已是最新：$after" || say "更新：$before → $after"
fi
say "当前提交：$(git log --oneline -1 | cat)"

# ---------- 2) 重启服务（systemctl 优先，kill 兜底） ----------
restarted=0
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q "^${SVC}"; then
  if sudo -n systemctl restart "$SVC" 2>/dev/null; then
    say "已重启：sudo systemctl restart $SVC"
    restarted=1
  else
    say "sudo 免密不可用，尝试 systemctl --user / kill 兜底"
  fi
fi
if [ "$restarted" = "0" ]; then
  # Restart=always 时，杀掉主进程 systemd 会自动拉起（等价重启）
  pkill -f 'webchat[.]py' 2>/dev/null && say "已发送 TERM，等待 systemd 自动拉起" \
    || die "没找到 webchat 进程，也没法重启服务；请手动确认服务名（SVC=…）"
fi

# ---------- 3) 健康检查（轮询到就绪） ----------
code="000"
for i in $(seq 1 "$WAIT_SECS"); do
  sleep 1
  code="$(curl -s -m 2 -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null || echo 000)"
  [ "$code" = "200" ] && break
done
if [ "$code" != "200" ]; then
  say "✗ 服务未就绪（HTTP $code），最近日志："
  journalctl -u "$SVC" -n 20 --no-pager 2>/dev/null | tail -20
  tail -20 "$PROJ_DIR/webchat.log" 2>/dev/null
  die "健康检查失败"
fi
say "服务健康：HTTP 200（$URL）"

# ---------- 4) 关键特性自检 + 版本 ----------
page="$(curl -s -m 5 "$URL" 2>/dev/null || true)"
ver="$(printf '%s' "$page" | grep -o 'v[0-9a-f]\{7,40\} · [0-9-]* [0-9:]*' | head -1)"
[ -n "$ver" ] && say "页面版本：$ver" || say "页面未包含版本徽标（可能是旧代码）"
printf '%s' "$page" | grep -q 'id="clearAll"' && say "✓ 含「清空全部对话」按钮" || say "✗ 缺「清空全部对话」按钮（旧代码？）"
printf '%s' "$page" | grep -q '记录时间' && say "✓ 面板含记录时间/版本行" || say "✗ 面板缺记录时间行（旧代码？）"
say "完成。浏览器请按 Ctrl+Shift+R 强制刷新。"
