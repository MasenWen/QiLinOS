# -*- coding: utf-8 -*-
"""优先级判定测试：强调/时间/敏感/密度/频率因子 + 批量排序 + 淘汰选择"""
import os, sys
sys.path.insert(0, "/home/kylin/work/projects/kylin-mem")

from src.memory.priority import (
    compute_priority, prioritize_items, lowest_priority_ids, PriorityLevel,
)
from security.sensitivity import SensitivityLevel

PASS = 0
FAIL = 0

def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")

print("== 1. 强调因子 ==")
r1 = compute_priority("用户小张非常喜欢喝咖啡，务必记住，这是最重要的偏好")
print(f"  强调记忆 score={r1['score']} level={r1['level']}")
check("强调记忆 HIGH", r1["level"] == PriorityLevel.HIGH.value, r1["level"])
r2 = compute_priority("用户小张昨天查了CPU")
check("普通记忆非HIGH", r2["level"] != PriorityLevel.HIGH.value, r2["level"])
check("强调 > 普通", r1["score"] > r2["score"])

print("\n== 2. 时间衰减 ==")
from datetime import datetime, timedelta
fresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
old = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")
rf = compute_priority("用户小张喜欢喝茶", created_at=fresh)
ro = compute_priority("用户小张喜欢喝茶", created_at=old)
print(f"  新记忆={rf['score']} 旧记忆={ro['score']}")
check("新记忆分数更高", rf["score"] > ro["score"])

print("\n== 3. 敏感加权 ==")
rs = compute_priority("用户小张的手机号是13812345678", sensitivity_level=SensitivityLevel.HIGH)
rn = compute_priority("用户小张喜欢喝茶", sensitivity_level=SensitivityLevel.NONE)
print(f"  敏感={rs['score']} 普通={rn['score']}")
check("敏感记忆分数更高", rs["score"] > rn["score"])
check("敏感记忆受保护(>=MEDIUM)", rs["level"] in ("high", "medium"), rs["level"])

print("\n== 4. 批量排序 + 淘汰选择 ==")
items = [
    {"id": "m1", "memory": "用户小张喜欢喝咖啡", "created_at": fresh},
    {"id": "m2", "memory": "用户的密码是secret123", "created_at": old,
     "sensitivity": SensitivityLevel.CRITICAL},
    {"id": "m3", "memory": "务必记住用户的生日是5月20日，非常重要的信息", "created_at": old},
    {"id": "m4", "memory": "用户小张的系统快照: CPU 45%", "created_at": old},
    {"id": "m5", "memory": "用户小张今天开了三次会议", "created_at": fresh},
]
ranked = prioritize_items(items)
order = [it["id"] for it in ranked]
print("  排序:", order)
for it in ranked:
    print(f"    {it['id']}: {it['priority_level']} {it['priority']} {it['memory'][:20]}")
check("最高优先级含敏感/强调记忆在前", order[0] in ("m2", "m3"))
check("快照记忆(LOW)在最后", order[-1] == "m4" or ranked[-1]["priority_level"] == "low")

victims = lowest_priority_ids(items, keep=3)
print("  淘汰(保留3条):", victims)
check("淘汰数为2", len(victims) == 2)
check("快照记忆被淘汰", "m4" in victims)
check("敏感记忆不被淘汰", "m2" not in victims)

print(f"\n===== 测试结果: PASS {PASS} / FAIL {FAIL} =====")
sys.exit(0 if FAIL == 0 else 1)
