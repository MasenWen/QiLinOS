#!/bin/bash
# ============================================================
# 麒麟记忆 · 部署与快捷方式自检（doctor）
#
# 用法（在目标主机上，用**桌面登录用户**执行；不要加 sudo）：
#   bash deploy/doctor.sh
#   bash deploy/doctor.sh --verbose     # 额外打印桌面项内容与日志尾部
#
# 只读检查：不改任何配置。输出 PASS/FAIL/WARN + 修复建议。
# ============================================================
set -u
cd "$(dirname "$0")/.." 2>/dev/null || true
PROJ_DIR="$(pwd)"
PORT="${PORT:-8080}"
URL="http://127.0.0.1:${PORT}/"
SVC="webchat"
VERBOSE=0
[ "${1:-}" = "--verbose" ] && VERBOSE=1

if command -v tput >/dev/null 2>&1 && [ -t 1 ]; then
  G="$(tput setaf 2)"; R="$(tput setaf 1)"; Y="$(tput setaf 3)"; N="$(tput sgr0)"
else
  G=""; R=""; Y=""; N=""
fi
PASS=0; FAIL=0; WARN=0
ok()   { echo "  ${G}[通过]${N} $*"; PASS=$((PASS+1)); }
bad()  { echo "  ${R}[失败]${N} $*"; FAIL=$((FAIL+1)); }
warn() { echo "  ${Y}[注意]${N} $*"; WARN=$((WARN+1)); }
hint() { echo "         ↳ 修复：$*"; }

# 桌面目录解析（与 make-shortcut.sh 同规则）
TARGET_USER="$(id -un)"; TARGET_HOME="$HOME"
if [ "$(id -u)" = "0" ] && [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
  TARGET_USER="${SUDO_USER}"
  TARGET_HOME="$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6)"; TARGET_HOME="${TARGET_HOME:-$HOME}"
fi
DESKTOP_DIR=""
command -v xdg-user-dir >/dev/null 2>&1 && DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null)"
[ -z "$DESKTOP_DIR" ] || [ "$DESKTOP_DIR" = "$TARGET_HOME" ] && {
  for c in "$TARGET_HOME/桌面" "$TARGET_HOME/Desktop"; do [ -d "$c" ] && DESKTOP_DIR="$c" && break; done
}
[ -z "$DESKTOP_DIR" ] && DESKTOP_DIR="$TARGET_HOME"

echo "麒麟记忆 · 自检报告  $(date '+%F %T')"
echo "主机/用户 : $(hostname) / $TARGET_USER （家目录 $TARGET_HOME）"
echo "项目目录 : $PROJ_DIR"
echo "桌面目录 : $DESKTOP_DIR"
echo "桌面环境 : ${XDG_CURRENT_DESKTOP:-未知} ｜ 端口 $PORT"
echo

echo "① 服务与端口"
# 体检：有没有把模板原文（含 <PROJECT_ROOT>）装进 systemd 目录 —— 会让服务永远起不来
for f in /etc/systemd/system/webchat.service /etc/systemd/system/webhook.service; do
  if [ -f "$f" ] && grep -q '<PROJECT_ROOT>' "$f" 2>/dev/null; then
    echo "❌ [$f] 仍是模板原文（含 <PROJECT_ROOT>）→ systemd 会报 'WorkingDirectory is not absolute'"
    hint "修复：sed 's#<PROJECT_ROOT>#/绝对/路径#g' deploy/webchat.service | sudo tee $f && sudo systemctl daemon-reload"
  fi
done

if systemctl is-active --quiet "$SVC" 2>/dev/null; then
  ok "systemd 服务 $SVC 正在运行"
else
  warn "systemd 服务 $SVC 未运行（也可手动方式启动）"
  hint "sudo systemctl start $SVC ｜ 或 nohup .venv/bin/python webchat.py $PORT >webchat.log 2>&1 &"
fi
if command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then ok "端口 $PORT 正在监听"; else bad "端口 $PORT 没有监听"; hint "看服务日志：journalctl -u $SVC -n 50 --no-pager"; fi
else
  warn "无 ss 命令，跳过端口检查"
fi
CODE="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null || echo 000)"
if [ "$CODE" = "200" ]; then ok "HTTP 探测 $URL → 200"; else bad "HTTP 探测 $URL → $CODE"; hint "服务进程/端口/依赖（.venv）三处查一遍：journalctl -u $SVC -n 50"; fi

echo
echo "② 快捷方式产物"
LAUNCHER="$TARGET_HOME/.local/bin/kylin-mem-open"
APPS="$TARGET_HOME/.local/share/applications/kylin-mem.desktop"
DESK="$DESKTOP_DIR/麒麟记忆.desktop"
if [ -f "$DESK" ]; then
  if [ -x "$DESK" ]; then ok "桌面图标存在且可执行：$DESK"; else warn "桌面图标存在但不可执行"; hint "chmod +x \"$DESK\""; fi
  if command -v gio >/dev/null 2>&1; then
    T="$(gio info "$DESK" 2>/dev/null | grep -i 'metadata::trusted' || true)"
    [ -n "$T" ] && ok "已标记可信（$T）" || warn "未标记可信，部分文件管理器会当成文本文件点不开"
    hint "gio set \"$DESK\" metadata::trusted true ｜ 或右键→允许启动"
  fi
else
  bad "桌面图标不存在：$DESK"
  hint "在项目根执行：bash deploy/make-shortcut.sh"
fi
[ -f "$APPS" ] && ok "应用菜单项存在：$APPS" || { warn "应用菜单项缺失"; hint "bash deploy/make-shortcut.sh"; }
if [ -x "$LAUNCHER" ]; then
  ok "启动器存在且可执行：$LAUNCHER"
  echo "       ── 启动器自检输出 ──"
  bash "$LAUNCHER" --check 2>&1 | sed 's/^/       /'
else
  bad "启动器缺失或不可执行：$LAUNCHER"; hint "bash deploy/make-shortcut.sh"
fi

echo
echo "③ 桌面项内容校验"
if [ -f "$DESK" ]; then
  EXEC="$(grep -m1 '^Exec=' "$DESK" | cut -d= -f2- | awk '{print $1}')"
  ICON="$(grep -m1 '^Icon=' "$DESK" | cut -d= -f2-)"
  echo "       Exec=$EXEC"; echo "       Icon=$ICON"
  [ -n "$EXEC" ] && [ -x "$EXEC" ] && ok "Exec 指向的启动器可执行" || { bad "Exec 目标不可执行：$EXEC"; hint "bash deploy/make-shortcut.sh（会重写桌面项）"; }
  if [ -n "$ICON" ] && [ -f "$ICON" ]; then ok "图标文件存在"; else warn "图标文件不存在（不影响启动，仅显示默认图标）"; fi
  if command -v desktop-file-validate >/dev/null 2>&1; then
    if desktop-file-validate "$DESK" 2>/dev/null; then ok "desktop 文件语法校验通过"; else bad "desktop 文件语法有问题"; hint "desktop-file-validate \"$DESK\" 看详情"; fi
  fi
  [ "$VERBOSE" = "1" ] && { echo "       ── 文件内容 ──"; sed 's/^/       /' "$DESK"; }
  if command -v gio >/dev/null 2>&1; then
    if gio launch "$DESK" >/dev/null 2>&1; then ok "gio launch 测试：桌面项可启动"; else warn "gio launch 测试未成功（无图形会话时属正常，桌面内双击才算）"; fi
  fi
fi

echo
echo "④ 浏览器（双击后要打开的就是它）"
DEF="$(xdg-settings get default-web-browser 2>/dev/null || true)"
echo "       默认浏览器记录：${DEF:-（未设置）}"
BROWSER=""
if [ -n "$DEF" ]; then
  for p in "$TARGET_HOME/.local/share/applications/$DEF" "/usr/share/applications/$DEF"; do
    if [ -f "$p" ]; then
      B="$(grep -m1 '^Exec=' "$p" | cut -d= -f2- | awk '{print $1}')"
      echo "       默认项 Exec=$B"
      command -v "$B" >/dev/null 2>&1 && BROWSER="$B"
      break
    fi
  done
  [ -z "$BROWSER" ] && warn "默认浏览器条目指向的可执行文件不可用（常见：配置残留）"
fi
for b in firefox chromium chromium-browser kylin-browser google-chrome browser360 qaxbrowser; do
  command -v "$b" >/dev/null 2>&1 && BROWSER="${BROWSER:-$b}" && echo "       发现浏览器：$(command -v "$b")"
done
if [ -n "$BROWSER" ]; then
  ok "存在可用浏览器：$BROWSER"
else
  bad "系统里没有任何可用图形浏览器 → 双击图标后无处显示页面（这就是“打不开”的最常见原因）"
  hint "sudo apt update && sudo apt install -y firefox ；然后 xdg-settings set default-web-browser firefox.desktop"
fi
if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then ok "图形会话可用（DISPLAY=${DISPLAY:-}${WAYLAND_DISPLAY:-}）"; else warn "当前 shell 不在图形会话（SSH 下正常）；浏览器检查请以桌面内双击为准"; fi

echo
echo "⑤ 常见坑位"
if [ "$(id -u)" = "0" ]; then warn "当前以 root 运行：快捷方式应装到调用者家目录"; hint "用桌面用户执行 bash deploy/doctor.sh（不要 sudo）"; fi
[ -d "$TARGET_HOME/桌面" ] && [ "$DESKTOP_DIR" != "$TARGET_HOME/桌面" ] && warn "桌面目录解析结果与 ~/桌面 不一致：$DESKTOP_DIR"
APP_ALT="/root/.local/share/applications/kylin-mem.desktop"
[ -f "$APP_ALT" ] && warn "发现 /root 下也有快捷方式（说明曾用 sudo 安装）" && hint "sudo rm -f /root/.local/share/applications/kylin-mem.desktop；然后用桌面用户重跑 make-shortcut.sh"
if [ -f "$TARGET_HOME/.local/state/kylin-mem-open.log" ]; then
  echo "       ── 启动器日志（最近 8 行）──"; tail -8 "$TARGET_HOME/.local/state/kylin-mem-open.log" | sed 's/^/       /'
else
  echo "       （还没有启动器日志：双击一次图标后本文件会生成）"
fi

echo
echo "小结：通过 $PASS 项 ｜ 失败 $FAIL 项 ｜ 注意 $WARN 项"
[ "$FAIL" -eq 0 ] && echo "没有硬性失败项；若双击仍无反应，请把本报告发给维护者。" || echo "请按上面标注的「修复」逐条处理后重跑本脚本。"
echo "常用命令：bash deploy/make-shortcut.sh --check ｜ journalctl -u $SVC -n 50 --no-pager ｜ tail -20 $TARGET_HOME/.local/state/kylin-mem-open.log"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
