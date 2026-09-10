#!/bin/bash
# ============================================================
# 桌面快捷方式生成器（麒麟 OS / 通用 Linux 桌面）
#
# 作用：安装后在「桌面 + 应用菜单」自动生成「麒麟记忆」图标，
#       双击即打开本机 Web 界面；服务未运行时会自动拉起。
#
# 用法（在项目根或 deploy/ 下执行均可）：
#   bash deploy/make-shortcut.sh              # 生成/刷新快捷方式（幂等）
#   bash deploy/make-shortcut.sh --check      # 只自检，不写文件
#   bash deploy/make-shortcut.sh --autostart  # 额外加入「开机自启」（登录后自动起服务）
#   bash deploy/make-shortcut.sh --uninstall  # 删除快捷方式与启动器
#
# 说明：本脚本不含机器专属路径，安装时按实际路径生成 .desktop；
#      图标取自 deploy/assets/kylin-mem.png（随包分发）。
# ============================================================
set -u

cd "$(dirname "$0")/.." 2>/dev/null || true
PROJ_DIR="$(pwd)"
PORT="${PORT:-8080}"
URL="http://127.0.0.1:${PORT}/"
APP_NAME="麒麟记忆"
APP_ID="kylin-mem"
SVC="webchat"
ICON_SRC="$PROJ_DIR/deploy/assets/kylin-mem.png"

# 若以 root 身份通过 sudo 执行，快捷方式应落到「调用者」的家目录（而不是 /root）
TARGET_USER="$(id -un)"; TARGET_HOME="$HOME"
if [ "$(id -u)" = "0" ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    TARGET_USER="${SUDO_USER}"
    TARGET_HOME="$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6)"
    [ -n "$TARGET_HOME" ] && [ -d "$TARGET_HOME" ] || TARGET_HOME="$HOME"
fi

BIN_DIR="$TARGET_HOME/.local/bin"
LAUNCHER="$BIN_DIR/${APP_ID}-open"
APPS_DIR="$TARGET_HOME/.local/share/applications"
AUTOSTART_DIR="$TARGET_HOME/.config/autostart"

# 桌面目录：优先 xdg-user-dir（已本地化，如 ~/桌面），回退常见中文/英文名
desktop_dir() {
    local d=""
    # 以目标用户身份解析本地化桌面目录（SUDO 场景下切到该用户执行 xdg-user-dir）
    if [ "$TARGET_HOME" != "$HOME" ] && command -v sudo >/dev/null 2>&1; then
        d="$(sudo -u "$TARGET_USER" -H xdg-user-dir DESKTOP 2>/dev/null)"
    else
        command -v xdg-user-dir >/dev/null 2>&1 && d="$(xdg-user-dir DESKTOP 2>/dev/null)"
    fi
    [ -z "$d" ] || [ "$d" = "$TARGET_HOME" ] && {
        for c in "$TARGET_HOME/桌面" "$TARGET_HOME/Desktop"; do [ -d "$c" ] && d="$c" && break; done
    }
    [ -z "$d" ] && d="$TARGET_HOME"
    echo "$d"
}
DESKTOP_DIR="$(desktop_dir)"

DO_CHECK=0; DO_UNINSTALL=0; DO_AUTOSTART=0
for arg in "$@"; do
    case "$arg" in
        --check)     DO_CHECK=1 ;;
        --uninstall) DO_UNINSTALL=1 ;;
        --autostart) DO_AUTOSTART=1 ;;
    esac
done

log() { echo "[快捷方式] $*"; }

# ------------------------------------------------------------
# 卸载
# ------------------------------------------------------------
if [ "$DO_UNINSTALL" = "1" ]; then
    rm -f "$APPS_DIR/${APP_ID}.desktop" "$DESKTOP_DIR/${APP_NAME}.desktop" \
          "$LAUNCHER" "$AUTOSTART_DIR/${APP_ID}.desktop"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true
    log "已删除：应用菜单项、桌面图标、启动器、开机自启项"
    exit 0
fi

if [ "$DO_CHECK" = "1" ]; then
    echo "目标用户   : $TARGET_USER （家目录 $TARGET_HOME）"
    echo "项目目录   : $PROJ_DIR"
    echo "桌面目录   : $DESKTOP_DIR"
    echo "端口/地址  : $PORT / $URL"
    echo "图标文件   : $ICON_SRC $([ -f "$ICON_SRC" ] && echo '（存在）' || echo '（缺失，将用系统主题图标）')"
    echo "启动器     : $LAUNCHER $([ -x "$LAUNCHER" ] && echo '（已安装）' || echo '（未安装）')"
    echo "应用菜单项 : $APPS_DIR/${APP_ID}.desktop $([ -f "$APPS_DIR/${APP_ID}.desktop" ] && echo '（已安装）' || echo '（未安装）')"
    echo "桌面图标   : $DESKTOP_DIR/${APP_NAME}.desktop $([ -f "$DESKTOP_DIR/${APP_NAME}.desktop" ] && echo '（已安装）' || echo '（未安装）')"
    exit 0
fi

# ------------------------------------------------------------
# 1) 启动器脚本：确保服务在跑 → 等 HTTP 200 → 打开浏览器
# ------------------------------------------------------------
mkdir -p "$BIN_DIR" "$APPS_DIR"
cat > "$LAUNCHER" <<EOF
#!/bin/bash
# 麒麟记忆启动器（由 deploy/make-shortcut.sh 生成）
# 日志：~/.local/state/kylin-mem-open.log
URL="$URL"
SVC="$SVC"
PROJ_DIR="$PROJ_DIR"      # 生成时写入真实项目路径
PORT="$PORT"
STATE_DIR="\$HOME/.local/state"
LOG="\$STATE_DIR/kylin-mem-open.log"
mkdir -p "\$STATE_DIR" 2>/dev/null || true
say() { echo "[\$(date '+%F %T')] \$*" >> "\$LOG" 2>/dev/null || true; }
notify() { command -v notify-send >/dev/null 2>&1 && notify-send -a "麒麟记忆" "\$1" 2>/dev/null || true; }

CHECK_ONLY=0
[ "\${1:-}" = "--check" ] && CHECK_ONLY=1
say "启动器执行（CHECK_ONLY=\$CHECK_ONLY）"

# 1) 服务未运行则拉起：优先 systemd；systemd 不可用/无权限时直接用 venv 解释器起进程
start_direct() {
  local PY="\$PROJ_DIR/.venv/bin/python"
  if [ ! -x "\$PY" ]; then
    say "虚拟环境缺失：\$PY 不存在"
    echo "虚拟环境缺失：请先在项目目录执行 bash deploy/install.sh"
    return 1
  fi
  # 已被别的进程占用端口则不再重复起
  if curl -s -m 2 -o /dev/null "\$URL" 2>/dev/null; then return 0; fi
  # 环境变量来源（按优先级）：
  #   ① ~/.nex-agent/webchat.env —— 项目已脱离 systemd，这是主要来源（600 权限）
  #   ② systemctl show —— 单元仍存在时的历史路径，保留兼容
  #   ③ 都没有 → 会跑在默认模式（非 strict、无密钥），此处显式告警
  local ENVV="" SRC=""
  if [ -f "\$HOME/.nex-agent/webchat.env" ]; then
    ENVV="\$(tr '\\n' ' ' < "\$HOME/.nex-agent/webchat.env")"
    SRC="环境文件 ~/.nex-agent/webchat.env"
  elif command -v systemctl >/dev/null 2>&1; then
    ENVV="\$(systemctl show "\$SVC" -p Environment --value 2>/dev/null || true)"
    [ -n "\$ENVV" ] && SRC="systemd 单元环境"
  fi
  [ -z "\$ENVV" ] && say "⚠ 未找到环境变量（严格引擎/密钥），将以默认模式启动"
  # 日志写用户可写路径（systemd 时期的 webchat.log 属 root，直接启动写不进去）
  local LOGF="\$HOME/.local/state/webchat-direct.log"
  mkdir -p "\$(dirname "\$LOGF")"
  say "直接启动：\$PY webchat.py \$PORT \${SRC:+（\$SRC）}"
  ( cd "\$PROJ_DIR" && env \$ENVV nohup "\$PY" webchat.py "\$PORT" >> "\$LOGF" 2>&1 & echo \$! > "\$HOME/.local/state/webchat.pid" )
  return 0
}
if ! systemctl is-active --quiet "\$SVC" 2>/dev/null; then
  say "服务未运行，尝试启动（systemd）"
  if ! sudo -n systemctl start "\$SVC" 2>/dev/null && ! systemctl --user start "\$SVC" 2>/dev/null; then
    say "systemd 启动不可用（无 sudo 免密/无 user 会话），改用直接启动兜底"
    start_direct || true
  fi
fi

# 2) 等待 HTTP 就绪
CODE=""
for _ in \$(seq 1 30); do
  CODE=\$(curl -s -m 2 -o /dev/null -w '%{http_code}' "\$URL" 2>/dev/null || true)
  [ "\$CODE" = "200" ] && break
  sleep 1
done
if [ "\$CODE" != "200" ]; then
  # 二次兜底：systemd 路径失败时（例如 --no-systemd 安装、服务被 mask）直接起进程
  say "HTTP 未就绪（\${CODE:-无响应}），尝试直接启动兜底"
  start_direct || true
  for _ in \$(seq 1 20); do
    CODE=\$(curl -s -m 2 -o /dev/null -w '%{http_code}' "\$URL" 2>/dev/null || true)
    [ "\$CODE" = "200" ] && break
    sleep 1
  done
fi
if [ "\$CODE" != "200" ]; then
  say "失败：服务未就绪（HTTP \${CODE:-无响应}）"
  notify "服务未就绪（HTTP \${CODE:-无响应}）：journalctl -u \$SVC -n 50"
  echo "服务未就绪（HTTP \${CODE:-无响应}）：systemctl status \$SVC ｜ journalctl -u \$SVC -n 50 ｜ tail -20 \$PROJ_DIR/webchat.log"
  exit 1
fi
say "服务就绪：\$URL"
[ "\$CHECK_ONLY" = "1" ] && { echo "服务就绪：\$URL"; exit 0; }

# 3) 打开浏览器（多级回退：默认浏览器 → 常见浏览器 → xdg-open）
open_url() {
  local u="\$1" b
  for b in firefox chromium chromium-browser kylin-browser google-chrome browser360 qaxbrowser; do
    if command -v "\$b" >/dev/null 2>&1; then
      "\$b" "\$u" >/dev/null 2>&1 & say "已用 \$b 打开"; return 0
    fi
  done
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "\$u" >/dev/null 2>&1 & sleep 1
    # xdg-open 在没有浏览器时会静默失败：用默认项再确认一次
    if command -v xdg-settings >/dev/null 2>&1; then
      local d; d="\$(xdg-settings get default-web-browser 2>/dev/null)"
      if [ -n "\$d" ]; then
        local f="/usr/share/applications/\$d"
        [ -f "\$f" ] || f="\$HOME/.local/share/applications/\$d"
        if [ -f "\$f" ]; then
          local ex; ex="\$(grep -m1 '^Exec=' "\$f" | cut -d= -f2- | awk '{print \$1}')"
          command -v "\$ex" >/dev/null 2>&1 || { say "默认浏览器不可用：\$d → \$ex"; notify "未找到可用浏览器，请安装：sudo apt install firefox"; return 1; }
        else
          say "默认浏览器条目缺失：\$d"; notify "浏览器配置异常，请安装：sudo apt install firefox"; return 1
        fi
      fi
    fi
    say "已用 xdg-open 打开"; return 0
  fi
  say "失败：没有可用的浏览器（xdg-open 也缺失）"
  notify "未找到浏览器，无法显示页面。请执行：sudo apt install firefox"
  return 1
}
open_url "\$URL" || {
  echo "未找到可用浏览器：请安装后重试（sudo apt install firefox），或手动访问 \$URL"
  exit 2
}
say "完成"
EOF
chmod +x "$LAUNCHER"
log "启动器已写入：$LAUNCHER"

# ------------------------------------------------------------
# 2) 图标（随包分发；缺失则退回系统主题图标）
# ------------------------------------------------------------
ICON_VALUE="applications-internet"
if [ -f "$ICON_SRC" ]; then ICON_VALUE="$ICON_SRC"; fi

# ------------------------------------------------------------
# 3) .desktop（应用菜单项 + 桌面图标）
# ------------------------------------------------------------
write_desktop() {  # $1=目标路径
    cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=${APP_NAME}
Name[zh_CN]=${APP_NAME}
GenericName=Kylin Mem
Comment=打开麒麟智能体记忆系统（本机 ${PORT} 服务）
Comment[zh_CN]=打开麒麟智能体记忆系统（本机 ${PORT} 服务）
Exec=${LAUNCHER}
Path=${PROJ_DIR}
Icon=${ICON_VALUE}
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
    chmod +x "$1" 2>/dev/null || true
}
write_desktop "$APPS_DIR/${APP_ID}.desktop"
report_ok=1
if [ -d "$DESKTOP_DIR" ]; then
    write_desktop "$DESKTOP_DIR/${APP_NAME}.desktop"
    # 标记为可信（GNOME/UKUI 双击执行需要）
    command -v gio >/dev/null 2>&1 && gio set "$DESKTOP_DIR/${APP_NAME}.desktop" metadata::trusted true 2>/dev/null || true
else
    report_ok=0
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true

# 语法自检
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$APPS_DIR/${APP_ID}.desktop" && log "desktop 文件语法校验通过"
fi

# ------------------------------------------------------------
# 4) 可选：开机自启（登录后自动拉起服务，不自动开浏览器）
# ------------------------------------------------------------
if [ "$DO_AUTOSTART" = "1" ]; then
    mkdir -p "$AUTOSTART_DIR"
    cat > "$AUTOSTART_DIR/${APP_ID}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=${APP_NAME} 服务自启
Exec=${LAUNCHER} --check
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    log "已加入开机自启：$AUTOSTART_DIR/${APP_ID}.desktop"
fi

log "应用菜单项：$APPS_DIR/${APP_ID}.desktop"
[ "$report_ok" = "1" ] && log "桌面图标：$DESKTOP_DIR/${APP_NAME}.desktop（双击即打开 ${URL}）" \
                       || log "⚠️ 未找到桌面目录，仅创建了应用菜单项"
# root 执行时把生成物归还目标用户（否则桌面上会显示为 root 所有/不可点）
if [ "$(id -u)" = "0" ] && [ "$TARGET_USER" != "root" ]; then
    chown -R "$TARGET_USER":"$TARGET_USER" "$BIN_DIR" "$APPS_DIR" "$AUTOSTART_DIR" 2>/dev/null || true
    [ -e "$DESKTOP_DIR/${APP_NAME}.desktop" ] &&         chown "$TARGET_USER":"$TARGET_USER" "$DESKTOP_DIR/${APP_NAME}.desktop" 2>/dev/null || true
fi

log "完成。若桌面图标显示为「文本文件」样式，右键 → 允许启动/信任 一次即可。"
