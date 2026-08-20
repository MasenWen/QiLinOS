# NexAgent（QiLinOS）

**麒麟 OS Agent**：运行在银河麒麟桌面系统上的智能助手，通过网页对话执行系统操作，并具备多层级记忆体系。

单进程 Python 服务（`webchat.py`），内置 27 个系统工具、4 层记忆存储、可切换的 LLM（麒麟 SDK / OpenAI 兼容 API）。

---

## 功能特性

- **网页聊天**（三栏界面：会话列表 / 对话区 / 记忆与配置面板，黑白主题）
- **27 个系统工具**：文件、Shell（受限白名单）、系统信息（CPU/内存/磁盘/网络/负载）、时区、日期、进程、电池、蓝牙、音量、WiFi、壁纸、截图、电源计划等
- **工具调用闭环**：AI 输出 JSON → 工具执行 → 验证 → 回滚 → 重试 → 降级兜底
- **麒麟 SDK 优先**：系统信息/硬件查询优先走官方 SDK（libky*），SDK 无数据时自动兜底系统命令
- **SDK C 库崩溃隔离**：所有 C 库调用放入子进程执行（`src/sdk/query_ext.py`），主进程永不因 SIGSEGV 崩溃
- **多层级记忆**：
  - 长期记忆（mem0 向量库，语义检索，上限 200 条自动淘汰）
  - 记忆流转（短期 → 中期 → 长期，JSON 持久化）
  - 配置记忆（SKILL，网页输入 → 长期记忆）
  - 日志驱动记忆（对话日志增量扫描，自动提炼动作事件）
  - 记忆防爆炸：同类快照自动裁剪、精确/语义去重
- **LLM 可配置**：默认麒麟 SDK，网页一键切换 OpenAI 兼容 API（DeepSeek/OpenAI 等，模型 + Key 可改）
- **会话管理**：多会话、会话重命名、会话历史服务端持久化、每个会话独立草稿
- **安全设计**：仅绑定 `127.0.0.1`、Shell 命令白名单（含参数级校验）、危险工具（重启/关机/睡眠）拦截、可配置访问令牌

---

## 快速开始

### 前置要求

- 银河麒麟 V11 桌面系统（x86_64）
- Python 3.12
- 麒麟 AI SDK（`/usr/lib/x86_64-linux-gnu/libky*.so`）

### 安装

```bash
# 1. 克隆仓库
git clone git@github.com:MasenWen/QiLinOS.git
cd QiLinOS
git checkout dev1

# 2. 创建虚拟环境并安装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3.（可选）安装 mem0 本地向量库（记忆必需）
.venv/bin/pip install mem0ai==2.0.18 milvus-lite qdrant-client

# 4. 启动
.venv/bin/python webchat.py 8080
```

### systemd 守护（推荐）

```bash
sudo cp deploy/webchat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now webchat
# 自动拉起 + 崩溃重启（Restart=always）
```

### 远程访问

服务只监听 `127.0.0.1`，从其他机器访问需 SSH 隧道：

```bash
ssh -N -L 8080:127.0.0.1:8080 kylin
# 浏览器打开 http://127.0.0.1:8080
```

---

## 架构

```
┌─────────────────────────────────────────────┐
│             浏览器（前端三栏界面）              │
│  会话列表 │ 对话区 │ 记忆/配置面板（模型/技能）  │
└──────────────────┬──────────────────────────┘
                   │ HTTP (127.0.0.1:8080)
┌──────────────────▼──────────────────────────┐
│              webchat.py（主服务）              │
│  · 系统提示词（分场景模板：工具/对话）           │
│  · AI 编排 → JSON 工具调用 → 执行 → 总结        │
│  · 会话持久化 / 草稿 / 日志驱动 / LLM 配置       │
└───────┬──────────────┬──────────────┬────────┘
        │              │              │
┌───────▼───────┐ ┌────▼─────┐ ┌─────▼──────┐
│  src/toolkit  │ │  src/sdk │ │   记忆系统   │
│  27 个工具     │ │  麒麟 SDK │ │ mem0(向量)  │
│  Executor     │ │  绑定     │ │ MemoryFlow │
│  白名单/闭环   │ │ 子进程隔离 │ │ SkillMemory│
│  验证/回滚     │ │ query_ext│ │ log_reader │
└───────────────┘ └──────────┘ └────────────┘
```

### 分层说明

| 层 | 位置 | 职责 |
|---|---|---|
| 服务层 | `webchat.py`（1218 行） | HTTP 服务、提示词模板、AI 编排、前端 HTML/JS、记忆接线 |
| 工具层 | `src/toolkit/` | 27 个工具 + 执行器（execute→verify→rollback→retry→fallback） |
| SDK 层 | `src/sdk/` | 麒麟官方 SDK 绑定（16 库）、C 调用子进程隔离、LLM 客户端 |
| 记忆层 | `src/memory/`、`src/memory_engine/` | mem0 封装、记忆流转、SKILL、遗忘、敏感度 |
| 安全层 | `src/security/` | 威胁扫描、权限规则、审计 |

---

## 工具列表（27 个）

`app` `battery` `bluetooth` `datetime` `directory` `diskinfo` `dns` `file` `music` `netstatus` `notify` `power` `power_idle` `power_plan` `process_kill` `process_list` `proxy` `screensaver` `screenshot` `shell` `sleep` `sysinfo` `timezone` `touchpad` `volume` `wallpaper` `wifi`

- `sysinfo` 支持：cpu / memory / load / disk / network / basic / hostname / uptime / arch / display(EDID) / temp / netspeed
- `shell` 受限管道：命令白名单（ls/du/df/top/cat/find 等）+ 参数级校验（禁止 `;`、`&`、`>`、`<` 及 find 的 `-exec/-delete`）

---

## 记忆系统

| 存储 | 位置 | 内容 |
|---|---|---|
| 长期记忆 | `~/.nex-agent/mem0_vectordb.db` | 事实/偏好，向量检索，上限 200 条 |
| 记忆流转 | `~/.nex-agent/memory_flow.json` | 短期→中期→长期 |
| 配置记忆 | `~/.nex-agent/skills.json` | 网页输入的 SKILL |
| 会话历史 | `~/.nex-agent/sessions.json` | 多会话持久化 |
| 日志驱动 | `~/.nex-agent/conversation.log` | 对话事件，增量扫描入记忆 |
| 知识图谱 | `~/.nex-agent/memory_kg.json` | 记忆节点/边（KG），重复事实自动强化 |

> **全部运行时数据都在 `~/.nex-agent/`，与代码目录分离**——重装/迁移代码不影响记忆数据。

### 记忆引擎能力（`src/memory_engine/`，技术报告第 5/6/9/10 章）

- **四主标签**：`tag_pipeline.py`——condition/obj/preferences/lastingtime 抽取，`remember_fact` 时写入证据（`extractor.tag_pipeline_v1`）
- **MATCHED 六字段输出**：`matched.py`——`MemoryEngine.retrieve_matched()` 返回 KEY/CONDITION/OBJ/PREFERENCE/LASTTIME/TEXT INPUT 结构化结果
- **知识图谱记忆**：`knowledge_graph.py`——节点+边（AYES 强化/DENIES 衰减）、强弱记忆、强相关节点群；`remember_fact` 同步入库，JSON 持久化
- **遗忘曲线**：`forgetting_curve.py`——幂律衰减（艾宾浩斯形态），记忆强度随时间衰减，`reinforce` 强化

---

## LLM 配置

默认使用麒麟 SDK；网页右侧"模型配置"可切换 OpenAI 兼容 API：

```json
// ~/.nex-agent/llm_config.json
{
  "provider": "sdk",                      // 或 "api"
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "",
  "model": "deepseek-chat"
}
```

统一入口 `src/llm_client.py`：`sdk` → 麒麟 SDK；`api` → OpenAI 兼容接口。

---

## 目录结构

```
webchat.py              # 主服务（HTTP + 前端 + AI 编排 + 记忆接线）
src/
├── toolkit/            # 27 个系统工具 + 执行器
├── sdk/                # 麒麟 SDK 绑定 + query_ext.py(子进程) + ai_text + llm_client.py
├── memory/             # mem0 封装、log_reader(日志驱动)
├── memory_engine/      # 记忆流转/遗忘/敏感度/向量检索
├── security/           # 威胁扫描/权限/审计
└── utils/              # DB/日志等
deploy/webchat.service  # systemd 服务单元
docs/                   # 依赖瘦身记录等
```

---

## 部署与运维

- **启动**：`sudo systemctl start webchat`
- **日志**：`project_dev1/webchat.log`（服务日志）、`logs/security_audit.jsonl`（安全审计）
- **重启**：`sudo systemctl restart webchat`
- **数据备份**：`~/.nex-agent/`（记忆/会话/配置）+ 代码仓库（git）

---

## 许可证

见 [LICENSE](LICENSE)
