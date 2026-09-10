#!/usr/bin/env bash
# 新机器"一条命令装好并直跑"（不使用 systemd，方便随时更新）
#
#   bash deploy/setup-direct.sh                        # 体检 → 装依赖 → 直跑 → 自检
#   bash deploy/setup-direct.sh --env-file ~/webchat.env   # 同时安装环境文件（严格引擎/密钥）
#   bash deploy/setup-direct.sh --check                # 只体检，不改动任何东西
#   bash deploy/setup-direct.sh --skip-install         # 跳过依赖安装（已装好 venv 时）
#
# 前置：Python >= 3.12、git；仓库已在本地（git clone -b dev1 <repo>）。
# 说明：本脚本不碰 /etc/systemd/system，也不创建桌面图标（那些见 install.sh 的 --no-systemd/--no-desktop）。
set -uo pipefail

PROJ_DIR="${PROJ_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE_SRC=""
CHECK_ONLY=0
SKIP_INSTALL=0
PORT="${PORT:-8080}"
HOME_ENV="$HOME/.nex-agent/webchat.env"

while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE_SRC="$2"; shift 2 ;;
    --check) CHECK_ONLY=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
done

say() { printf '[setup] %s\n' "$*"; }
die() { printf '[setup] ✗ %s\n' "$*" >&2; exit 1; }

cd "$PROJ_DIR" || die "目录不存在：$PROJ_DIR"
say "项目目录：$PROJ_DIR"
say "系统：$(uname -srm)  发行版：$( (grep -m1 PRETTY_NAME /etc/os-release 2>/dev/null || sw_vers 2>/dev/null || echo 未知) | cut -d= -f2- | tr -d '"')"

# ---------------- 1) 体检 ----------------
fail=0
PY_BIN=""
for c in python3.12 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    v="$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)"
    if [ "$(printf '%s\n3.12\n' "$v" | sort -V | head -1)" = "3.12" ]; then PY_BIN="$c"; break; fi
    say "⚠ $c 版本 $v < 3.12"
  fi
done
[ -n "$PY_BIN" ] && say "✓ Python：$PY_BIN ($v)" || { say "✗ 需要 Python ≥ 3.12"; fail=1; }

command -v git >/dev/null 2>&1 && say "✓ git：$(git --version)" || { say "✗ 缺 git"; fail=1; }

if [ -d .git ]; then
  say "✓ 仓库：分支 $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)"
  case "$(git rev-parse --abbrev-ref HEAD)" in
    dev1) ;;
    *) say "⚠ 当前不是 dev1 分支（默认 master 落后 dev1 很多）：git checkout dev1" ;;
  esac
else
  say "✗ 这里不是 git 仓库，请先 git clone -b dev1 <repo> $PROJ_DIR"; fail=1
fi

if [ -x .venv/bin/python ]; then
  say "✓ 虚拟环境：$(.venv/bin/python -V 2>&1)"
else
  say "· 虚拟环境尚未创建（下一步会建）"
fi

if [ -f "$HOME_ENV" ]; then
  say "✓ 环境文件：$HOME_ENV（$(wc -l < "$HOME_ENV") 行，权限 $(stat -c %a "$HOME_ENV" 2>/dev/null || echo '?'))"
else
  say "⚠ 缺环境文件 $HOME_ENV —— 没有它服务会以默认模式启动（严格记忆引擎关闭、无 LLM 密钥）"
fi

if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
  say "⚠ 端口 $PORT 已被占用：$(ss -ltnp 2>/dev/null | grep ":${PORT} " | head -1)"
fi

for u in /etc/systemd/system/webchat.service /etc/systemd/system/webhook.service; do
  if [ -f "$u" ] && grep -q '<PROJECT_ROOT>' "$u" 2>/dev/null; then
    say "✗ $u 是模板原文（含 <PROJECT_ROOT>）→ systemd 会报 'WorkingDirectory is not absolute'"
    fail=1
  fi
done

[ "$CHECK_ONLY" = "1" ] && { say "体检结束（--check，未做任何改动）"; exit $fail; }
[ "$fail" = "0" ] || die "体检未通过，请先修掉上面带 ✗ 的项"

# ---------------- 2) 装依赖（复用 install.sh，跳过 systemd 与桌面图标） ----------------
if [ "$SKIP_INSTALL" = "0" ]; then
  say "安装依赖：bash deploy/install.sh --no-systemd --no-desktop"
  bash deploy/install.sh --no-systemd --no-desktop || die "install.sh 失败（看上面输出）"
else
  say "跳过依赖安装（--skip-install）"
fi

# ---------------- 3) 环境文件 ----------------
mkdir -p "$HOME/.nex-agent"
if [ -n "$ENV_FILE_SRC" ]; then
  [ -f "$ENV_FILE_SRC" ] || die "找不到 --env-file 指定的文件：$ENV_FILE_SRC"
  install -m 600 "$ENV_FILE_SRC" "$HOME_ENV"
  say "已安装环境文件：$HOME_ENV（600）"
elif [ ! -f "$HOME_ENV" ]; then
  umask 077
  cat > "$HOME_ENV" <<'EOF'
# 严格记忆引擎与 LLM 密钥（照抄 kylin 上 ~/.nex-agent/webchat.env）
NEX_STRICT_ENGINE=1
NEX_DEEPSEEK_API_KEY=
NEX_GROK_API_KEY=
EOF
  chmod 600 "$HOME_ENV"
  say "⚠ 已生成模板 $HOME_ENV —— 请补上 API key 后重启，否则对话会报密钥错误"
fi

# ---------------- 4) 直跑 + 自检 ----------------
say "启动（不使用 systemd）：bash deploy/webchat-direct.sh start"
bash deploy/webchat-direct.sh start || die "启动失败（看 webchat-direct.sh 输出）"
bash deploy/webchat-direct.sh status || true

cat <<EOF

下一步：
  · 另开一台机器看界面 → 在**那台**机器上：ssh -N -L 127.0.0.1:18080:127.0.0.1:${PORT} $(whoami)@<本机IP>
    然后浏览器打开 http://127.0.0.1:18080/?panel=1
  · 更新代码 → bash deploy/update.sh            （自动识别"直跑"模式并重启）
  · 停止     → bash deploy/webchat-direct.sh stop
  · 开机自启（不用 systemd）：~/.config/autostart/kylin-webchat.desktop 里 Exec 调 webchat-direct.sh start
EOF
