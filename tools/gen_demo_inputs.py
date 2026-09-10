#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从视频脚本生成「界面输入清单」（Markdown + JSON），并宣称可被 run_demo_inputs.py 直接驱动。

用法：
    python tools/gen_demo_inputs.py --script <脚本.md> --out-dir <仓库目录>

设计要点：输入文字一律从脚本对应行号的 “……” 引号内**字符级抽取**，
不手工转写；脚本改动后重跑本脚本即可同步，抽取失败会直接报错。
"""
import argparse
import hashlib
import json
import os
import re
import datetime

# 步骤元数据：UI 输入文字由脚本行号抽取，其余为人工标注的会话/核对要求
STEPS = [
    dict(id="s1-1", scene=1, time="00:46-01:03", line=22, session="new", session_id="s1_decl",
         title="建立两项工作习惯",
         ui=["新建会话", "输入后保留完整响应"],
         expect_reply=["分别确认两条习惯（结论优先、任务编号按紧急度）"],
         expect_panel=["两条独立偏好记录：结论优先 / 编号并按紧急程度排序"],
         checks=[dict(kind="reply_contains", value="结论", name="回复含「结论」"),
                 dict(kind="reply_contains_any", value=["编号", "排序"], name="回复含编号/排序说明"),
                 dict(kind="panel_contains", value="结论优先", name="面板出现「结论优先」"),
                 dict(kind="panel_contains", value="编号并按紧急程度排序", name="面板出现「编号并按紧急程度排序」")]),
    dict(id="s1-2", scene=1, time="01:18-01:32", line=24, session="new", session_id="s1_use",
         title="新会话复用偏好",
         ui=["新建会话（空白）"],
         expect_reply=["先给结论，再用编号按紧急程度排列三项任务"],
         expect_panel=["不变：两条偏好"],
         checks=[dict(kind="reply_regex", value=r"(^|\n|\s)1[.、)]", name="回复为编号列表"),
                 dict(kind="reply_contains", value="结论", name="回复先给结论"),
                 dict(kind="reply_order", value=["彩排", "报销", "纪要"], name="三项按彩排→报销→纪要排序")]),
    dict(id="s1-3", scene=1, time="01:48-02:02", line=26, session="same", session_id="s1_use",
         title="本轮要求优先（临时覆盖）",
         ui=["同一会话继续输入"],
         expect_reply=["改为一句话回答，不套用编号偏好"],
         expect_panel=["偏好未被改写"],
         checks=[dict(kind="reply_not_regex", value=r"(^|\n)\s*1[.、)]", name="回复不再编号"),
                 dict(kind="reply_maxlen", value=140, name="回复为一句话（≤140 字）")]),
    dict(id="s2-1", scene=2, time="02:30-02:47", line=36, session="new", session_id="s2_create",
         title="建立会议与任务记录",
         ui=["新建会话"],
         expect_reply=["确认保存会议时间/地点/两项待办状态"],
         expect_panel=["任务档案：麒麟软件项目会议 · 上午10点 · 会议室 A · 两项未完成 + 记录时间"],
         checks=[dict(kind="panel_contains", value="麒麟软件项目会议", name="面板出现会议名"),
                 dict(kind="panel_contains", value="会议室 A", name="面板出现地点"),
                 dict(kind="panel_contains", value="上午10点", name="面板出现上午10点"),
                 dict(kind="reply_contains", value="上午", name="回复含上午时间")]),
    dict(id="s2-2", scene=2, time="03:02-03:20", line=38, session="new", session_id="s2_update",
         title="跨会话更新（新旧冲突）",
         ui=["新建会话"],
         expect_reply=["最新状态生效：下午两点/线上/功能清单已完成"],
         expect_panel=["新记录：下午2点 · 线上 · 功能清单（已完成）", "较早记录保留可查"],
         checks=[dict(kind="panel_contains", value="下午2点", name="面板出现下午2点"),
                 dict(kind="panel_contains", value="线上", name="面板出现线上"),
                 dict(kind="panel_contains", value="已完成", name="面板出现已完成"),
                 dict(kind="panel_count_task", value=2, name="面板同时保留新旧两条任务档案")]),
    dict(id="s2-3", scene=2, time="03:35-03:52", line=40, session="new", session_id="s2_restore",
         title="中断任务恢复",
         ui=["新建会话", "可打开「记忆」面板核对两条记录"],
         expect_reply=["本周五下午两点线上；功能清单已完成；下一步准备演示账号；并说明依据"],
         expect_panel=["新旧两条记录同屏，标注记录时间"],
         checks=[dict(kind="reply_contains_any", value=["下午两点", "下午2点", "14:00"], name="恢复最新时间"),
                 dict(kind="reply_contains", value="线上", name="恢复会议方式=线上"),
                 dict(kind="reply_contains", value="已完成", name="指出已完成内容"),
                 dict(kind="reply_contains_any", value=["依据", "来源", "记录", "版本"], name="给出判断依据"),
                 dict(kind="reply_not_contains", value="13800000001", name="回复不含完整号码")]),
    dict(id="s3-1", scene=3, time="04:48-05:06", line=52, session="new", session_id="s3_decl",
         title="敏感信息保护 + 两项习惯",
         ui=["新建会话"],
         expect_reply=["两项偏好分别保存；电话以掩码显示，不出现完整号码"],
         expect_panel=["二十四小时制 / 总结末尾加「下一步」两项偏好", "面板中不出现任何号码"],
         checks=[dict(kind="reply_contains", value="138****0001", name="回复显示掩码 138****0001"),
                 dict(kind="reply_not_contains", value="13800000001", name="回复不含完整号码"),
                 dict(kind="panel_not_contains", value="13800000001", name="面板不含完整号码"),
                 dict(kind="panel_not_contains", value="138****0001", name="面板不保留号码片段"),
                 dict(kind="panel_contains_any", value=["24_hour_clock", "二十四小时制"], name="面板含时间格式偏好")]),
    dict(id="s3-2", scene=3, time="05:24-05:39", line=54, session="new", session_id="s3_use",
         title="跨会话复用 + 不泄露号码",
         ui=["新建会话（不重复号码）"],
         expect_reply=["用 15:00 二十四小时制，末尾给出「下一步」，画面不出现完整号码"],
         expect_panel=["不变"],
         checks=[dict(kind="reply_contains_any", value=["15:00", "15 点", "15点"], name="二十四小时制生效"),
                 dict(kind="reply_contains", value="下一步", name="末尾含「下一步」"),
                 dict(kind="reply_not_contains", value="13800000001", name="未泄露完整号码")]),
    dict(id="s3-3", scene=3, time="05:54-06:09", line=56, session="same", session_id="s3_use",
         title="自然语言指定遗忘（待确认）",
         ui=["同一会话继续输入", "展示唯一命中项"],
         expect_reply=["列出唯一命中的时间格式偏好，等待确认"],
         expect_panel=["两条偏好仍在（尚未删除）"],
         checks=[dict(kind="reply_contains_any", value=["确认", "删除"], name="要求确认删除"),
                 dict(kind="panel_contains_any", value=["24_hour_clock", "二十四小时制"], name="确认前偏好仍在")]),
    dict(id="s3-4", scene=3, time="05:54-06:09", line=56, session="same", session_id="s3_use",
         title="确认删除（脚本未给原文，按系统提示输入）",
         derived=True, input_override="确认删除。",
         ui=["系统提示「回复「确认删除」删除全部，或指定「删除第1条」」后输入"],
         expect_reply=["执行删除，仅删除时间格式偏好"],
         expect_panel=["24_hour_clock 消失；总结末尾加「下一步」保留"],
         checks=[dict(kind="panel_not_contains", value="24_hour_clock", name="时间格式偏好已删除"),
                 dict(kind="panel_contains", value="add_next_step_line", name="「下一步」偏好保留")]),
    dict(id="s3-5", scene=3, time="06:09-06:24", line=57, session="new", session_id="s3_verify",
         title="删除后再次验证",
         ui=["新建会话，再输入同一句", "打开记忆列表核对"],
         expect_reply=["已删除的时间偏好不再生效；「下一步」习惯仍在；号码未被带入"],
         expect_panel=["只剩「下一步」偏好"],
         checks=[dict(kind="reply_contains", value="下一步", name="「下一步」习惯仍在"),
                 dict(kind="reply_not_contains", value="13800000001", name="号码未带入回答"),
                 dict(kind="panel_contains", value="add_next_step_line", name="面板保留「下一步」偏好"),
                 dict(kind="panel_not_contains", value="24_hour_clock", name="面板无时间格式偏好")]),
]


def extract_line(script_lines, lineno):
    """返回脚本第 lineno 行第一个 “……” 的原文。"""
    if lineno < 1 or lineno > len(script_lines):
        raise SystemExit("行号越界: %d" % lineno)
    line = script_lines[lineno - 1]
    m = re.search(r"“([^”]+)”", line)
    if not m:
        raise SystemExit("第 %d 行未找到 “……” 原文: %s" % (lineno, line[:80]))
    return m.group(1)


def build(script_path):
    raw = open(script_path, encoding="utf-8").read()
    lines = raw.split("\n")
    steps = []
    for st in STEPS:
        text = st.get("input_override") or extract_line(lines, st["line"])
        steps.append(dict(st, input=text,
                          input_md5=hashlib.md5(text.encode("utf-8")).hexdigest(),
                          source=("manual" if st.get("input_override") else "script"),
                          source_line=st["line"],
                          source_line_text=lines[st["line"] - 1].strip()[:200]))
    meta = {
        "script": os.path.basename(script_path),
        "script_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "steps": steps,
    }
    return meta


def to_markdown(meta):
    o = []
    o.append("# 麒麟 OS Agent 记忆系统 · 三场景「界面输入」清单（逐字）\n")
    o.append("> 由 `tools/gen_demo_inputs.py` 从视频脚本自动生成，**输入文字为脚本原文抽取**"
             "（脚本行号与 MD5 见每节标注），请勿手改本文件，改脚本后重跑生成即可。\n")
    o.append("- 来源脚本：`%s`" % meta["script"])
    o.append("- 脚本 SHA256：`%s`" % meta["script_sha256"])
    o.append("- 生成时间：%s\n" % meta["generated_at"])
    o.append("## 一、录制前剪贴板准备（按顺序复制，共 %d 条）\n" % len(meta["steps"]))
    for st in meta["steps"]:
        tag = "" if st["source"] == "script" else "（脚本未给原文，按系统提示输入）"
        o.append("**%s｜场景%d %s%s**" % (st["id"], st["scene"], st["time"], tag))
        o.append("```text")
        o.append(st["input"])
        o.append("```")
    o.append("## 二、逐步输入与核对清单\n")
    o.append("| 步骤 | 场景/时间码 | 会话 | 界面输入（逐字） | 输入后应看到 | 同屏操作 | 脚本行 |")
    o.append("|---|---|---|---|---|---|---|")
    for st in meta["steps"]:
        sess = {"new": "**新建会话**", "same": "同一会话继续"}[st["session"]]
        inp = st["input"].replace("|", "\\|")
        exp = "；".join(st["expect_reply"] + ["面板：" + x for x in st["expect_panel"]])
        ui = "；".join(st["ui"])
        o.append("| %s | S%d %s | %s | `%s` | %s | %s | %d |" %
                 (st["id"], st["scene"], st["time"], sess, inp, exp, ui, st["source_line"]))
    o.append("\n## 三、步骤明细（含 MD5 与自动核对项）\n")
    for st in meta["steps"]:
        o.append("### %s　%s（场景%d %s）" % (st["id"], st["title"], st["scene"], st["time"]))
        o.append("- 输入（原文%s）：`%s`" % ("，脚本第 %d 行" % st["source_line"] if st["source"] == "script"
                                            else "，人工补全", st["input"]))
        o.append("- 输入 MD5：`%s`" % st["input_md5"])
        o.append("- 会话：%s（session_id=`%s`）" % ({"new": "新建会话", "same": "沿用上一会话"}[st["session"]],
                                                 st["session_id"]))
        o.append("- 同屏操作：%s" % "；".join(st["ui"]))
        o.append("- 输入后应看到：%s" % "；".join(st["expect_reply"]))
        o.append("- 面板应显示：%s" % "；".join(st["expect_panel"]))
        o.append("- 自动核对：%s" % "；".join(c["name"] for c in st["checks"]))
        o.append("")
    o.append("## 四、一句话复现\n")
    o.append("```bash")
    o.append("# 在麒麟 OS 本机（记忆引擎已就绪）执行：")
    o.append("python tests/run_demo_inputs.py            # 清空记忆后按上表逐条原文输入并核对面板")
    o.append("python tests/run_demo_inputs.py --no-clear # 不清空，直接在现有记忆上复跑")
    o.append("```")
    o.append("\n核对结果写入 `docs/demo_inputs_report.json`（回复全文、面板快照、逐项 PASS/FAIL、时延）。\n")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--json-name", default="演示界面输入清单.json")
    ap.add_argument("--md-name", default="演示界面输入清单.md")
    a = ap.parse_args()
    meta = build(a.script)
    os.makedirs(a.out_dir, exist_ok=True)
    jp = os.path.join(a.out_dir, a.json_name)
    mp = os.path.join(a.out_dir, a.md_name)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(to_markdown(meta))
    print("已生成：")
    print("  " + mp)
    print("  " + jp)
    print("步骤 %d 条，输入字符级来源=脚本 %d 条 / 人工补全 %d 条" % (
        len(meta["steps"]),
        sum(1 for s in meta["steps"] if s["source"] == "script"),
        sum(1 for s in meta["steps"] if s["source"] != "script")))


if __name__ == "__main__":
    main()
