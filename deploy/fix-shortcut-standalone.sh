#!/bin/bash
# ============================================================
# 麒麟记忆 · 快捷方式独立修复脚本（自包含，不依赖仓库其他文件）
#
# 用途：主机上「桌面图标点了没反应」时，一条命令完成 体检 + 重建快捷方式
#
# 用法（在主机上，用桌面登录用户执行，不要 sudo）：
#   bash fix-shortcut-standalone.sh                 # 自动找项目目录（含 webchat.py）
#   bash fix-shortcut-standalone.sh /path/to/kylin-mem
#   PORT=8080 bash fix-shortcut-standalone.sh       # 指定端口
#   bash fix-shortcut-standalone.sh --check         # 只体检，不写文件
# ============================================================
set -u
PORT="${PORT:-8080}"
URL="http://127.0.0.1:${PORT}/"
CHECK_ONLY=0
PROJ_ARG=""
for a in "$@"; do
  case "$a" in
    --check) CHECK_ONLY=1 ;;
    /*) PROJ_ARG="$a" ;;
  esac
done

G=""; R=""; Y=""; N=""
if command -v tput >/dev/null 2>&1 && [ -t 1 ]; then
  G="$(tput setaf 2)"; R="$(tput setaf 1)"; Y="$(tput setaf 3)"; N="$(tput sgr0)"
fi
ok(){ echo "  ${G}[通过]${N} $*"; }; bad(){ echo "  ${R}[失败]${N} $*"; }
warn(){ echo "  ${Y}[注意]${N} $*"; }; hint(){ echo "         ↳ $*"; }

# ---------- 定位项目目录 ----------
if [ -n "$PROJ_ARG" ]; then PROJ_DIR="$PROJ_ARG"
elif [ -f ./webchat.py ]; then PROJ_DIR="$(pwd)"
else
  PROJ_DIR="$(find "$HOME" -maxdepth 4 -name webchat.py -printf '%h\n' 2>/dev/null | head -1)"
fi
[ -n "${PROJ_DIR:-}" ] && [ -f "$PROJ_DIR/webchat.py" ] || { bad "找不到项目目录（webchat.py）"; hint "把项目路径作为参数传入：bash $0 /path/to/kylin-mem"; exit 1; }

HOME_DIR="$HOME"
DESKTOP_DIR=""
command -v xdg-user-dir >/dev/null 2>&1 && DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null)"
[ -z "$DESKTOP_DIR" ] || [ "$DESKTOP_DIR" = "$HOME_DIR" ] && {
  for c in "$HOME_DIR/桌面" "$HOME_DIR/Desktop"; do [ -d "$c" ] && DESKTOP_DIR="$c" && break; done
}
[ -z "$DESKTOP_DIR" ] && DESKTOP_DIR="$HOME_DIR"

echo "麒麟记忆 · 快捷方式修复  $(date '+%F %T')"
echo "主机 $(hostname) ｜ 用户 $(id -un) ｜ 桌面环境 ${XDG_CURRENT_DESKTOP:-未知}"
echo "项目 $PROJ_DIR ｜ 端口 $PORT ｜ 桌面目录 $DESKTOP_DIR"
echo

echo "① 服务与端口"
systemctl is-active --quiet webchat 2>/dev/null && ok "webchat.service 运行中" || { warn "webchat.service 未运行"; hint "sudo systemctl start webchat"; }
ss -ltn 2>/dev/null | grep -q ":${PORT} " && ok "端口 ${PORT} 监听中" || { bad "端口 ${PORT} 未监听"; hint "journalctl -u webchat -n 50 --no-pager"; }
CODE="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null || echo 000)"
[ "$CODE" = "200" ] && ok "HTTP $URL → 200" || { bad "HTTP $URL → $CODE"; hint "看日志：journalctl -u webchat -n 50 --no-pager ｜ tail -30 $PROJ_DIR/webchat.log"; }
[ -x "$PROJ_DIR/.venv/bin/python" ] && ok "虚拟环境解释器存在（.venv/bin/python）" || { bad "缺少虚拟环境：$PROJ_DIR/.venv/bin/python"; hint "bash deploy/install.sh"; }

echo
echo "② 点击链路：上一次点击有没有真的执行脚本"
LOG="$HOME_DIR/.local/state/kylin-mem-open.log"
if [ -f "$LOG" ]; then
  echo "       最近 3 次执行记录："; tail -3 "$LOG" | sed 's/^/       /'
  echo "       现在时间：$(date '+%F %T')"
  warn "如果上面的时间早于你刚点击的时间 → 说明点击没触发脚本（桌面项/可信标记问题，看 ③）"
  warn "如果有刚点击的记录且写着浏览器相关错误 → 说明系统没有可用浏览器（看 ④）"
else
  warn "还没有日志文件：说明启动器从未被执行过（点击没生效）"
fi

echo
echo "③ 桌面图标与菜单项"
LAUNCHER="$HOME_DIR/.local/bin/kylin-mem-open"
DESK="$DESKTOP_DIR/麒麟记忆.desktop"
APPS="$HOME_DIR/.local/share/applications/kylin-mem.desktop"
[ -f "$DESK" ] && { ok "桌面图标存在"; } || { bad "桌面图标不存在：$DESK"; }
[ -f "$DESK" ] && { [ -x "$DESK" ] && ok "桌面图标可执行" || { bad "桌面图标不可执行"; hint "chmod +x \"$DESK\""; }; }
if [ -f "$DESK" ] && command -v gio >/dev/null 2>&1; then
  gio info "$DESK" 2>/dev/null | grep -qi 'metadata::trusted: true' \
    && ok "已标记可信（可双击）" \
    || { warn "未标记可信：UKUI/peony 会当文本文件，点了没反应"; hint "gio set \"$DESK\" metadata::trusted true ｜ 或右键→允许启动"; }
fi
[ -f "$APPS" ] && ok "应用菜单项存在（开始菜单里也能打开）" || warn "应用菜单项缺失"
[ -x "$LAUNCHER" ] && ok "启动器存在" || warn "启动器缺失（下面会重建）"

echo
echo "④ 浏览器（双击后要靠它显示页面）"
BROWSER=""
for b in firefox chromium chromium-browser kylin-browser google-chrome browser360 qaxbrowser; do
  command -v "$b" >/dev/null 2>&1 && { BROWSER="$b"; ok "发现浏览器：$(command -v "$b")"; }
done
[ -z "$BROWSER" ] && { bad "系统里没有任何可用图形浏览器"; hint "sudo apt update && sudo apt install -y firefox && xdg-settings set default-web-browser firefox.desktop"; }
DEF="$(xdg-settings get default-web-browser 2>/dev/null || true)"
[ -n "$DEF" ] && echo "       默认浏览器记录：$DEF"
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then ok "当前在图形会话中"; else warn "当前不在图形会话（SSH 下正常，请以桌面内双击为准）"; fi

# ---------- 重建 ----------
if [ "$CHECK_ONLY" = "1" ]; then
  echo; echo "（--check 模式：未修改任何文件）"; exit 0
fi

echo
echo "⑤ 重建快捷方式"
mkdir -p "$HOME_DIR/.local/bin" "$HOME_DIR/.local/share/applications"
cat > "$LAUNCHER" <<EOF
#!/bin/bash
# 麒麟记忆启动器（由 fix-shortcut-standalone.sh 生成）
URL="$URL"; SVC="webchat"; PROJ_DIR="$PROJ_DIR"; PORT="$PORT"
STATE="\$HOME/.local/state"; mkdir -p "\$STATE" 2>/dev/null || true
LOG="\$STATE/kylin-mem-open.log"
say(){ echo "[\$(date '+%F %T')] \$*" >> "\$LOG" 2>/dev/null || true; }
notify(){ command -v notify-send >/dev/null 2>&1 && notify-send -a "麒麟记忆" "\$1" 2>/dev/null || true; }
CHECK_ONLY=0; [ "\${1:-}" = "--check" ] && CHECK_ONLY=1
say "启动器执行（CHECK_ONLY=\$CHECK_ONLY）"
start_direct(){
  local PY="\$PROJ_DIR/.venv/bin/python"
  [ -x "\$PY" ] || { say "虚拟环境缺失：\$PY"; echo "虚拟环境缺失：先执行 bash deploy/install.sh"; return 1; }
  curl -s -m 2 -o /dev/null "\$URL" 2>/dev/null && return 0
  say "直接启动：\$PY webchat.py \$PORT"
  ( cd "\$PROJ_DIR" && nohup "\$PY" webchat.py "\$PORT" >> "\$PROJ_DIR/webchat.log" 2>&1 & )
  return 0
}
if ! systemctl is-active --quiet "\$SVC" 2>/dev/null; then
  say "服务未运行，尝试 systemd 启动"
  if ! sudo -n systemctl start "\$SVC" 2>/dev/null && ! systemctl --user start "\$SVC" 2>/dev/null; then
    say "systemd 不可用，改用直接启动"; start_direct || true
  fi
fi
CODE=""
for _ in \$(seq 1 30); do
  CODE=\$(curl -s -m 2 -o /dev/null -w '%{http_code}' "\$URL" 2>/dev/null || true)
  [ "\$CODE" = "200" ] && break; sleep 1
done
if [ "\$CODE" != "200" ]; then say "HTTP 未就绪，兜底直接启动"; start_direct || true
  for _ in \$(seq 1 20); do CODE=\$(curl -s -m 2 -o /dev/null -w '%{http_code}' "\$URL" 2>/dev/null || true); [ "\$CODE" = "200" ] && break; sleep 1; done
fi
if [ "\$CODE" != "200" ]; then
  say "失败：服务未就绪（HTTP \${CODE:-无响应}）"
  notify "服务未就绪：journalctl -u \$SVC -n 50"
  { echo "麒麟记忆：服务未就绪（HTTP \${CODE:-无响应}）"; echo "排查：systemctl status \$SVC ｜ journalctl -u \$SVC -n 50 ｜ tail -30 \$PROJ_DIR/webchat.log"; } > "\$HOME/麒麟记忆-启动失败.txt"
  exit 1
fi
say "服务就绪：\$URL"
[ "\$CHECK_ONLY" = "1" ] && { echo "服务就绪：\$URL"; exit 0; }
for b in firefox chromium chromium-browser kylin-browser google-chrome browser360 qaxbrowser; do
  if command -v "\$b" >/dev/null 2>&1; then "\$b" "\$URL" >/dev/null 2>&1 & say "已用 \$b 打开"; exit 0; fi
done
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "\$URL" >/dev/null 2>&1 & say "已用 xdg-open 打开"; exit 0
fi
say "失败：没有可用浏览器"
notify "未找到浏览器，请安装：sudo apt install firefox"
{ echo "麒麟记忆：系统里没有可用浏览器，页面无法显示。"; echo "修复：sudo apt update && sudo apt install -y firefox"; echo "临时：在另一台机器上 ssh -N -L 18080:127.0.0.1:${PORT} 本机地址，再打开 http://127.0.0.1:18080/"; } > "$HOME_DIR/麒麟记忆-缺少浏览器.txt"
exit 2
EOF
chmod +x "$LAUNCHER"
ok "启动器已写入：$LAUNCHER"

ICON="applications-internet"
[ -f "$PROJ_DIR/deploy/assets/kylin-mem.png" ] && ICON="$PROJ_DIR/deploy/assets/kylin-mem.png"
write_desk(){ cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=麒麟记忆
Name[zh_CN]=麒麟记忆
Comment=打开麒麟智能体记忆系统（本机 $PORT 服务）
Exec=$LAUNCHER
Path=$PROJ_DIR
Icon=$ICON
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
chmod +x "$1" 2>/dev/null || true; }
write_desk "$APPS/kylin-mem.desktop"
[ -d "$DESKTOP_DIR" ] && write_desk "$DESKTOP_DIR/麒麟记忆.desktop"
command -v gio >/dev/null 2>&1 && gio set "$DESKTOP_DIR/麒麟记忆.desktop" metadata::trusted true 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME_DIR/.local/share/applications" 2>/dev/null || true
ok "应用菜单项：$APPS/kylin-mem.desktop"
ok "桌面图标：$DESKTOP_DIR/麒麟记忆.desktop（已 chmod +x + 标记可信）"

echo
echo "⑥ 收尾验证"
bash "$LAUNCHER" --check 2>&1 | sed 's/^/       /'
echo
echo "现在请：① 回桌面双击「麒麟记忆」；② 若仍无反应，执行下面两条并把结果发我："
echo "   tail -5 $HOME_DIR/.local/state/kylin-mem-open.log"
echo "   ls -la \"$DESKTOP_DIR/麒麟记忆.desktop\" && gio info \"$DESKTOP_DIR/麒麟记忆.desktop\" | grep -i trusted"
echo "也可先试：开始菜单里搜「麒麟记忆」（应用菜单项不受桌面可信标记影响）；"
echo "或终端直接执行：$LAUNCHER"
