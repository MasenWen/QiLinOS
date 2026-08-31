#!/bin/bash
# ============================================================
# Kylin Mem（麒麟记忆）统一部署脚本 —— deploy/install.sh
#
# 用法（脚本在 deploy/ 下，会回到项目根）：
#   bash deploy/install.sh                部署（venv+依赖+systemd）
#   bash deploy/install.sh --pack         打包（源码+记忆数据 → tar.gz，用于移植）
#   bash deploy/install.sh --with-sdk     部署 + 检查安装麒麟 SDK 系统依赖
#   bash deploy/install.sh --with-data    部署 + 还原 data/nex-agent 记忆数据
#   bash deploy/install.sh --all          全部（SDK+依赖+数据+systemd）
#   bash deploy/install.sh --no-systemd   不注册 systemd（手动启动）
# ============================================================
set -e
cd "$(dirname "$0")/.."   # 回到项目根

# apt 超时配置（麒麟官方源可能慢，防安装挂死）：单次连接 30s，重试 2 次
APT_OPTS="-o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::Retries=2"
# pip 超时配置：120s 超时 + 3 次重试
PIP_OPTS="--timeout 120 --retries 3"

PROJ_DIR="$(pwd)"
PORT="${PORT:-8080}"

WITH_SDK=0; WITH_DATA=0; NO_SYSTEMD=0; DO_PACK=0
for arg in "$@"; do
    case "$arg" in
        --with-sdk)   WITH_SDK=1 ;;
        --with-data)  WITH_DATA=1 ;;
        --all)        WITH_SDK=1; WITH_DATA=1 ;;
        --no-systemd) NO_SYSTEMD=1 ;;
        --pack)       DO_PACK=1 ;;
    esac
done

# ============================================================
# 打包模式（源机执行，生成移植包）
# ============================================================
if [ "$DO_PACK" = "1" ]; then
    DATE="$(date +%Y%m%d)"
    OUT="/home/kylin/kylin-mem-release-${DATE}.tar.gz"
    TMP="$(mktemp -d)"
    STAGE="$TMP/kylin-mem"
    echo "==> 打包模式：源码 + 记忆数据"
    mkdir -p "$STAGE"
    tar --exclude=".venv" --exclude=".git" --exclude="logs" \
        --exclude="__pycache__" --exclude="*.pyc" \
        --exclude="_benchmark" --exclude="uploads" \
        -cf - . | (cd "$STAGE" && tar -xf -)
    # 记忆数据
    mkdir -p "$STAGE/data/nex-agent"
    for item in banner_config.json forget_pending_candidates.json llm_config.json \
                log_reader_state.json memory_engine.db memory_flow.json memory_kg.json \
                sessions.json skills.json mem0_vectordb.db; do
        [ -e "$HOME/.nex-agent/$item" ] && cp -r "$HOME/.nex-agent/$item" "$STAGE/data/nex-agent/" 2>/dev/null || true
    done
    tar -czf "$OUT" -C "$TMP" kylin-mem
    rm -rf "$TMP"
    echo "✅ 打包完成: $OUT ($(du -sh "$OUT" | cut -f1))"
    echo "目标机部署: tar -xzf $(basename "$OUT") && cd kylin-mem && bash deploy/install.sh --all"
    exit 0
fi

echo "=== Kylin Mem 部署开始 ==="
echo "工作目录: $PROJ_DIR"

# ============================================================
# 1. Python 版本检查
# ============================================================
PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "!! 未找到 python3，尝试安装："
    sudo apt-get update -y $APT_OPTS
    sudo apt-get install -y $APT_OPTS python3 python3-venv python3-pip || {
        # 麒麟 V11 无第三方镜像（清华/阿里均无麒麟源），用官方双源回退
        echo "!! apt 默认源失败，尝试官方备用源 archive2.kylinos.cn"
        sudo sed -i "s|http://archive.kylinos.cn|https://archive2.kylinos.cn|g" \
            /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || true
        sudo apt-get update -y $APT_OPTS
        sudo apt-get install -y $APT_OPTS python3 python3-venv python3-pip
    }
fi
$PY --version || true

# ============================================================
# 2. 麒麟 SDK 系统依赖检查（--with-sdk / --all）
# ============================================================
if [ "$WITH_SDK" = "1" ]; then
    echo "--- 检查麒麟 SDK 系统依赖 ---"
    # 优先检测 .so 库（可靠，不限安装方式）；再查 dpkg 包名（apt 安装用）
    if ldconfig -p 2>/dev/null | grep -q "libkyai"; then
        echo "✅ SDK 已就绪（检测到 libkyai 库）"
    else
        echo "!! 未检测到麒麟 SDK，尝试 apt 安装（libkysdk 系统 SDK + kylin-ai AI 能力）"
        # webchat 系统工具依赖 libkysdk-*（sysinfo/disk/battery/shutdown/restart 等）
        SDK_PKGS="libkysdk-sysinfo libkysdk-package libkysdk-net libkysdk-hardware \
                  libkysdk-systime libkysdk-proc libkysdk-realtime libkysdk-disk \
                  libkysdk-restart libkysdk-shutdown libkysdk-battery libkysdk-global \
                  libkysdk-location libkysdk-powermanagement \
                  kylin-ai-runtime kylin-ai-abstract-models kylin-ai-knowledge-base-service"
        sudo apt-get update -y $APT_OPTS
        if ! sudo apt-get install -y $APT_OPTS $SDK_PKGS; then
            echo "!! 默认源失败，尝试官方备用源 archive2.kylinos.cn"
            sudo sed -i "s|http://archive.kylinos.cn|https://archive2.kylinos.cn|g" \
                /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || true
            sudo apt-get update -y $APT_OPTS
            sudo apt-get install -y $APT_OPTS $SDK_PKGS || echo "⚠️ SDK 安装失败——webchat 对话/记忆仍可用，系统工具降级"
        fi
    fi
    fc-list 2>/dev/null | grep -qi "noto sans cjk\|wqy" || sudo apt-get install -y $APT_OPTS fonts-noto-cjk 2>/dev/null || true
fi

# ============================================================
# 3. 虚拟环境
# ============================================================
if [ ! -d .venv ]; then
    echo "--- 创建虚拟环境 .venv ---"
    $PY -m venv .venv 2>/dev/null || { sudo apt-get install -y $APT_OPTS python3-venv; $PY -m venv .venv; }
fi

# ============================================================
# 4. 依赖安装（多镜像源自动切换）
# ============================================================
echo "--- 安装依赖（多镜像源自动切换）---"
.venv/bin/pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple -q $PIP_OPTS || \
    .venv/bin/pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ -q $PIP_OPTS
MIRRORS=(
    "https://pypi.tuna.tsinghua.edu.cn/simple"
    "https://mirrors.aliyun.com/pypi/simple/"
    "https://pypi.doubanio.com/simple"
    "https://pypi.org/simple"
)
install_ok=0
for mirror in "${MIRRORS[@]}"; do
    echo "---- 镜像: $mirror ----"
    if .venv/bin/pip install -r requirements.txt -i "$mirror" $PIP_OPTS; then
        install_ok=1; echo "✅ 依赖安装成功"; break
    fi
done
[ "$install_ok" = "1" ] || { echo "❌ 依赖安装失败"; exit 1; }

# 4b. spacy 英文模型（知识库 LightRAG 的 pipeline 需要，provider=lightrag 时）
#     清华源没有 spacy 模型，用官方 GitHub release（国内网络慢，失败不阻塞部署）
echo "--- spacy en_core_web_sm 模型（知识库 LightRAG 可选依赖）---"
if .venv/bin/python -c "import spacy, sys; spacy.load('en_core_web_sm')" 2>/dev/null; then
    echo "✅ spacy 模型已存在"
else
    .venv/bin/pip install --timeout 120 --retries 2 \
        "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl" \
        && echo "✅ spacy 模型安装成功" \
        || echo "⚠️ spacy 模型下载失败（不影响核心功能；kb 工具首次调用会再尝试）"
fi

# ============================================================
# 5. 还原记忆数据（--with-data / --all）
# ============================================================
if [ "$WITH_DATA" = "1" ] && [ -d data/nex-agent ]; then
    echo "--- 还原记忆数据 data/nex-agent → ~/.nex-agent ---"
    mkdir -p "$HOME/.nex-agent"
    cp -rn data/nex-agent/* "$HOME/.nex-agent/" 2>/dev/null || true
    echo "✅ 数据已还原"
fi

# ============================================================
# 6. 冒烟自检
# ============================================================
echo "--- 冒烟自检 ---"
.venv/bin/python -c "import webchat; print('✅ webchat import OK')" || echo "⚠️ webchat import 失败"

# ============================================================
# 7. systemd 托管（默认开，--no-systemd 跳过）
# ============================================================
if [ "$NO_SYSTEMD" = "0" ]; then
    echo "--- 注册 systemd 服务 ---"
    sudo cp deploy/webchat.service /etc/systemd/system/ 2>/dev/null || true
    sudo systemctl daemon-reload 2>/dev/null || true
    sudo systemctl enable webchat 2>/dev/null || true
    sudo systemctl restart webchat 2>/dev/null || true
    echo "✅ systemd 服务已注册: systemctl status webchat"
    sleep 5
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:$PORT/" 2>/dev/null || echo 000)
    [ "$code" = "200" ] && echo "✅ 健康检查: HTTP 200" || echo "⚠️ 健康检查 HTTP $code（查看日志）"
else
    echo "--- 跳过 systemd，手动启动: nohup .venv/bin/python webchat.py $PORT > webchat.log 2>&1 &"
fi

echo
echo "=== 部署完成 ==="
echo "访问: http://127.0.0.1:$PORT/ （远程: ssh -N -L $PORT:127.0.0.1:$PORT 用户@主机）"
