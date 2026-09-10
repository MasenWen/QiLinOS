#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并已有重复偏好：同一 canonical key（dim=val 相同、仅 scope/原文措辞不同）只留最新一条。

用法：
    python tools/dedupe_preferences.py            # 预演（只报告，不改库）
    python tools/dedupe_preferences.py --apply    # 执行（旧的重复项标记 deleted，保留可查审计）
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

DB = os.environ.get("NEX_STRICT_DB",
                    os.path.expanduser("~/.nex-agent/memory_engine_strict.db"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="nex_user")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只预演）")
    ap.add_argument("--db", default=DB)
    a = ap.parse_args()

    from src.memory_engine.strict.evidence import canonical_claim_key
    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    rows = list(con.execute(
        "SELECT memory_id, slot_key, status, updated_at, payload_json FROM strict_memories "
        "WHERE user_id = ? AND status NOT IN ('deleted','blocked') ORDER BY updated_at",
        (a.user,)))

    groups: dict = {}
    for r in rows:
        payload = json.loads(r["payload_json"])
        # 记忆正文在 semantic_value（严格引擎 payload 里没有 text/content 字段）
        text = str(payload.get("semantic_value") or payload.get("text")
                   or payload.get("content") or "")
        key = canonical_claim_key(text)
        groups.setdefault(key, []).append((r, payload, text))

    dup_total = 0
    print("用户 %s：%d 条活跃记忆，%d 个归一化键" % (a.user, len(rows), len(groups)))
    for key, items in groups.items():
        if len(items) < 2:
            continue
        dup_total += len(items) - 1
        keep = items[-1]
        print("\n[重复] 归一化键 %s（%d 条 → 保留 1 条）" % (key, len(items)))
        for r, payload, text in items:
            mark = "保留" if r["memory_id"] == keep[0]["memory_id"] else "标记删除"
            print("   %-6s %-10s %-26s v%-2s %s" % (
                mark, r["memory_id"][:10], r["updated_at"], payload.get("version"), text[:70]))
        if a.apply:
            for r, payload, text in items:
                if r["memory_id"] == keep[0]["memory_id"]:
                    continue
                # 审计信息写进 provenance（payload 顶层只能放 schema 字段，
                # 否则 StrictMemory(**payload) 会 TypeError → 面板读空）
                prov = payload.get("provenance")
                if not isinstance(prov, dict):
                    prov = {}
                prov.update({
                    "dedupe_of": keep[0]["memory_id"],
                    "dedupe_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "dedupe_reason": "canonical_claim_key 相同（仅 scope/原文措辞不同）",
                })
                payload["provenance"] = prov
                # status 同时写在列与 payload：读取侧用的是 payload（list_memories 只取 payload_json）
                payload["status"] = "deleted"
                con.execute(
                    "UPDATE strict_memories SET status = 'deleted', payload_json = ? WHERE memory_id = ?",
                    (json.dumps(payload, ensure_ascii=False), r["memory_id"]))
            con.commit()

    if a.apply:
        con.commit()
        print("\n已合并重复项 %d 条（状态置 deleted，原内容保留在 payload 中可追溯）" % dup_total)
    else:
        print("\n预演结束：可合并 %d 条；加 --apply 执行" % dup_total)
    con.close()


if __name__ == "__main__":
    main()
