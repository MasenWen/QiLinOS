from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from src.memory_engine.knowledge_tags import (
    WorkplaceTagKnowledgeBase,
    load_seed_tags,
    merge_canonical_tags,
)
from src.memory_engine.preference_matching import CanonicalTag


def _desktop_values(path: Path) -> dict[str, str]:
    values = {}
    in_entry = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def scan_desktop_tags(paths: list[Path]) -> tuple[CanonicalTag, ...]:
    tags = []
    for directory in paths:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.desktop")):
            values = _desktop_values(path)
            if values.get("Type", "Application") != "Application":
                continue
            if values.get("NoDisplay", "false").casefold() == "true":
                continue
            names = [
                values.get("Name", ""),
                values.get("Name[zh_CN]", ""),
                values.get("GenericName", ""),
                values.get("GenericName[zh_CN]", ""),
            ]
            names.extend(
                item
                for item in values.get("Keywords", "").split(";")
                if item
            )
            aliases = tuple(dict.fromkeys(item.strip() for item in names if item.strip()))
            if not aliases:
                continue
            desktop_id = re.sub(r"[^a-z0-9]+", "_", path.stem.casefold()).strip("_")
            if not desktop_id:
                continue
            tags.append(
                CanonicalTag(
                    tag_id=f"app:desktop:{desktop_id}",
                    name=aliases[0],
                    groups=("condition", "object"),
                    aliases=aliases[1:],
                    prototypes=(f"在{aliases[0]}应用中处理办公任务",),
                )
            )
    return tuple(tags)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        default="knowledge/workplace_tags_seed_v1.json",
    )
    parser.add_argument(
        "--database",
        default="runtime/knowledge/workplace_tags_v1.sqlite",
    )
    parser.add_argument("--scan-desktop", action="store_true")
    args = parser.parse_args()

    started = time.perf_counter()
    tags, packs, sources = load_seed_tags(args.seed)
    desktop_tags = ()
    if args.scan_desktop:
        desktop_tags = scan_desktop_tags(
            [
                Path("/usr/share/applications"),
                Path.home() / ".local/share/applications",
            ]
        )
        for tag in desktop_tags:
            packs[tag.tag_id] = "kylin-desktop"
            sources[tag.tag_id] = "desktop-entry"
    merged = merge_canonical_tags(tags, desktop_tags)
    knowledge = WorkplaceTagKnowledgeBase.build(
        args.database,
        merged,
        pack_by_tag=packs,
        source_by_tag=sources,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print(
        json.dumps(
            {
                **knowledge.statistics(),
                "seed_tag_count": len(tags),
                "desktop_tag_count": len(desktop_tags),
                "build_ms": elapsed_ms,
                "database": str(Path(args.database).resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
