# OS Agent 人类化记忆查询测试集 v3.1

## 1. 本版目的

v3.1 是 v3 的精简人工复审版。它不新增操作数据，而是减少同一答案的重复问法、重排人工审阅字段、补充完整答案逻辑，并删除 Query 表中的逐行冗余标签。

v3 保持不变；v3.1 是独立副本。

本版共有 530 条 Query、106 个 `answer_group_id`，每个答案组固定 5 条 Query。同一规范化完整答案最多出现 5 次。

## 2. Query 数量

| 评测轨道 | 数量 |
| --- | ---: |
| `single_memory` | 235 |
| `complementary_multi_memory` | 150 |
| `conflict_resolution` | 75 |
| `clarification_required` | 70 |
| 合计 | 530 |

保留的五种 Query 类型为：

1. `human_context_explicit`：明确说明工作场景和对象。
2. `human_goal_oriented`：从用户工作目标表达请求。
3. `contextual_ellipsis`：省略可由当前上下文补全的信息。
4. `low_overlap_paraphrase`：使用低词面重合的人类表达。
5. `human_constraint_emphasis`：重点强调范围、格式或禁止事项。

五种类型各有 106 条。v3 单记忆题后来增加的 10 类包装变体已删除，因为它们没有增加新的独立操作信息。

## 3. 数据来源与引用

本版没有引入新的外部任务数据，操作内容仍只来自 47 条 LibreOffice Calc / OSWorld 任务和对应的 47 条记忆记录。

- 原始任务包：`os_agent_test_data(1)(1).zip`。
- OSWorld：https://github.com/xlang-ai/OSWorld
- OSWorld 文件缓存：https://huggingface.co/datasets/xlangai/ubuntu_osworld_file_cache
- 记忆类型和生命周期设计参考：`11_MemoryEngine算法设计_专业修订版.md`。

没有编造 WPS、邮件、浏览器或跨 App 操作。在线记忆更新数据将在取得新的连续操作数据后另行构建，本版仍是离线检索与决策评测。

## 4. 唯一数据源

`processed_data/query_set.csv` 是唯一规范 Query 数据源。

`processed_data_backup/query_set_human_review.xlsx` 是由 CSV 生成的人工审阅视图，不是第二套独立 Query。工作簿包含：

- `Human_Review`：逐条人工复审。
- `Review_Guide`：字段和复审顺序说明。
- `Summary`：随人工填写更新的统计结果。

人工若在 XLSX 中完成复审，需要把最终结果同步回规范 CSV 后再进行机器评测，不能长期维护两套不一致内容。

## 5. 人工复审布局

`Human_Review` 工作表按“左侧机器信息、右侧人工内容”排列。

左侧主要是 ID、编码和自动评测字段：

- Query、答案组、场景和来源 ID；
- 评测轨道、Query 类型和数据分区；
- 必需、候选、禁止记忆 ID；
- 目标内容/记忆类型；
- App、工作流、动作和评分 JSON。

最右侧是需要人工重点复审的完整文本：

1. `query_text`：用户实际问法。
2. `required_memory_texts`：应调用记忆及其完整约束。
3. `candidate_memory_texts`：澄清题的全部候选记忆。
4. `forbidden_memory_texts`：冲突题必须排除的完整记忆。
5. `expected_conclusion`：应给用户的信息。
6. `expected_operation_text`：实际应执行或暂停的完整操作。
7. `answer_reasoning`：为什么应得到该答案的完整证据链。
8. `scoring_rubric_text`：自然语言评分标准及完整证据。
9. `status`：人工填写。
10. `rank`：人工填写。

## 6. status 和 rank

`status` 和 `rank` 完全交给人工确定，数据集不根据内容判断二者。

- `status` 初始值统一为 `not_pass`，工作簿允许人工填写 `not_pass` 或 `pass`。
- `rank` 初始值统一为数值 `0`，工作簿允许人工填写 0 至 5。

初始 `not_pass` 和 `0` 只是占位值，不表示系统认为 Query 不合格或质量为零。验证脚本只检查字段是否存在、取值是否在允许范围内，不检查 status 与 rank 的关系，也不替人工改变任何值。

## 7. 答案逻辑

`answer_reasoning` 不要求人工再根据 ID 到其他表查找记忆。每条说明完整包含：

1. 用户 Query 原文；
2. 当前可见上下文；
3. 必需、候选或禁止记忆的完整文本和约束；
4. 各记忆为什么支持、互补、冲突或不足以唯一选择；
5. 为什么不能使用其他方案；
6. 应形成的完整结论。

不同轨道的逻辑为：

- 单记忆：Query 和当前上下文唯一对应一条记忆，且没有新冲突条件，因此恢复该记忆的完整操作。
- 多记忆：每条必需记忆分别支持一个子任务，单独任何一条都不足以完成全部请求，因此必须合成。
- 冲突：必需记忆与 Query 的目标和输出一致；禁止记忆虽然相似，但会产生错误操作或输出，因此必须显式排除。
- 澄清：多个候选都与当前主题相关，但操作或输出不同，Query 缺少唯一选择条件，因此不得擅自执行。

说明文本不使用“同上”“略”“见前文”等省略方式。

## 8. 评分标准

`scoring_points_json` 保留给机器评测；右侧 `scoring_rubric_text` 提供完整人类可读版本。

每题总分 1.00，各得分点独立累计。每个得分点包含：

- 分值；
- 应满足的结论或操作；
- 所依据的完整记忆文本和约束；
- 部分正确时的计分边界。

人工应评价模型最终结论和实际操作，而不是只检查是否返回了 memory ID。语义等价表达可以得分，错误调用禁止记忆或擅自在澄清前执行应按对应得分点扣分。

## 9. 精简字段

以下固定、可推导或与逐条复审无关的标签已从 Query 表移除：

- `schema_version`
- `query_variant_id`
- `interaction_mode`
- `domain`
- `scene`
- `app_scope`
- `workflow_scope`
- `dependency_order`
- `source_dataset`
- `source_fidelity`
- `synthetic_dimensions`
- `memory_count`
- `evidence_relation`
- `constraints`
- `scoring_reason`
- `answerability`
- `top_k`
- `automatic_evaluation_available`

其中版本和统一来源信息改在 README 记录；计数和证据关系由 ID 与评测轨道推导；约束、评分理由已经完整写入人工复审文本。

为未来多 App 数据保留 `apps_involved`、`workflow_steps_json` 和 `handoff_artifacts_json`。

## 10. 数据分区

| 分区 | 数量 |
| --- | ---: |
| train | 150 |
| dev | 45 |
| test | 40 |
| challenge | 295 |

同一 `answer_group_id` 不跨分区。公开包包含答案，因此仍属于开发评测；正式比赛需要隐藏测试答案。

## 11. 运行方法

验证数据结构：

```powershell
python scripts/validate_dataset.py
```

评测预测文件：

```powershell
python scripts/evaluate_predictions.py predictions.csv --output evaluation.json
```

预测文件至少包含：

```text
query_id,predicted_memory_ids,predicted_decision_class,predicted_action_keys,response_time_ms
```

可选 `awarded_point_ids` 用于依据 `scoring_points_json` 汇总部分结论分。该列应由独立人工或明确披露的 LLM 裁判提供，评测脚本不会自行判断自然语言是否命中得分点。

## 12. 适用边界

v3.1 减少了重复 Query，提高了人工复审效率和答案可解释性，但底层仍只有 47 个独立操作任务。530 条 Query 不能被解释成 530 个独立办公任务，也不能证明跨 App 或广泛 OS 泛化能力。

后续应优先增加有来源的新操作任务、真实操作轨迹、连续用户反馈和执行结果，而不是继续扩写同一答案的更多问法。
