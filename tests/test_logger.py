"""Tests for logger.py — secret redaction in tool logs.

Run: python -m unittest tests.test_logger -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logger


class LoggerRedactTest(unittest.TestCase):

    def test_api_key_redacted(self):
        out = logger._redact({"api_key": "AIzaSy...", "name": "x"})
        self.assertEqual(out["api_key"], "***")
        self.assertEqual(out["name"], "x")

    def test_nested_token_redacted(self):
        out = logger._redact({"inner": {"access_token": "abc"}})
        self.assertEqual(out["inner"]["access_token"], "***")

    def test_plain_values_kept(self):
        out = logger._redact({"path": "C:/x", "count": 3})
        self.assertEqual(out["path"], "C:/x")
        self.assertEqual(out["count"], 3)


if __name__ == "__main__":
    unittest.main()