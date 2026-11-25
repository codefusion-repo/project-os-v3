import subprocess
import importlib.util
import tempfile
from unittest.mock import patch
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

class GuidedActionsTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("provider_setup", ROOT / "tools/provider_setup.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_noninteractive_never_launches(self):
        def forbidden(*args):
            self.fail("unexpected action")
        self.assertEqual(self.module.guide("both", ROOT, run=lambda a: (0, ""),
                         out=lambda s: None, ask=forbidden, launch=forbidden), 0)

    def test_decline_and_eof_do_not_launch(self):
        def forbidden(*args):
            self.fail("unexpected launch")
        answers = iter(["n", "n"])
        self.assertEqual(self.module.guide("both", ROOT, run=lambda a: (0, ""),
                         out=lambda s: None, ask=lambda q: next(answers), interactive=True,
                         launch=forbidden), 0)
        def eof(q):
            raise EOFError
        self.assertEqual(self.module.guide("both", ROOT, run=lambda a: (0, ""),
                         out=lambda s: None, ask=eof, interactive=True, launch=forbidden), 1)

    def test_verified_checkout_rejects_mismatch(self):
        self.assertFalse(self.module.reviewed_checkout(ROOT, "bad"))
        self.assertFalse(self.module.reviewed_checkout(ROOT, "a"*40, lambda a: (0, "wrong")))

    def test_bridge_failure_stops_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = iter(["n", "s", "a"*40, "s"])
            calls = []
            with patch.object(self.module, "reviewed_checkout", return_value=True), patch.object(self.module.os, "getuid", return_value=1000):
                rc = self.module.guide("both", Path(tmp), run=lambda a: (0, ""),
                     out=lambda s: None, ask=lambda q: next(answers), interactive=True,
                     launch=lambda args: calls.append(args) or 7)
            self.assertEqual(rc, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][-1], "a"*40)

    def test_private_setup_delegates_without_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / "local-bridge/.venv/bin/python"
            python.parent.mkdir(parents=True)
            python.touch()
            instance = root / "new-instance"
            answers = iter(["s", str(instance), "s"])
            calls = []
            with patch.object(self.module, "reviewed_checkout", return_value=True):
                result = self.module.private_setup(root, "a"*40, lambda a: (0, ""),
                    lambda s: None, lambda q: next(answers), lambda a: calls.append(a) or 0)
            self.assertEqual(result, 0)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1], calls[0] + ["--prepare-service", "--no-fixture"])

    def test_private_setup_preserves_existing_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = iter(["s", tmp])
            self.assertEqual(self.module.private_setup(ROOT, "a"*40, lambda a: (0, ""),
                lambda s: None, lambda q: next(answers), lambda a: self.fail("unexpected action")), 1)
