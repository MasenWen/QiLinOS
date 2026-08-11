from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

import numpy as np

from src.memory_engine.observation import ObservationMatcher
from src.memory_engine.fast_preference_matching import (
    EmbeddingFormationGate,
    GreedyOptionAnchoredSpanProposer,
    MemoizingTextEmbedder,
    ObservationBudget,
    ObservationDeadlineExceeded,
    _has_temporal_scope_cue,
)
from src.memory_engine.preference_matching import (
    AttitudeValue,
    CanonicalRoleMatch,
    CanonicalTagRegistry,
    PreferenceFrameAssembler,
    PreferenceFrameMatcher,
    PreferenceObservationMemoryExtractor,
    PreferenceObservationOptions,
    temporal_values,
)
from src.memory_engine.normalizers import dialogue_to_observation
from src.memory_engine.span_matching import (
    CharacterSpanTokenizer,
    RoleHypothesis,
)


class _PreferenceToyEmbedder:
    dimensions = (
        "condition",
        "temporal_short",
        "temporal_medium",
        "temporal_long",
        "attitude_positive",
        "attitude_negative",
        "attitude_uncertain",
        "object",
        "codex",
        "bar",
        "line",
        "template",
        "setting",
        "budget",
        "formation",
        "residual",
    )

    patterns = {
        "condition": (
            "场景",
            "任务",
            "工作",
            "代码解释",
            "代码讲解",
            "预算比较",
            "财务汇总",
            "普通聊天",
        ),
        "temporal_short": (
            "当前",
            "本次",
            "本轮",
            "今天",
            "今晚",
            "暂时",
            "短期",
            "失效",
            "only for this task",
        ),
        "temporal_medium": (
            "后续",
            "近期",
            "下个月",
            "个月开始",
            "这周",
            "中期",
            "项目期间",
            "同一个文件",
            "limited period",
        ),
        "temporal_long": (
            "以后",
            "长期",
            "每次",
            "一直",
            "今后",
            "所有类似任务",
            "通用规则",
            "跨不同",
            "all future tasks",
        ),
        "attitude_positive": (
            "偏好",
            "优先",
            "默认",
            "继续使用",
            "认可",
            "希望",
            "采用",
        ),
        "attitude_negative": (
            "反对",
            "不要",
            "别",
            "避免",
            "不喜欢",
            "不适合",
            "禁止",
        ),
        "attitude_uncertain": (
            "不确定",
            "考虑",
            "随意",
            "尚未决定",
            "或许",
            "勉强",
        ),
        "object": (
            "对象",
            "应用",
            "助手",
            "图表",
            "模板",
            "文件",
            "设置",
            "工具",
        ),
        "codex": (
            "codex",
            "编程",
            "代码助手",
            "人工智能助手",
        ),
        "bar": ("柱状图", "柱形图", "bar chart", "柱形", "条形"),
        "line": ("折线图", "line chart", "折线"),
        "template": ("模板", "版式"),
        "setting": ("设置", "配置"),
        "budget": ("预算表", "报价表", "办公表格"),
        "formation": (
            "用户已经表达",
            "用户要求使用",
            "用户决定",
            "用户请求执行",
            "the user asks",
            "暂时用",
            "优先",
            "默认",
            "别用",
            "避免",
            "每次",
            "后续",
        ),
        "residual": (
            "礼貌",
            "无关",
            "催促",
            "系统运行",
            "系统日志",
            "文件里面包含",
            "创建了进程",
            "这不是我的偏好",
            "不用记住",
            "没有可提取",
            "普通陈述",
        ),
    }


    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            [self._vector(text) for text in texts],
            dtype=np.float32,
        )

    def _vector(self, text: str) -> np.ndarray:
        normalized = text.casefold()
        vector = np.full(len(self.dimensions), 0.001, dtype=np.float32)
        matched = False
        for index, dimension in enumerate(self.dimensions):
            if any(
                pattern.casefold() in normalized
                for pattern in self.patterns[dimension]
            ):
                vector[index] = 1.0
                matched = True
        if not matched:
            vector[self.dimensions.index("residual")] = 1.0
        return vector


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, value: float) -> None:
        self.now += value / 1000.0


class _TimedVectorBackend:
    def __init__(self, clock: _FakeClock, latency_ms: float) -> None:
        self.clock = clock
        self.latency_ms = latency_ms
        self.calls: list[str] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        values = []
        for text in texts:
            self.calls.append(text)
            self.clock.advance_ms(self.latency_ms)
            values.append(np.asarray((len(text), 1.0), dtype=np.float32))
        return np.stack(values)


class _BlockingVectorBackend:
    def __init__(self, latency_seconds: float) -> None:
        self.latency_seconds = latency_seconds

    def embed(self, texts: list[str]) -> np.ndarray:
        time.sleep(self.latency_seconds)
        return np.ones((len(texts), 2), dtype=np.float32)


class PreferenceMatchingTest(unittest.TestCase):
    def test_observation_budget_progressively_reduces_new_work(self):
        clock = _FakeClock()
        budget = ObservationBudget(
            started_at=0.0,
            soft_limit_ms=500.0,
            hard_limit_ms=800.0,
            clock=clock,
        )

        self.assertEqual("full", budget.phase)
        clock.advance_ms(550.0)
        self.assertEqual("selective", budget.phase)
        self.assertFalse(
            budget.allows_candidate(
                priority=0.40,
                group_count=1,
                cached=False,
            )
        )
        self.assertTrue(
            budget.allows_candidate(
                priority=0.65,
                group_count=1,
                cached=False,
            )
        )
        clock.advance_ms(70.0)
        self.assertEqual("strict", budget.phase)
        self.assertFalse(
            budget.allows_candidate(
                priority=0.65,
                group_count=1,
                cached=False,
            )
        )
        self.assertTrue(
            budget.allows_candidate(
                priority=0.65,
                group_count=2,
                cached=False,
            )
        )
        clock.advance_ms(110.0)
        self.assertEqual("finalize", budget.phase)
        self.assertFalse(
            budget.allows_candidate(
                priority=1.0,
                group_count=4,
                cached=False,
            )
        )
        self.assertTrue(
            budget.allows_candidate(
                priority=0.0,
                group_count=1,
                cached=True,
            )
        )
        clock.advance_ms(80.0)
        self.assertEqual("expired", budget.phase)

    def test_memoized_embedder_stops_before_unbounded_tail(self):
        clock = _FakeClock()
        backend = _TimedVectorBackend(clock, latency_ms=120.0)
        embedder = MemoizingTextEmbedder(backend)
        budget = ObservationBudget(
            started_at=0.0,
            soft_limit_ms=200.0,
            hard_limit_ms=500.0,
            clock=clock,
        )

        with self.assertRaises(ObservationDeadlineExceeded):
            with embedder.budget_scope(budget):
                embedder.embed(["one", "two", "three", "four"])

        self.assertEqual(3, embedder.computed)
        self.assertEqual(3, budget.completed_embeddings)
        self.assertEqual(1, budget.skipped_embeddings)
        self.assertLess(clock.now * 1000.0, budget.hard_limit_ms)
        self.assertEqual(3, len(backend.calls))
        self.assertEqual(3, len(embedder.cache))

    def test_embedding_estimate_is_not_poisoned_by_one_outlier(self):
        clock = _FakeClock()
        backend = _TimedVectorBackend(clock, latency_ms=2000.0)
        embedder = MemoizingTextEmbedder(backend)
        budget = ObservationBudget(
            started_at=0.0,
            soft_limit_ms=4000.0,
            hard_limit_ms=5000.0,
            clock=clock,
        )

        with embedder.budget_scope(budget):
            embedder.embed(["outlier"])

        self.assertLessEqual(embedder.estimated_embedding_ms, 220.0)
        self.assertGreaterEqual(embedder.estimated_embedding_ms, 80.0)

    def test_cached_vector_does_not_invoke_backend(self):
        clock = _FakeClock()
        backend = _TimedVectorBackend(clock, latency_ms=10.0)
        embedder = MemoizingTextEmbedder(backend)
        embedder.embed(["cached"])
        calls_before = len(backend.calls)

        vector = embedder.cached_vector("cached")

        self.assertIsNotNone(vector)
        self.assertEqual(calls_before, len(backend.calls))
        self.assertIsNone(embedder.cached_vector("missing"))

    def test_blocking_backend_returns_control_at_hard_deadline(self):
        embedder = MemoizingTextEmbedder(
            _BlockingVectorBackend(latency_seconds=0.20)
        )
        embedder.estimated_embedding_ms = 1.0
        started = time.perf_counter()
        budget = ObservationBudget(
            started_at=started,
            soft_limit_ms=20.0,
            hard_limit_ms=60.0,
            finalization_reserve_ms=5.0,
        )

        with self.assertRaises(ObservationDeadlineExceeded):
            with embedder.budget_scope(budget):
                embedder.embed(["slow"])

        self.assertLess((time.perf_counter() - started) * 1000.0, 120.0)
        self.assertTrue(budget.hard_stop_reached)
        time.sleep(0.16)

    @staticmethod
    def _canonical(
        start,
        end,
        text,
        group,
        tag_id,
        *,
        exact=False,
        score=0.90,
        similarity=0.86,
        margin=0.20,
    ):
        return CanonicalRoleMatch(
            start=start,
            end=end,
            text=text,
            group=group,
            tag_id=tag_id,
            tag_name=tag_id,
            score=score,
            similarity=similarity,
            exact_alias=exact,
            hypothesis_score=1.0 if exact else 0.62,
            sources=(
                ("fast_exact_option",)
                if exact
                else ("fast_greedy", "semantic_task_core")
            ),
            competition_margin=margin,
        )

    def test_command_attitude_fallback_forms_english_imperative(self):
        text = (
            'NetIncome.xlsx: Copy the "Revenue" column '
            'to a new sheet named "Sheet2".'
        )
        condition_text = "NetIncome.xlsx"
        object_text = 'Copy the "Revenue" column'
        frames = PreferenceFrameAssembler().assemble(
            text,
            (
                self._canonical(
                    0,
                    len(condition_text),
                    condition_text,
                    "condition",
                    "condition:file:netincome",
                    exact=True,
                ),
                self._canonical(
                    text.index(object_text),
                    text.index(object_text) + len(object_text),
                    object_text,
                    "object",
                    "object:copy_revenue",
                ),
            ),
            (),
            (),
        )
        self.assertEqual(1, len(frames))
        self.assertEqual(
            ("command_attitude_fallback",),
            frames[0].attitude.sources,
        )
        self.assertGreater(frames[0].attitude.value, 0.0)

    def test_command_attitude_fallback_forms_two_task_frames(self):
        text = (
            "先做第1件事：在 A.xlsx 中计算月度总额；"
            "再做第2件事：在 B.xlsx 中导出当前工作表。"
        )
        canonical = []
        for filename, object_text, suffix in (
            ("A.xlsx", "计算月度总额", "a"),
            ("B.xlsx", "导出当前工作表", "b"),
        ):
            canonical.extend(
                (
                    self._canonical(
                        text.index(filename),
                        text.index(filename) + len(filename),
                        filename,
                        "condition",
                        f"condition:{suffix}",
                        exact=True,
                    ),
                    self._canonical(
                        text.index(object_text),
                        text.index(object_text) + len(object_text),
                        object_text,
                        "object",
                        f"object:{suffix}",
                    ),
                )
            )
        frames = PreferenceFrameAssembler().assemble(
            text,
            tuple(canonical),
            (),
            (),
        )
        self.assertEqual(
            {
                ("condition:a", "object:a"),
                ("condition:b", "object:b"),
            },
            {
                (frame.condition.tag_id, frame.object.tag_id)
                for frame in frames
            },
        )

    def test_command_attitude_fallback_rejects_system_fact(self):
        text = "System service created process 19328."
        object_text = "created process"
        frames = PreferenceFrameAssembler().assemble(
            text,
            (
                self._canonical(
                    text.index(object_text),
                    text.index(object_text) + len(object_text),
                    object_text,
                    "object",
                    "object:create_process",
                ),
            ),
            (),
            (),
        )
        self.assertEqual((), frames)

    def test_command_attitude_fallback_corrects_command_polarity(self):
        text = "在季度报告中汇总每个月的总成本。"
        object_text = "汇总每个月的总成本"
        start = text.index(object_text)
        negative_embedding = AttitudeValue(
            start=start,
            end=start + 2,
            text="汇总",
            value=-0.32,
            anchor="negative",
            confidence=0.62,
            similarity=0.68,
            hypothesis_score=0.70,
            sources=("fast_greedy", "semantic_task_core"),
        )
        frames = PreferenceFrameAssembler().assemble(
            text,
            (
                self._canonical(
                    start,
                    start + len(object_text),
                    object_text,
                    "object",
                    "object:summarize_cost",
                ),
            ),
            (negative_embedding,),
            (),
        )
        self.assertEqual(1, len(frames))
        self.assertGreater(frames[0].attitude.value, 0.0)
        self.assertEqual(
            ("command_attitude_fallback",),
            frames[0].attitude.sources,
        )

    def test_condition_span_is_not_carried_as_object_attitude(self):
        text = "通常使用公司API，除非网络不稳定。"
        object_text = "通常使用公司API"
        condition_text = "除非网络不稳定"
        frames = PreferenceFrameAssembler().assemble(
            text,
            (
                self._canonical(
                    0,
                    len(object_text),
                    object_text,
                    "object",
                    "tool:company_api",
                ),
                self._canonical(
                    text.index(condition_text),
                    text.index(condition_text) + len(condition_text),
                    condition_text,
                    "condition",
                    "condition:network_unstable",
                ),
            ),
            (
                AttitudeValue(
                    0,
                    4,
                    "通常使用",
                    0.38,
                    "positive",
                    0.65,
                    0.72,
                    0.72,
                    ("test",),
                ),
                AttitudeValue(
                    text.index(condition_text),
                    text.index(condition_text) + len(condition_text),
                    condition_text,
                    -0.24,
                    "negative",
                    0.62,
                    0.68,
                    0.68,
                    ("test",),
                ),
            ),
            (),
        )
        self.assertEqual(1, len(frames))
        self.assertGreater(frames[0].attitude.value, 0.0)
        self.assertIsNone(frames[0].condition)

    def test_exact_noun_does_not_hide_semantic_action_candidate(self):
        text = "那时手工核对报价表"
        registry = CanonicalTagRegistry()
        mentions = tuple(
            mention
            for mention in registry.find_mentions(text)
            if mention.tag_id == "artifact:budget_sheet"
        )
        proposal = GreedyOptionAnchoredSpanProposer(
            CharacterSpanTokenizer()
        ).propose(
            text,
            mentions,
            condition_ids=set(),
            object_ids={
                "artifact:budget_sheet",
                "action:manual_quote_check",
            },
        )
        self.assertTrue(
            any(
                value.group == "object"
                and "手工核对" in value.candidate.text
                for value in proposal.candidates
            )
        )

    def test_temporal_scope_cue_rejects_task_time(self):
        self.assertFalse(_has_temporal_scope_cue("Calculate the"))
        self.assertFalse(_has_temporal_scope_cue("2019每个月"))
        self.assertFalse(_has_temporal_scope_cue("According to the"))
        self.assertTrue(_has_temporal_scope_cue("当前会话先按"))
        self.assertTrue(_has_temporal_scope_cue("以后沿用"))
        self.assertTrue(_has_temporal_scope_cue("same as before"))

    def test_registry_prefers_longest_codex_alias(self):
        registry = CanonicalTagRegistry()
        mentions = [
            mention
            for mention in registry.find_mentions(
                "默认用 ChatGPT-codex 处理代码解释"
            )
            if mention.tag_id == "app:chatgpt_codex"
        ]
        self.assertEqual(1, len(mentions))
        self.assertEqual("ChatGPT-codex", mentions[0].text)

    def test_temporal_scale_distinguishes_explicit_long_term(self):
        hypotheses = (
            RoleHypothesis(
                0,
                2,
                "以后",
                "temporal",
                "temporal_long",
                0.9,
                0.8,
                0.2,
                0.1,
                ("test",),
            ),
            RoleHypothesis(
                2,
                4,
                "本轮",
                "temporal",
                "temporal_short",
                0.9,
                0.8,
                0.2,
                0.1,
                ("test",),
            ),
        )
        values = temporal_values(hypotheses)
        by_label = {value.label: value for value in values}
        self.assertEqual(0.0, by_label["temporal_short"].promotion_seed)
        self.assertEqual(1.0, by_label["temporal_long"].promotion_seed)
        self.assertTrue(
            by_label["temporal_long"].explicit_long_term
        )

    def test_context_assigns_codex_condition_and_chart_object(self):
        matcher = PreferenceFrameMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        result = matcher.match(
            "在ChatGPT Codex中做代码解释时，优先用柱状图。"
        )
        frames = [
            frame
            for frame in result.frames
            if frame.object.tag_id == "chart:bar"
        ]
        self.assertTrue(frames)
        self.assertGreater(frames[0].attitude.value, 0.0)
        self.assertIsNotNone(frames[0].condition)
        self.assertIn(
            frames[0].condition.tag_id,
            {"app:chatgpt_codex", "task:code_explanation"},
        )

    def test_context_assigns_codex_as_object_after_attitude(self):
        matcher = PreferenceFrameMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        result = matcher.match(
            "以后默认用ChatGPT Codex处理代码解释。"
        )
        self.assertTrue(
            any(
                frame.object.tag_id == "app:chatgpt_codex"
                for frame in result.frames
            )
        )

    def test_log_without_attitude_does_not_form_preference_frame(self):
        matcher = PreferenceFrameMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        result = matcher.match(
            "W32time service synchronized system time."
        )
        self.assertEqual((), result.frames)

    def test_observation_memory_becomes_preference_evidence(self):
        matcher = PreferenceFrameMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        observation = dialogue_to_observation(
            "今后在终端做代码解释时，默认用 ChatGPT Codex。",
            actor="user",
            user_id="user-1",
            session_id="session-1",
            source_event_id="event-1",
            event_time="2026-07-27T00:00:00+00:00",
        )
        extraction = PreferenceObservationMemoryExtractor(
            matcher
        ).extract(
            observation,
            options=PreferenceObservationOptions(
                condition_tag_ids=(
                    "app:terminal",
                    "app:web_browser",
                ),
                object_tag_ids=(
                    "app:chatgpt_codex",
                    "chart:bar",
                ),
                temporal_labels=(
                    "temporal_short",
                    "temporal_medium",
                    "temporal_long",
                ),
            ),
        )
        self.assertTrue(extraction.memories)
        memory = max(
            extraction.memories,
            key=lambda value: value.extraction_confidence,
        )
        self.assertEqual("app:terminal", memory.condition_tag_id)
        self.assertEqual("app:chatgpt_codex", memory.object_tag_id)
        self.assertGreater(memory.attitude_value, 0.0)
        self.assertEqual("temporal_long", memory.temporal_label)
        self.assertTrue(memory.explicit_long_term)

        evidence = next(
            item
            for item in extraction.evidence
            if item.evidence_id
            == memory.to_evidence(
                source_reliability=observation.source_reliability,
                privacy=observation.privacy,
            ).evidence_id
        )
        self.assertEqual("preference", evidence.memory_family)
        self.assertEqual("preference:tool", evidence.claim_slot)
        self.assertEqual("support", evidence.claim_polarity)
        self.assertEqual(
            (observation.observation_id,),
            evidence.source_observation_ids,
        )

    def test_non_preference_observation_yields_no_memory(self):
        matcher = PreferenceFrameMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        observation = dialogue_to_observation(
            "W32time service synchronized system time.",
            actor="system",
            user_id="user-1",
            session_id="session-1",
            source_event_id="event-2",
            event_time="2026-07-27T00:00:00+00:00",
        )
        extraction = PreferenceObservationMemoryExtractor(
            matcher
        ).extract(observation)
        self.assertEqual((), extraction.memories)
        self.assertEqual((), extraction.evidence)

    def test_fast_closed_choice_path_keeps_batch_correct(self):
        cases = json.loads(
            (
                Path(__file__).parent
                / "data"
                / "preference_observation_choices_v1.json"
            ).read_text(encoding="utf-8")
        )
        matcher = ObservationMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        self.assertEqual("kylin_observation_v1", matcher.name)
        for case in cases:
            with self.subTest(case=case["id"]):
                result = matcher.match(
                    case["text"],
                    options=PreferenceObservationOptions(
                        **{
                            key: tuple(value)
                            for key, value in case["options"].items()
                        }
                    ),
                )
                self.assertTrue(result.frames)
                selected = max(
                    result.frames,
                    key=lambda value: value.confidence,
                )
                expected = case["expected"]
                self.assertEqual(
                    expected["condition_tag_id"],
                    selected.condition.tag_id,
                )
                self.assertEqual(
                    expected["object_tag_id"],
                    selected.object.tag_id,
                )
                self.assertEqual(
                    expected["temporal_label"],
                    selected.temporal.label,
                )
                self.assertLessEqual(
                    result.diagnostics["embedding_computed_delta"],
                    (
                        result.diagnostics["embedding_candidate_count"]
                        + len(result.diagnostics["formation_gate"])
                        + 1
                    ),
                )
                self.assertEqual(
                    {"condition", "attitude", "object", "temporal"},
                    set(
                        result.diagnostics[
                            "dynamic_candidate_thresholds"
                        ]
                    ),
                )

    def test_cross_language_bridge_keeps_company_api_context(self):
        proposer = GreedyOptionAnchoredSpanProposer(
            CharacterSpanTokenizer()
        )
        proposal = proposer.propose(
            "改用公司API",
            (),
            condition_ids={"task:quote_email"},
            object_ids={"tool:company_api"},
        )
        self.assertIn(
            "改用公司API",
            [
                value.candidate.text
                for value in proposal.candidates
                if value.group == "object"
            ],
        )

    def test_formation_gate_vetoes_fact_but_keeps_preference(self):
        gate = EmbeddingFormationGate(_PreferenceToyEmbedder())
        preference, fact = gate.assess(
            (
                "以后默认用折线图",
                "系统运行事实没有可提取的偏好",
            )
        )
        self.assertFalse(preference.rejected)
        self.assertTrue(fact.rejected)

    def test_fast_path_candidate_capacity_grows_with_input(self):
        matcher = ObservationMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        options = PreferenceObservationOptions(
            condition_tag_ids=("app:spreadsheet",),
            object_tag_ids=(
                "chart:line",
                "chart:bar",
                "document:template",
            ),
            temporal_labels=(
                "temporal_short",
                "temporal_medium",
                "temporal_long",
            ),
        )
        short = matcher.match("本轮优先用折线图。", options=options)
        long = matcher.match(
            "本轮优先用折线图；后续创建柱状图；"
            "以后沿用这份模板；当前还要整理预算表。",
            options=options,
        )
        self.assertGreater(
            long.diagnostics["greedy_candidate_count"],
            short.diagnostics["greedy_candidate_count"],
        )
        self.assertGreater(
            long.diagnostics["greedy_candidate_count"],
            4,
        )

    def test_chinese_spaces_and_language_switches_are_soft_boundaries(
        self,
    ):
        matcher = ObservationMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        options = PreferenceObservationOptions(
            condition_tag_ids=("task:code_explanation",),
            object_tag_ids=("app:chatgpt_codex",),
            temporal_labels=(
                "temporal_short",
                "temporal_medium",
                "temporal_long",
            ),
        )
        result = matcher.match(
            "以后 我喜欢用 ChatGPT Codex 做代码解释",
            options=options,
        )
        self.assertEqual(
            "cjk",
            result.diagnostics["dominant_language"],
        )
        self.assertIn(
            "ChatGPT Codex",
            [
                value["text"]
                for value in result.diagnostics["language_atoms"]
            ],
        )
        self.assertGreaterEqual(
            len(result.diagnostics["soft_ranges"]),
            4,
        )

    def test_english_word_spaces_do_not_become_soft_boundaries(self):
        matcher = ObservationMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        result = matcher.match(
            "Please use ChatGPT Codex for code explanations",
            options=PreferenceObservationOptions(
                condition_tag_ids=("task:code_explanation",),
                object_tag_ids=("app:chatgpt_codex",),
                temporal_labels=(
                    "temporal_short",
                    "temporal_medium",
                    "temporal_long",
                ),
            ),
        )
        self.assertEqual(
            "latin",
            result.diagnostics["dominant_language"],
        )
        self.assertEqual(1, len(result.diagnostics["soft_ranges"]))
        self.assertEqual(
            [],
            result.diagnostics["language_atoms"],
        )

    def test_chinese_atom_is_soft_boundary_in_english_dominant_text(
        self,
    ):
        matcher = ObservationMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        result = matcher.match(
            "Please use Codex \u5904\u7406\u4ee3\u7801 for reports",
            options=PreferenceObservationOptions(
                condition_tag_ids=("task:code_explanation",),
                object_tag_ids=("app:chatgpt_codex",),
                temporal_labels=(
                    "temporal_short",
                    "temporal_medium",
                    "temporal_long",
                ),
            ),
        )
        self.assertEqual(
            "latin",
            result.diagnostics["dominant_language"],
        )
        self.assertEqual(
            ["\u5904\u7406\u4ee3\u7801"],
            [
                value["text"]
                for value in result.diagnostics["language_atoms"]
            ],
        )
        self.assertEqual(3, len(result.diagnostics["soft_ranges"]))

    def test_identifier_punctuation_is_protected_inside_latin_atoms(
        self,
    ):
        matcher = ObservationMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        result = matcher.match(
            "\u6574\u7406 Student_Level.xlsx B1:E30 "
            "\u7684\u7a7a\u767d\u5355\u5143\u683c",
            options=PreferenceObservationOptions(
                condition_tag_ids=("task:code_explanation",),
                object_tag_ids=("app:chatgpt_codex",),
                temporal_labels=(
                    "temporal_short",
                    "temporal_medium",
                    "temporal_long",
                ),
            ),
        )
        self.assertEqual(
            ["Student_Level.xlsx", "B1:E30"],
            [
                value["text"]
                for value in result.diagnostics["language_atoms"]
            ],
        )
        self.assertIn(
            "B1:E30",
            [
                value["text"]
                for value in result.diagnostics["soft_ranges"]
            ],
        )

    def test_original_chinese_punctuation_remains_a_hard_boundary(
        self,
    ):
        matcher = ObservationMatcher(
            _PreferenceToyEmbedder(),
            tokenizer=CharacterSpanTokenizer(),
        )
        result = matcher.match(
            "\u4ee5\u540e\u7528 Codex\uff0c"
            "\u5f53\u524d\u7528\u8fd9\u4e2a\u6a21\u677f\u3002",
            options=PreferenceObservationOptions(
                condition_tag_ids=("task:code_explanation",),
                object_tag_ids=("app:chatgpt_codex",),
                temporal_labels=(
                    "temporal_short",
                    "temporal_medium",
                    "temporal_long",
                ),
            ),
        )
        self.assertEqual(
            2,
            len(
                result.diagnostics["segmentations"][
                    "punctuation_only"
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
