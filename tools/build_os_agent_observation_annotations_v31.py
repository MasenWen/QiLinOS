from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.os_agent_observation_annotations import (
    build_annotation_dataset,
)


DEFAULT_DATASET = (
    Path(__file__).resolve().parents[2]
    / "os_agent_memory_query_benchmark_v3.1"
    / "os_agent_memory_query_benchmark_v3.1_20260725"
)
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "data"
    / "os_agent_observation_benchmark_v31.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    dataset = build_annotation_dataset(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(dataset["audit"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
