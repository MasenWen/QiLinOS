# -*- coding: utf-8 -*-
"""评测2 最小验证：30 query embedding 精排"""
import csv, os, random, re, sys, time
sys.path.insert(0, "/home/kylin/work/projects/project_dev1")
os.chdir("/home/kylin/work/projects/project_dev1")
from src.memory_engine.strict.retrieval import _bm25
from src.memory.kylin_embedder import KylinEmbedder

BASE = "_benchmark/test_subset_dev"
answers = {r["answer_group_id"]: r for r in csv.DictReader(open(f"{BASE}/answer_key_dev_core.csv", encoding="utf-8-sig"))}
queries = list(csv.DictReader(open(f"{BASE}/query_set_dev.csv", encoding="utf-8-sig")))


def split_items(text):
    if not text or text.strip() in ("不适用", "不适用：本题没有该类证据。"):
        return []
    parts = re.split(r"\n\s*\d+\.\s*", text.strip())
    out = [p.strip() for p in parts if p.strip() and not re.fullmatch(r"\d+\.", p.strip())]
    if out and out[0].startswith("1. "):
        out[0] = out[0][3:].strip()
    return [x for x in out if x]


def ids_of(items):
    return {m for it in items for m in re.findall(r"\[([A-Z0-9_\-]+)\]", it)}


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5) + 1e-9)


random.seed(7)
sample = random.sample(queries, 30)
emb = KylinEmbedder()
h1_b = h1_e = h3_b = h3_e = 0
lat = 0.0
n = 0
for q in sample:
    ans = answers.get(q["answer_group_id"])
    if not ans:
        continue
    pool_items = split_items(ans["dialogue_memory_texts"]) + split_items(ans["operation_log_texts"])
    pool = {f"m{i}": t for i, t in enumerate(pool_items)}
    req = ids_of(split_items(ans["required_memory_texts"]))
    if not pool or not req:
        continue
    t0 = time.time()
    scores = _bm25(q["query_text"], pool, k1=1.5, b=0.75)
    ranked = [p for p, _ in sorted(scores.items(), key=lambda x: -x[1])][:8]
    qv = emb.embed(q["query_text"][:200])
    cand = {pid: cos(qv, emb.embed(pool[pid][:150])) for pid in ranked}
    er = [p for p, _ in sorted(cand.items(), key=lambda x: -x[1])]
    lat += time.time() - t0

    def hit(idset, top):
        return any(any(r in pool[p] for r in idset) for p in top)

    n += 1
    if hit(req, ranked[:1]):
        h1_b += 1
    if hit(req, er[:1]):
        h1_e += 1
    if hit(req, ranked[:3]):
        h3_b += 1
    if hit(req, er[:3]):
        h3_e += 1

print(f"样本: {n}", flush=True)
print(f"BM25      R@1={h1_b/n:.2%} R@3={h3_b/n:.2%}", flush=True)
print(f"BM25+Emb  R@1={h1_e/n:.2%} R@3={h3_e/n:.2%}", flush=True)
print(f"平均耗时: {lat/n*1000:.0f}ms/query", flush=True)
print("评测2完成", flush=True)
