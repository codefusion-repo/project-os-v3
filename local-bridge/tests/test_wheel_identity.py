import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("wheel_identity", Path(__file__).resolve().parents[1] / "scripts" / "wheel_identity.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WheelIdentityTests(unittest.TestCase):
    def test_identical_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d)/"a", Path(d)/"b"
            a.mkdir()
            b.mkdir()
            for p in (a,b):
                (p/"project.whl").write_bytes(b"wheel")
            self.assertEqual(module.compare(a,b), ("project.whl", hashlib.sha256(b"wheel").hexdigest()))
            (b/"project.whl").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                module.compare(a,b)
            with self.assertRaisesRegex(ValueError, "Independent"):
                module.compare(a,a)

    def test_missing_or_extra_wheel_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            with self.assertRaises(ValueError):
                module.identity(p)
            (p/"one.whl").write_bytes(b"one")
            (p/"two.whl").write_bytes(b"two")
            with self.assertRaises(ValueError):
                module.identity(p)
