# OS Agent Memory Query Official 1000

固定正式集包含200个前置案例和800条离线Query。40个案例来自v3.1，用于保持旧回归连续性；160个案例从v5.3的1000条人工复核池中分层选取。

每个前置案例保留4种不同问法，Query按四轮交错排列，同一案例不会连续出现；完全相同的Query文本最多出现2次。Query只形成临时Observation，不写回记忆库。

- `processed_data/query_set.csv`：800条无答案Query。
- `processed_data/answer_key.csv`：200组独立答案，仅用于事后评分。
- `processed_data/precedent_set.ndjson.gz`：200个前置证据包索引。
- `processed_data/precedent_inputs.ndjson.gz`：200行可直接顺序导入的完整前置输入。
- `evidence/`：筛选后的旧版记忆、对话事件和操作日志。
- `selection_report.json`：抽样及分布报告。
- `validation_report.json`：结构、重复和证据完整性检查。

选择过程不读取答案字段，也不修改MemoryEngine算法。后续调参应另建开发子集；本目录应固定版本使用。
