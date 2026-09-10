#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 docs/演示界面输入清单.json 逐条**原文输入** webchat，核对回复与「记忆」面板。

用法：
    python tests/run_demo_inputs.py [--base http://127.0.0.1:8080] [--no-clear]
                                    [--out docs/demo_inputs_report.json]

清单里的输入文字由 tools/gen_demo_inputs.py 从视频脚本字符级抽取，
本脚本只负责"原样发送 + 核对"，不做任何文本改写（避免与脚本不一致）。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _json_req(url, payload=None, timeout=600):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"} if data else {},
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def chat(base, session_id, message, t_limit=900):
    """SSE 流式读取，遇 [DONE]/done 即停；返回 (回复, 首块秒, 完成秒)。"""
    req = urllib.request.Request(
        base + "/api/chat/stream",
        data=json.dumps({"message": message, "session_id": session_id}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    t0, first, done, chunks = time.time(), None, None, []
    with urllib.request.urlopen(req, timeout=t_limit) as r:
        while True:
            raw = r.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "ignore")
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            if "chunk" in obj:
                first = first if first is not None else time.time() - t0
                chunks.append(obj["chunk"])
            if obj.get("done"):
                done = time.time() - t0
    return "".join(chunks), first or -1, done or -1


def panel_text(items):
    return json.dumps(items, ensure_ascii=False)


def run_check(chk, reply, items):
    kind, val, name = chk["kind"], chk.get("value"), chk["name"]
    flat = panel_text(items)
    if kind == "reply_contains":
        return val in reply, name
    if kind == "reply_contains_any":
        return any(v in reply for v in val), name
    if kind == "reply_not_contains":
        return val not in reply, name
    if kind == "reply_regex":
        return bool(re.search(val, reply)), name
    if kind == "reply_not_regex":
        return not re.search(val, reply), name
    if kind == "reply_maxlen":
        return len(reply) <= val, name
    if kind == "reply_order":
        idx = [reply.find(v) for v in val]
        return all(i >= 0 for i in idx) and idx == sorted(idx), name
    if kind == "panel_contains":
        return val in flat, name
    if kind == "panel_contains_any":
        return any(v in flat for v in val), name
    if kind == "panel_not_contains":
        return val not in flat, name
    if kind == "panel_count_task":
        return sum(1 for it in items if it.get("kind") == "task_event") >= val, name
    return False, name + "(未知核对类型)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--spec", default=os.path.join(ROOT, "docs", "演示界面输入清单.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "demo_inputs_report.json"))
    ap.add_argument("--no-clear", action="store_true", help="不清空记忆，直接在现有状态上跑")
    ap.add_argument("--steps", default="", help="只跑指定步骤（逗号分隔，如 s1-1,s1-2），默认全部")
    a = ap.parse_args()

    spec = json.load(open(a.spec, encoding="utf-8"))
    steps = spec["steps"]
    if a.steps.strip():
        want = [s.strip() for s in a.steps.split(",") if s.strip()]
        steps = [s for s in steps if s["id"] in want]
        missing = [w for w in want if w not in [s["id"] for s in spec["steps"]]]
        if missing:
            print("清单中不存在这些步骤：%s" % ",".join(missing))
            return 2
    print("清单：%s（脚本 SHA256 %s，共 %d 步）" % (spec["script"], spec["script_sha256"][:12], len(steps)))

    if not a.no_clear:
        for path, payload in (("/api/mem/clear", {"confirm": True}),
                              ("/api/sessions/clear_all", {"confirm": True, "clear_log": True})):
            try:
                print("  %-24s -> %s" % (path, json.dumps(_json_req(a.base + path, payload), ensure_ascii=False)[:110]))
            except Exception as e:
                print("  %-24s 失败: %s" % (path, e))

    results, checks = [], []
    for st in steps:
        t0 = time.time()
        try:
            reply, t_first, t_done = chat(a.base, st["session_id"], st["input"])
        except Exception as e:
            reply, t_first, t_done = "(请求失败: %s)" % e, -1, -1
        time.sleep(2)
        try:
            items = _json_req(a.base + "/api/memories").get("memories", [])
        except Exception as e:
            items = [{"error": str(e)}]
        row = dict(id=st["id"], session=st["session_id"], input=st["input"], input_md5=st["input_md5"],
                   reply=reply, first_chunk_s=round(t_first, 1), done_s=round(t_done, 1),
                   wall_s=round(time.time() - t0, 1), panel=items, checks=[])
        print("\n[%s] %s 首块 %.1fs / 完成 %.1fs" % (st["id"], st["title"], t_first, t_done))
        print("   输入: %s" % st["input"])
        print("   回复: %s" % reply.replace("\n", " ⏎ ")[:220])
        for it in items:
            print("   面板: %-11s v%-3s %s" % (it.get("kind", "?"), it.get("version", "?"), it.get("text", "")[:100]))
        for chk in st["checks"]:
            ok, name = run_check(chk, reply, items)
            row["checks"].append({"name": name, "ok": bool(ok), "kind": chk["kind"], "value": chk.get("value")})
            checks.append((st["id"], name, bool(ok)))
            print("   %s %s" % ("[PASS]" if ok else "[FAIL]", name))
        results.append(row)

    passed = sum(1 for _, _, ok in checks if ok)
    print("\n=== 核对结果：%d/%d 通过 ===" % (passed, len(checks)))
    for sid, name, ok in checks:
        if not ok:
            print("  [FAIL] %s %s" % (sid, name))
    report = {"spec": os.path.basename(a.spec), "script_sha256": spec["script_sha256"],
              "generated_at": spec["generated_at"], "base": a.base,
              "passed": passed, "total": len(checks), "steps": results}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("报告已写入 %s" % a.out)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
