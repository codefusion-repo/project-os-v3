import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProviderGuideTests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools/select.py"), *args],
                              capture_output=True, text=True, timeout=15)

    def test_terminal_guide(self):
        result = self.invoke("--providers", "terminal")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Terminal:", result.stdout)
        self.assertNotIn("WorkOS", result.stdout)

    def test_chatgpt_guide(self):
        result = self.invoke("--providers", "chatgpt")
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("GitHub Connector", "WorkOS", "Local Bridge", "--bridge-setup", "no verificados"):
            self.assertIn(expected, result.stdout)

    def test_both_modes(self):
        result = self.invoke("--providers", "both")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Terminal:", result.stdout)
        self.assertIn("ChatGPT:", result.stdout)

    def test_reject_invalid_and_mixed_options(self):
        for args in (("--providers", "unknown"), ("--providers", "both", "--configure"),
                     ("--providers", "both", "--bridge-setup", "/tmp/unused")):
            with self.subTest(args=args):
                self.assertEqual(self.invoke(*args).returncode, 2)
