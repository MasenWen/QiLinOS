#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精准删除 LLM 对比测试 — DeepSeek vs 麒麟SDK（除千问外，grok 不测）

对每个 LLM 后端跑同一评测集（tests/eval_precision_forget.py 的 5 案例），
对比：forget_triggered / target_deleted / non_target_kept / pass_rate。

用法：
  .venv/bin/python tests/compare_forget_llm.py [--verbose]
"""
import sys, os, json, time, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MEM0_TELEMETRY"] = "False"

import webchat
from src.memory.mem0_store import mem0_store

parser = argparse.ArgumentParser()
parser.add_argument("--verbose", action="store_true")
args = parser.parse_args()

KW_MAP = {
    "豆浆": ["豆浆", "soy milk", "soymilk"], "北京": ["北京", "beijing", "peking"],
    "联想": ["联想", "lenovo"], "蓝色": ["蓝色", "blue"], "仓鼠": ["仓鼠", "hamster"],
    "足球": ["足球", "football", "soccer"], "上海": ["上海", "shanghai"],
    "华为": ["华为", "huawei"], "绿色": ["绿色", "green"], "乌龟": ["乌龟", "turtle", "tortoise"],
}

def _kw_exists(any_kws):
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

def clear_pending():
    try:
        p = os.path.expanduser("~/.nex-agent/forget_pending_candidates.json")
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass

def run_suite(backend):
    """backend: 'deepseek' 或 'sdk'（直接指定 llm_client 行为）"""
    results = []
    for target, dist, expr, tkw, dkw in CASES:
        clear_pending()
        try:
            mem0_store.delete_all()
        except Exception:
            pass
        for t in (target, dist):
            try:
                mem0_store.add_fact(t)
            except Exception:
                pass
        sid = "cmp-%s-%d" % (backend, int(time.time()))
        try:
            reply1 = webchat._chat(expr, sid)
        except Exception as e:
            reply1 = "(异常: %s)" % e
        triggered = ("确认删除" in reply1) or ("找到" in reply1 and "记忆" in reply1)
        if triggered:
            try:
                reply2 = webchat._chat("确认删除", sid)
            except Exception as e:
                reply2 = "(异常: %s)" % e
        else:
            reply2 = ""
        time.sleep(1)
        target_deleted = (not _kw_exists(KW_MAP.get(tkw, [tkw]))) if triggered else False
        non_target_kept = _kw_exists(KW_MAP.get(dkw, [dkw]))
        results.append({
            "expr": expr, "triggered": triggered,
            "target_deleted": target_deleted, "non_target_kept": non_target_kept,
            "pass": triggered and target_deleted and non_target_kept,
            "reply1": reply1[:100],
        })
    passed = sum(1 for r in results if r["pass"])
    return {"backend": backend, "total": len(results), "passed": passed,
            "pass_rate": round(passed / len(results), 3), "results": results}

def main():
    # 切换 LLM 后端并跑评测
    from src import llm_client
    report = {"suite": "precision_forget_llm_compare", "date": time.strftime("%Y-%m-%d %H:%M")}
    backends = []

    # ① DeepSeek（api provider）
    cfg = llm_client.load_config()
    if cfg.get("provider") == "api" and cfg.get("api_choice") == "deepseek":
        print("\n===== 后端: DeepSeek (deepseek-v4-flash) =====", flush=True)
        r = run_suite("deepseek")
        backends.append(r)
        for i, c in enumerate(r["results"], 1):
            print(f"  [case {i}] {'PASS' if c['pass'] else 'FAIL'} 触发:{c['triggered']} 删:{c['target_deleted']} 留:{c['non_target_kept']}", flush=True)
        print(f"  → {r['passed']}/{r['total']} ({r['pass_rate']*100:.0f}%)", flush=True)

    # ② 麒麟 SDK（provider=sdk）
    print("\n===== 后端: 麒麟 SDK =====", flush=True)
    try:
        os.environ["NEX_LLM_BACKEND_TEST"] = "sdk"
        # 直接改配置切 SDK
        import json as _json
        _cfg_path = os.path.expanduser("~/.nex-agent/llm_config.json")
        _d = _json.load(open(_cfg_path))
        _d["provider"] = "sdk"
        _json.dump(_d, open(_cfg_path, "w"), ensure_ascii=False, indent=2)
        r2 = run_suite("sdk")
        backends.append(r2)
        for i, c in enumerate(r2["results"], 1):
            print(f"  [case {i}] {'PASS' if c['pass'] else 'FAIL'} 触发:{c['triggered']} 删:{c['target_deleted']} 留:{c['non_target_kept']}", flush=True)
        print(f"  → {r2['passed']}/{r2['total']} ({r2['pass_rate']*100:.0f}%)", flush=True)
        # 切回 deepseek
        _d["provider"] = "api"
        _json.dump(_d, open(_cfg_path, "w"), ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  麒麟 SDK 评测失败: {e}", flush=True)

    report["backends"] = backends
    with open("/tmp/compare_forget_llm_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n结果已写: /tmp/compare_forget_llm_result.json")
    return 0

if __name__ == "__main__":
    sys.exit(main())
