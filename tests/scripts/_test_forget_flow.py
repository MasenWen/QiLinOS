# -*- coding: utf-8 -*-
"""ForgetFlow 端到端测试 v2：精确验证 取消 / 删除全部 / 删除指定条"""
import io, os, sys, json

os.environ["MEM0_TELEMETRY"] = "False"
sys.path.insert(0, "/home/kylin/work/projects/project_dev1")

from src.memory.forget_flow import ForgetFlow
from src.memory.mem0_store import mem0_store

STATE = os.path.expanduser("~/.nex-agent/forget_pending_candidates.json")
if os.path.exists(STATE):
    os.remove(STATE)

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

def count_with(kw):
    items = mem0_store.list_all(top_k=100)
    return len([i for i in items if kw in str(i.get("memory", ""))])

print("== 准备：清空后写入 3 条测试记忆 ==")
try:
    mem0_store.delete_all(user_id="nex_user")
except Exception as e:
    print("  clear:", e)
mem0_store.add_fact("用户喜欢喝咖啡，每天一杯", user_id="nex_user")
mem0_store.add_fact("用户喜欢喝绿茶", user_id="nex_user")
mem0_store.add_fact("用户的打印机型号是 HP LaserJet", user_id="nex_user")
print(f"  咖啡:{count_with('coffee')} 绿茶:{count_with('green tea')} 打印机:{count_with('printer')}")

ff = ForgetFlow()

print("\n== 场景1：忘记「咖啡」→ 展示候选 ==")
reply, handled = ff.handle("忘记我喜欢喝咖啡", "sess-1")
print("  reply:", reply.replace("\n", " | ")[:180])
check("1 handled=True", handled)
check("1 展示候选", "确认" in reply)
st = ff._load_state()
check("1 状态已保存", st.get("active") and len(st.get("candidates", [])) >= 1)

print("\n== 场景2：取消 ==")
reply2, handled2 = ff.handle("算了，取消吧", "sess-1")
check("2 handled=True 回复取消", handled2 and "取消" in reply2)
check("2 记忆仍在", count_with("coffee") == 1)

print("\n== 场景3：再次发起 → 删除「第1条」=咖啡 ==")
reply3, handled3 = ff.handle("删除 咖啡", "sess-1")
check("3 展示候选", handled3 and "确认" in reply3)
# 找到候选里咖啡那条的序号
cands = ff._load_state().get("candidates", [])
coffee_idx = None
for i, c in enumerate(cands, 1):
    if "coffee" in str(c.get("text", "")).lower():
        coffee_idx = i
print(f"  候选{len(cands)}条, 咖啡在第{coffee_idx}条")
reply4, handled4 = ff.handle(f"只删除第{coffee_idx}条", "sess-1")
print("  reply4:", reply4.replace("\n", " | ")[:150])
check("4 handled=True", handled4)
check("4 咖啡已删除", count_with("coffee") == 0)
check("4 绿茶保留", count_with("green tea") == 1)

print("\n== 场景4：删除「绿茶」（确认全部）==")
reply5, handled5 = ff.handle("忘记 绿茶", "sess-1")
check("5 展示绿茶候选", handled5 and "green tea" in reply5)
reply6, handled6 = ff.handle("确认删除", "sess-1")
print("  reply6:", reply6.replace("\n", " | ")[:150])
check("6 绿茶已删除", count_with("green tea") == 0)
check("6 打印机保留", count_with("printer") == 1)

print("\n== 场景5：非遗忘消息不拦截 ==")
reply7, handled7 = ff.handle("帮我查一下CPU占用", "sess-1")
check("7 handled=False", not handled7)

print("\n== 场景6：无匹配记忆 ==")
reply8, handled8 = ff.handle("忘记 火星车配置", "sess-1")
check("8 提示未找到", handled8 and "没有找到" in reply8)

print("\n== 场景7：跨会话不打扰（pending 属于 sess-1 时 sess-2 正常对话）==")
reply9, handled9 = ff.handle("忘记 打印机", "sess-1")
check("9 sess-1 进入 pending", handled9 and "确认" in reply9)
reply10, handled10 = ff.handle("你好", "sess-2")
check("10 sess-2 不受影响 handled=False", not handled10)
reply11, handled11 = ff.handle("取消", "sess-1")
check("11 sess-1 取消", handled11 and "取消" in reply11)
check("11 打印机保留", count_with("printer") == 1)

print(f"\n===== 测试结果: PASS {PASS} / FAIL {FAIL} =====")
sys.exit(0 if FAIL == 0 else 1)
