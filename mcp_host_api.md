# MCP Host 接口文档（Markdown 版）

> 基础思路：  
> - 先把 **Server** 连上（connect）。  
> - 用 **工具查询**（/servers/.../tools）了解每个工具的 `inputSchema`。  
> - 进行 **agent** 级调用：`plan`（只出方案）、`ask`（执行1个）、`select/ask_plus/answer`（进阶：多候选并发与汇总）。  

---

## 通用信息

- **Base URL**：`http://127.0.0.1:50066`
- **Headers**：`Content-Type: application/json`（POST 时）
- **返回里的常见字段**：
  - `request_id`：请求追踪 ID  
  - `parts`：工具原始文本分片（数组，元素含 `type`、`text`）  
  - `raw_repr`：底层内容快照（调试/排障）  

---

## 目录
- [健康检查](#健康检查)
- [Server 与工具管理](#server-与工具管理)
  - [/servers/registry](#get-serversregistry)
  - [/servers/{name}/connect](#post-serversnameconnect)
  - [/servers/{name}/disconnect](#post-serversnamedisconnect)
  - [/servers](#get-servers)
  - [/servers/{name}](#get-serversname)
  - [/servers/{name}/tools](#get-serversnametools)
  - [/servers/{name}/tools/{tool_name}](#get-serversnametoolstool_name)
  - [/servers/{name}/tools/{tool_name}（调用）](#post-serversnametoolstool_name)
- [批量与工作流](#批量与工作流)
  - [/batch/tools](#post-batchtools)
  - [/workflow/run](#post-workflowrun)
- [日志](#日志)
  - [/logs](#get-logs)
- [Agent（基础）](#agent基础)
  - [/agent/plan](#post-agentplan)
  - [/agent/ask](#post-agentask)
- [Agent（进阶）](#agent进阶)
  - [/agent/select](#post-agentselect)
  - [/agent/ask_plus](#post-agentask_plus)
  - [/agent/answer](#post-agentanswer)
- [常见问题](#常见问题快速提示)

---

## 健康检查

### GET `/healthz`
**用途**：探活。

**响应示例**
```json
{ "ok": true }
```

**curl**
```bash
curl -X GET http://127.0.0.1:50066/healthz
```

---

## Server 与工具管理

### GET `/servers/registry`
**用途**：查看注册表（本地配置）及当前连接状态。

**响应示例（部分）**
```json
{
  "servers": [
    { "name": "gdmap_server", "abs_path": "./mcp_server/server/gdmap_server.py", "auto_start": true, "connected": true }
  ]
}
```

**curl**
```bash
curl -X GET http://127.0.0.1:50066/servers/registry
```

---

### POST `/servers/{name}/connect`
**用途**：连接并启动某 server。  
**请求体**
```json
{ "path": "./mcp_server/server/gdmap_server.py" }   // 可选；为空则用注册表里的 abs_path
```

**响应示例**
```json
{ "server": "gdmap_server", "path": "./mcp_server/server/gdmap_server.py", "connected": true, "request_id": "..." }
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/servers/gdmap_server/connect \
  -H 'Content-Type: application/json' \
  -d '{"path":"./mcp_server/server/gdmap_server.py"}'
```

---

### POST `/servers/{name}/disconnect`
**用途**：断开某 server。  

**响应示例**
```json
{ "server": "gdmap_server", "connected": false, "request_id": "..." }
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/servers/gdmap_server/disconnect
```

---

### GET `/servers`
**用途**：列出当前 **已连接** 的 server 名称数组。

**响应示例**
```json
{ "servers": ["gdmap_server","bdmap_server","filesystem_server"] }
```

**curl**
```bash
curl -X GET http://127.0.0.1:50066/servers
```

---

### GET `/servers/{name}`
**用途**：查看某个 server 的状态（是否连接/是否在注册表、路径等）。

**响应示例**
```json
{
  "server":"gdmap_server",
  "connected":true,
  "registered":true,
  "description":"...",
  "auto_start":true,
  "abs_path":"./mcp_server/server/gdmap_server.py"
}
```

**curl**
```bash
curl -X GET http://127.0.0.1:50066/servers/gdmap_server
```

---

### GET `/servers/{name}/tools`
**用途**：列出某 server 的工具。  
**响应示例（部分）**
```json
{
  "server":"gdmap_server",
  "tool_count": 5,
  "tools":[
    {
      "name":"maps_geo",
      "description":"将地址转换为经纬度",
      "inputSchema":{
        "type":"object",
        "properties":{"address":{"type":"string"}, "city":{"type":"string"}},
        "required":["address"]
      }
    }
  ]
}
```

**curl**
```bash
curl -X GET http://127.0.0.1:50066/servers/gdmap_server/tools
```

---

### GET `/servers/{name}/tools/{tool_name}`
**用途**：查看单个工具的 Schema 与描述。  
**响应示例**
```json
{
  "server":"gdmap_server",
  "tool":"maps_geo",
  "schema":{ "...inputSchema..." },
  "description":"将地址转换为经纬度"
}
```

**curl**
```bash
curl -X GET http://127.0.0.1:50066/servers/gdmap_server/tools/maps_geo
```

---

### POST `/servers/{name}/tools/{tool_name}`
**用途**：直接调用某个工具。  
**请求体**
```json
{ "args": { "address": "长沙市", "city": "长沙市" } }
```

**响应示例（部分）**
```json
{
  "server":"gdmap_server",
  "tool":"maps_geo",
  "args":{"address":"长沙市","city":"长沙市"},
  "result":{
    "parts":[{"type":"text","text":"{ \"return\": [ { \"location\": \"112.93,28.22\" } ] }"}],
    "raw_repr":"..."
  },
  "request_id":"..."
}
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/servers/gdmap_server/tools/maps_geo \
  -H 'Content-Type: application/json' \
  -d '{"args":{"address":"长沙市","city":"长沙市"}}'
```

---

## 批量与工作流

### POST `/batch/tools`
**用途**：**并发**调用多个工具。  
**请求体**
```json
{
  "calls": [
    { "server":"gdmap_server", "tool":"maps_geo", "args":{"address":"长沙市"}, "timeout_ms":10000 },
    { "server":"bdmap_server", "tool":"geo", "args":{"address":"长沙市"} }
  ]
}
```

**响应示例（部分）**
```json
{
  "count": 2,
  "results": [
    { "ok": true,  "server":"gdmap_server", "tool":"maps_geo", "result":{...}, "elapsed_ms": 220 },
    { "ok": false, "server":"bdmap_server", "tool":"geo",      "error":"timeout" }
  ]
}
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/batch/tools \
  -H 'Content-Type: application/json' \
  -d '{"calls":[{"server":"gdmap_server","tool":"maps_geo","args":{"address":"长沙市"}}]}'
```

---

### POST `/workflow/run`
**用途**：**顺序**执行多个步骤，支持模板把上一步文本结果注入下一步参数。  
**请求体（示例）**
```json
{
  "steps": [
    { "name":"step1","server":"gdmap_server","tool":"maps_geo","args":{"address":"长沙市"} },
    { "name":"step2","server":"web_search_server","tool":"search","args_template":{"q":"长沙市经纬度 {{step1.result}}"} }
  ],
  "stop_on_error": true
}
```

**响应示例（部分）**
```json
{
  "ok": true,
  "steps": [
    { "name":"step1","ok":true,"result":{...}},
    { "name":"step2","ok":true,"result":{...}}
  ]
}
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/workflow/run \
  -H 'Content-Type: application/json' \
  -d '{"steps":[{"server":"gdmap_server","tool":"maps_geo","args":{"address":"长沙市"}}]}'
```

---

## 日志

### GET `/logs`
**用途**：查询审计日志（可筛选）。  
**Query 参数**：`limit`、`event`、`server`、`tool`、`success`  
**响应示例**
```json
{ "logs":[ { "ts":"...","event":"tool_call_end","server":"gdmap_server","tool":"maps_geo", ... } ] }
```

**curl**
```bash
curl -X GET 'http://127.0.0.1:50066/logs?limit=50&server=gdmap_server'
```

---

## Agent（基础）

### POST `/agent/plan`
**用途**：**只做规划**（LLM 选择 1 个 `server.tool`，并生成 `args`），**不执行**。  
**请求体**
```json
{ "query": "查询长沙市的经纬度" }
```

**响应示例**
```json
{
  "used_llm": true,
  "plan": { "server":"gdmap_server", "tool":"maps_geo", "args":{"address":"长沙市","city":"长沙市"} },
  "available_tools": 42,
  "request_id": "..."
}
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/agent/plan \
  -H 'Content-Type: application/json' \
  -d '{"query":"查询长沙市的经纬度"}'
```

---

### POST `/agent/ask`
**用途**：**规划 + 执行 + 总结**（只选 1 个工具）。  
**请求体**
```json
{ "query": "查询长沙市的经纬度", "timeout_ms": 10000, "dry_run": false }
```

**响应示例（部分）**
```json
{
  "executed": true,
  "used_llm_plan": true,
  "used_llm_answer": true,
  "plan": { "server":"gdmap_server", "tool":"maps_geo", "args":{...} },
  "result": { "parts":[...], "raw_repr":"..." },
  "answer": "长沙市的经纬度是……",
  "request_id": "..."
}
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/agent/ask \
  -H 'Content-Type: application/json' \
  -d '{"query":"查询长沙市的经纬度","timeout_ms":10000}'
```

> **注意**：内部已做 LLM 参数补全与“地理类 address 清洗”（把整句换成“长沙市”等），尽可能降低 500 错误概率；若 schema 仍有必填缺失，会返回 `clarification_needed:true` 提示缺少字段。

---

## Agent（进阶）

### POST `/agent/select`
**用途**：**LLM 自主挑多个候选**（1..N，非固定 K），每个候选包含 `server/tool/args/reason`。  
**请求体**
```json
{
  "query": "查询长沙市的经纬度",
  "allow_servers": ["gdmap_server","bdmap_server"], // 可选；不填=全量
  "deny_servers": [],
  "max_candidates": 6
}
```

**响应示例**
```json
{
  "request_id":"...",
  "query":"查询长沙市的经纬度",
  "candidates":[
    { "server":"gdmap_server","tool":"maps_geo","args":{"address":"长沙市"},"reason":"地址转坐标" },
    { "server":"bdmap_server","tool":"geo","args":{"address":"长沙市"},"reason":"备用源" }
  ]
}
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/agent/select \
  -H 'Content-Type: application/json' \
  -d '{"query":"查询长沙市的经纬度","max_candidates":4}'
```

---

### POST `/agent/ask_plus`
**用途**：**并发执行多个候选**，可先对每条做摘要，返回所有结果。  
**请求体**
```json
{
  "query": "查询长沙市的经纬度",
  "allow_servers": null,       // 可选：不填=全量
  "deny_servers": null,        // 可选
  "max_candidates": 6,         // LLM 最多选几个
  "max_exec": 4,               // 最多并发执行几个
  "timeout_ms": 10000,         // 单次调用超时
  "summarize_each": true       // 先做单条摘要再返回
}
```

**响应示例（部分）**
```json
{
  "request_id":"...",
  "query":"查询长沙市的经纬度",
  "candidates":[ { "server":"gdmap_server","tool":"maps_geo","args":{...},"reason":"..." }, ... ],
  "results":[
    { "server":"gdmap_server","tool":"maps_geo","args":{...},"ok":true,"summary":"...", "raw":{...}, "quality":1 },
    { "server":"bdmap_server","tool":"geo","args":{...},"ok":false,"error":"timeout" }
  ]
}
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/agent/ask_plus \
  -H 'Content-Type: application/json' \
  -d '{"query":"查询长沙市的经纬度","max_candidates":3,"max_exec":3}'
```

---

### POST `/agent/answer`
**用途**：**选择 + 并发执行 + 融合** → 给出最终中文答案，并附 `trace` 以便回溯。  
**请求体**
```json
{
  "query": "查询长沙市的经纬度",
  "allow_servers": null,
  "deny_servers": null,
  "max_candidates": 6,
  "max_exec": 4,
  "timeout_ms": 10000
}
```

**响应示例（部分）**
```json
{
  "request_id":"...",
  "final_answer":"根据查询结果，长沙市的地理坐标如下：东经112.938882°，北纬28.228304° ...",
  "trace": {
    "request_id":"...",
    "query":"查询长沙市的经纬度",
    "candidates":[ ... 来自 select ... ],
    "results":[ ... 来自 ask_plus ... ]
  }
}
```

**curl**
```bash
curl -X POST http://127.0.0.1:50066/agent/answer \
  -H 'Content-Type: application/json' \
  -d '{"query":"查询长沙市的经纬度"}'
```

