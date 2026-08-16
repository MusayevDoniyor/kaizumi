"""Tests for zip-slip protection and reminder script generation.

file_controller's _unzip_path must reject members that escape the target dir.
Run: python -m unittest tests.test_file_controller -v
"""

import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import file_controller


class ZipSlipTest(unittest.TestCase):

    def test_legitimate_extract_ok(self):
        with tempfile.TemporaryDirectory() as d:
            zpath = os.path.join(d, "safe.zip")
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("readme.txt", "hello")
            res = file_controller._unzip_path(zpath, os.path.join(d, "out"))
            self.assertIn("Extracted", res)
            self.assertTrue(os.path.exists(os.path.join(d, "out", "readme.txt")))

    def test_zip_slip_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            zpath = os.path.join(d, "evil.zip")
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("../../escape.txt", "pwned")
            res = file_controller._unzip_path(zpath, os.path.join(d, "out"))
            self.assertIn("blocked", res.lower())


if __name__ == "__main__":
    unittest.main()