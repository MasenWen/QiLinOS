# NexAgent

NexAgent-基于意图识别与动态规划的通用系统操作多智能体


## 目录
- [快速开始](#快速开始)
- [架构](#架构)
- [功能特性](#功能特性)
- [安装及配置](#安装及配置)
    - [前置要求](#前置要求)
    - [安装步骤](#安装步骤)
    - [安装依赖](#安装依赖)
    - [配置](#配置)
- [使用方法](#使用方法)
    - [基本执行](#基本执行)
    - [API服务器](#API服务器)
    - [高级配置](#高级配置)
    - [智能体提示系统](#智能体提示系统)
- [贡献](#贡献)
- [许可证](#许可证)
- [致谢](#致谢)

## 快速开始

```bash
# 克隆仓库
git clone 
cd nex-agent

# 用uv创建并激活虚拟环境
uv python install 3.12
uv venv --python 3.12

source .venv/bin/activate  # Windows系统使用: .venv\Scripts\activate

# 安装依赖
uv sync

# 配置环境
cp .env.example .env
# 编辑 .env 文件，填入你的 API 密钥

# 运行项目
uv run main.py
```

## 架构

基于意图识别与动态规划的通用系统操作多智能体，对于用户的输入，首先通过意图识别确定任务类别（如问答、知识库操作、简单系统操作、智能填表、ppt生成、复杂任务及系统操作），路由到下一级相关智能体，其中通用复杂任务由规划智能体生成计划，然后由主管智能体协调专门的智能体来完成复杂任务。任务过程中，用户可通过交互修改计划或执行细节，并动态生成新的规划。


系统由以下智能体协同工作：

1. **协调员（Coordinator）**：工作流程的入口点，处理意图识别并路由任务
2. **知识管理员（konwledge manager）**：处理添加文本、链接以及文件到知识库的任务
3. **系统操作员（System Operator）**：处理单一的系统操作任务，复杂任务可通过多次调用系统操作执行者实现
4. **填表员（Form filler）**：处理文档中的智能填表任务
5. **PPT制作专家（PPT Generator）**：处理ppt相关设计和制作
6. **规划员（Planner）**：分析任务并制定执行策略
7. **主管（Supervisor）**：监督和管理其他智能体的执行
8. **研究员（Researcher）**：收集和分析信息
9. **程序员（Coder）**：负责代码生成和修改
10. **浏览器（Browser）**：执行网页浏览和信息检索
11. **汇报员（Reporter）**：生成工作流结果的报告和总结

## 功能特性

### 核心能力

- 多智能体协同，理解和识别用户意图，规划决策，并支持用户协作，动态生成规划
- 直观的多角色对话方式，详细的执行过程展示
- 多任务并行
- 任务暂停/恢复，断点/恢复
- 功能集成：网络搜索、神经搜索、高级内容提取、知识库管理、智能填表、PPT制作、OCR
- 记忆：用户画像、行为模式、短期会话记忆、长期记忆（通过用户输入信息、及任务执行情况获取，决策时应用）
- MCP服务拓展及配置：系统操作、地图导航、文件管理等。且规划时能根据MCP服务在线情况动态拓展团队成员及能力
- A2A：其它智能体交互协作，适配Crawl AI架构智能体，实现文生图能力
- 文件处理，并支持文件拖拽上传
- 兼容OpenAI、Ollama、vllm等大模型 API 接口，支持云端/本地大模型，例如Qwen、DeepSeek、llama.cpp等
- 兼容麒麟AI SDK，调用OCR接口，实现文本识别能力
- 多类型 LLM 配置，适配不同任务场景，如通用、推理、多模态大模型

## 安装及配置

### 前置要求

- [uv](https://github.com/astral-sh/uv) 包管理器

安装uv
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
### 安装步骤

NexAgent 使用 [uv](https://github.com/astral-sh/uv) 作为包管理器以简化依赖管理。
按照以下步骤设置虚拟环境并安装必要的依赖：

```bash
# 步骤 1：用uv创建并激活虚拟环境
uv python install 3.12
uv venv --python 3.12

source .venv/bin/activate

# 步骤 2：安装项目依赖
uv sync
```


### 安装依赖
基础数据库服务
```bash
sudo apt install mysql-server
sudo mysql -u root -p
ALTER USER 'root'@'localhost' IDENTIFIED WITH caching_sha2_password BY '12345678';
FLUSH PRIVILEGES;
exit;
```

系统操作相关功能需安装 `kylin-actuator`， 仓库地址 [kylin-actuator](https://gitee.com/openkylin/kylin-actuator.git)
```bash
git clone https://gitee.com/openkylin/kylin-actuator.git
cd kylin-actuator
./tools/install.sh
```
A2A相关功能需要启动 `A2A` 服务:
```bash
uv run a2a_host.py
```

MCP相关功能需要启动 `MCP` 服务:
```bash
uv run mcp_host.py
```

OCR（文本识别）基于麒麟AI SDK，openKylin SP2桌面环境
```bash
sudo apt install libkysdk-coreai-vision-dev libglib2.0-dev
cd ocr_tool
mkdir build
cd build
cmake ..
make
sudo make install
```

### 配置

NexAgent 使用三层 LLM 系统，分别用于推理、基础任务和视觉语言任务。在项目根目录创建 `.env` 文件并配置以下环境变量：

```ini
# 推理 LLM 配置（用于复杂推理任务）
REASONING_MODEL=your_reasoning_model
REASONING_API_KEY=your_reasoning_api_key
REASONING_BASE_URL=your_custom_base_url  # 可选

# 基础 LLM 配置（用于简单任务）
BASIC_MODEL=your_basic_model
BASIC_API_KEY=your_basic_api_key
BASIC_BASE_URL=your_custom_base_url  # 可选

# 视觉语言 LLM 配置（用于涉及图像的任务）
VL_MODEL=your_vl_model
VL_API_KEY=your_vl_api_key
VL_BASE_URL=your_custom_base_url  # 可选

# 工具 API 密钥  # 可选
TAVILY_API_KEY=your_tavily_api_key
JINA_API_KEY=your_jina_api_key  

# 浏览器配置
CHROME_INSTANCE_PATH=  # 可选，Chrome 可执行文件路径
```

> **注意：**
>
> - 系统对不同类型的任务使用不同的模型：
>     - 推理 LLM 用于复杂的决策和分析
>     - 基础 LLM 用于简单的文本任务
>     - 视觉语言 LLM 用于涉及图像理解的任务
> - 所有 LLM 的基础 URL 都可以独立自定义
> - 每个 LLM 可以使用不同的 API 密钥
> - Jina API 密钥是可选的，提供自己的密钥可以获得更高的速率限制（你可以在 [jina.ai](https://jina.ai/) 获该密钥）
> - Tavily 搜索默认配置为最多返回 5 个结果（你可以在 [app.tavily.com](https://app.tavily.com/) 获取该密钥）

您可以复制 `env_example` 文件作为模板开始：

```bash
cp env_example .env
```

## 使用方法

### 基本执行

使用默认设置运行 NexAgent：

```bash
uv run main.py
```

### API服务器

NexAgent 提供基于 FastAPI 的 API 服务器，支持流式响应：

或直接运行
```bash
uv run app.py
```

### 高级配置

可以通过 `src/config` 目录中的各种配置文件进行自定义：
- `env.py`：配置 LLM 模型、API 密钥和基础 URL
- `tools.py`：调整工具特定设置（如 Tavily 搜索结果限制）
- `agents.py`：修改团队组成和智能体系统提示

### 智能体提示系统

NexAgent 在 `src/prompts` 目录中使用复杂的提示系统来定义智能体的行为和职责：

#### 核心智能体角色

- **协调员（[`src/prompts/coordinator_zh.md`](src/prompts/coordinator_zh.md)）**：专注于意图识别与任务分发，将任务转交给专业的团队成员处理。

- **操作员（由MCP封装的kylin-server实现）**：负责处理openkylin系统环境的应用调用、桌面交互、系统设置等系统操作相关能力。

- **知识管理员（[`src/prompts/src/prompts/knowledge_manager_zh.md.md`](src/prompts/knowledge_manager_zh.md)）**：负责将文本内容、网页链接、文件添加到知识库。

- **填表员（[`src/prompts/form_filler_zh.md`](src/prompts/form_filler_zh.md)）**：专注于智能填表，通过解析文档，并根据输入、上下文及知识库的信息，分析和确定要填入的信息，自动填入到表格。

- **PPT制作专家（[`src/prompts/ppt_generator_zh.md`](src/prompts/ppt_generator_zh.md)）**：分析用户需求，并使用可用模板和内容资源创建高质量的PPT演示文稿。

- **规划员（[`src/prompts/planner_zh.md`](src/prompts/planner_zh.md)）**：协调团队成员来完成给定的需求，创建一个详细的计划，明确所需的步骤以及每个步骤负责的成员智能体。

- **主管（[`src/prompts/supervisor_zh.md`](src/prompts/supervisor_zh.md)）**：通过分析请求并确定由哪个专家处理来协调团队并分配任务。负责决定任务完成情况和工作流转换。

- **研究员（[`src/prompts/researcher_zh.md`](src/prompts/researcher_zh.md)）**：专门通过网络搜索和数据收集来收集信息。使用 Tavily 搜索和网络爬取功能，避免数学计算或文件操作。

- **程序员（[`src/prompts/coder_zh.md`](src/prompts/coder_zh.md)）**：专业软件工程师角色，专注于 Python 和 bash 脚本。处理：
    - Python 代码执行和分析
    - Shell 命令执行
    - 技术问题解决和实现

- **浏览器（[`src/prompts/browser_zh.md`](src/prompts/browser_zh.md)）**：网络交互专家，处理：
    - 网站导航
    - 页面交互（点击、输入、滚动）
    - 从网页提取内容

- **汇报员（[`src/prompts/reporter_zh.md`](src/prompts/reporter_zh.md)）**：基于所提供的信息和可验证的事实，负责撰写清晰、全面的报告。
#### 提示系统架构

提示系统使用模板引擎（[`src/prompts/template.py`](src/prompts/template.py)）来：
- 加载特定角色的 markdown 模板
- 处理变量替换（如当前时间、团队成员信息）
- 为每个智能体格式化系统提示

每个智能体的提示都在单独的 markdown 文件中定义，这样无需更改底层代码就可以轻松修改行为和职责。

## 贡献

我们欢迎各种形式的贡献！无论是修复错别字、改进文档，还是添加新功能，您的帮助都将备受感激。


## 许可证

本项目是开源的，基于 [GPL-3.0+ 许可证](LICENSE)。

## 致谢

特别感谢所有让 NexAgent 成为可能的开源项目和贡献者。我们站在巨人的肩膀上。
特别感谢开源项目：LangGraph、麒麟AI SDK、AutoFill
