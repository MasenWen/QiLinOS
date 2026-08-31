#!/usr/bin/env python3
"""LLM-blind item-level relevance judging for v5.5 retrieval outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.llm_client import load_config  # noqa: E402


SYSTEM_PROMPT = """You are a strict, independent evaluator of memory retrieval.
Judge each returned memory separately. You may use the query, expected answer,
expected behavior, and rubric only to understand what information is useful.
You do not see retrieval scores or gold memory IDs.

Labels:
- direct_useful: the memory directly supplies correct information needed to
  answer or execute the current query, including a necessary prior preference,
  configuration, decision, task state, or operation history.
- related_background: same application/topic but not needed for this query.
- irrelevant: unrelated or too generic to help.
- misleading: conflicts with the expected behavior or would likely cause an
  incorrect response/action.

Do not mark a memory direct_useful merely because it shares keywords. Return
only a JSON array. Each element must have record_id and decisions; each decision
must have memory_id, label, and a concise reason."""


def parse_json(value: str) -> list[dict[str, Any]]:
    text = value.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("response does not contain a JSON array")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("response root is not a list")
    return parsed


def deepseek_generate(prompt: str, cfg: dict[str, Any]) -> str:
    import requests

    base = str(cfg.get("base_url") or "").rstrip("/")
    if "api.deepseek.com" not in base:
        raise RuntimeError(f"refusing non-DeepSeek endpoint: {base}")
    response = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json={
            "model": cfg["model"],
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def compact_record(record: dict[str, Any], text_limit: int) -> dict[str, Any]:
    query_tokens = set(
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", record["query"])
    )

    def excerpt(text: str) -> str:
        parts = [
            part.strip()
            for part in re.split(r"(?<=[\n。！？.!?;；])|\n+", text)
            if part.strip()
        ]
        ranked = sorted(
            enumerate(parts),
            key=lambda item: (
                -len(
                    query_tokens.intersection(
                        token.casefold()
                        for token in re.findall(
                            r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", item[1]
                        )
                    )
                ),
                item[0],
            ),
        )
        chosen: list[tuple[int, str]] = []
        used = 0
        for index, part in ranked:
            if used >= text_limit:
                break
            chosen.append((index, part[: max(0, text_limit - used)]))
            used += len(chosen[-1][1])
        return " ".join(part for _, part in sorted(chosen))

    return {
        "record_id": record["record_id"],
        "query": record["query"],
        "expected_user_facing_answer": record["expected_user_facing_answer"],
        "expected_effective_behavior": record["expected_effective_behavior"],
        "scoring_rubric": record["scoring_rubric"],
        "returned_memories": [
            {
                "memory_id": memory["memory_id"],
                "text": excerpt(memory["text"]),
            }
            for memory in record["returned_memories"]
        ],
    }


def judge_batch(
    batch: list[dict[str, Any]], cfg: dict[str, Any], text_limit: int
) -> list[dict[str, Any]]:
    payload = [compact_record(record, text_limit) for record in batch]
    prompt = "Evaluate these retrieval records:\n" + json.dumps(
        payload, ensure_ascii=False
    )
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            result = parse_json(deepseek_generate(prompt, cfg))
            by_id = {item.get("record_id"): item for item in result}
            if set(by_id) != {record["record_id"] for record in batch}:
                raise ValueError("response record IDs do not match request")
            return result
        except Exception as exc:  # network/model formatting retries are recorded
            last_error = exc
            time.sleep(min(120.0, 5.0 * (2**attempt)))
    raise RuntimeError(f"judge batch failed after retries: {last_error}")


def validate(
    records: list[dict[str, Any]], judgments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    record_by_id = {record["record_id"]: record for record in records}
    valid_labels = {
        "direct_useful",
        "related_background",
        "irrelevant",
        "misleading",
    }
    validated: list[dict[str, Any]] = []
    for judgment in judgments:
        record_id = judgment["record_id"]
        record = record_by_id[record_id]
        expected_ids = {
            memory["memory_id"] for memory in record["returned_memories"]
        }
        decisions = judgment.get("decisions") or []
        decision_ids = {decision.get("memory_id") for decision in decisions}
        if decision_ids != expected_ids:
            raise ValueError(f"{record_id}: decision memory IDs do not match")
        if any(decision.get("label") not in valid_labels for decision in decisions):
            raise ValueError(f"{record_id}: invalid label")
        validated.append(judgment)
    return validated


def metrics(
    records: list[dict[str, Any]], judgments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    judgment_by_id = {item["record_id"]: item for item in judgments}
    results: list[dict[str, Any]] = []
    for pressure in sorted({record["pressure"] for record in records}):
        level = [record for record in records if record["pressure"] == pressure]
        labels = [
            decision["label"]
            for record in level
            for decision in judgment_by_id[record["record_id"]]["decisions"]
        ]
        useful = labels.count("direct_useful")
        results.append(
            {
                "pressure": pressure,
                "pool_size": level[0]["pool_size"],
                "query_count": len(level),
                "returned_memory_count": len(labels),
                "direct_useful_count": useful,
                "semantic_precision": useful / len(labels) if labels else 0.0,
                "label_counts": {
                    label: labels.count(label)
                    for label in (
                        "direct_useful",
                        "related_background",
                        "irrelevant",
                        "misleading",
                    )
                },
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=REPO_ROOT / "_benchmark/results/v55_episode_pressure.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "_benchmark/results/v55_semantic_precision_judgments.json",
    )
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--text-limit", type=int, default=4000)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument(
        "--pressures",
        default="1,2,3,4",
        help="comma-separated pressure levels to judge",
    )
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    pressures = {int(value) for value in args.pressures.split(",") if value.strip()}
    records = [
        record
        for record in source.get("semantic_judge_inputs", [])
        if record["has_required_memory"]
        and record["returned_memories"]
        and record["pressure"] in pressures
    ]
    if args.max_records > 0:
        records = records[: args.max_records]
    if not records:
        raise SystemExit("input has no answer-bearing semantic_judge_inputs")
    partial_path = args.output.with_suffix(args.output.suffix + ".partial")
    completed: dict[str, dict[str, Any]] = {}
    if partial_path.exists():
        partial = json.loads(partial_path.read_text(encoding="utf-8"))
        completed = {item["record_id"]: item for item in partial}
    pending = [record for record in records if record["record_id"] not in completed]
    batches = [
        pending[index : index + args.batch_size]
        for index in range(0, len(pending), args.batch_size)
    ]
    cfg = load_config()
    cfg["temperature"] = 0.0
    if cfg.get("provider") != "api" or not cfg.get("api_key"):
        raise SystemExit("configured API provider/key is required for reproducible judging")
    if (cfg.get("api_choice") or "") != "deepseek":
        raise SystemExit("DeepSeek must be the selected API provider")

    judged: list[dict[str, Any]] = list(completed.values())
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(judge_batch, batch, cfg, args.text_limit): batch
            for batch in batches
        }
        for index, future in enumerate(as_completed(futures), start=1):
            new_items = future.result()
            judged.extend(new_items)
            completed.update({item["record_id"]: item for item in new_items})
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_text(
                json.dumps(list(completed.values()), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"Judged {index}/{len(batches)} batches", flush=True)

    validated = validate(records, judged)
    report = {
        "metadata": {
            "dataset": "OS_Agent_v5.5 held-out answer-bearing retrievals",
            "provider": cfg.get("api_choice") or cfg.get("provider"),
            "model": cfg.get("model"),
            "temperature": 0.0,
            "prompt_sha256": hashlib.sha256(
                SYSTEM_PROMPT.encode("utf-8")
            ).hexdigest(),
            "record_count": len(records),
            "item_level_definition": "direct_useful / all returned memories",
        },
        "metrics": metrics(records, validated),
        "judgments": sorted(validated, key=lambda item: item["record_id"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    partial_path.unlink(missing_ok=True)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"Output: {args.output}", flush=True)


if __name__ == "__main__":
    main()
