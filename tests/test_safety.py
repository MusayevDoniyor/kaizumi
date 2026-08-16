"""Tests for safety.py — risk classification, confirmation gate, sanitization.

Run: python -m unittest tests.test_safety -v
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import safety


class RiskClassificationTest(unittest.TestCase):

    def test_low_risk_read_only(self):
        self.assertEqual(safety.classify("web_search", {}), safety.Risk.LOW)
        self.assertEqual(safety.classify("system_status", {}), safety.Risk.LOW)

    def test_file_delete_is_high(self):
        self.assertEqual(
            safety.classify("file_controller", {"action": "delete", "name": "x.txt"}),
            safety.Risk.HIGH,
        )

    def test_file_read_not_high(self):
        self.assertNotEqual(
            safety.classify("file_controller", {"action": "read", "name": "x.txt"}),
            safety.Risk.HIGH,
        )

    def test_terminal_is_high(self):
        self.assertEqual(safety.classify("cmd_control", {"command": "dir"}), safety.Risk.HIGH)

    def test_gmail_send_high_read_low(self):
        self.assertEqual(safety.classify("gmail", {"action": "send"}), safety.Risk.HIGH)
        self.assertEqual(safety.classify("gmail", {"action": "read"}), safety.Risk.LOW)

    def test_task_manager_kill_high(self):
        self.assertEqual(safety.classify("task_manager", {"action": "kill"}), safety.Risk.HIGH)

    def test_open_app_medium(self):
        self.assertEqual(safety.classify("open_app", {"app_name": "Chrome"}), safety.Risk.MEDIUM)

    def test_unknown_tool_defaults_to_medium(self):
        self.assertEqual(safety.classify("totally_unknown_tool", {}), safety.Risk.MEDIUM)


class ConfirmationTest(unittest.TestCase):

    def test_high_needs_confirmation(self):
        self.assertTrue(safety.needs_confirmation("cmd_control", {"command": "dir"}))

    def test_low_does_not_need_confirmation(self):
        self.assertFalse(safety.needs_confirmation("web_search", {"query": "x"}))

    def test_confirm_flag_bypasses(self):
        self.assertFalse(
            safety.needs_confirmation("cmd_control", {"command": "dir"}, confirm=True)
        )


class DescribeTest(unittest.TestCase):

    def test_delete_description(self):
        desc = safety.describe("file_controller", {"action": "delete", "name": "notes.txt"})
        self.assertIn("delete notes.txt", desc)

    def test_command_description(self):
        desc = safety.describe("cmd_control", {"command": "dir"})
        self.assertIn("dir", desc)


class SanitizeTest(unittest.TestCase):

    def test_api_key_masked(self):
        out = safety.sanitize("api_add_key", {"key": "AIzaSyB-...", "note": "hi"})
        self.assertEqual(out["key"], "***")
        self.assertEqual(out["note"], "hi")

    def test_token_masked(self):
        out = safety.sanitize("any", {"access_token": "abc123", "path": "C:/x"})
        self.assertEqual(out["access_token"], "***")
        self.assertEqual(out["path"], "C:/x")


if __name__ == "__main__":
    unittest.main()