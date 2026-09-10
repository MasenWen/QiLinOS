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

BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/${APP_ID}-open"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"

# 桌面目录：优先 xdg-user-dir（已本地化，如 ~/桌面），回退常见中文/英文名
desktop_dir() {
    local d=""
    command -v xdg-user-dir >/dev/null 2>&1 && d="$(xdg-user-dir DESKTOP 2>/dev/null)"
    [ -z "$d" ] || [ "$d" = "$HOME" ] && {
        for c in "$HOME/桌面" "$HOME/Desktop"; do [ -d "$c" ] && d="$c" && break; done
    }
    [ -z "$d" ] && d="$HOME"
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
URL="$URL"
SVC="$SVC"
CHECK_ONLY=0
[ "\${1:-}" = "--check" ] && CHECK_ONLY=1
if ! systemctl is-active --quiet "\$SVC" 2>/dev/null; then
  sudo -n systemctl start "\$SVC" 2>/dev/null || systemctl --user start "\$SVC" 2>/dev/null || true
fi
CODE=""
for _ in \$(seq 1 30); do
  CODE=\$(curl -s -m 2 -o /dev/null -w '%{http_code}' "\$URL" 2>/dev/null || true)
  [ "\$CODE" = "200" ] && break
  sleep 1
done
if [ "\$CODE" != "200" ]; then
  echo "服务未就绪（HTTP \${CODE:-无响应}）：systemctl status \$SVC ｜ journalctl -u \$SVC -n 50"
  exit 1
fi
[ "\$CHECK_ONLY" = "1" ] && { echo "服务就绪：\$URL"; exit 0; }
command -v xdg-open >/dev/null 2>&1 && xdg-open "\$URL" >/dev/null 2>&1 &
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
log "完成。若桌面图标显示为「文本文件」样式，右键 → 允许启动/信任 一次即可。"
