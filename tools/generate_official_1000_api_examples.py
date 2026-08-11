from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.memory_engine.reflection import DeepSeekReflectionClient
from tools.evaluate_official_1000_end_to_end import (
    _api_summary,
    _latency,
    _read_csv,
    render_markdown,
    run_api_examples,
    select_examples,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--sample-count", type=int, default=8)
    args = parser.parse_args()

    report = json.loads(args.input.read_text(encoding="utf-8"))
    data_root = args.dataset / "processed_data"
    queries = _read_csv(data_root / "query_set.csv")
    answers = _read_csv(data_root / "answer_key.csv")
    query_by_id = {row["query_id"]: row for row in queries}
    answer_by_group = {row["answer_group_id"]: row for row in answers}
    selected = select_examples(
        report["rows"],
        count=min(10, max(5, args.sample_count)),
    )

    client = DeepSeekReflectionClient(max_tokens=2500)
    examples = run_api_examples(
        selected,
        query_by_id=query_by_id,
        answer_by_group=answer_by_group,
        client=client,
    )
    report["examples"] = examples
    report["api_calls"] = client.calls
    report["summary"]["api_examples"] = _api_summary(examples)
    report["summary"]["api_call_latency"] = _latency(
        [
            float(value["elapsed_ms"])
            for value in client.calls
            if value.get("status") == "ok"
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(
        render_markdown(examples, report["summary"]),
        encoding="utf-8",
    )
    print(
        json.dumps(report["summary"]["api_examples"], ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
