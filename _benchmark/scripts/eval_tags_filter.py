# -*- coding: utf-8 -*-
"""评测 3+4：forbidden 硬过滤 + 四标签覆盖（无 embedding，快）"""
import csv, os, re, sys
from collections import Counter, defaultdict

sys.path.insert(0, "/home/kylin/work/projects/project_dev1")
os.chdir("/home/kylin/work/projects/project_dev1")

from src.memory_engine.strict.retrieval import _bm25
from src.memory_engine.tag_pipeline import TagClassifier

BASE = "_benchmark/test_subset_dev"
answers = {r["answer_group_id"]: r for r in csv.DictReader(open(f"{BASE}/answer_key_dev_core.csv", encoding="utf-8-sig"))}
queries = list(csv.DictReader(open(f"{BASE}/query_set_dev.csv", encoding="utf-8-sig")))
print(f"answer_group={len(answers)} query={len(queries)}", flush=True)


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


# ===== 评测4: 四标签覆盖 =====
print("\n========== 评测4: 四主标签分类覆盖（全量 3000）==========", flush=True)
clf = TagClassifier()
tag_dist = {l: 0 for l in ("condition", "obj", "preferences", "lastingtime")}
ability_tag = defaultdict(lambda: Counter())
for q in queries:
    h = clf.classify(q["query_text"])
    for l in tag_dist:
        if h[l]:
            tag_dist[l] += 1
    ability_tag[q["ability_label"]].update({l: bool(h[l]) for l in tag_dist})
for l, n in tag_dist.items():
    print(f"  {l:<12} {n:>5}  ({n/len(queries):.1%})", flush=True)
print("\n能力→标签命中（前6）:", flush=True)
for ab in sorted(ability_tag, key=lambda k: -sum(ability_tag[k].values()))[:6]:
    c = ability_tag[ab]
    print(f"  {ab:<22} c={c['condition']} obj={c['obj']} pref={c['preferences']} time={c['lastingtime']}", flush=True)

# ===== 评测3: forbidden 硬过滤 =====
print("\n========== 评测3: forbidden 硬过滤（全量）==========", flush=True)
err_base = err_filtered = n = 0
r3_base = r3_filtered = 0
for q in queries:
    ans = answers.get(q["answer_group_id"])
    if not ans:
        continue
    pool_items = split_items(ans["dialogue_memory_texts"]) + split_items(ans["operation_log_texts"])
    pool = {f"m{i}": t for i, t in enumerate(pool_items)}
    if not pool:
        continue
    forbidden_ids = ids_of(split_items(ans["forbidden_memory_texts"]))
    required_ids = ids_of(split_items(ans["required_memory_texts"]))
    if not required_ids:
        continue
    n += 1
    scores = _bm25(q["query_text"], pool, k1=1.5, b=0.75)
    ranked = [p for p, _ in sorted(scores.items(), key=lambda x: -x[1])]
    base3, filt3 = ranked[:3], [p for p in ranked if not any(f in pool[p] for f in forbidden_ids)][:3]
    if forbidden_ids:
        if any(any(f in pool[p] for f in forbidden_ids) for p in base3):
            err_base += 1
        if any(any(f in pool[p] for f in forbidden_ids) for p in filt3):
            err_filtered += 1
    if any(any(r in pool[p] for r in required_ids) for p in base3):
        r3_base += 1
    if any(any(r in pool[p] for r in required_ids) for p in filt3):
        r3_filtered += 1
print(f"  样本: {n}", flush=True)
print(f"  基线 forbidden 误召回@3: {err_base}  →  硬过滤后: {err_filtered}", flush=True)
print(f"  R@3 基线: {r3_base/n:.2%}  →  硬过滤后: {r3_filtered/n:.2%}", flush=True)
print("\n评测3+4 完成", flush=True)
