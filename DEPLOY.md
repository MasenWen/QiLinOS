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
git clone <你的仓库地址>
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
# 崩溃自动重启（Restart=always）；日志在 QiLinOS/webchat.log
```

## 六、验证清单

| 类别 | 命令（网页对话） | 预期 |
|---|---|---|
| 基础 | "当前时区是什么" | 返回时区 ✅ |
| SDK 查询 | "CPU 占用率" / "内存" / "磁盘" | 官方 SDK 数据或 df 兜底 ✅ |
| 记忆 | "记住我喜欢简洁报告" → 刷新右侧记忆面板 | 出现新记忆 ✅ |
| OCR | "识别图片 ~/图片/xx.png 的文字" | 返回识别文本 ✅（真实硬件/虚拟机均可） |
| 知识库 | "把这句话加入知识库：服务器叫 kylin-pc" → "查询知识库：服务器叫什么" | 入库 + 正确回答 ✅（首次 kb 调用初始化约 1-2 分钟） |
| 真实硬件差异 | "显示器信息" "电池电量" "蓝牙" "触摸板" | 真机有真实数据（虚拟机可能无设备）|
| 文件 | "在桌面建文件夹放5个md文件" | 5 个文件 ✅ |
| 危险拦截 | "关机" | 被拦截（power 禁用）✅ |

> **知识库（RAG）说明**：kb 工具默认 provider=kylin（麒麟知识库 SDK，仅桌面会话 D-Bus 可用，SSH 环境自动隐藏）；`provider=lightrag` 显式走内置 LightRAG（Faiss + GTE-base，数据存 `~/.nex-agent/rag_storage/`）。LightRAG 首次调用需下载 spacy en_core_web_sm 模型——`install.sh` 已含自动安装步骤（GitHub 源，失败不阻塞，kb 首次调用会重试）。

## 六、代码更新体系（推 GitHub 即上线）

### 工具清单（deploy/ 下）

| 工具 | 用途 |
|---|---|
| `install.sh` | 首次安装（venv + 依赖 + systemd + **桌面快捷方式**） |
| `make-shortcut.sh` | 生成/刷新/卸载「麒麟记忆」桌面图标与启动器（`--check` 自检、`--autostart` 开机自启、`--uninstall` 卸载） |
| `assets/kylin-mem.png` | 快捷方式图标（随包分发） |
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
# 1. 配置密钥（HMAC 校验用；服务器上已生成于 /etc/webhook.env，600 权限）
sudo bash -c 'echo "WEBHOOK_SECRET=$(openssl rand -hex 32)" > /etc/webhook.env && chmod 600 /etc/webhook.env'

# 2. 注册并启动监听器（systemd 托管，deploy/webhook.service 已提供）
sudo cp deploy/webhook.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now webhook

# 3. GitHub → 仓库 Settings → Webhooks → Add webhook
#    Payload URL: http://<公网IP>:9000/github-webhook
#    Content type: application/json
#    Secret: /etc/webhook.env 里的 WEBHOOK_SECRET（HMAC-SHA256 校验）
#    Events: 勾选 Push

# 4. 之后每次 git push dev1 → 服务器自动更新并重启
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


## 九、桌面快捷方式（安装自动生成）

`install.sh` 安装完成后会**自动**在「桌面 + 应用菜单」生成「麒麟记忆」图标，双击即打开
`http://127.0.0.1:8080/`；若服务未运行，启动器会先 `systemctl start webchat` 再等 HTTP 200（最多 30s）。

产物（路径按实际用户/项目目录生成，不含机器专属常量）：

| 位置 | 内容 |
|---|---|
| `~/桌面/麒麟记忆.desktop` | 桌面图标（已 `chmod +x`、`gio metadata::trusted` 标记） |
| `~/.local/share/applications/kylin-mem.desktop` | 应用菜单项 |
| `~/.local/bin/kylin-mem-open` | 启动器（`--check` 仅自检、不起浏览器） |
| `~/.config/autostart/kylin-mem.desktop` | 仅 `--desktop-autostart` / `--autostart` 时生成 |

常用命令：

```bash
bash deploy/install.sh                    # 安装（默认生成快捷方式）
bash deploy/install.sh --no-desktop       # 安装但跳过快捷方式
bash deploy/install.sh --desktop-autostart# 安装 + 快捷方式 + 开机自启
bash deploy/make-shortcut.sh              # 单独生成/刷新（幂等，重复执行安全）
bash deploy/make-shortcut.sh --check      # 自检：打印路径与安装状态
bash deploy/make-shortcut.sh --uninstall  # 卸载快捷方式与启动器
PORT=9090 bash deploy/make-shortcut.sh    # 自定义端口
```

说明：桌面目录按 `xdg-user-dir DESKTOP` 解析（中文系统为 `~/桌面`），回退 `~/Desktop`；
图标缺失时退回首选 `applications-internet` 主题图标。若桌面图标显示为文本文件样式，
右键 → 允许启动/信任 一次即可（部分文件管理器首次需要）。

## 十、快捷方式打不开？先跑自检

```bash
# 在目标主机上，用【桌面登录用户】执行（不要加 sudo）
cd ~/kylin-mem      # 或实际项目目录
bash deploy/doctor.sh            # 一键体检（只读，不改配置）
bash deploy/doctor.sh --verbose  # 附打印桌面项内容
```

`doctor.sh` 逐项检查并给出修复命令：服务/端口/HTTP → 快捷方式三件套（桌面图标、应用菜单、启动器）
→ 桌面项语法与 Exec/Icon 有效性 → **浏览器是否可用** → 常见坑位（sudo 装到 /root、桌面目录中英文不一致等）。

### 最常见原因（按概率排序）

| 现象 | 原因 | 修复 |
|---|---|---|
| 双击图标毫无反应 | **系统里没有任何图形浏览器**（麒麟最小安装常见；`xdg-open` 静默失败） | `sudo apt update && sudo apt install -y firefox && xdg-settings set default-web-browser firefox.desktop` |
| 双击显示为文本/被问“是否执行” | 桌面项未标记可信 | `gio set ~/桌面/麒麟记忆.desktop metadata::trusted true`，或右键→允许启动 |
| 图标是文本文件样式且点了没反应 | 用 `sudo` 跑安装 → 装到 /root | 用桌面用户重跑 `bash deploy/make-shortcut.sh`；删掉 `/root/.local/share/applications/kylin-mem.desktop` |
| 双击后浏览器打开但页面打不开 | 服务未运行/端口未监听 | `systemctl status webchat` ｜ `journalctl -u webchat -n 50 --no-pager` |
| 完全查不到线索 | 启动器已内置日志 | `tail -20 ~/.local/state/kylin-mem-open.log`（每次双击都会写一行） |

> 启动器现在自带日志与浏览器多级回退（firefox/chromium/kylin-browser… → xdg-open），
> 若没有任何浏览器会弹出桌面通知提示安装，不再“静默失败”。
>
> 常用命令：`bash deploy/make-shortcut.sh --check`（看产物路径与状态）、
> `bash deploy/make-shortcut.sh --uninstall`（卸载快捷方式，服务不受影响）。

## 十一、主机（形态 B）快捷方式点了没反应：三步定位

主机上没有服务器那套 systemd 命令经验，按下面三步走，**每步都会留下证据**。

### 第 1 步：确认"点击"有没有真的执行脚本

```bash
tail -5 ~/.local/state/kylin-mem-open.log
date '+%F %T'
```

- 日志最后一条时间 **早于**你刚点击的时间 → 点击没触发脚本，看第 2 步
- 有刚刚的记录、且写着 `失败：没有可用浏览器` → 看第 3 步
- 完全没有这个文件 → 启动器从未被执行（也看第 2 步）

### 第 2 步：桌面项本身能不能被执行

```bash
ls -la ~/桌面/麒麟记忆.desktop                      # 需要 -rwx（可执行）
gio info ~/桌面/麒麟记忆.desktop | grep trusted      # 需要 metadata::trusted: true
gio launch ~/桌面/麒麟记忆.desktop                   # 手动触发一次，等价于双击
```

- 不可执行：`chmod +x ~/桌面/麒麟记忆.desktop`
- 未标记可信：`gio set ~/桌面/麒麟记忆.desktop metadata::trusted true`，或右键 → 允许启动/信任
- 仍点不开：先用**开始菜单**里搜「麒麟记忆」（菜单项不受桌面可信标记影响），或终端直接跑
  `~/.local/bin/kylin-mem-open`

### 第 3 步：系统里有没有浏览器

```bash
for b in firefox chromium chromium-browser kylin-browser browser360 qaxbrowser; do
  command -v $b || echo "$b: 无"
done
```

一个都没有 → **这就是"点了没反应"的根因**（服务在跑、页面也在，但没有程序能显示它）：

```bash
sudo apt update && sudo apt install -y firefox
xdg-settings set default-web-browser firefox.desktop   # 可选，设为默认
```

> 麒麟最小安装默认不带浏览器；`xdg-open` 在没有浏览器时会**静默失败**，
> 加上桌面项 `Terminal=false`，现场就表现为"什么都没发生"。

### 一条命令搞定体检 + 重建

```bash
cd <项目目录>
bash deploy/fix-shortcut-standalone.sh          # 自包含：体检 + 重建桌面图标/菜单项/启动器
bash deploy/fix-shortcut-standalone.sh --check  # 只体检，不写文件
```

该脚本还会：检查点击链路日志、探测浏览器、在服务未就绪时给出日志路径；
若系统确实没有浏览器，会写一份 `~/麒麟记忆-缺少浏览器.txt` 提示修复命令。
