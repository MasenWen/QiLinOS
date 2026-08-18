# -*- coding: utf-8 -*-
"""v5.5 stress 压力测试：4 级池规模 BM25 检索命中率（含 required gold）"""
import csv
import gzip
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, "/home/kylin/work/projects/project_dev1")
os.chdir("/home/kylin/work/projects/project_dev1")

from src.memory_engine.strict.retrieval import _bm25

BASE = "_benchmark/test_subset_v55"
random.seed(42)

# ---------- 加载全局记忆条目 ----------
print("加载全局记忆池（150,456 条目）...", flush=True)
GLOBAL_ITEMS = {}  # memory_id -> raw_text
with gzip.open(f"{BASE}/pools/initial_memory_pools.ndjson.gz", "rt", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        for it in d.get("items", []):
            GLOBAL_ITEMS[it["memory_id"]] = it.get("raw_text", "")
print(f"  全局条目: {len(GLOBAL_ITEMS)}", flush=True)

# ---------- 加载 stress answer_key ----------
print("加载 stress answer_key ...", flush=True)
rows = []
with open(f"{BASE}/answer_key.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        try:
            req_ids = json.loads(r["required_memory_ids_json"])
        except Exception:
            req_ids = []
        rows.append({
            "condition_id": r["condition_id"],
            "tier": r["stress_tier"],
            "pool_size": int(r["target_pool_size"]),
            "query": r["current_query"],
            "required_ids": req_ids,
        })
print(f"  条件数: {len(rows)}", flush=True)

# ---------- 评测 ----------
results = {}
for cond in rows:
    req_ids = [rid for rid in cond["required_ids"] if rid in GLOBAL_ITEMS]
    if not req_ids:
        continue
    # 构造池：relevant(required 条目) + distractor(全局随机，排除 relevant)
    req_set = set(req_ids)
    pool_size = cond["pool_size"]
    relevant = {rid: GLOBAL_ITEMS[rid] for rid in req_ids}
    distractors = [
        mid for mid in GLOBAL_ITEMS
        if mid not in req_set
    ]
    random.shuffle(distractors)
    need = pool_size - len(relevant)
    pool_items = dict(relevant)
    for mid in distractors[: max(0, need)]:
        pool_items[mid] = GLOBAL_ITEMS[mid]
    pool = {f"m{i}": t for i, t in enumerate(pool_items.values())}
    id2idx = {mid: f"m{i}" for i, mid in enumerate(pool_items.keys())}

    t0 = time.time()
    scores = _bm25(cond["query"], pool, k1=1.5, b=0.75)
    latency = time.time() - t0
    ranked = [pid for pid, _ in sorted(scores.items(), key=lambda x: -x[1])]

    def hit(top_n):
        top_ids = {mid for mid, idx in id2idx.items() if idx in set(ranked[:top_n])}
        return bool(req_set & top_ids)

    r = results.setdefault(cond["tier"], {"total": 0, "h1": 0, "h3": 0, "h5": 0, "lat": 0.0})
    r["total"] += 1
    if hit(1):
        r["h1"] += 1
    if hit(3):
        r["h3"] += 1
    if hit(5):
        r["h5"] += 1
    r["lat"] += latency

# ---------- 输出 ----------
print("\n========== v5.5 stress 压力测试结果 ==========", flush=True)
grand = {"total": 0, "h1": 0, "h3": 0, "h5": 0, "lat": 0.0}
order = ["Small", "Medium", "Large", "XL"]
for tier in order:
    r = results.get(tier)
    if not r or r["total"] == 0:
        continue
    print(f"{tier:<8} 池={ {'Small':100,'Medium':500,'Large':2000,'XL':10000}[tier]:>5}  "
          f"n={r['total']:>3}  R@1={r['h1']/r['total']:.2%}  R@3={r['h3']/r['total']:.2%}  "
          f"R@5={r['h5']/r['total']:.2%}  平均检索={r['lat']/r['total']*1000:.1f}ms", flush=True)
    for k in grand:
        grand[k] += r[k]
print("-" * 70, flush=True)
print(f"合计    n={grand['total']}  R@1={grand['h1']/grand['total']:.2%}  "
      f"R@3={grand['h3']/grand['total']:.2%}  R@5={grand['h5']/grand['total']:.2%}  "
      f"平均检索={grand['lat']/grand['total']*1000:.1f}ms", flush=True)
print("\nv5.5 stress 评测完成", flush=True)
