#!/bin/bash
# OS-Agent（麒麟 webchat）一键安装脚本
# 用法: bash install.sh [--no-systemd]
# 默认: 创建 venv + 装依赖 + 注册 systemd 服务

set -e
cd "$(dirname "$0")/.."   # 脚本在 deploy/ 下，回到项目根

echo "=== OS-Agent 安装开始 ==="
echo "工作目录: $(pwd)"

# 1. Python 版本检查
PY=python3
$PY --version | grep -q "3.12" || echo "⚠ 建议 Python 3.12（当前: $($PY --version)）"

# 2. 创建虚拟环境
if [ ! -d .venv ]; then
    echo "--- 创建虚拟环境 .venv ---"
    $PY -m venv .venv
fi

# 3. 安装依赖（清华源加速）
echo "--- 安装依赖 requirements.txt ---"
.venv/bin/pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple -q
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 30 --retries 2

# 4. 记忆系统依赖（mem0 + 本地向量库）
echo "--- 安装记忆系统依赖 ---"
.venv/bin/pip install mem0ai==2.0.18 milvus-lite qdrant-client -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 30 --retries 2

# 4.5 知识库依赖（LightRAG 需要 spacy 模型；GitHub 下载较慢）
echo "--- 安装 spacy 中文模型（知识库 RAG 用）---"
.venv/bin/pip install en-core-web-sm 2>/dev/null || \
  curl -sL -o /tmp/en_core_web_sm.whl https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl && \
  .venv/bin/pip install /tmp/en_core_web_sm.whl || echo "⚠ spacy 模型未装（知识库功能不可用，可稍后手动装）"

# 5. 冒烟自检
echo "--- 冒烟自检 ---"
.venv/bin/python -c "import webchat; print('✅ webchat import OK')"
.venv/bin/python -c "from src.sdk import ai_vision; print('✅ OCR SDK:', ai_vision.is_available())"

# 6. systemd 托管（可选）
if [ "$1" != "--no-systemd" ]; then
    echo "--- 注册 systemd 服务 ---"
    sudo cp deploy/webchat.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable webchat || true
    sudo systemctl restart webchat || true
    echo "✅ systemd 服务已注册: sudo systemctl status webchat"
else
    echo "--- 跳过 systemd（手动启动）---"
    echo "启动: nohup .venv/bin/python webchat.py 8080 > webchat.log 2>&1 &"
fi

echo
echo "=== 安装完成 ==="
echo "访问: http://127.0.0.1:8080 （远程需 SSH 隧道: ssh -N -L 8080:127.0.0.1:8080 用户名@主机）"
