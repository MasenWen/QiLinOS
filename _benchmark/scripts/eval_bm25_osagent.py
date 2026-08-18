# -*- coding: utf-8 -*-
"""首轮评测：BM25 记忆检索命中率（dev 3000 条）

对照 answer_key 的 required_memory_texts（必须召回的证据），
用项目 _bm25 在答案组记忆池（dialogue+operation）中检索 query_text，
统计 Recall@1/@3/@5 与 forbidden 误召回，按能力维度分组。
"""
import csv
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, "/home/kylin/work/projects/project_dev1")
os.chdir("/home/kylin/work/projects/project_dev1")

from src.memory_engine.strict.retrieval import _bm25

BASE = "_benchmark/test_subset_dev"

# ---------- 加载 ----------
print("加载 answer_key / query_set ...")
answers = {}
with open(f"{BASE}/answer_key_dev_core.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        answers[r["answer_group_id"]] = r

queries = []
with open(f"{BASE}/query_set_dev.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        queries.append(r)
print(f"  answer_group: {len(answers)}, query: {len(queries)}")


def split_items(text: str) -> list[str]:
    """按 '数字.' 序号切分文本条目。"""
    if not text or text.strip() in ("不适用", "不适用：本题没有该类证据。"):
        return []
    parts = re.split(r"\n\s*\d+\.\s*", text.strip())
    out = []
    for p in parts:
        p = p.strip()
        if p and not re.fullmatch(r"\d+\.", p):
            out.append(p)
    # 首条若以 "1." 开头也处理
    if out and out[0].startswith("1. "):
        out[0] = out[0][3:].strip()
    return [x for x in out if x]


def ids_of(items: list[str]) -> set[str]:
    """提取条目中的事件 ID，如 [CERT_R1_XXX]。"""
    ids = set()
    for it in items:
        for m in re.findall(r"\[([A-Z0-9_\-]+)\]", it):
            ids.add(m)
    return ids


# ---------- 评测 ----------
stats = defaultdict(lambda: {"total": 0, "hit1": 0, "hit3": 0, "hit5": 0, "forbid_err": 0})
grand = {"total": 0, "hit1": 0, "hit3": 0, "hit5": 0, "forbid_err": 0}

K1, K3, K5 = 1, 3, 5
for q in queries:
    ans = answers.get(q["answer_group_id"])
    if not ans:
        continue
    # 记忆池：dialogue + operation 条目
    pool_items = split_items(ans["dialogue_memory_texts"]) + split_items(ans["operation_log_texts"])
    pool = {f"mem{i}": t for i, t in enumerate(pool_items)}
    if not pool:
        continue
    required = split_items(ans["required_memory_texts"])
    required_ids = ids_of(required)
    forbidden_ids = ids_of(split_items(ans["forbidden_memory_texts"]))
    if not required_ids:
        # 无 required 时跳过（部分题可能无检索目标）
        continue

    scores = _bm25(q["query_text"], pool, k1=1.5, b=0.75)
    ranked = [pid for pid, _ in sorted(scores.items(), key=lambda x: -x[1])]
    top1, top3, top5 = set(ranked[:K1]), set(ranked[:K3]), set(ranked[:K5])

    # 命中：required ID 出现在 top-k 条目的文本中
    def hit(idset, top):
        return any(any(rid in pool[pid] for rid in idset) for pid in top)

    label = q["ability_label"] or "unknown"
    s = stats[label]
    g = grand
    for bucket in (s, g):
        bucket["total"] += 1
        if hit(required_ids, top1):
            bucket["hit1"] += 1
        if hit(required_ids, top3):
            bucket["hit3"] += 1
        if hit(required_ids, top5):
            bucket["hit5"] += 1
        if forbidden_ids:
            if any(any(fid in pool[pid] for fid in forbidden_ids) for pid in top3):
                bucket["forbid_err"] += 1

# ---------- 输出 ----------
print("\n========== 总体指标（dev 3000 条）==========")
t = grand
print(f"  有效样本: {t['total']}")
print(f"  Recall@1 : {t['hit1']/t['total']:.2%}  ({t['hit1']}/{t['total']})")
print(f"  Recall@3 : {t['hit3']/t['total']:.2%}  ({t['hit3']}/{t['total']})")
print(f"  Recall@5 : {t['hit5']/t['total']:.2%}  ({t['hit5']}/{t['total']})")
print(f"  forbidden 误召回@3: {t['forbid_err']} 次")

print("\n========== 按能力维度分组 ==========")
for label in sorted(stats):
    s = stats[label]
    if s["total"] == 0:
        continue
    print(f"  {label:<22} n={s['total']:>4}  R@1={s['hit1']/s['total']:.2%}  R@3={s['hit3']/s['total']:.2%}  R@5={s['hit5']/s['total']:.2%}  forbid_err={s['forbid_err']}")

print("\n========== 样例（3 条命中/未命中）==========")
shown = 0
for q in queries:
    if shown >= 3:
        break
    ans = answers.get(q["answer_group_id"])
    if not ans:
        continue
    required_ids = ids_of(split_items(ans["required_memory_texts"]))
    if not required_ids:
        continue
    pool_items = split_items(ans["dialogue_memory_texts"]) + split_items(ans["operation_log_texts"])
    pool = {f"mem{i}": t for i, t in enumerate(pool_items)}
    scores = _bm25(q["query_text"], pool, k1=1.5, b=0.75)
    ranked = [pid for pid, _ in sorted(scores.items(), key=lambda x: -x[1])][:3]
    hit = any(any(rid in pool[pid] for rid in required_ids) for pid in ranked)
    print(f"\n[{q['query_id']}] {'命中' if hit else '未命中'} ({q['ability_label']})")
    print(f"  query: {q['query_text'][:100]}")
    print(f"  top3: {[pool[p][:60] for p in ranked]}")
    shown += 1

print("\n评测完成")
