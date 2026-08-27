#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精准遗忘端到端评测 v3 — 验证用 list_all 全量 + 中英关键词

v3 修正：记忆经 LLM 审查可能存为英文（如「仓鼠」→ hamster），
验证改为 list_all 全量扫描 + 关键词中英对照，避免误判。
"""
import sys, os, json, time, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MEM0_TELEMETRY"] = "False"

import webchat
from src.memory.mem0_store import mem0_store

parser = argparse.ArgumentParser()
parser.add_argument("--cases", type=int, default=5)
parser.add_argument("--verbose", action="store_true")
args = parser.parse_args()

# 关键词中英对照（用于验证）
KW_MAP = {
    "豆浆": ["豆浆", "soy milk", "soymilk"],
    "北京": ["北京", "beijing", "peking"],
    "联想": ["联想", "lenovo"],
    "蓝色": ["蓝色", "blue"],
    "仓鼠": ["仓鼠", "hamster"],
    "足球": ["足球", "football", "soccer"],
    "上海": ["上海", "shanghai"],
    "华为": ["华为", "huawei"],
    "绿色": ["绿色", "green"],
    "乌龟": ["乌龟", "turtle", "tortoise"],
}

def _kw_exists(any_kws):
    """全量扫描：任一关键词（中英）出现在任一记忆文本中。"""
    try:
        items = mem0_store.list_all(top_k=300)
    except Exception:
        return False
    for it in items:
        t = str(it.get("memory", "")).lower()
        for k in any_kws:
            if k.lower() in t:
                return True
    return False

CASES = [
    ("用户喜欢喝豆浆", "用户喜欢踢足球", "忘掉我喜欢喝豆浆的记忆", "豆浆", "足球"),
    ("用户家住北京", "用户家住上海", "删除我住在北京的记录", "北京", "上海"),
    ("用户的电脑是联想", "用户的手机是华为", "忘掉电脑品牌的记忆", "联想", "华为"),
    ("用户喜欢蓝色", "用户喜欢绿色", "忘记我喜欢蓝色的偏好", "蓝色", "绿色"),
    ("用户的宠物是仓鼠", "用户的宠物是乌龟", "删除关于仓鼠的记忆", "仓鼠", "乌龟"),
]

def _clear_pending():
    # 清理 ForgetFlow 残留 pending 状态（避免上个 case 拦截）
    try:
        p = os.path.expanduser("~/.nex-agent/forget_pending_candidates.json")
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass

def run_case(target, distractor, forget_expr, target_kw, dist_kw):
    r = {"target": target, "distractor": distractor, "expr": forget_expr,
         "target_kw": target_kw, "dist_kw": dist_kw}
    _clear_pending()
    try:
        mem0_store.delete_all()
    except Exception:
        pass
    for t in (target, distractor):
        try:
            mem0_store.add_fact(t)
        except Exception as e:
            r["write_error"] = str(e)[:60]
            return r
    sid = "eval-fg-%d" % int(time.time())
    try:
        reply1 = webchat._chat(forget_expr, sid)
    except Exception as e:
        reply1 = "(异常: %s)" % e
    r["reply1"] = reply1[:150]
    r["forget_triggered"] = ("确认删除" in reply1) or ("找到" in reply1 and "记忆" in reply1)
    if r["forget_triggered"]:
        try:
            reply2 = webchat._chat("确认删除", sid)
        except Exception as e:
            reply2 = "(异常: %s)" % e
        r["reply2"] = reply2[:100]
    else:
        r["reply2"] = ""
    time.sleep(1)
    # 验证：目标关键词不存在（已删），干扰关键词仍存在（保留）
    r["target_deleted"] = not _kw_exists(KW_MAP.get(target_kw, [target_kw])) if r["forget_triggered"] else False
    r["non_target_kept"] = _kw_exists(KW_MAP.get(dist_kw, [dist_kw]))
    r["pass"] = r["forget_triggered"] and r["target_deleted"] and r["non_target_kept"]
    return r

def main():
    results = []
    for i in range(min(args.cases, len(CASES))):
        target, dist, expr, tkw, dkw = CASES[i]
        r = run_case(target, dist, expr, tkw, dkw)
        results.append(r)
        if args.verbose:
            status = "PASS" if r["pass"] else "FAIL"
            print(f"[case {i+1}] {status} | 触发:{r.get('forget_triggered')} 目标删:{r.get('target_deleted')} 干扰留:{r.get('non_target_kept')}")
            print(f"    reply1: {(r.get('reply1') or '')[:70]}")
            print(f"    reply2: {(r.get('reply2') or '')[:70]}")
    passed = sum(1 for r in results if r.get("pass"))
    total = len(results)
    report = {"suite": "precision_forget_e2e_v3", "total": total, "passed": passed,
              "pass_rate": round(passed / total, 3) if total else None, "results": results}
    with open("/tmp/eval_precision_forget_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n===== 精准遗忘端到端 v3: {passed}/{total} PASS ({report['pass_rate']*100 if report['pass_rate'] else 0:.0f}%) =====")
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
