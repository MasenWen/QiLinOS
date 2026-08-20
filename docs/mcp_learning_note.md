# MCP 注册命令与工具限制学习笔记（Codex vs Claude Code）

> 调研日期：2026-08-20
> 工具版本：Claude Code 2.1.70 / Codex CLI 0.145.0（本机实测 `--help` + 官方文档）

## 一、MCP 服务器注册命令

### Claude Code（`claude mcp`）

```bash
# 注册（默认 stdio 传输）
claude mcp add my-server -- npx my-mcp-server
claude mcp add my-server -- my-command --some-flag arg1

# HTTP / SSE 传输
claude mcp add --transport http sentry https://mcp.sentry.dev/mcp
claude mcp add --transport sse my-server https://example.com/mcp

# 环境变量（stdio 场景）
claude mcp add -e API_KEY=xxx my-server -- npx my-mcp-server

# HTTP 认证头
claude mcp add --transport http corridor https://app.corridor.dev/api/mcp \
  --header "Authorization: Bearer ..."

# 配置作用域
claude mcp add -s local   <name> ...   # 当前项目本地
claude mcp add -s user    <name> ...   # 用户级（~/.claude.json）
claude mcp add -s project <name> ...   # 项目级（.mcp.json，随仓库分发）

# JSON 形式添加（stdio/SSE）
claude mcp add-json my-server '{"type":"stdio","command":"npx","args":["x"]}'

# 从 Claude Desktop 导入（Mac/WSL）
claude mcp add-from-claude-desktop

# 管理
claude mcp list / get <name> / remove <name>
claude mcp serve            # 把 Claude Code 自身作为 MCP server 暴露
claude mcp reset-project-choices
```

**配置位置**：
- 项目级：仓库根 `.mcp.json`（可提交共享）
- 用户级：`~/.claude.json`（`mcpServers` 字段）
- 本地：当前项目 `.claude/settings.json` 附近

### Codex CLI（`codex mcp`）

```bash
# 注册 stdio 服务器
codex mcp add my-tool -- my-command
codex mcp add my-tool -- npx -y @some/mcp-server

# 注册 streamable HTTP 服务器
codex mcp add my-tool --url https://mcp.example.com/mcp

# 环境变量（仅 stdio）
codex mcp add my-tool --env KEY=VALUE -- my-command

# HTTP Bearer 认证（token 从环境变量读，不落盘明文）
codex mcp add my-tool --url https://... --bearer-token-env-var MY_TOKEN_ENV

# 远程服务器认证
codex mcp login / logout

# 管理
codex mcp list / get <name> / remove <name>
```

**配置位置**：`~/.codex/config.toml`

```toml
[mcp_servers.my-tool]
command = "my-command"
args = ["--flag"]
env = { KEY = "VALUE" }

[mcp_servers.remote]
url = "https://mcp.example.com/mcp"
bearer_token_env_var = "MY_TOKEN_ENV"
```

## 二、工具限制（权限模型）

### Claude Code

| 机制 | 命令/配置 | 说明 |
|---|---|---|
| 内置工具白名单 | `--tools "Bash,Edit,Read"` | `""` 禁用全部 / `"default"` 全量 / 指定工具名 |
| 细粒度允许 | `--allowedTools "Bash(git:*) Edit"` | 工具名 + 子命令过滤（`Bash(git:*)` 只允许 git 子命令）|
| 细粒度拒绝 | `--disallowedTools "Bash(rm:*)"` | 拒绝特定工具/子命令 |
| 权限模式 | `--permission-mode <mode>` | `acceptEdits` / `bypassPermissions` / `default` / `dontAsk` / `plan` |
| 目录限制 | `--add-dir <dirs>` | 工具可访问的额外目录 |
| 危险旁路 | `--allow-dangerously-skip-permissions` | 需显式启用，建议隔离环境 |
| 持久规则 | `settings.json` permissions | allow/deny/ask + 工具 + 正则匹配 |

> **MCP 服务器工具遵循同一权限体系**：每个 MCP 工具可单独 allow/deny/ask。

### Codex CLI

| 机制 | 命令/配置 | 说明 |
|---|---|---|
| 沙箱模式 | `--sandbox <mode>` | `read-only` / `workspace-write` / `danger-full-access` 三档 |
| 审批策略 | `--ask-for-approval <policy>` | `on-failure` / `never` / `untrusted-tools` |
| 磁盘权限 | `sandbox_permissions` | 细粒度，如 `["disk-full-read-access"]` |
| 危险旁路 | `--dangerously-bypass-approvals-and-sandbox` | 极度危险，仅限外部已沙箱环境 |
| 持久配置 | `~/.codex/config.toml` | `approval_policy` / `sandbox_mode` / `shell_environment_policy` |

> **MCP 工具默认视为不可信**：在 `untrusted-tools` 审批策略下，MCP 工具调用需用户确认。

## 三、关键差异对照

| 维度 | Claude Code | Codex |
|---|---|---|
| MCP 传输 | stdio / SSE / HTTP | stdio / streamable HTTP |
| 配置作用域 | project（.mcp.json）/ user / local | 全局 config.toml（+ `--config` 逐项覆盖）|
| 认证方式 | OAuth（HTTP/SSE）+ header | bearer-token-env-var + login/logout |
| 工具限制粒度 | 工具名 + 子命令（`Bash(git:*)`）| 沙箱模式 + 审批策略（粗粒度）|
| MCP 工具信任 | 进入统一权限体系，可逐工具设置 | 默认不可信，需审批 |
| 危险旁路开关 | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` |

## 四、对我们项目（webchat / OS-Agent）的启示

现有设计已部分对齐，可借鉴补强：

| 我们的现状 | 对应概念 | 可借鉴改进 |
|---|---|---|
| shell 白名单 `READONLY_CMDS/WRITE_CMDS` | Claude `--tools` / Codex sandbox | 支持"工具+子命令"粒度（如 `Bash(git:*)`）|
| 危险工具拦截（power/sleep/datetime）| approval 机制 | 改为可配置 ask/deny 策略 |
| shell 参数级校验（禁 `;`/`&`/find -exec）| 细粒度工具过滤 | 保持，可扩展正则规则 |
| 子进程隔离（query_ext/ocr）| Codex sandbox 精神 | 保持一致 |
| 无 MCP 支持 | — | 若加 MCP：学 `claude mcp add`（stdio/http、env、scope）+ Codex 的"MCP 工具默认 ask"策略 |
