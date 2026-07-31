"""Unit tests for security.audit — SecurityAuditLogger."""
import json
import os
import tempfile
import unittest
from security.audit import SecurityAuditLogger


class TestSecurityAuditLogger(unittest.TestCase):
    """Tests for SecurityAuditLogger class."""

    def test_log_threat_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_audit.jsonl")
            logger = SecurityAuditLogger(path=path)
            logger.log_threat_block(
                "恶意内容", ["prompt_injection"], "high",
                request_id="req-001",
            )
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertEqual(rec["event"], "threat_block")
            self.assertEqual(rec["payload"]["severity"], "high")
            self.assertIn("prompt_injection", rec["payload"]["threat_ids"])
            self.assertIn("ts", rec)

    def test_log_permission_deny(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_audit.jsonl")
            logger = SecurityAuditLogger(path=path)
            logger.log_permission_deny(
                "danger_server", "danger_tool", "策略拒绝",
                request_id="req-002",
            )
            with open(path) as f:
                rec = json.loads(f.readline())
            self.assertEqual(rec["event"], "permission_deny")
            self.assertEqual(rec["payload"]["server_name"], "danger_server")
            self.assertEqual(rec["payload"]["tool_name"], "danger_tool")

    def test_log_permission_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_audit.jsonl")
            logger = SecurityAuditLogger(path=path)
            logger.log_permission_confirm(
                "kylin_sdk_server", "volume_up",
                request_id="req-003",
            )
            with open(path) as f:
                rec = json.loads(f.readline())
            self.assertEqual(rec["event"], "permission_confirm")
            self.assertEqual(rec["payload"]["server_name"], "kylin_sdk_server")

    def test_log_memory_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_audit.jsonl")
            logger = SecurityAuditLogger(path=path)
            logger.log_memory_review(
                "fact", "remember_fact", True,
                [], reason="审查通过",
                request_id="req-004",
            )
            with open(path) as f:
                rec = json.loads(f.readline())
            self.assertEqual(rec["event"], "memory_review")
            self.assertEqual(rec["payload"]["allowed"], True)
            self.assertEqual(rec["payload"]["category"], "fact")
            self.assertEqual(rec["payload"]["source"], "remember_fact")

    def test_timestamp_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_audit.jsonl")
            logger = SecurityAuditLogger(path=path)
            logger.log_threat_block("test", ["test_id"], "low")
            with open(path) as f:
                rec = json.loads(f.readline())
            ts = rec["ts"]
            self.assertTrue(ts.endswith("Z"))
            self.assertIn("T", ts)

    def test_jsonl_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_audit.jsonl")
            logger = SecurityAuditLogger(path=path)
            logger.log_threat_block("e1", ["t1"], "low")
            logger.log_threat_block("e2", ["t2"], "medium")
            with open(path) as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)
            for line in lines:
                rec = json.loads(line.strip())
                self.assertIn("ts", rec)
                self.assertIn("event", rec)
                self.assertIn("request_id", rec)
                self.assertIn("payload", rec)

    def test_memory_review_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test_audit.jsonl")
            logger = SecurityAuditLogger(path=path)
            logger.log_memory_review(
                "general", "ingest_event", False,
                ["injection"], reason="威胁拦截",
            )
            with open(path) as f:
                rec = json.loads(f.readline())
            self.assertEqual(rec["event"], "memory_review")
            self.assertEqual(rec["payload"]["allowed"], False)


if __name__ == "__main__":
    unittest.main()