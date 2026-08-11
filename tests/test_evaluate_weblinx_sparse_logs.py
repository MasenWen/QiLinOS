from __future__ import annotations

import unittest

from tools.evaluate_weblinx_sparse_logs import semantic_values


class WeblinxSparseLogEvaluationTest(unittest.TestCase):
    def test_extracts_only_semantic_fields(self):
        row = {
            "episode_id": "secret-episode",
            "user_id": "secret-user",
            "event_time_basis": "session_relative_source",
            "apps_involved": ["web_browser"],
            "action_keys": ["click", "say"],
            "context_json": {
                "timestamp_recovery": "recovered from action history",
                "excluded_target_count_without_time": 7,
            },
        }
        values = semantic_values(row)
        self.assertIn(("apps_involved", "web_browser"), values)
        self.assertIn(("action_keys", "click"), values)
        self.assertIn(
            (
                "context_json.timestamp_recovery",
                "recovered from action history",
            ),
            values,
        )
        flattened = {value for _, value in values}
        self.assertNotIn("secret-episode", flattened)
        self.assertNotIn("secret-user", flattened)

    def test_ignores_numeric_and_unknown_context_fields(self):
        row = {
            "source_event_count": 8,
            "unknown_text": "do not ingest",
            "context_json": {
                "excluded_target_count_without_time": 4,
            },
        }
        self.assertEqual((), semantic_values(row))


if __name__ == "__main__":
    unittest.main()
