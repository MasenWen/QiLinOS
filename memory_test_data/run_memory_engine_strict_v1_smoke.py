from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.kylin import KylinSDKSemanticScorer
from src.memory_engine.strict.store import StrictMemoryEngineStore


def run(output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    database = output.parent / "memory_engine_strict_v1.db"
    config = StrictMemoryEngineConfig.load(database_path=database)
    scorer = KylinSDKSemanticScorer()
    store = StrictMemoryEngineStore(database)
    engine = StrictMemoryEngine(
        config=config,
        store=store,
        semantic_scorer=scorer,
    )
    start = datetime(
        2026,
        6,
        1,
        10,
        tzinfo=timezone(timedelta(hours=8)),
    )
    ingest_runs = []
    for index, day in enumerate((0, 4, 8, 15, 22), start=1):
        ingest_runs.append(
            engine.ingest_observation(
                {
                    "source_type": "dialogue",
                    "source_event_id": f"server-gold-{index}",
                    "user_id": "STRICT_SERVER_SMOKE",
                    "session_id": f"STRICT_SERVER_SESSION_{index}",
                    "event_time": (start + timedelta(days=day)).isoformat(),
                    "actor": "user",
                    "content": (
                        "以后默认 USD，回复保持简洁，"
                        "外部邮件发送前必须确认。"
                    ),
                    "task": "quotation reply",
                    "context": {"customer_type": "external"},
                },
                stage_limit="lifecycle",
            )
        )
    retrieval = engine.retrieve(
        "为外部客户生成报价并发送邮件",
        {
            "user_id": "STRICT_SERVER_SMOKE",
            "query_time": "2026-07-01T10:00:00+08:00",
            "task": "quotation reply",
            "customer_type": "external",
            "memory_need": "currency output_style safety",
        },
        top_k=5,
    )
    reflection = engine.reflect("STRICT_SERVER_SMOKE")
    result = {
        "status": "passed"
        if len(retrieval["planner"]["selected_memory_ids"]) == 3
        and all(
            artifact["grounding_verified"]
            for artifact in reflection["artifacts"]
        )
        else "failed",
        "database": str(database),
        "schema_counts": store.counts(),
        "final_ingest_run_id": ingest_runs[-1]["run_id"],
        "retrieval": retrieval,
        "reflection": reflection,
        "kylin_backend": scorer.backend_id,
    }
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / ".strict_memory_engine_smoke"
        / "strict_v1_smoke.json",
    )
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
