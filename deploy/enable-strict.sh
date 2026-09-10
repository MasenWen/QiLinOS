#!/usr/bin/env bash
# 一条命令：更新仓库 → 打开严格记忆引擎(strict) → 重启 → 自检
#
#   bash deploy/enable-strict.sh              # 只设置 strict + 重启 + 自检
#   bash deploy/enable-strict.sh --pull       # 先 git pull dev1，再设置 strict（最常用）
#   bash deploy/enable-strict.sh --check      # 只体检，不改动
#   bash deploy/enable-strict.sh --off        # 关闭 strict（回到 mem0/四层模式）
#
# 原理：决定走 strict 还是 mem0 的唯一开关，是【服务进程】里的环境变量
#   NEX_STRICT_ENGINE=1（不设置 = 默认关闭）。
# 项目已脱离 systemd，所以变量写在 ~/.nex-agent/webchat.env，由
# deploy/webchat-direct.sh 启动时加载；若本机仍在用 systemd，则自动写 drop-in。
set -uo pipefail

PROJ_DIR="${PROJ_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$HOME/.nex-agent/webchat.env}"
PORT="${PORT:-8080}"
SVC="${SVC:-webchat.service}"
BRANCH="${BRANCH:-dev1}"
PID_FILE="${PID_FILE:-$HOME/.local/state/webchat.pid}"
LOG_FILE="${LOG_FILE:-$HOME/.local/state/webchat-direct.log}"
TARGET=1
MODE="set"

while [ $# -gt 0 ]; do
  case "$1" in
    --pull) MODE="pull"; shift ;;
    --check) MODE="check"; shift ;;
    --off) TARGET=0; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
done

say() { printf '[strict] %s\n' "$*"; }
die() { printf '[strict] ✗ %s\n' "$*" >&2; exit 1; }
cd "$PROJ_DIR" || die "目录不存在：$PROJ_DIR"

# ---------- 1) 可选：更新仓库 ----------
if [ "$MODE" = "pull" ]; then
  say "更新仓库：git pull --ff-only origin $BRANCH"
  cur="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  [ "$cur" = "$BRANCH" ] || git checkout "$BRANCH" || die "切到 $BRANCH 失败（本地有改动？先 git stash）"
  git fetch origin "$BRANCH" || die "git fetch 失败"
  before="$(git rev-parse --short HEAD)"
  git pull --ff-only origin "$BRANCH" || die "git pull 失败（处理冲突/先 stash）"
  after="$(git rev-parse --short HEAD)"
  [ "$before" = "$after" ] && say "仓库已是最新：$after" || say "仓库更新：$before → $after"
fi
say "当前提交：$(git log --oneline -1 | cat)"

# ---------- 2) 写入 / 关闭 开关 ----------
current_env() {
  [ -f "$ENV_FILE" ] && grep -E '^NEX_STRICT_ENGINE=' "$ENV_FILE" 2>/dev/null | tail -1 || true
}
if [ "$MODE" = "check" ]; then
  say "体检模式：不改动任何文件"
else
  mkdir -p "$(dirname "$ENV_FILE")"
  if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$ENV_FILE.bak_$(date +%Y%m%d_%H%M%S)"
    if grep -q '^NEX_STRICT_ENGINE=' "$ENV_FILE"; then
      sed -i "s/^NEX_STRICT_ENGINE=.*/NEX_STRICT_ENGINE=$TARGET/" "$ENV_FILE"
    else
      echo "NEX_STRICT_ENGINE=$TARGET" >> "$ENV_FILE"
    fi
  else
    umask 077
    {
      echo "NEX_STRICT_ENGINE=$TARGET"
      echo "# 还需要补上 LLM 密钥，否则对话会报错："
      echo "NEX_DEEPSEEK_API_KEY="
    } > "$ENV_FILE"
    say "⚠ 新建了 $ENV_FILE —— 请补上 NEX_DEEPSEEK_API_KEY（可从服务器 scp 过来）"
  fi
  chmod 600 "$ENV_FILE"
  # 仍在使用 systemd 的环境：顺手写 drop-in（单元不存在时跳过）
  if command -v systemctl >/dev/null 2>&1 && systemctl cat "$SVC" >/dev/null 2>&1; then
    sudo -n mkdir -p "/etc/systemd/system/${SVC}.d" 2>/dev/null && \
      printf '[Service]\nEnvironment=NEX_STRICT_ENGINE=%s\n' "$TARGET" \
      | sudo -n tee "/etc/systemd/system/${SVC}.d/strict.conf" >/dev/null 2>&1 \
      && sudo -n systemctl daemon-reload 2>/dev/null && say "已写 systemd drop-in: strict.conf"
  fi
  say "环境文件 $ENV_FILE → $(current_env)"
fi

# ---------- 3) 重启（直跑优先，systemd 兜底） ----------
running_direct() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; }
if [ "$MODE" != "check" ]; then
  if [ -x deploy/webchat-direct.sh ] && { running_direct || ! systemctl is-active --quiet "$SVC" 2>/dev/null; }; then
    say "重启（直跑模式）：bash deploy/webchat-direct.sh restart"
    bash deploy/webchat-direct.sh restart | tail -4
  elif command -v systemctl >/dev/null 2>&1 && systemctl cat "$SVC" >/dev/null 2>&1; then
    say "重启（systemd）：sudo systemctl restart $SVC"
    sudo -n systemctl restart "$SVC" || die "重启失败"
    for i in $(seq 1 30); do sleep 1; [ "$(curl -s -m 2 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" || echo 000)" = "200" ] && break; done
  else
    die "既没有直跑进程也没有 systemd 单元，无法重启（请先 deploy/webchat-direct.sh start）"
  fi
fi

# ---------- 4) 自检 ----------
say "—— 自检 ——"
fail=0
code="$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null || echo 000)"
[ "$code" = "200" ] && say "✓ HTTP 200" || { say "✗ HTTP $code"; fail=1; }

PID="$(pgrep -f 'webchat[.]py' | head -1)"
if [ -n "$PID" ]; then
  got="$(sudo -n tr '\0' '\n' < "/proc/$PID/environ" 2>/dev/null | grep '^NEX_STRICT_ENGINE=' || tr '\0' '\n' < "/proc/$PID/environ" 2>/dev/null | grep '^NEX_STRICT_ENGINE=' || true)"
  if [ -n "$got" ]; then say "✓ 进程环境：$got （PID $PID）"; else say "✗ 进程环境里没有 NEX_STRICT_ENGINE（PID $PID）"; fail=1; fi
else
  say "✗ 找不到 webchat 进程"; fail=1
fi

if grep -aq 'strict 引擎已启用' "$LOG_FILE" 2>/dev/null; then
  say "✓ 启动日志：strict 引擎已启用"
else
  say "⚠ 日志里没有「strict 引擎已启用」（引擎可能初始化失败，看日志里有无「记忆引擎初始化失败」）"
  grep -a '记忆引擎初始化失败' "$LOG_FILE" 2>/dev/null | tail -1 | sed 's/^/   /'
  fail=1
fi

if curl -s -m 5 "http://127.0.0.1:$PORT/api/memories" 2>/dev/null | grep -q 'updated_at'; then
  say "✓ 面板 API 走 strict 分支（含 updated_at/version → 会显示「记录时间」）"
else
  say "✗ 面板 API 没有 updated_at → 说明还在 mem0 分支"; fail=1
fi

if [ "$fail" = "0" ]; then
  say "完成：当前为 strict 模式。浏览器请 Ctrl+Shift+R 强制刷新。"
else
  say "未完全通过，请把上面 ✗/⚠ 的内容连同日志一起发我。"
fi
exit $fail
