#!/usr/bin/env bash
# ============================================================
# Kylin Mem（麒麟记忆）安装脚本 — Kylin OS V11 桌面版
# 用途：创建 venv + 安装 requirements.txt（含镜像源切换/重试）
# ============================================================
set -e

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR=".venv"

echo "==> 1/4 检查 Python3（麒麟系统 python3 下载可能出问题，自动换源重试）"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "!! 未找到 python3，尝试安装："
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-venv python3-pip || {
        echo "!! apt 安装失败，尝试镜像源："
        sudo sed -i 's|http://archive.ubuntu.com/ubuntu|https://mirrors.aliyun.com/ubuntu|g' /etc/apt/sources.list 2>/dev/null || true
        sudo apt-get update -y
        sudo apt-get install -y python3 python3-venv python3-pip
    }
fi

echo "==> 2/4 创建虚拟环境"
"$PYTHON_BIN" -m venv "$VENV_DIR" 2>/dev/null || {
    echo "!! venv 创建失败，尝试安装 python3-venv："
    sudo apt-get install -y python3-venv
    "$PYTHON_BIN" -m venv "$VENV_DIR"
}
source "$VENV_DIR/bin/activate"

echo "==> 3/4 升级 pip（换清华镜像源）"
pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple || \
    pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/

echo "==> 4/4 安装依赖（多镜像源自动切换，失败自动重试下一个）"
MIRRORS=(
    "https://pypi.tuna.tsinghua.edu.cn/simple"
    "https://mirrors.aliyun.com/pypi/simple/"
    "https://pypi.doubanio.com/simple"
    "https://pypi.org/simple"
)
install_ok=0
for mirror in "${MIRRORS[@]}"; do
    echo "---- 尝试镜像源: $mirror ----"
    if pip install -r requirements.txt -i "$mirror" --timeout 120 --retries 3; then
        install_ok=1
        echo "✅ 安装成功（镜像: $mirror）"
        break
    else
        echo "⚠️ 该镜像源失败，切换下一个..."
    fi
done

if [ "$install_ok" -ne 1 ]; then
    echo "❌ 所有镜像源均失败。请检查网络后重试，或手动执行："
    echo "   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
    exit 1
fi

echo ""
echo "=========================================="
echo " ✅ Kylin Mem 依赖安装完成"
echo " 启动 webchat:  .venv/bin/python webchat.py 8080"
echo "=========================================="
