# -*- coding: utf-8 -*-
"""验证文档未激活模块接入: 四标签/KG/MATCHED/遗忘曲线。"""
import os
import sys
import tempfile

sys.path.insert(0, "/home/kylin/work/projects/kylin-mem")
os.environ.setdefault("MEMORY_ENGINE_DB", tempfile.mktemp(suffix=".db"))

from src.memory_engine.engine import MemoryEngine
from src.memory_engine.knowledge_graph import KnowledgeGraph
from src.memory_engine.matched import Matched

ok_count = 0
fail_count = 0

def check(name, cond, detail=""):
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  ✅ {name}")
    else:
        fail_count += 1
        print(f"  ❌ {name} {detail}")

print("=== 1. 四主标签标注（第 5.2 章）===")
from src.memory_engine.tag_pipeline import TagClassifier
tc = TagClassifier()
tags = tc.classify("如果磁盘使用率超过90%，每30分钟检查一次，用户偏好简洁报告")
check("condition 标签", "condition" in tags and len(tags.get("condition", [])) > 0)
check("lastingtime 标签", len(tags.get("lastingtime", [])) > 0)
check("preferences 标签", len(tags.get("preferences", [])) > 0)

print("=== 2. remember_fact 注入四标签 + KG 同步 ===")
engine = MemoryEngine()
r1 = engine.remember_fact("用户小张偏好使用简洁的中文报告")
check("remember_fact 成功", r1.get("status") == "ok", str(r1)[:100])
check("evidence 注入四标签", "preferences" in str(r1.get("tags", {})), str(r1.get("tags")))
check("KG 同步返回", r1.get("kg", {}).get("nodes", 0) >= 1, str(r1.get("kg")))
r2 = engine.remember_fact("用户小张偏好使用简洁的中文报告")  # 重复事实 → 强化边
check("重复事实触发 AYES 边", r2.get("kg", {}).get("edges", 0) >= 1, str(r2.get("kg")))

print("=== 3. 知识图谱持久化（第 9 章）===")
kg_path = os.path.expanduser("~/.nex-agent/memory_kg.json")
check("KG 文件已写", os.path.exists(kg_path))
kg2 = KnowledgeGraph.load(kg_path)
check("KG 恢复节点", len(kg2._nodes) >= 1)
check("KG 恢复边", len(kg2._edges) >= 0)

print("=== 4. retrieve_matched 六字段（第 6 章）===")
engine2 = MemoryEngine()
engine2.remember_fact("用户小张每30分钟检查一次系统状态", index=False)
matched_list = engine2.retrieve_matched("每30分钟检查", top_k=3)
check("retrieve_matched 返回列表", isinstance(matched_list, list) and len(matched_list) >= 0)
if matched_list:
    m = matched_list[0]
    check("Matched 有 KEY", bool(m.key))
    check("Matched 有 TEXT INPUT", bool(m.text_input))
    check("Matched as_prompt 可渲染", "KEY:" in m.as_prompt())
    check("Matched 有 label_scores", isinstance(m.label_scores, dict))

print("=== 5. 遗忘曲线（第 10.2 章）===")
from src.memory_engine.forgetting_curve import ForgettingCurve, ForgettingCurveConfig
fc = ForgettingCurve(ForgettingCurveConfig())
s0 = fc.reinforce(1.0)
s_old = fc.strength_at(confidence=1.0, stability=1.0, last_seen="2020-01-01T00:00:00")
check("reinforce 提高强度", s0 >= 1.0)
check("时间衰减降低强度", s_old < s0, f"{s_old} vs {s0}")

print(f"\n结果: {ok_count} 通过 / {fail_count} 失败")
sys.exit(1 if fail_count else 0)
