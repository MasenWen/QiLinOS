# nex-agent 集成 Mem0 自动记忆系统 — 方案

## 一、当前状态

nex-agent 没有自动记忆，记忆能力委托给 Hermes（`hermes_bridge`）。不用 Hermes 时，跨会话记忆完全空白。

## 二、Mem0 简介

Mem0 是开源记忆层，提供：
- **自动提取**：从对话中提取用户偏好、事实、上下文
- **语义检索**：基于向量的记忆搜索
- **用户/会话隔离**：`user_id` + `agent_id` + `session_id` 三级隔离

关键 API：
```python
from mem0 import Memory

m = Memory()
m.add("用户不喜欢咖啡", user_id="user_1")           # 写入
results = m.search("饮品偏好", user_id="user_1")      # 检索
```

## 三、架构设计

```
用户输入 → coordinator_node
              │
              ├─ ① 自动注入记忆（前置钩子）
              │      m.search(user_input, user_id=uid)
              │      → "用户偏好：不喜咖啡 | 历史：上周写过年终总结"
              │      → 拼接到 user_input 末尾
              │
              ├─ LLM 处理（各节点正常执行）
              │
              └─ ② 自动提取记忆（后置钩子）
                     m.add(facts, user_id=uid)
                     → "用户喜欢简洁风格" / "用户下周要出差"
```

## 四、需要修改的文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/memory/mem0_store.py` | **新建** | Mem0 封装层（embedding 复用麒麟 SDK） |
| `agent.py` | **修改** | `run_workflow_with_review` 中注入前置/后置钩子 |
| `requirements.txt` | **修改** | 添加 `mem0ai` |

## 五、核心代码

### 5.1 `src/memory/mem0_store.py`（新建）

```python
"""
Mem0 记忆层 — 复用麒麟 Embedding SDK
自动从对话中提取/检索用户记忆
"""
from mem0 import Memory
import os

# 配置 Mem0 使用麒麟 Embedding（而非默认 OpenAI）
config = {
    "embedder": {
        "provider": "custom",
        "embedding_dim": 768,
        "embedding_fn": None,  # 运行时注入
    },
    "vector_store": {
        "provider": "qdrant",           # Mem0 内置 Qdrant
        "config": {
            "path": os.path.expanduser("~/.nex-agent/mem0_db"),
        },
    },
    "llm": {
        "provider": "openai",           # 记忆提取用的 LLM
        "config": {
            "model": os.getenv("MEM0_LLM_MODEL", "qwen3-max"),
            "api_key": os.getenv("QWEN_API_KEY"),
            "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
    },
}


class Mem0Store:
    """Mem0 记忆存储 — 单例"""

    def __init__(self):
        from src.rag.kylin_embedding_sdk import get_kylin_embedder
        embedder = get_kylin_embedder()

        # 注入麒麟 embedding 函数
        def kylin_embed(texts: list[str]):
            return embedder.embed(texts).tolist()

        config["embedder"]["embedding_fn"] = kylin_embed
        self._memory = Memory.from_config(config)
        self._default_user = os.getenv("MEM0_USER_ID", "nex_user")

    def search(self, query: str, user_id: str = None, top_k: int = 3) -> str:
        """检索相关记忆 → 拼接为 prompt 注入文本"""
        results = self._memory.search(
            query, user_id=user_id or self._default_user, limit=top_k
        )
        if not results:
            return ""
        lines = []
        for r in results:
            mem = r.get("memory", "")
            score = r.get("score", 0)
            if score > 0.3:
                lines.append(f"- {mem}")
        return "用户相关记忆:\n" + "\n".join(lines) if lines else ""

    def extract_and_add(self, messages: list[dict], user_id: str = None):
        """
        从对话中提取事实并自动写入。
        messages 格式: [{"role": "user", "content": "..."},
                        {"role": "assistant", "content": "..."}]
        """
        try:
            self._memory.add(
                messages, user_id=user_id or self._default_user
            )
        except Exception as e:
            pass  # 记忆写入失败不阻塞主流程

    def add_fact(self, fact: str, user_id: str = None):
        """手动添加一条记忆"""
        self._memory.add(fact, user_id=user_id or self._default_user)


# 全局单例
mem0_store = Mem0Store()
```

### 5.2 `agent.py` 修改

在 `run_workflow_with_review` 方法中添加两个钩子：

```python
# === 文件顶部新增导入 ===
from src.memory.mem0_store import mem0_store


# === 在 run_workflow_with_review 中，user_input 构建完成后（约 line 271 附近）===

    # ① 前置钩子：自动注入用户记忆
    # ================================================================
    if self.mem0_enabled:  # 可通过配置控制开关
        try:
            memories = mem0_store.search(user_input, user_id=str(session_id))
            if memories:
                user_input = memories + "\n\n" + user_input
        except Exception:
            pass  # 记忆检索失败不阻塞主流程
    # ================================================================


# === 在 workflow 完成后（约 line 350 附近），添加后置钩子 ===

    # ② 后置钩子：自动提取并存储记忆
    # ================================================================
    if getattr(self, 'mem0_enabled', True):
        try:
            # 从消息历史中提取最后一轮对话
            last_messages = []
            for msg in reversed(workflow_state.get("messages", [])):
                role = "user" if msg.name in ("用户", "user") else "assistant"
                last_messages.insert(0, {
                    "role": role,
                    "content": msg.content[:500]  # 截断长内容
                })
                if len(last_messages) >= 2:
                    break
            if last_messages:
                mem0_store.extract_and_add(last_messages, user_id=str(session_id))
        except Exception:
            pass
    # ================================================================
```

### 5.3 `requirements.txt` 添加

```
mem0ai
```

## 六、调用时机

| 时机 | 操作 | 触发条件 |
|------|------|----------|
| 用户消息到达后 | `mem0_store.search(query)` → 注入记忆上下文 | **自动**，每次 |
| 工作流执行完毕 | `mem0_store.extract_and_add(messages)` → 提取事实写入 | **自动**，每次 |

用户不需要说"记住xxx"，系统自动从对话中提取偏好和事实。

## 七、记忆示例

```
第一轮:
  用户: "帮我写一份周报，内容简洁一点"
  系统: [自动提取] → mem0.add("用户喜欢简洁风格的周报")
  系统: [生成周报...]

第二轮（新会话）:
  用户: "再写一份周报"
  系统: [自动检索] → "用户喜欢简洁风格的周报"
  系统: [生成周报时自动采用简洁风格]
```

## 八、与现有系统的关系

```
nex-agent
├─ Mem0 记忆层 (新增)          ← 自动跨会话记忆
│   ├─ embedding: 复用麒麟 SDK (kylin_embedding_sdk)
│   └─ 向量库: Mem0 内置 Qdrant
│
├─ RAG 知识库 (保留)            ← 用户主动导入的文档检索
│   └─ LightRAG + PostgreSQL + 麒麟 embedding
│
└─ Hermes Bridge (保留)        ← 系统操作 + Hermes 自有记忆
    └─ 如果不用 Hermes，Mem0 承接记忆功能
```

Mem0 和 RAG 的差别：

| | Mem0 记忆 | RAG 知识库 |
|------|------|------|
| 写入方式 | **自动**提取 | 用户手动导入文档 |
| 内容 | 偏好、事实、习惯 | 文档、表格、网页 |
| 典型场景 | "上次你说过..." | "查一下合同里的条款" |
| 粒度 | 单条记忆 | 大段文档 |

## 九、部署

```bash
pip install mem0ai qdrant-client
mkdir -p ~/.nex-agent/mem0_db
```

无需额外服务——Mem0 内置 Qdrant 本地模式，数据存在 `~/.nex-agent/mem0_db/`。
