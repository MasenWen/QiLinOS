# -*- coding: utf-8 -*-
"""ForgetFlow v2 测试（mock store，纯逻辑验证）：
分页 / 敏感二次确认 / 审计 / 批量遗忘 / LLM开关 / 会话隔离 / 指定删除"""
import io, os, sys, json

sys.path.insert(0, "/home/kylin/work/projects/project_dev1")
from src.memory.forget_flow import ForgetFlow

# ---- mock store：绕开 mem0/嵌入/LLM，只测 ForgetFlow 逻辑 ----
class MockStore:
    def __init__(self):
        self.memories = {}   # id -> text
        self._seq = 0

    def add_fact(self, text):
        self._seq += 1
        mid = f"m{self._seq}"
        self.memories[mid] = text
        return mid

    def search(self, query, top_k=10):
        out = []
        for mid, text in self.memories.items():
            if query.lower() in text.lower():
                out.append({"id": mid, "memory": text, "score": 0.9})
            else:
                out.append({"id": mid, "memory": text, "score": 0.5})
        return out[:top_k]

    def list_all(self, top_k=300):
        return [{"id": mid, "memory": text} for mid, text in self.memories.items()]

    class _Mem:
        def __init__(self, store):
            self.store = store
        def delete(self, memory_id=None):
            if memory_id in self.store.memories:
                del self.store.memories[memory_id]
                return True
            return False

    @property
    def _memory(self):
        return self._Mem(self)


STATE = os.path.expanduser("~/.nex-agent/forget_pending_candidates.json")
AUDIT = os.path.expanduser("~/.nex-agent/forget_audit.log")
for p in (STATE, AUDIT):
    if os.path.exists(p):
        os.remove(p)

PASS = 0
FAIL = 0

def reset_state():
    if os.path.exists(STATE):
        os.remove(STATE)

def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")

def count_with(store, kw):
    return len([t for t in store.memories.values() if kw.lower() in t.lower()])

store = MockStore()
store.add_fact("用户小张喜欢喝咖啡")
store.add_fact("用户小张喜欢喝绿茶")
store.add_fact("用户小张的电话号码是13812345678")   # 敏感(手机号)
store.add_fact("用户小张的身份证号是110101199001011234")  # 敏感(身份证)
for i in range(6):
    store.add_fact(f"用户小张的收藏夹第{i+1}项是科幻小说")

ff = ForgetFlow(store=store, llm_routing=False)   # 纯规则模式（同时验证 ⑤）

print("\n== ④ 批量遗忘：删除关于咖啡和绿茶 ==")
reply, handled = ff.handle("删除关于咖啡和绿茶的所有记忆", "sess-b")
print("  reply:", reply.replace("\n", " | ")[:150])
check("批量 handled=True", handled)
check("批量 候选含咖啡", "咖啡" in reply)
check("批量 候选含绿茶", "绿茶" in reply)
reply2, handled2 = ff.handle("确认删除", "sess-b")
print("  reply2:", reply2.replace("\n", " | ")[:110])
check("批量 删除成功", "已删除" in reply2)
check("批量 咖啡已删", count_with(store, "咖啡") == 0)
check("批量 绿茶已删", count_with(store, "绿茶") == 0)

reset_state()
print("\n== ② 敏感二次确认（手机号）==")
reply3, handled3 = ff.handle("忘记 电话", "sess-s")
print("  reply3:", reply3.replace("\n", " | ")[:160])
check("敏感 候选带⚠️标记", handled3 and "⚠️[敏感]" in reply3)
reply4, handled4 = ff.handle("确认删除", "sess-s")
print("  reply4:", reply4.replace("\n", " | ")[:120])
check("敏感 首轮被拦截", handled4 and "确认删除敏感记忆" in reply4)
check("敏感 拦截后未删除", count_with(store, "13812345678") == 1)
reply5, handled5 = ff.handle("确认删除敏感记忆", "sess-s")
print("  reply5:", reply5.replace("\n", " | ")[:100])
check("敏感 解锁", handled5 and "再次回复" in reply5)
reply6, handled6 = ff.handle("确认删除", "sess-s")
print("  reply6:", reply6.replace("\n", " | ")[:110])
check("敏感 最终删除", handled6 and "已删除" in reply6)
check("敏感 手机号已删", count_with(store, "13812345678") == 0)

reset_state()
print("\n== ②b 敏感二次确认（身份证，指定删除也要二次确认）==")
reply3b, handled3b = ff.handle("忘记 身份证", "sess-s2")
print("  reply3b:", reply3b.replace("\n", " | ")[:160])
check("身份证 候选带标记", handled3b and "⚠️[敏感]" in reply3b)
reply4b, handled4b = ff.handle("只删除第1条", "sess-s2")
print("  reply4b:", reply4b.replace("\n", " | ")[:120])
check("身份证 指定删除也被拦截", handled4b and "确认删除敏感记忆" in reply4b)
reply5b, handled5b = ff.handle("确认删除敏感记忆", "sess-s2")
check("身份证 解锁", handled5b and "再次回复" in reply5b)
reply6b, handled6b = ff.handle("确认删除", "sess-s2")
check("身份证 最终删除", handled6b and "已删除" in reply6b)
check("身份证已删", count_with(store, "110101") == 0)

reset_state()
print("\n== ① 分页：6条候选 → 第1页5条 → 下一页 ==")
reply7, handled7 = ff.handle("忘记 收藏夹", "sess-p")
print("  reply7:", reply7.replace("\n", " | ")[:180])
check("分页 提示第1/2页", handled7 and "1/2" in reply7)
reply8, handled8 = ff.handle("下一页", "sess-p")
print("  reply8:", reply8.replace("\n", " | ")[:130])
check("分页 翻到2/2", handled8 and "2/2" in reply8)
reply8b, handled8b = ff.handle("下一页", "sess-p")
check("分页 末页提示", handled8b and "最后一页" in reply8b)
reply9, handled9 = ff.handle("取消", "sess-p")
check("分页 取消", handled9 and "取消" in reply9)

print("\n== ③ 审计日志 ==")
if os.path.exists(AUDIT):
    lines = open(AUDIT, encoding="utf-8").read().strip().splitlines()
    print(f"  审计 {len(lines)} 条")
    check("审计 有删除", any("delete" in l for l in lines))
    check("审计 有取消", any("cancel" in l for l in lines))
    check("审计 有敏感标记", any('"sensitive": true' in l for l in lines))
else:
    check("审计 文件存在", False, "无文件")

print("\n== ⑤ LLM 开关验证 ==")
check("llm_routing=False", ff._llm_routing is False)
reset_state()
reply10, handled10 = ff.handle("忘记 科幻", "sess-r")
check("纯规则可工作", handled10 and "科幻" in reply10)
reply10c, handled10c = ff.handle("取消", "sess-r")
reset_state()
reply11, handled11 = ff.handle("帮我查CPU", "sess-r")
check("非遗忘不拦截", not handled11)

print("\n== 指定删除 + 会话隔离 ==")
reset_state()
reply12, handled12 = ff.handle("忘记 科幻", "sess-iso")
check("展示候选", handled12 and "科幻" in reply12)
cands = ff._load_state().get("candidates", [])
check("候选6条", len(cands) == 6)
reply13, handled13 = ff.handle("只删除第1条", "sess-iso")
print("  reply13:", reply13.replace("\n", " | ")[:120])
check("删除第1条成功", handled13 and "已删除 1 条" in reply13)
check("还剩5条科幻", count_with(store, "科幻") == 5)
reset_state()
reply14, handled14 = ff.handle("忘记 科幻", "sess-other")
check("新会话可发起流程", handled14 and "科幻" in reply14)
reply15, handled15 = ff.handle("取消", "sess-other")
check("新会话取消", handled15 and "取消" in reply15)

print(f"\n===== 测试结果: PASS {PASS} / FAIL {FAIL} =====")
sys.exit(0 if FAIL == 0 else 1)
