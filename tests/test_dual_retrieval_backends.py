# -*- coding: utf-8 -*-
"""集成测试：BM25 与 HNSW 检索后端切换对比（保留 BM25 架构）"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/kylin/work/projects/project_dev1")
os.chdir("/home/kylin/work/projects/project_dev1")

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.store import StrictMemoryEngineStore


class ZeroKylinScorer:
    backend_id = "openkylin_test_double"
    def score(self, query, memories):
        return {memory.memory_id: 0.0 for memory in memories}


def make_engine(tmp, backend):
    config = StrictMemoryEngineConfig.load(database_path=Path(tmp) / "strict.db")
    # 切换检索后端（保留两种后端并存）
    import dataclasses
    mods = dict(config.modules)
    mods["retrieval"] = backend
    config = dataclasses.replace(config, modules=mods)
    store = StrictMemoryEngineStore(config.database_path)
    return StrictMemoryEngine(config=config, store=store, semantic_scorer=ZeroKylinScorer())


def ingest(engine, index, content, day, task="quotation reply"):
    from datetime import datetime, timedelta, timezone
    event_time = datetime(2026, 7, 1, 10, tzinfo=timezone(timedelta(hours=8))) + timedelta(days=day)
    engine.ingest_observation(
        {
            "source_type": "dialogue",
            "source_event_id": f"t-{index}",
            "user_id": "U001",
            "session_id": f"S{index:03d}",
            "event_time": event_time.isoformat(),
            "actor": "user",
            "content": content,
            "task": task,
            "context": {},
        },
        stage_limit="lifecycle",
    )


BACKENDS = {
    "bm25": "retrieval.structured_bm25.v1",
    "hnsw": "retrieval.structured_hnsw.v1",
}
MEMORIES = [
    "以后默认使用 USD 结算报价。",
    "客户要求报价单使用中英文双语。",
    "每周五下午整理本周报价汇总。",
    "偏好使用简洁的邮件风格回复客户。",
    "打印机故障时先重启再报修。",
    "桌面文件夹按修改时间排列。",
    "报价有效期默认 30 天。",
    "喜欢在早上处理邮件。",
]

results = {}
for name, backend in BACKENDS.items():
    tmp = tempfile.mkdtemp(prefix=f"eng_{name}_")
    print(f"\n===== 后端: {name} ({backend}) =====", flush=True)
    engine = make_engine(tmp, backend)
    for i, mem in enumerate(MEMORIES, start=1):
        ingest(engine, i, mem, day=i)
    r = engine.retrieve(
        "生成报价时默认使用什么货币结算？",
        {"user_id": "U001", "query_time": "2026-07-15T10:00:00+08:00",
         "task": "quotation reply", "memory_need": "currency"},
    )
    results[name] = r
    print(f"  module_id: {r['trace']['module_id']}", flush=True)
    print(f"  selected: {r['planner']['selected_memory_ids']}", flush=True)
    print(f"  advisory: {r['planner']['advisory_memory_ids']}", flush=True)
    print(f"  items: {[(i['memory_id'][:12], i['decision'], round(i['scores']['hybrid'],3)) for i in r['items'][:4]]}", flush=True)

# 对比
print("\n===== 对比 =====", flush=True)
b, h = results["bm25"], results["hnsw"]
print(f"BM25 选中: {b['planner']['selected_memory_ids']}", flush=True)
print(f"HNSW 选中: {h['planner']['selected_memory_ids']}", flush=True)
print(f"输出结构一致: {set(b.keys()) == set(h.keys())} (keys={sorted(b.keys())})", flush=True)
print(f"item 字段一致: {set(b['items'][0].keys()) == set(h['items'][0].keys()) if b['items'] and h['items'] else 'N/A'}", flush=True)
print("\n集成测试完成", flush=True)
