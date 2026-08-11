#!/usr/bin/env python3
"""Plot the correct-memory content distribution with Pillow."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


COLORS = {
    "required": "#2F855A",
    "candidate": "#3182CE",
    "forbidden": "#C53030",
    "other": "#718096",
    "text": "#1A202C",
    "muted": "#4A5568",
    "grid": "#CBD5E0",
    "background": "#FFFFFF",
}


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    )
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def centered(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, fnt, fill: str) -> None:
    box = draw.textbbox((0, 0), text, font=fnt)
    draw.text(
        (xy[0] - (box[2] - box[0]) / 2, xy[1] - (box[3] - box[1]) / 2),
        text,
        font=fnt,
        fill=fill,
    )


def dashed_line(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    *,
    fill: str,
    width: int = 4,
    dash: int = 14,
) -> None:
    for start, end in zip(points, points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = (dx * dx + dy * dy) ** 0.5
        if not length:
            continue
        step = dash * 2
        distance = 0.0
        while distance < length:
            stop = min(distance + dash, length)
            p1 = (start[0] + dx * distance / length, start[1] + dy * distance / length)
            p2 = (start[0] + dx * stop / length, start[1] + dy * stop / length)
            draw.line((p1, p2), fill=fill, width=width)
            distance += step


def classify(row: dict, memory_id: str) -> str:
    required = set(row["required_memory_ids"])
    candidates = set(row["candidate_memory_ids"])
    forbidden_only = set(row["forbidden_memory_ids"]) - required - candidates
    if memory_id in required:
        return "required"
    if memory_id in candidates:
        return "candidate"
    if memory_id in forbidden_only:
        return "forbidden"
    return "other"


def aggregate(rows: list[dict]) -> tuple[list[dict], Counter[float]]:
    ranks = []
    for index in range(3):
        counts: Counter[str] = Counter()
        for row in rows:
            ranked = row["ranked_memory_ids"]
            if index < len(ranked):
                counts[classify(row, ranked[index])] += 1
        ranks.append({"rank": index + 1, "total": sum(counts.values()), "counts": counts})

    ratios: Counter[float] = Counter()
    for row in rows:
        returned = row["ranked_memory_ids"][:3]
        correct = len(set(returned) & set(row["required_memory_ids"]))
        ratios[correct / len(returned)] += 1
    return ranks, ratios


def draw_chart(rows: list[dict], output: Path) -> None:
    ranks, ratios = aggregate(rows)
    image = Image.new("RGB", (2400, 1180), COLORS["background"])
    draw = ImageDraw.Draw(image)
    title = font(54, bold=True)
    panel_title = font(34, bold=True)
    label = font(25)
    label_bold = font(25, bold=True)
    small = font(21)

    centered(draw, (1200, 58), "返回记忆的正确内容分布", title, COLORS["text"])

    legend = (("必需记忆", "required"), ("可接受候选", "candidate"), ("纯冲突记忆", "forbidden"))
    legend_x = 665
    for text, key in legend:
        draw.rectangle((legend_x, 105, legend_x + 28, 133), fill=COLORS[key])
        draw.text((legend_x + 40, 101), text, font=small, fill=COLORS["text"])
        legend_x += 300

    left = (115, 220, 1140, 900)
    right = (1370, 220, 2290, 900)
    centered(draw, ((left[0] + left[2]) / 2, 178), "各返回位置的内容构成", panel_title, COLORS["text"])
    centered(draw, ((right[0] + right[2]) / 2, 178), "每条查询的正确记忆含量", panel_title, COLORS["text"])

    for tick in (0, 25, 50, 75, 100):
        y = left[3] - (left[3] - left[1]) * tick / 100
        draw.line((left[0], y, left[2], y), fill=COLORS["grid"], width=2)
        text = f"{tick}%"
        box = draw.textbbox((0, 0), text, font=small)
        draw.text((left[0] - 18 - (box[2] - box[0]), y - 13), text, font=small, fill=COLORS["muted"])
    draw.line((left[0], left[1], left[0], left[3]), fill=COLORS["text"], width=3)
    draw.line((left[0], left[3], left[2], left[3]), fill=COLORS["text"], width=3)

    bar_centers = (300, 625, 950)
    bar_width = 170
    cumulative_points = []
    for rank, center_x in zip(ranks, bar_centers):
        bottom = left[3]
        for key in ("required", "candidate", "forbidden", "other"):
            count = rank["counts"].get(key, 0)
            if not count:
                continue
            ratio = count / rank["total"]
            height = (left[3] - left[1]) * ratio
            top = bottom - height
            draw.rectangle((center_x - bar_width / 2, top, center_x + bar_width / 2, bottom), fill=COLORS[key])
            if ratio >= 0.045:
                centered(draw, (center_x, top + height / 2), f"{ratio:.1%}", label_bold, "#FFFFFF")
            bottom = top
        centered(draw, (center_x, 935), f"Top {rank['rank']}", label_bold, COLORS["text"])
        centered(draw, (center_x, 971), f"n={rank['total']}", small, COLORS["muted"])

        returned_slots = 0
        correct_slots = 0
        for row in rows:
            returned = row["ranked_memory_ids"][: rank["rank"]]
            returned_slots += len(returned)
            correct_slots += len(set(returned) & set(row["required_memory_ids"]))
        cumulative = correct_slots / returned_slots
        point_y = left[3] - (left[3] - left[1]) * cumulative
        cumulative_points.append((center_x, point_y))
        centered(draw, (center_x, 207), f"累计 {cumulative:.2%}", small, COLORS["text"])

    dashed_line(draw, cumulative_points, fill=COLORS["text"], width=4)
    for x, y in cumulative_points:
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=COLORS["text"])
    centered(draw, ((left[0] + left[2]) / 2, 1030), "返回位置", label, COLORS["text"])

    max_count = max(ratios.values())
    y_max = 800
    for tick in (0, 200, 400, 600, 800):
        y = right[3] - (right[3] - right[1]) * tick / y_max
        draw.line((right[0], y, right[2], y), fill=COLORS["grid"], width=2)
        text = str(tick)
        box = draw.textbbox((0, 0), text, font=small)
        draw.text((right[0] - 18 - (box[2] - box[0]), y - 13), text, font=small, fill=COLORS["muted"])
    draw.line((right[0], right[1], right[0], right[3]), fill=COLORS["text"], width=3)
    draw.line((right[0], right[3], right[2], right[3]), fill=COLORS["text"], width=3)

    ratio_values = sorted(ratios)
    ratio_centers = (1530, 1830, 2130)
    for ratio, center_x in zip(ratio_values, ratio_centers):
        count = ratios[ratio]
        top = right[3] - (right[3] - right[1]) * count / y_max
        key = "forbidden" if ratio < 0.5 else "candidate" if ratio < 1 else "required"
        draw.rectangle((center_x - 90, top, center_x + 90, right[3]), fill=COLORS[key])
        centered(draw, (center_x, top - 43), f"{count} 条", label_bold, COLORS["text"])
        centered(draw, (center_x, top - 12), f"占查询 {count / len(rows):.1%}", small, COLORS["muted"])
        text = "33.3%" if abs(ratio - 1 / 3) < 1e-8 else f"{ratio:.0%}"
        centered(draw, (center_x, 940), text, label_bold, COLORS["text"])
    centered(draw, ((right[0] + right[2]) / 2, 1000), "返回内容中必需记忆的比例（最多取 Top3）", label, COLORS["text"])

    note = "注：纯冲突记忆已排除同时属于必需或候选的父 Episode；候选记忆可接受，但不计入必需记忆含量。"
    centered(draw, (1200, 1120), note, small, COLORS["muted"])

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.result.read_text(encoding="utf-8"))
    draw_chart(report["rows"], args.output)
    print(json.dumps({"output": str(args.output), "bytes": args.output.stat().st_size}))


if __name__ == "__main__":
    main()
