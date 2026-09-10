#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conflict.static.active_config_recency.v2 单元测试。

对应手册 5.4 节 v0.7 结论：
  · 生效配置 = 最新配置版本（不因旧版本被引用次数多而胜出）
  · 临时做法/例外记忆在未要求恢复时降级
  · 非配置类冲突行为与 v1 一致（仍由支撑单元数量决定）
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.memory_engine.strict.conflict import (  # noqa: E402
    ActiveConfigRecencyStaticResolver,
    SourceVersionCountStaticResolver,
)
from src.memory_engine.strict.contracts import (  # noqa: E402
    ConflictType,
    LifecycleStatus,
    StrictConflictGroup,
    StrictMemory,
)


def memory(
    memory_id: str,
    *,
    config_version: str = "",
    support: int = 1,
    semantic_value: str = "",
    valid_from: str = "2025-01-01T00:00:00+00:00",
    directness: str = "",
    temporary: bool = False,
) -> StrictMemory:
    provenance: dict = {}
    if config_version:
        provenance["config_version"] = config_version
    if directness:
        provenance["directness"] = directness
    if temporary:
        provenance["temporary"] = True
    return StrictMemory(
        memory_id=memory_id,
        user_id="u1",
        memory_family="preference",
        candidate_kind="tool_preference",
        slot_key="reply_style",
        semantic_value=semantic_value,
        condition={},
        scope={},
        cardinality="single",
        status=LifecycleStatus.STABLE,
        evidence_ids=("ev_%s" % memory_id,),
        support_unit_ids=tuple("s%d" % i for i in range(support)),
        oppose_unit_ids=(),
        applicable_unit_ids=(),
        valid_from=valid_from,
        valid_to="",
        predecessor_memory_ids=(),
        successor_memory_ids=(),
        conflict_group_ids=(),
        confidence={},
        stability={},
        provenance=provenance,
        version=1,
        created_at=valid_from,
        updated_at=valid_from,
    )


def group(*ids: str) -> StrictConflictGroup:
    return StrictConflictGroup(
        conflict_group_id="g1",
        user_id="u1",
        slot_key="reply_style",
        conflict_type=ConflictType.STATIC,
        memory_ids=tuple(ids),
        condition_relations={},
        condition_partition={},
        timeline=(),
        winner_memory_id="",
        unresolved_reason="",
        status="open",
        confidence={},
        updated_at="2026-09-11T00:00:00+00:00",
    )


class ActiveConfigRecencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.v2 = ActiveConfigRecencyStaticResolver()

    def test_latest_config_version_wins_over_more_support(self) -> None:
        """新配置版本（支撑少）应胜过旧配置版本（支撑多）——v1 会判反。"""
        old = memory("m_old", config_version="V542_CFG_00009_V1", support=9)
        new = memory("m_new", config_version="V542_CFG_00009_V2", support=1)
        memories = {m.memory_id: m for m in (old, new)}

        self.assertEqual(self.v2.resolve(group("m_old", "m_new"), memories).winner_memory_id, "m_new")
        # v1 对照：旧分支按支撑数取胜
        self.assertEqual(
            SourceVersionCountStaticResolver().resolve(group("m_old", "m_new"), memories).winner_memory_id,
            "m_old",
        )

    def test_temporary_memory_is_demoted(self) -> None:
        """带临时/例外标记的记忆降级，即使其来源优先级更高、支撑更多。"""
        temp = memory("m_temp", semantic_value="这是临时变通做法，先别照着用", support=9, directness="explicit_user")
        normal = memory("m_normal", config_version="V542_CFG_00009_V1", support=1)
        memories = {m.memory_id: m for m in (temp, normal)}
        self.assertEqual(self.v2.resolve(group("m_temp", "m_normal"), memories).winner_memory_id, "m_normal")

    def test_temporary_flag_in_provenance(self) -> None:
        temp = memory("m_temp", support=5, directness="explicit_user", temporary=True)
        normal = memory("m_normal", config_version="V1", support=1)
        memories = {m.memory_id: m for m in (temp, normal)}
        self.assertEqual(self.v2.resolve(group("m_temp", "m_normal"), memories).winner_memory_id, "m_normal")

    def test_non_config_conflicts_match_v1(self) -> None:
        """非配置类记忆：仍由支撑单元数量决定（与 v1 行为一致）。"""
        more = memory("m_more", support=7)
        fewer = memory("m_fewer", support=2)
        memories = {m.memory_id: m for m in (more, fewer)}
        self.assertEqual(self.v2.resolve(group("m_more", "m_fewer"), memories).winner_memory_id, "m_more")
        self.assertEqual(
            SourceVersionCountStaticResolver().resolve(group("m_more", "m_fewer"), memories).winner_memory_id,
            "m_more",
        )

    def test_tie_stays_unresolved(self) -> None:
        a = memory("m_a", config_version="V1", support=1)
        b = memory("m_b", config_version="V1", support=1)
        memories = {m.memory_id: m for m in (a, b)}
        out = self.v2.resolve(group("m_a", "m_b"), memories)
        self.assertEqual(out.status, "unresolved")
        self.assertEqual(out.unresolved_reason, "static_priority_tie")

    def test_non_static_group_is_untouched(self) -> None:
        a = memory("m_a", support=1)
        b = memory("m_b", support=2)
        g = group("m_a", "m_b")
        g = StrictConflictGroup(**{**g.__dict__, "conflict_type": ConflictType.DYNAMIC})
        out = self.v2.resolve(g, {m.memory_id: m for m in (a, b)})
        self.assertEqual(out.winner_memory_id, "")

    def test_registered_in_engine_config(self) -> None:
        """配置必须指向存在的模块 id（registry 校验会失败否则）。"""
        import tomllib

        cfg = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "config/memory_engine_strict_v1.toml").read_text("utf-8")
        )
        self.assertEqual(cfg["modules"]["static_resolver"], ActiveConfigRecencyStaticResolver.module_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
