# 部署到真实麒麟操作系统指南

> 目标：把 OS-Agent（webchat）完整部署到一台真实的银河麒麟桌面系统（非虚拟机）。

## 一、目标环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | 银河麒麟桌面操作系统 V11（SP1/SP2 均可，x86_64） |
| Python | 3.12（项目 `.venv` 基于 3.12 构建） |
| 麒麟 AI SDK | `kylin-ai-runtime` 运行时 + `libky*.so` 系统库（LLM/OCR/硬件接口） |
| MySQL | 8.x（用户画像 DB，可选——无则跳过画像注入） |
| 音频 | `pactl` / `amixer`（音量工具兜底） |
| 磁盘 | 项目 2.5G（含 .venv）+ 记忆数据 ~500M |

## 二、前置安装（在目标机上）

### 1. 麒麟 AI SDK 运行时（LLM/Embedding/OCR 必需）

```bash
# 安装 kylin-ai-runtime（麒麟应用商店或系统镜像自带，也可从官网 SDK 包安装）
sudo apt install kylin-ai-runtime   # 或按官方 SDK 文档安装

# 验证运行时服务
ps aux | grep kylin-ai-runtime      # 应有进程
ls /tmp/.kylin-ai-runtime-unix/     # 应有 socket 目录（如 1000）
```

### 2. 麒麟系统库（libky*）

```bash
# 大部分随桌面系统预装；缺失时从麒麟 SDK 包补齐
ls /usr/lib/x86_64-linux-gnu/libky*.so   # 应含 20+ 个（battery/bluetooth/date/diskinfo/edid/fan/hwinfo/hw/ocr...）
```

> **无 SDK 也可运行**：查询类工具会自动降级到系统命令（df/free/top 等）；LLM 可在网页配置为 OpenAI 兼容 API（DeepSeek 等）——但**官方 SDK 优先**是项目原则。

### 3. MySQL（可选，用户画像）

```bash
sudo apt install mysql-server
sudo mysql -u root -p
# 建库与用户（与 src/utils/db_manager.py 配置一致）
```

## 三、代码部署

```bash
# 1. 获取代码
git clone git@github.com:MasenWen/QiLinOS.git
cd QiLinOS
git checkout dev1

# 2. 虚拟环境
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 记忆系统依赖（mem0 + 本地向量库）
.venv/bin/pip install mem0ai==2.0.18 milvus-lite qdrant-client

# 4. 冒烟自检（确认 import 与 SDK 加载）
.venv/bin/python -c "import webchat; print('webchat OK')"
.venv/bin/python -c "from src.sdk import ai_vision; print('OCR SDK:', ai_vision.is_available())"
```

## 四、配置

### 1. 访问令牌（可选但推荐）

```bash
# 启动前设置环境变量（或写进 systemd 服务）
export WEBCHAT_TOKEN='你的访问令牌'
# 前端请求需带 X-Api-Token 头；不设置则本机直连免认证
```

### 2. LLM 配置（默认麒麟 SDK，无需配置）

- 默认 `provider=sdk`：自动使用 `kylin-ai-runtime` 的本地大模型
- 可选切换：网页右侧"模型配置" → 自定义 API（如 DeepSeek），持久化 `~/.nex-agent/llm_config.json`
- SDK 不可用时：直接配 API 即可工作

### 3. 防火墙（可选）

webchat 只监听 `127.0.0.1`，无需开放端口；远程访问用 SSH 隧道：

```bash
ssh -N -L 8080:127.0.0.1:8080 kylin
```

## 五、systemd 托管（推荐）

```bash
sudo cp deploy/webchat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now webchat
# 崩溃自动重启（Restart=always）；日志在 project_dev1/webchat.log
```

## 六、验证清单

| 类别 | 命令（网页对话） | 预期 |
|---|---|---|
| 基础 | "当前时区是什么" | 返回时区 ✅ |
| SDK 查询 | "CPU 占用率" / "内存" / "磁盘" | 官方 SDK 数据或 df 兜底 ✅ |
| 记忆 | "记住我喜欢简洁报告" → 刷新右侧记忆面板 | 出现新记忆 ✅ |
| OCR | "识别图片 ~/图片/xx.png 的文字" | 返回识别文本 ✅（真实硬件/虚拟机均可） |
| 真实硬件差异 | "显示器信息" "电池电量" "蓝牙" "触摸板" | 真机有真实数据（虚拟机可能无设备）|
| 文件 | "在桌面建文件夹放5个md文件" | 5 个文件 ✅ |
| 危险拦截 | "关机" | 被拦截（power 禁用）✅ |

## 六、代码更新体系（推 GitHub 即上线）

### 工具清单（deploy/ 下）

| 工具 | 用途 |
|---|---|
| `install.sh` | 首次安装（venv + 依赖 + systemd） |
| `update.sh` | 一键更新：git pull → 检测依赖变更重装 → 重启 webchat |
| `webhook_server.py` | GitHub Webhook 监听（推送 dev1 即自动 update.sh） |
| `rollback.sh` | 回滚到上一版本/指定提交并重启 |

### 三种更新方式

**① 手动更新**（任何时候可跑）
```bash
bash deploy/update.sh
```

**② Webhook 全自动**（推送即上线，需公网）
```bash
# 1. 启动监听器（systemd 托管建议）
WEBHOOK_SECRET=你的密钥 nohup .venv/bin/python deploy/webhook_server.py 9000 &

# 2. GitHub → 仓库 Settings → Webhooks → Add webhook
#    Payload URL: http://<公网IP>:9000/github-webhook
#    Content type: application/json
#    Secret: 你的密钥（HMAC-SHA256 校验）
#    Events: 勾选 Push

# 3. 之后每次 git push dev1 → 服务器自动更新并重启
#    安全: 签名错误 3 次自动封禁 IP 10 分钟；日志 logs/webhook.log
```

**③ crontab 兜底**（无需公网，定期检查）
```bash
crontab -e
# 每 10 分钟检查一次，有更新自动部署
*/10 * * * * cd /path/to/QiLinOS && git fetch origin dev1 -q && \
  [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/dev1)" ] && \
  bash deploy/update.sh >> logs/auto_update.log 2>&1
```

**回滚**（更新出问题时）
```bash
bash deploy/rollback.sh          # 回退到上一版本
bash deploy/rollback.sh abc1234  # 回退到指定提交
```

> 建议组合：**② 实时 + ③ 兜底**双保险；出问题立即 ④ 回滚。

## 七、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 对话报 `milvus-lite is required` | mem0 缺向量库 | `pip install milvus-lite` |
| SDK 查询"不可用" | libky* 缺失或版本不符 | 装对应麒麟 SDK 包；或接受系统命令兜底 |
| 记忆为空 | `~/.nex-agent` 无数据或向量库锁 | 首次会自动初始化；确认磁盘可写 |
| 语音/LLM 慢 | kylin-ai-runtime 未启动 | `systemctl start kylin-ai-runtime` 或重启服务 |
| 网页打不开 | 隧道未建/服务未起 | `bash ~/open-webchat.sh`（本机）或 systemctl status |
| OCR 中文识别差 | SDK 模型限制 | 换更清晰图片；后续可接入 PaddleOCR 等 |

## 八、数据位置速查

- 代码：`QiLinOS/`（git 管理，随时可从 GitHub 恢复）
- 记忆/会话/配置：`~/.nex-agent/`（**备份此目录 = 备份全部用户数据**）
- 日志：`QiLinOS/webchat.log`（服务）、`QiLinOS/logs/security_audit.jsonl`（安全审计）
