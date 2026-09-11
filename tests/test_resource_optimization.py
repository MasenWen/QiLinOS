# -*- coding: utf-8 -*-
"""内存充足条件下的优化单元测试（unittest，标准库）。

覆盖三件事：
1. 资源闸门判定（auto/on/off、阈值、内存不可读）；
2. 草图候选扩展（保留基线候选、补入草图候选、不重复）；
3. 贝叶斯先验平滑（冷启动靠拢群体、证据充分后回到个人）与检索链路接线。
"""
import os
import unittest

from src.memory_engine.optimization import (
    SketchCandidateExtender,
    apply_prior_smoothing,
    bayes_prior_adjust,
    tokens_to_sparse,
)
from src.memory_engine.resource_gate import optimization_decision
from src.memory_engine.retrieval import StructuredHybridRetriever

SNAP_RICH = {"total_mb": 15000.0, "available_mb": 8000.0, "readable": True}
SNAP_TIGHT = {"total_mb": 8000.0, "available_mb": 256.0, "readable": True}
SNAP_UNREADABLE = {"total_mb": 0.0, "available_mb": 0.0, "readable": False}


class ResourceGateTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("NEX_MEM_OPTIMIZATION")
        os.environ.pop("NEX_MEM_OPTIMIZATION", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("NEX_MEM_OPTIMIZATION", None)
        else:
            os.environ["NEX_MEM_OPTIMIZATION"] = self._saved

    def test_auto_enabled_when_memory_sufficient(self):
        d = optimization_decision(snapshot=SNAP_RICH)
        self.assertTrue(d["enabled"])
        self.assertEqual(d["reason"], "available_above_threshold")

    def test_auto_disabled_when_memory_tight(self):
        d = optimization_decision(snapshot=SNAP_TIGHT)
        self.assertFalse(d["enabled"])
        self.assertEqual(d["reason"], "available_below_threshold")

    def test_disabled_when_memory_unreadable(self):
        d = optimization_decision(snapshot=SNAP_UNREADABLE)
        self.assertFalse(d["enabled"])
        self.assertEqual(d["reason"], "memory_unreadable")

    def test_explicit_switch_wins(self):
        os.environ["NEX_MEM_OPTIMIZATION"] = "on"
        self.assertTrue(optimization_decision(snapshot=SNAP_TIGHT)["enabled"])
        os.environ["NEX_MEM_OPTIMIZATION"] = "off"
        self.assertFalse(optimization_decision(snapshot=SNAP_RICH)["enabled"])

    def test_threshold_is_configurable(self):
        self.assertFalse(optimization_decision(min_available_mb=9000.0, snapshot=SNAP_RICH)["enabled"])
        self.assertTrue(optimization_decision(min_available_mb=100.0, snapshot=SNAP_TIGHT)["enabled"])


class SketchExtendTest(unittest.TestCase):
    def test_token_sparse_vector(self):
        vec = tokens_to_sparse(["记忆", "记忆", "检索"])
        self.assertEqual(sum(vec.values()), 3.0)
        self.assertEqual(len(vec), 2)
        self.assertEqual(vec, tokens_to_sparse(["记忆", "记忆", "检索"]))  # 稳定哈希

    def test_base_candidates_are_preserved(self):
        entries = [({"id": "v%d" % i}, tokens_to_sparse(["向量"])) for i in range(10)]
        entries += [({"id": "s%d" % i}, tokens_to_sparse(["记忆", "检索"])) for i in range(10)]
        extender = SketchCandidateExtender(buckets=64)
        kept, meta = extender.extend(tokens_to_sparse(["记忆", "检索"]), entries,
                                     base_keep=10, extra_keep=5)
        kept_ids = [item["id"] for item in kept]
        self.assertEqual(kept_ids[:10], ["v%d" % i for i in range(10)])   # 基线候选顺序不变
        self.assertGreaterEqual(meta["sketch_added"], 1)                  # 补入草图候选
        self.assertEqual(len(kept_ids), len(set(kept_ids)))               # 不重复
        self.assertEqual(meta["candidates"], 20)

    def test_empty_query_keeps_base_only(self):
        entries = [({"id": "v%d" % i}, tokens_to_sparse(["向量"])) for i in range(10)]
        entries += [({"id": "s%d" % i}, tokens_to_sparse(["记忆"])) for i in range(5)]
        kept, meta = SketchCandidateExtender(buckets=32).extend({}, entries, 10, 5)
        self.assertEqual(len(kept), 10)
        self.assertEqual(meta["sketch_added"], 0)


class BayesAdjustTest(unittest.TestCase):
    def test_cold_start_follows_peer_prior(self):
        adjusted, meta = bayes_prior_adjust(0.9, 0.0, 0.4, kappa_g=5.0)
        self.assertAlmostEqual(adjusted, 0.4, places=6)
        self.assertAlmostEqual(meta["lambda_g"], 1.0, places=6)

    def test_warm_user_keeps_own_score(self):
        # kappa_g=5、n=995 → lambda_u≈0.995，得分几乎等于个人得分
        adjusted, meta = bayes_prior_adjust(0.9, 995.0, 0.4, kappa_g=5.0)
        self.assertAlmostEqual(adjusted, 0.9, places=2)
        self.assertGreater(meta["lambda_u"], 0.99)

    def test_weights_sum_to_one(self):
        _, meta = bayes_prior_adjust(0.5, 5.0, 0.5, kappa_g=5.0)
        self.assertAlmostEqual(meta["lambda_g"] + meta["lambda_u"], 1.0, places=6)

    def test_smoothing_reports_when_evidence_missing(self):
        result = apply_prior_smoothing([{"activation": 0.5}], None)
        self.assertFalse(result["active"])
        self.assertEqual(result["reason"], "evidence_provider_unavailable")

    def test_cold_start_ranks_by_peer_signal(self):
        """n=0 时完全依靠群体系（通用语义相似度），且逐候选保留差异。"""
        items = [{"activation": 0.9, "activation_components": {"semantic": 0.2}},
                 {"activation": 0.3, "activation_components": {"semantic": 0.8}}]
        result = apply_prior_smoothing(items, 0.0, kappa_g=5.0)
        self.assertTrue(result["active"])
        self.assertAlmostEqual(items[0]["activation"], 0.2, places=6)
        self.assertAlmostEqual(items[1]["activation"], 0.8, places=6)
        self.assertIn("bayes_prior", items[0]["activation_components"])
        self.assertEqual(items[0]["activation_components"]["bayes_prior"]["peer_source"], "item_semantic")

    def test_warm_user_keeps_structured_score(self):
        items = [{"activation": 0.9, "activation_components": {"semantic": 0.2}}]
        apply_prior_smoothing(items, 995.0, kappa_g=5.0)
        self.assertAlmostEqual(items[0]["activation"], 0.9, places=2)

    def test_smoothing_falls_back_to_mean_without_semantic(self):
        items = [{"activation": 0.9, "activation_components": {}}, {"activation": 0.3, "activation_components": {}}]
        apply_prior_smoothing(items, 0.0, kappa_g=5.0)
        self.assertAlmostEqual(items[0]["activation"], 0.6, places=6)


class RetrieverWiringTest(unittest.TestCase):
    def _backend(self, pool_size=30):
        def backend(_query, _user_id, limit):
            out = []
            for i in range(min(limit, pool_size)):
                out.append({
                    "id": "m%02d" % i,
                    "memory": "记忆条目 %d 关于会议记录与偏好设置" % i,
                    "score": 1.0 - i * 0.01,
                    "metadata": {"status": "active", "memory_category": "workflow"},
                })
            return out
        return backend

    def _context(self):
        from src.memory_engine.models import RetrievalContext
        return RetrievalContext.from_mapping("会议记录怎么整理", {}, user_id="u1")

    def test_disabled_path_is_unchanged(self):
        r = StructuredHybridRetriever(self._backend(), candidate_top_k=10,
                                      optimization={"enabled": False, "reason": "explicit_off"})
        resp = r.retrieve(self._context(), top_k=5)
        self.assertEqual(resp.trace["candidate_top_k"], 10)
        self.assertFalse(resp.trace["optimization"]["enabled"])
        self.assertEqual(resp.trace["optimization"]["recall_k"], 10)
        self.assertIsNone(resp.trace["optimization"]["prune"])

    def test_enabled_path_recalls_wider_and_extends(self):
        r = StructuredHybridRetriever(self._backend(), candidate_top_k=10,
                                      optimization={"enabled": True, "reason": "explicit_on"},
                                      evidence_count=lambda _uid: 3.0)
        resp = r.retrieve(self._context(), top_k=5)
        opt = resp.trace["optimization"]
        self.assertTrue(opt["enabled"])
        self.assertEqual(opt["recall_k"], 40)                 # 扩大到 4 倍
        self.assertIsNotNone(opt["prune"])
        self.assertGreater(opt["prune"]["candidates"], 10)    # 召回更宽
        self.assertTrue(opt["bayes"]["active"])               # 先验平滑生效
        self.assertEqual(len(resp.items), 5)

    def test_baseline_candidates_survive_optimization(self):
        """优化只做扩展：基线要用的候选必须仍在候选集内。"""
        ctx = self._context()
        base = StructuredHybridRetriever(self._backend(), candidate_top_k=10,
                                         optimization={"enabled": False, "reason": "explicit_off"})
        base_ids = {item["id"] for item in base.retrieve(ctx, top_k=10).items}
        opt = StructuredHybridRetriever(self._backend(), candidate_top_k=10,
                                        optimization={"enabled": True, "reason": "explicit_on"})
        opt_ids = {item["id"] for item in opt.retrieve(ctx, top_k=10).items}
        self.assertTrue(base_ids <= opt_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
