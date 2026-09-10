#!/usr/bin/env bash
# 不依赖 systemd 直接运行 webchat（适合"直接打开"、调试、录制）
#
#   bash deploy/webchat-direct.sh start      # 直接后台启动（读环境文件、写自己的日志与 PID）
#   bash deploy/webchat-direct.sh stop       # 停止
#   bash deploy/webchat-direct.sh restart    # 重启
#   bash deploy/webchat-direct.sh status     # 看状态（PID/端口/HTTP/版本徽标）
#   bash deploy/webchat-direct.sh logs [N]   # 看最近 N 行日志（默认 40）
#
# 与 systemd 的关系：
#   · 启动前会检查端口占用：若 systemd 实例还在跑，会提示先 `sudo systemctl stop webchat.service`；
#   · 想彻底摆脱 systemd（可逆）：`sudo systemctl disable --now webchat.service`
#   · 想彻底删除单元（不可逆，需要时按注释重建）：
#       sudo rm /etc/systemd/system/webchat.service
#       sudo rm -rf /etc/systemd/system/webchat.service.d
#       sudo systemctl daemon-reload && sudo systemctl reset-failed
#
# 环境变量文件（NEX_STRICT_ENGINE / NEX_DEEPSEEK_API_KEY / …）：
#   默认 $HOME/.nex-agent/webchat.env，权限 600；没有它不会启用严格记忆引擎，
#   面板会显示成 mem0 那套内容，容易被误判为"没更新"。
set -uo pipefail

PROJ_DIR="${PROJ_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PORT="${PORT:-8080}"
ENV_FILE="${ENV_FILE:-$HOME/.nex-agent/webchat.env}"
PID_FILE="${PID_FILE:-$HOME/.local/state/webchat.pid}"
LOG_FILE="${LOG_FILE:-$HOME/.local/state/webchat-direct.log}"
PY="$PROJ_DIR/.venv/bin/python"
URL="http://127.0.0.1:${PORT}/"

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"
say() { printf '[direct] %s\n' "$*"; }

pid_running() {
  [ -f "$PID_FILE" ] || return 1
  local p; p="$(cat "$PID_FILE" 2>/dev/null || true)"
  [ -n "$p" ] || return 1
  kill -0 "$p" 2>/dev/null
}

port_busy() { ss -ltn 2>/dev/null | grep -q "127.0.0.1:${PORT} "; }

wait_ready() {
  local code="000" i
  for i in $(seq 1 "${WAIT_SECS:-40}"); do
    sleep 1
    code="$(curl -s -m 2 -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null || echo 000)"
    [ "$code" = "200" ] && { say "服务健康：HTTP 200（$URL）"; return 0; }
  done
  say "✗ 未就绪（HTTP $code），日志尾部："
  tail -20 "$LOG_FILE" 2>/dev/null
  return 1
}

do_start() {
  if pid_running; then say "已在运行（PID $(cat "$PID_FILE")）"; return 0; fi
  if port_busy; then
    say "✗ 端口 $PORT 已被占用（很可能是 systemd 实例）：先执行 sudo systemctl stop webchat.service"
    return 1
  fi
  [ -x "$PY" ] || { say "✗ 找不到解释器：$PY"; return 1; }
  if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
    say "已加载环境文件：$ENV_FILE"
  else
    say "⚠ 缺少环境文件 $ENV_FILE —— 严格记忆引擎/密钥不会注入（面板内容会不一样）"
  fi
  cd "$PROJ_DIR" || return 1
  nohup "$PY" webchat.py "$PORT" >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  say "已启动（直接运行，无 systemd）：PID $(cat "$PID_FILE")"
  say "日志：$LOG_FILE  ｜ 停止：bash deploy/webchat-direct.sh stop"
  wait_ready
}

do_stop() {
  if pid_running; then
    local p; p="$(cat "$PID_FILE")"
    kill "$p" 2>/dev/null
    for i in $(seq 1 15); do sleep 1; kill -0 "$p" 2>/dev/null || break; done
    kill -0 "$p" 2>/dev/null && { say "优雅退出超时，强制 kill -9"; kill -9 "$p" 2>/dev/null; }
    rm -f "$PID_FILE"
    say "已停止（PID $p）"
  else
    rm -f "$PID_FILE"
    if pkill -f 'webchat[.]py' 2>/dev/null; then say "已按进程名停止（无 PID 文件）"; else say "没有在运行"; fi
  fi
}

do_status() {
  if pid_running; then say "运行中：PID $(cat "$PID_FILE")"; else say "未运行（PID 文件：$( [ -f "$PID_FILE" ] && echo 存在 || echo 不存在 )）"; fi
  say "端口 $PORT 占用：$(port_busy && echo 是 || echo 否)"
  local code; code="$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null || echo 000)"
  say "HTTP：$code"
  local ver; ver="$(curl -s -m 5 "$URL" 2>/dev/null | tr '\n' ' ' | grep -o 'v[0-9a-f]\{7,40\} · [0-9-]* [0-9:]*' | head -1)"
  [ -n "$ver" ] && say "页面版本：$ver"
  local en ac
  en="$(systemctl is-enabled webchat.service 2>/dev/null)" || en="未知/未启用"
  ac="$(systemctl is-active webchat.service 2>/dev/null)" || ac="inactive"
  say "systemd 单元：$en / $ac"
}

case "${1:-start}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; do_start ;;
  status)  do_status ;;
  logs)    tail -n "${2:-40}" "$LOG_FILE" ;;
  *)       echo "用法: $0 {start|stop|restart|status|logs [N]}"; exit 2 ;;
esac
