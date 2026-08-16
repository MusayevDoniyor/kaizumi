"""Tests for memory/memory_manager.py — CRUD, pruning, secret filtering.

Uses a temp file so the user's real memory/long_term.json is never touched.
Run: python -m unittest tests.test_memory -v
"""

import os
import sys
import tempfile
import unittest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory.memory_manager as mm


class MemoryTest(unittest.TestCase):

    def setUp(self):
        fd, self.tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(self.tmp, "w", encoding="utf-8") as f:
            import json
            json.dump({}, f)
        mm.MEMORY_PATH = mm.Path(self.tmp)

    def tearDown(self):
        try:
            mm.Path(self.tmp).unlink()
        except Exception:
            pass

    def test_remember_and_search(self):
        mm.remember("favorite_food", "pizza", "preferences")
        self.assertIn("pizza", mm.search_memory("pizza"))

    def test_forget(self):
        mm.remember("favorite_food", "pizza", "preferences")
        res = mm.forget("favorite_food", "preferences")
        self.assertIn("Forgotten", res)
        result = mm.search_memory("pizza")
        self.assertIn("don't have anything", result.lower())

    def test_clear_all(self):
        mm.remember("favorite_food", "pizza", "preferences")
        mm.remember("name", "Ali", "identity")
        res = mm.clear_memory()
        self.assertIn("All memory cleared", res)
        self.assertEqual(mm.load_memory()["preferences"], {})
        self.assertEqual(mm.load_memory()["identity"], {})

    def test_secrets_never_stored(self):
        mm.remember("api_key", "AIzaSyINVALIDTESTKEY-NOT-A-REAL-KEY-12345", "notes")
        mm.remember("wifi_password", "hunter2secret", "notes")
        mem = mm.load_memory()
        self.assertNotIn("api_key", mem["notes"])
        self.assertNotIn("wifi_password", mem["notes"])

    def test_prune_keeps_recent(self):
        for i in range(50):
            mm.remember(f"key_{i}", f"value_{i}", "notes")
        mem = mm.load_memory()
        self.assertLessEqual(len(mem["notes"]), 40)

    def test_truncate_long_values(self):
        mm.remember("long_note", "x" * 500, "notes")
        mem = mm.load_memory()
        val = mem["notes"]["long_note"]["value"]
        self.assertLessEqual(len(val), mm.MAX_VALUE_LENGTH + 1)


if __name__ == "__main__":
    unittest.main()