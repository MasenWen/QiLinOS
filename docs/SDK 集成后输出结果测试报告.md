---
tags:
  - Agent
  - SDK
  - 测试
  - 报告
created: 2026-08-14
aliases:
  - SDK 集成后输出结果测试报告
  - SDK 语义检索服务器实测
---
# SDK 集成后输出结果测试报告

> 测试日期：2026-08-14
> 测试对象：SDK 语义嵌入通道（会话池）＋ 严格记忆引擎语义检索
> 测试环境：阿里云 ECS，Kylin V11，Python 3.12.3
> 背景：回答「加入 SDK 后又进行输出结果的测试吗」——在 Kylin 服务器上实测 SDK 语义通道的输出结果

---

## 一、测试背景与目的

Phase 1 数据流合并已实测通过，但语义检索此前因 `KylinEmbedder` 共享会话 + ctypes 状态累积导致 **segfault**，BM25-only 召回率为 0%（详见 [[Kylin V11 Python ctypes segfault 问题]]）。

修复方案是 `KylinEmbeddingSessionPool` 会话池（每次 embed 完整走 create→init→embed→get→destroy 生命周期），并建立四级回退链：**SDK 会话池（主通道）→ ONNX GTE-base → DashScope 云 API → 增强 BM25**。

本次测试目的是在服务器上验证两点：
1. SDK 会话池连续调用不再崩溃，且输出向量正确；
2. SDK 语义通道能正确参与检索并返回正确的 top1 结果。

---

## 二、测试环境

| 项目 | 详情 |
|------|------|
| **服务器** | 阿里云 ECS（`120.76.241.252`，SSH 别名 `kylin`） |
| **操作系统** | Kylin Linux V11（openKylin） |
| **Python** | 3.12.3 |
| **项目路径** | `~/work/projects/project_dev1` |
| **核心代码** | `src/memory_engine/embedding_service.py`（EmbeddingService）、`src/memory_engine/strict/kylin.py`（KylinSDKSemanticScorer）、`src/memory_engine/strict/engine.py`（StrictMemoryEngine） |

---

## 三、测试一：SDK 语义嵌入会话池冒烟测试

连续调用 8 次 embed，验证会话池生命周期下不再崩溃。

| 指标 | 结果 |
|------|------|
| 连续 embed 次数 | 8 次 |
| segfault | ✅ **无崩溃**（此前 5-6 次即崩溃） |
| 后端 | `openkylin_sdk_session_pool` |
| 模型 | `ensemble-embd_gte-base_uint8-text` |
| 向量维度 | 768 |
| 总耗时 | ~8.46s（约 1.06s/次） |

**结论**：P0 的 ctypes segfault 问题已通过会话池彻底修复，主通道（SDK）可用。

---

## 四、测试二：SDK 语义检索测试

注入 5 条 `AtomicEvidence`（`admission=SCOPED_ONLY`，自然语言 claim_value），再用 5 条改写后的查询分别走 BM25-only 基线与 SDK 语义通道。

**注入证据（claim_value 摘要）**：

| 编号 | 语义内容 |
|------|----------|
| e1 | 默认时区偏好（Asia/Shanghai） |
| e2 | 终端主题偏好 |
| e3 | 壁纸风格偏好 |
| e4 | 音量级别偏好 |
| e5 | 家庭 WiFi 偏好 |

**检索结果**：

| 通道 | 命中率 | top1 正确性 |
|------|--------|-------------|
| BM25-only 基线 | 5/5（100%） | ✅ 全部正确 |
| SDK 语义通道 | 5/5（100%） | ✅ e1~e5 一一对应 |

**性能**：5 次语义查询耗时 11.1s（约 2.2s/查询，含会话池每次完整 create→embed→destroy 生命周期）。

**结论**：SDK 语义通道**能跑通且输出结果正确**——无崩溃，top1 全部命中。

---

## 五、发现的问题

### 5.1 `backend=?` 小瑕疵

结果字典中 `semantic_backend` 键不在预期位置（顶层取值为 `?`），但日志已确认实际走的是 `openkylin_sdk_session_pool`。**不影响正确性**，属于结果字段位置问题，后续可补。

### 5.2 测试设计局限（重要）

查询词与 claim_value 存在**词汇重叠**，导致 BM25 基线也拿到 100% 命中。因此本次测试**证明的是「SDK 语义通道能跑通且正确」，但尚未干净地证明「语义通道优于 BM25」**。

真正的召回率优势仍需在 benchmark 数据集上评估（对应 P0 #3，目标 >50%，依赖语义通道已就绪）。

---

## 六、结论与下一步

| 项 | 状态 |
|----|------|
| SDK 会话池 embedding 冒烟 | ✅ 通过（无 segfault） |
| SDK 语义检索输出正确性 | ✅ 通过（5/5 top1 正确） |
| 语义 vs BM25 的召回率优势 | ⏳ 待 benchmark 验证 |

**下一步**：
1. 在 benchmark 数据集上重跑语义检索，验证召回率从 0% → >50%（P0 #3）
2. 修复 `semantic_backend` 字段位置小瑕疵
3. 用「无词汇重叠」的改写查询补一组对照测试，干净证明语义通道优势

---

*关联文档：[[SDK 测试报告]] | [[Kylin V11 Python ctypes segfault 问题]] | [[SDK-记忆管线合并 Phase 1 测试报告]] | [[项目进度报告]]*
