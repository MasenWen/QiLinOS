#!/usr/bin/env bash
# 不依赖 systemd 直接运行本项目（webchat + 可选 GitHub webhook 自动更新）
#
#   bash deploy/webchat-direct.sh start          # 启动 webchat（后台，读环境文件、写自己的 PID/日志）
#   bash deploy/webchat-direct.sh stop           # 停止 webchat
#   bash deploy/webchat-direct.sh restart        # 重启 webchat
#   bash deploy/webchat-direct.sh status         # 状态（PID/端口/HTTP/页面版本/systemd 残留检查）
#   bash deploy/webchat-direct.sh logs [N]       # webchat 最近 N 行日志（默认 40）
#
#   bash deploy/webchat-direct.sh start-webhook  # 直接启动 GitHub webhook（push 到 dev1 自动更新）
#   bash deploy/webchat-direct.sh stop-webhook   # 停止 webhook
#   bash deploy/webchat-direct.sh webhook-logs [N]
#
# 环境变量文件：
#   webchat : $HOME/.nex-agent/webchat.env   （严格引擎 + LLM 密钥）
#   webhook : $HOME/.nex-agent/webhook.env   （WEBHOOK_SECRET）
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
WH_ENV_FILE="${WH_ENV_FILE:-$HOME/.nex-agent/webhook.env}"
WH_PID_FILE="${WH_PID_FILE:-$HOME/.local/state/webhook.pid}"
WH_LOG_FILE="${WH_LOG_FILE:-$HOME/.local/state/webhook-direct.log}"
WH_PORT="${WH_PORT:-9000}"
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

wh_running() {
  [ -f "$WH_PID_FILE" ] || return 1
  local p; p="$(cat "$WH_PID_FILE" 2>/dev/null || true)"
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}

do_start_webhook() {
  if wh_running; then say "webhook 已在运行（PID $(cat "$WH_PID_FILE")）"; return 0; fi
  if ss -ltn 2>/dev/null | grep -q ":${WH_PORT} "; then
    say "✗ 端口 $WH_PORT 已被占用（很可能是 systemd 的 webhook 实例）：先 sudo systemctl stop webhook.service"
    return 1
  fi
  if [ -f "$WH_ENV_FILE" ]; then
    set -a; . "$WH_ENV_FILE"; set +a
    [ -n "${WEBHOOK_SECRET:-}" ] || say "⚠ $WH_ENV_FILE 里没有 WEBHOOK_SECRET，签名校验会失败"
  else
    say "✗ 缺少 $WH_ENV_FILE（需要 WEBHOOK_SECRET=…）"; return 1
  fi
  nohup /usr/bin/python3 "$PROJ_DIR/deploy/webhook_server.py" "$WH_PORT" "$WEBHOOK_SECRET" "$PROJ_DIR" \
    >> "$WH_LOG_FILE" 2>&1 &
  echo $! > "$WH_PID_FILE"
  sleep 1
  if wh_running; then
    say "webhook 已启动（PID $(cat "$WH_PID_FILE")，端口 $WH_PORT，日志 $WH_LOG_FILE）"
    say "push 到 dev1 分支会自动执行 deploy/update.sh（已适配"直接运行"模式）"
  else
    say "✗ webhook 启动失败，日志尾部："; tail -10 "$WH_LOG_FILE" 2>/dev/null; return 1
  fi
}

do_stop_webhook() {
  if wh_running; then
    local p; p="$(cat "$WH_PID_FILE")"; kill "$p" 2>/dev/null
    for i in $(seq 1 10); do sleep 1; kill -0 "$p" 2>/dev/null || break; done
    kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null
    rm -f "$WH_PID_FILE"; say "webhook 已停止（PID $p）"
  else
    rm -f "$WH_PID_FILE"
    if pkill -f 'webhook_server[.]py' 2>/dev/null; then say "webhook 已按进程名停止"; else say "webhook 未在运行"; fi
  fi
}

do_status_all() {
  say "webhook：$(wh_running && echo "运行中 PID $(cat "$WH_PID_FILE")" || echo 未运行)  端口 $WH_PORT $(ss -ltn 2>/dev/null | grep -q ":$WH_PORT " && echo 占用 || echo 空闲)"
  local ru
  ru="$(systemctl list-unit-files 2>/dev/null | grep -ciE '^(webchat|webhook)\.service')" || ru=0
  say "systemd 残留单元：${ru:-0} 个（0 = 已彻底脱离 systemd）"
}

case "${1:-start}" in
  start-webhook)  do_start_webhook ;;
  stop-webhook)   do_stop_webhook ;;
  webhook-logs)   tail -n "${2:-40}" "$WH_LOG_FILE" ;;
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; do_start ;;
  status)  do_status; do_status_all ;;
  logs)    tail -n "${2:-40}" "$LOG_FILE" ;;
  *)       echo "用法: $0 {start|stop|restart|status|logs [N]|start-webhook|stop-webhook|webhook-logs [N]}"; exit 2 ;;
esac
