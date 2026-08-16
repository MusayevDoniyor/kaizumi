"""Tests for api_keys.py — multi-key loading + env var support.

Uses temp config files so the user's real config/api_keys.json is untouched.
Run: python -m unittest tests.test_api_keys -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_keys


class ApiKeysTest(unittest.TestCase):

    def setUp(self):
        self._old_path = api_keys.CONFIG_PATH
        self._old_env_key = os.environ.get("KAIZUMI_GEMINI_API_KEY")
        self._old_env_keys = os.environ.get("KAIZUMI_GEMINI_API_KEYS")
        if self._old_env_key is None:
            os.environ.pop("KAIZUMI_GEMINI_API_KEY", None)
        if self._old_env_keys is None:
            os.environ.pop("KAIZUMI_GEMINI_API_KEYS", None)

    def tearDown(self):
        api_keys.CONFIG_PATH = self._old_path
        for name in ("KAIZUMI_GEMINI_API_KEY", "KAIZUMI_GEMINI_API_KEYS"):
            if name == "KAIZUMI_GEMINI_API_KEY" and self._old_env_key is not None:
                os.environ[name] = self._old_env_key
            elif name == "KAIZUMI_GEMINI_API_KEYS" and self._old_env_keys is not None:
                os.environ[name] = self._old_env_keys
            else:
                os.environ.pop(name, None)

    def _write_config(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            import json
            json.dump(data, f)
        api_keys.CONFIG_PATH = Path(os.path.abspath(path))
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

    def test_loads_single_key(self):
        self._write_config({"gemini_api_key": "AIzaA"})
        self.assertEqual(api_keys.get_all_keys(), ["AIzaA"])

    def test_loads_multi_key_dedup(self):
        self._write_config({
            "gemini_api_key": "AIzaA",
            "gemini_api_keys": ["AIzaB", "AIzaA"],
        })
        self.assertEqual(api_keys.get_all_keys(), ["AIzaA", "AIzaB"])

    def test_env_key_included(self):
        self._write_config({"gemini_api_key": "AIzaA"})
        os.environ["KAIZUMI_GEMINI_API_KEY"] = "AIzaEnv"
        self.assertIn("AIzaEnv", api_keys.get_all_keys())

    def test_env_list_included(self):
        self._write_config({"gemini_api_key": "AIzaA"})
        os.environ["KAIZUMI_GEMINI_API_KEYS"] = "AIzaEnv1,AIzaEnv2"
        keys = api_keys.get_all_keys()
        self.assertIn("AIzaEnv1", keys)
        self.assertIn("AIzaEnv2", keys)

    def test_no_keys_raises(self):
        self._write_config({})
        with self.assertRaises(KeyError):
            api_keys.next_key()


if __name__ == "__main__":
    unittest.main()