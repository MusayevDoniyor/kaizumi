"""Tests for the P0 security & robustness fixes.

Covers:
  - document_qa SSRF guard (private/literal-IP targets are refused)
  - desktop.py exec sandbox (ctypes escape removed, spaced-obfuscation blocked)
  - executor UnknownToolError (deterministic skip, no LLM loop)
  - ui.py _api_keys_exist (validates real keys, not just file existence)

Run: python -m unittest tests.test_p0_security -v
"""

import os
import sys
import inspect
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DocumentQaSsrTest(unittest.TestCase):
    def setUp(self):
        from actions import document_qa
        self._is_private_target = document_qa._is_private_target

    def test_loopback_refused(self):
        self.assertTrue(self._is_private_target("http://127.0.0.1:8000/x"))
        self.assertTrue(self._is_private_target("http://localhost/x"))
        self.assertTrue(self._is_private_target("http://[::1]/x"))

    def test_private_literal_ip_refused(self):
        self.assertTrue(self._is_private_target("http://10.0.0.1/x"))
        self.assertTrue(self._is_private_target("http://192.168.1.1/x"))
        self.assertTrue(self._is_private_target("http://172.16.0.1/x"))

    def test_link_local_metadata_refused(self):
        self.assertTrue(self._is_private_target("http://169.254.169.254/latest/meta-data/"))
        self.assertTrue(self._is_private_target("http://metadata.google.internal/x"))

    def test_public_host_allowed(self):
        self.assertFalse(self._is_private_target("http://example.com/x"))
        self.assertFalse(self._is_private_target("https://en.wikipedia.org/x"))


class DesktopSandboxTest(unittest.TestCase):
    def setUp(self):
        from actions import desktop
        self.desktop = desktop

    def _safe(self, code):
        ok, _ = self.desktop._is_safe_code(code)
        return ok

    def test_ctypes_escape_blocked(self):
        code = 'ctypes.windll.kernel32.WinExec("cmd /c calc")'
        self.assertFalse(self._safe(code))

    def test_spaced_open_obfuscation_blocked(self):
        code = "f = open ('C:/x', 'w')\nf.write('y')"
        self.assertFalse(self._safe(code))

    def test_import_os_with_spaces_blocked(self):
        code = "import   os\nos.system('dir')"
        self.assertFalse(self._safe(code))

    def test_subclass_escape_blocked(self):
        code = "print(().__class__.__subclasses__())"
        self.assertFalse(self._safe(code))

    def test_normal_pyautogui_allowed(self):
        code = "pyautogui.moveTo(10, 10)\npyautogui.click()"
        self.assertTrue(self._safe(code))

    def test_ctypes_not_in_globals(self):
        # Re-run the executor's globals construction path: parse the source of
        # _execute_generated_code and confirm ctypes is not among the names.
        src = inspect.getsource(self.desktop._execute_generated_code)
        self.assertNotIn('"ctypes"', src)
        self.assertNotIn("'ctypes'", src)


class ExecutorUnknownToolTest(unittest.TestCase):
    def test_unknown_tool_raises_specific_type(self):
        from agent.executor import _call_tool, UnknownToolError
        with self.assertRaises(UnknownToolError):
            _call_tool("does_not_exist_xyz", {}, None)

    def test_known_tool_dispatches(self):
        from agent.executor import _call_tool
        out = _call_tool("system_status", {}, None)
        self.assertIsInstance(out, str)

    def test_newly_wired_tools_dispatch(self):
        from agent.executor import _call_tool
        for tool, params in [
            ("translate", {"text": "hello"}),
            ("media_control", {"action": "play"}),
            ("pc_health", {"action": "status"}),
        ]:
            try:
                out = _call_tool(tool, params, None)
                self.assertIsInstance(out, str)
            except Exception as e:
                # Tools may legitimately fail at runtime (no creds etc.) — the
                # key assertion is that they're KNOWN (not UnknownToolError).
                from agent.executor import UnknownToolError
                self.assertNotIsInstance(e, UnknownToolError)


class ApiKeysExistTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        import ui
        self._tmp = tempfile.TemporaryDirectory()
        self._old_file = ui.API_FILE
        self._old_env = os.environ.get("KAIZUMI_GEMINI_API_KEY")
        self._old_env2 = os.environ.get("KAIZUMI_GEMINI_API_KEYS")
        os.environ.pop("KAIZUMI_GEMINI_API_KEY", None)
        os.environ.pop("KAIZUMI_GEMINI_API_KEYS", None)
        ui.API_FILE = Path(self._tmp.name) / "api_keys.json"
        self.ui = ui

    def tearDown(self):
        self.ui.API_FILE = self._old_file
        if self._old_env is not None:
            os.environ["KAIZUMI_GEMINI_API_KEY"] = self._old_env
        if self._old_env2 is not None:
            os.environ["KAIZUMI_GEMINI_API_KEYS"] = self._old_env2
        self._tmp.cleanup()

    def _write(self, content: str):
        self.ui.API_FILE.write_text(content, encoding="utf-8")

    def _exists(self):
        # Build a minimal stand-in: reuse the class method via a stub instance.
        class Stub:
            pass
        inst = Stub()
        from types import MethodType
        inst._api_keys_exist = MethodType(self.ui.KaizumiUI._api_keys_exist, inst)
        return inst._api_keys_exist()

    def test_empty_file_is_not_ready(self):
        self._write("{}")
        self.assertFalse(self._exists())

    def test_valid_single_key_is_ready(self):
        self._write('{"gemini_api_key": "AIzaSyB-valid"}')
        self.assertTrue(self._exists())

    def test_valid_key_list_is_ready(self):
        self._write('{"gemini_api_keys": ["AIzaSyB-valid"]}')
        self.assertTrue(self._exists())

    def test_malformed_json_is_not_ready(self):
        self._write("{not json!!")
        self.assertFalse(self._exists())

    def test_missing_file_is_not_ready(self):
        self.assertFalse(self._exists())


class SetupTokenTest(unittest.TestCase):
    def test_create_bridge_token_generates_hex(self):
        import importlib.util
        import tempfile
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "setup_mod", Path(__file__).resolve().parent.parent / "setup.py")
        setup = importlib.util.module_from_spec(spec)
        # Only load the functions — do NOT run module-level main().
        import types
        setup.__name__ = "setup_mod"
        spec.loader.exec_module(setup)
        self.assertTrue(callable(setup.create_bridge_token))

        tmp = Path(tempfile.mkdtemp())
        try:
            old_root = setup.ROOT
            setup.ROOT = tmp
            setup.create_bridge_token()
            token = (tmp / "config" / "bridge_token.txt").read_text(encoding="utf-8").strip()
            self.assertGreaterEqual(len(token), 16)
            self.assertTrue(all(c in "0123456789abcdef" for c in token))
            # Idempotent: a second call must not overwrite it.
            setup.create_bridge_token()
            self.assertEqual(
                token, (tmp / "config" / "bridge_token.txt").read_text(encoding="utf-8").strip())
            setup.ROOT = old_root
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class BridgeTokenTest(unittest.TestCase):
    def test_auto_provisions_token_when_missing(self):
        import tempfile
        import remote.bluetooth_transport as bt
        tmp = Path(tempfile.mkdtemp())
        try:
            old_file = bt.TOKEN_FILE
            old_env = os.environ.get("KAIZUMI_BRIDGE_TOKEN")
            os.environ.pop("KAIZUMI_BRIDGE_TOKEN", None)
            bt.TOKEN_FILE = tmp / "bridge_token.txt"
            token = bt.get_bridge_token()
            self.assertGreaterEqual(len(token), 16)
            self.assertTrue((tmp / "bridge_token.txt").exists())
            # Second call returns the same persisted token.
            self.assertEqual(token, bt.get_bridge_token())
            bt.TOKEN_FILE = old_file
            if old_env is not None:
                os.environ["KAIZUMI_BRIDGE_TOKEN"] = old_env
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_env_token_wins_over_generated(self):
        import tempfile
        import remote.bluetooth_transport as bt
        tmp = Path(tempfile.mkdtemp())
        old_env = os.environ.get("KAIZUMI_BRIDGE_TOKEN")
        try:
            bt.TOKEN_FILE = tmp / "bridge_token.txt"
            os.environ["KAIZUMI_BRIDGE_TOKEN"] = "a" * 40
            self.assertEqual(bt.get_bridge_token(), "a" * 40)
            self.assertFalse((tmp / "bridge_token.txt").exists())
            if old_env is not None:
                os.environ["KAIZUMI_BRIDGE_TOKEN"] = old_env
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()