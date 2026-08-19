# -*- coding: utf-8 -*-
"""v5.5 双后端对比：BM25(全池) vs HNSW(BM25粗筛50 + 麒麟embedding + HNSW ANN)
严格 Recall@k：每条 query = |top-k ∩ required| / |required|，取平均
"""
import csv
import gzip
import json
import os
import random
import sys
import time

sys.path.insert(0, "/home/kylin/work/projects/project_dev1")
os.chdir("/home/kylin/work/projects/project_dev1")

from src.memory_engine.strict.retrieval import _bm25
from src.memory.kylin_embedder import KylinEmbedder
from src.memory_engine.vector_index import HNSWVectorIndex

BASE = "_benchmark/test_subset_v55"
random.seed(42)

GLOBAL_ITEMS = {}
with gzip.open(f"{BASE}/pools/initial_memory_pools.ndjson.gz", "rt", encoding="utf-8") as f:
    for line in f:
        for it in json.loads(line).get("items", []):
            GLOBAL_ITEMS[it["memory_id"]] = it.get("raw_text", "")
rows = []
with open(f"{BASE}/answer_key.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        try:
            req = json.loads(r["required_memory_ids_json"])
        except Exception:
            req = []
        rows.append({"tier": r["stress_tier"], "pool_size": int(r["target_pool_size"]),
                     "query": r["current_query"], "required": req})
print(f"全局条目={len(GLOBAL_ITEMS)} 条件={len(rows)}", flush=True)

emb = KylinEmbedder()
N_CAND = 50  # HNSW 粗筛宽度（对齐候选）


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5) + 1e-9)


def build_pool(cond):
    req_ids = [rid for rid in cond["required"] if rid in GLOBAL_ITEMS]
    req_set = set(req_ids)
    pool_items = {rid: GLOBAL_ITEMS[rid] for rid in req_ids}
    distractors = [mid for mid in GLOBAL_ITEMS if mid not in req_set]
    random.shuffle(distractors)
    for mid in distractors[: max(0, cond["pool_size"] - len(pool_items))]:
        pool_items[mid] = GLOBAL_ITEMS[mid]
    return pool_items, req_set


def strict_recall(req_set, top_ids):
    return len(req_set & top_ids) / len(req_set)


SAMPLE = {"Small": 4, "Medium": 4, "Large": 4, "XL": 4}
stats = {}
for tier in ["Small", "Medium", "Large", "XL"]:
    tier_rows = [r for r in rows if r["tier"] == tier and r["required"]]
    random.shuffle(tier_rows)
    for ci, cond in enumerate(tier_rows[: SAMPLE[tier]]):
        pool, req = build_pool(cond)
        if not pool or not req:
            continue
        print(f"  [{tier} {ci+1}/{SAMPLE[tier]}] 处理中...", flush=True)
        s = stats.setdefault(tier, {"n": 0, "b1": 0.0, "b3": 0.0, "h1": 0.0, "h3": 0.0, "b_lat": 0.0, "h_lat": 0.0})
        s["n"] += 1
        # ---- 管线 A: BM25 全池 ----
        t0 = time.time()
        sc = _bm25(cond["query"], pool, k1=1.5, b=0.75)
        b_ranked = [pid for pid, _ in sorted(sc.items(), key=lambda x: -x[1])]
        s["b_lat"] += (time.time() - t0) * 1000
        b_top5 = set(b_ranked[:5])
        s["b1"] += strict_recall(req, set(b_ranked[:1]))
        s["b3"] += strict_recall(req, set(b_ranked[:3]))
        # ---- 管线 B: BM25 粗筛 + embedding + HNSW ----
        t0 = time.time()
        cand = b_ranked[:N_CAND]
        try:
            qv = emb.embed(cond["query"][:200])
            vecs = [emb.embed(pool[pid][:150]) for pid in cand]
            idx = HNSWVectorIndex(dim=768)
            idx.build(cand, vecs, [pool[pid] for pid in cand])
            ann = idx.search(qv, top_k=5)
            idx.close()
            ann_ids = {nid for nid, _ in ann}
            s["h1"] += strict_recall(req, set(ann[:1] and [ann[0][0]]))
            s["h3"] += strict_recall(req, ann_ids)
        except Exception as e:
            s["n"] -= 1
            print(f"  [skip] {tier} {cond['query'][:30]}... {type(e).__name__}", flush=True)
        s["h_lat"] += (time.time() - t0) * 1000

print("\n========== 双后端对比（严格 Recall@k，每级抽 10 条）==========", flush=True)
grand = {"n": 0, "b1": 0.0, "b3": 0.0, "h1": 0.0, "h3": 0.0, "b_lat": 0.0, "h_lat": 0.0}
for tier in ["Small", "Medium", "Large", "XL"]:
    s = stats.get(tier)
    if not s or s["n"] == 0:
        continue
    print(f"{tier:<7} n={s['n']:>2} | BM25 R@1={s['b1']/s['n']:.2%} R@3={s['b3']/s['n']:.2%} {s['b_lat']/s['n']:.0f}ms | "
          f"HNSW R@1={s['h1']/s['n']:.2%} R@3={s['h3']/s['n']:.2%} {s['h_lat']/s['n']:.0f}ms", flush=True)
    for k in grand:
        grand[k] += s[k]
print("-" * 90, flush=True)
print(f"合计  n={grand['n']} | BM25 R@1={grand['b1']/grand['n']:.2%} R@3={grand['b3']/grand['n']:.2%} | "
      f"HNSW R@1={grand['h1']/grand['n']:.2%} R@3={grand['h3']/grand['n']:.2%} | "
      f"延迟 BM25={grand['b_lat']/grand['n']:.0f}ms HNSW={grand['h_lat']/grand['n']:.0f}ms", flush=True)
print("\n对比评测完成", flush=True)
