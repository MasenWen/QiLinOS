"""Unit tests for security.permission — PermissionEngine."""
import os
import tempfile
from pathlib import Path

import unittest
import yaml
from security.permission import PermissionEngine, Permission, PermissionResult


class TestPermissionEngine(unittest.TestCase):

    def _make_engine(self, data: dict):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(data, f)
            tmp = f.name

        class _TempEngine(PermissionEngine):
            def __init__(self_inner):
                self_inner._rules_path = Path(tmp)
                self_inner._servers = {}
                self_inner._dsl = {}
                self_inner._reload()

        return _TempEngine(), tmp

    def test_exact_server_tool_match(self):
        eng, tmp = self._make_engine({
            "servers": {"test_server": {"test_tool": "L1"}},
            "dsl_actions": {},
        })
        r = eng.check("test_server", "test_tool")
        self.assertEqual(r.permission, Permission.REQUIRE_CONFIRM)
        self.assertEqual(r.level, "L1")
        os.unlink(tmp)

    def test_wildcard_server_match(self):
        eng, tmp = self._make_engine({
            "servers": {"test_server": {"*": "L0"}},
            "dsl_actions": {},
        })
        r = eng.check("test_server", "unknown_tool")
        self.assertEqual(r.permission, Permission.ALLOW)
        self.assertEqual(r.level, "L0")
        os.unlink(tmp)

    def test_deny_level(self):
        eng, tmp = self._make_engine({
            "servers": {"danger_server": {"*": "L2"}},
            "dsl_actions": {},
        })
        r = eng.check("danger_server", "any_tool")
        self.assertEqual(r.permission, Permission.DENY)
        self.assertEqual(r.level, "L2")
        os.unlink(tmp)

    def test_unknown_server_default_allow(self):
        eng, tmp = self._make_engine({
            "servers": {},
            "dsl_actions": {},
        })
        r = eng.check("unregistered_server", "some_tool")
        self.assertEqual(r.permission, Permission.ALLOW)
        self.assertEqual(r.level, "L0")
        os.unlink(tmp)

    def test_unknown_tool_default_allow(self):
        eng, tmp = self._make_engine({
            "servers": {"test_server": {}},
            "dsl_actions": {},
        })
        r = eng.check("test_server", "unregistered_tool")
        self.assertEqual(r.permission, Permission.ALLOW)
        os.unlink(tmp)

    def test_missing_yaml_fail_open(self):
        eng = PermissionEngine(rules_path=Path("/nonexistent/path.yaml"))
        r = eng.check("any_server", "any_tool")
        self.assertEqual(r.permission, Permission.ALLOW)

    def test_corrupt_yaml_fail_open(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(": [[ invalid yaml {{{{{\n")
            tmp = f.name
        eng = PermissionEngine(rules_path=Path(tmp))
        r = eng.check("any_server", "any_tool")
        self.assertEqual(r.permission, Permission.ALLOW)
        os.unlink(tmp)

    def test_exact_dsl_match(self):
        eng, tmp = self._make_engine({
            "servers": {},
            "dsl_actions": {"reboot": "L2"},
        })
        r = eng.check_action("reboot")
        self.assertEqual(r.permission, Permission.DENY)
        r = eng.check_action("{reboot}")
        self.assertEqual(r.permission, Permission.DENY)
        os.unlink(tmp)

    def test_dsl_prefix_match(self):
        eng, tmp = self._make_engine({
            "servers": {},
            "dsl_actions": {"set background": "L1"},
        })
        r = eng.check_action("{set background /path/to/image.jpg}")
        self.assertEqual(r.permission, Permission.REQUIRE_CONFIRM)
        os.unlink(tmp)

    def test_dsl_wildcard(self):
        eng, tmp = self._make_engine({
            "servers": {},
            "dsl_actions": {"*": "L0"},
        })
        r = eng.check_action("unknown_action")
        self.assertEqual(r.permission, Permission.ALLOW)
        os.unlink(tmp)

    def test_dsl_default_allow(self):
        eng, tmp = self._make_engine({
            "servers": {},
            "dsl_actions": {},
        })
        r = eng.check_action("completely_unknown")
        self.assertEqual(r.permission, Permission.ALLOW)
        os.unlink(tmp)


class TestPermissionEnum(unittest.TestCase):

    def test_permission_values(self):
        self.assertEqual(Permission.ALLOW.value, "allow")
        self.assertEqual(Permission.REQUIRE_CONFIRM.value, "require_confirm")
        self.assertEqual(Permission.DENY.value, "deny")


class TestPermissionResult(unittest.TestCase):

    def test_basic(self):
        r = PermissionResult(Permission.ALLOW, "L0", "test reason")
        self.assertEqual(r.permission, Permission.ALLOW)
        self.assertEqual(r.level, "L0")
        self.assertEqual(r.reason, "test reason")


class TestSingletonFactory(unittest.TestCase):

    def test_singleton_returns_same_instance(self):
        from security.permission import get_permission_engine
        e1 = get_permission_engine()
        e2 = get_permission_engine()
        self.assertIs(e1, e2)


if __name__ == "__main__":
    unittest.main()