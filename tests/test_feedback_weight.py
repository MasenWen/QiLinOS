"""反馈权重模块单元测试（unittest，标准库；临时路径隔离）。"""
import os
import tempfile
import unittest

import src.feedback_weight as fw


class FeedbackWeightTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="fbw_")
        self._old_path = os.environ.get("NEX_FEEDBACK_PATH")
        os.environ["NEX_FEEDBACK_PATH"] = os.path.join(self._tmp, "feedback.json")

    def tearDown(self):
        if self._old_path is None:
            os.environ.pop("NEX_FEEDBACK_PATH", None)
        else:
            os.environ["NEX_FEEDBACK_PATH"] = self._old_path

    def test_normalize(self):
        self.assertEqual(fw.normalize("稳定偏好：format_policy=concise"),
                         "format_policy=concise")
        self.assertEqual(fw.normalize("请记住： 我  喜欢  跑步"), "我 喜欢 跑步")

    def test_record_and_score(self):
        prefs = ["稳定偏好：format_policy=concise"]
        fw.record(prefs, "up")
        fw.record(prefs, "up")
        self.assertAlmostEqual(fw.score("format_policy=concise"), 3.0 / 4.0)
        fw.record(prefs, "down")
        self.assertAlmostEqual(fw.score("format_policy=concise"), 3.0 / 5.0)

    def test_rank_filter(self):
        lines = [
            "稳定偏好：format_policy=concise",
            "稳定偏好：detail_policy=one_sentence",
            "稳定偏好：workflow_order=verify_state_then_resume",
        ]
        # 给第一条点赞、第三条连踩两次
        fw.record([lines[0]], "up")
        fw.record([lines[2]], "down")
        fw.record([lines[2]], "down")
        ranked = fw.rank_preference_lines(lines, limit=10)
        self.assertIn(lines[0], ranked)          # 高采纳率保留
        self.assertIn(lines[1], ranked)          # 无反馈保留
        self.assertNotIn(lines[2], ranked)       # 连续反对被剔除
        # 排序：点赞的应排在无反馈之前
        self.assertLess(ranked.index(lines[0]), ranked.index(lines[1]))

    def test_rank_limit(self):
        lines = ["稳定偏好：x%d=value" % i for i in range(10)]
        out = fw.rank_preference_lines(lines, limit=3)
        self.assertEqual(len(out), 3)

    def test_invalid_vote(self):
        r = fw.record(["a"], "sideways")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
