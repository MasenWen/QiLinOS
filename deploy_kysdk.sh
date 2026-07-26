#!/bin/bash
# ============================================================
# 麒麟 SDK (kysdk) 完整部署脚本
# 适用系统：银河麒麟 / openKylin / Debian
# 在目标 Kylin 机器上执行：bash deploy_kysdk.sh
# ============================================================

set -e

echo "========================================"
echo "  麒麟 kysdk 开发者套件部署"
echo "========================================"

# ---- 步骤 1：检查是否为 Kylin 系统 ----
echo ""
echo "[1/4] 检查系统环境..."

if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "  系统: $NAME $VERSION"
else
    echo "  ⚠️  未检测到 /etc/os-release，继续尝试安装..."
fi

# ---- 步骤 2：添加 kysdk 源（非 Kylin 系统需要）----
echo ""
echo "[2/4] 配置 apt 软件源..."

KYLIN_SOURCE="/etc/apt/sources.list.d/kysdk.list"

# 检查是否已经是 Kylin 系统
IS_KYLIN=false
if [ -f /etc/os-release ]; then
    . /etc/os-release
    case "$ID" in
        kylin|openkylin|ubuntukylin|Kylin|openKylin)
            IS_KYLIN=true
            ;;
    esac
fi

if [ "$IS_KYLIN" = true ]; then
    echo "  ✅ 检测到 Kylin 系统，无需额外添加软件源"
else
    echo "  非 Kylin 系统，添加 kysdk 源..."
    if [ ! -f "$KYLIN_SOURCE" ]; then
        sudo tee "$KYLIN_SOURCE" > /dev/null <<'EOF'
deb http://archive.kylinos.cn/kylin/KYLIN-ALL developer-kits main restricted universe
EOF
        echo "  ✅ 已添加 kysdk 源到 $KYLIN_SOURCE"
    else
        echo "  ✅ kysdk 源已存在"
    fi
fi

# ---- 步骤 3：更新 apt 并安装 ----
echo ""
echo "[3/4] 更新软件源..."

sudo apt update

echo ""
echo "[4/4] 安装 kysdk 开发包..."

# -------- 基础 SDK --------
echo "  → 基础开发 SDK (日志、配置、工具函数)"
sudo apt install -y libkysdk-base-dev

# -------- 系统能力 SDK --------
echo "  → 系统能力 SDK (硬件信息、系统信息、磁盘、网络、电池)"
sudo apt install -y libkysdk-system-dev

# -------- 桌面环境 SDK --------
echo "  → 桌面环境 SDK (桌面控制、声音、通知、快捷键、主题、应用管理)"
sudo apt install -y libkysdk-desktop-dev

# -------- 系统安全 SDK --------
echo "  → 系统安全 SDK"
sudo apt install -y libkysdk-security-dev

# -------- AI SDK --------
echo "  → AI SDK - 文字识别 (OCR)"
sudo apt install -y libkysdk-coreai-vision-dev

echo "  → AI SDK - AI 公共库"
sudo apt install -y kysdk-ai-common || echo "  ⚠️  kysdk-ai-common 安装失败（可能不存在），跳过"

# -------- Python 绑定 --------
echo "  → Python 绑定"
sudo apt install -y libkysdk-system-python || echo "  ⚠️  libkysdk-system-python 安装失败（可能不存在），跳过"

# -------- 桌面子模块（独立安装，防止遗漏）-------
echo "  → 桌面环境子模块"
sudo apt install -y libkysdk-soundeffects-dev || echo "  ⚠️  跳过"
sudo apt install -y libkysdk-notification-dev || echo "  ⚠️  跳过"
sudo apt install -y libkysdk-appmanager-dev || echo "  ⚠️  跳过"
sudo apt install -y libkysdk-thememanager-dev || echo "  ⚠️  跳过"

echo ""
echo "========================================"
echo "  ✅ 部署完成！"
echo "========================================"
echo ""
echo "已安装的包列表："
dpkg -l | grep -E "libkysdk|kysdk" | awk '{print "  " $2, $3}'
echo ""
echo "头文件位置："
echo "  /usr/include/kysdk/"
ls /usr/include/kysdk/ 2>/dev/null || echo "  (请检查实际路径)"
echo ""
echo ".so 库位置："
echo "  /usr/lib/x86_64-linux-gnu/"
ls /usr/lib/*/libkysdk-* 2>/dev/null | head -10 || echo "  (请检查实际路径)"
echo ""
echo "Python 绑定位置（如已安装）："
python3 -c "import kysdk" 2>/dev/null && echo "  ✅ Python kysdk 模块可用" || echo "  ⚠️  Python 绑定不可用，需通过 ctypes 调用 .so"
