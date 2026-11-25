import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("bootstrap_verify", Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_verify.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.wheel = self.root / "pip-26.3-py3-none-any.whl"
        self.lock = self.root / "requirements-bootstrap.lock"

    def fixture(self, extra=None):
        with zipfile.ZipFile(self.wheel, "w") as z:
            z.writestr("pip/_vendor/pkg_resources/__init__.py", "synthetic")
            z.writestr("pip/_vendor/pkg_resources/LICENSE", "synthetic")
            z.writestr("pip/_vendor/vendor.txt", "setuptools==70.3.0")
            if extra:
                z.writestr(extra, "synthetic")
        self.lock.write_text("pip==26.3 --hash=sha256:" + hashlib.sha256(self.wheel.read_bytes()).hexdigest() + "\n")

    def test_verified_layout(self):
        self.fixture()
        self.assertEqual(module.verify(self.wheel, self.lock), ["pip/_vendor/pkg_resources/LICENSE", "pip/_vendor/pkg_resources/__init__.py"])

    def test_changed_bytes_rejected_before_zip_parsing(self):
        self.fixture()
        self.wheel.write_bytes(b"not a wheel")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            module.verify(self.wheel, self.lock)

    def test_affected_code_rejected_even_with_matching_hash(self):
        for path in ("pip/_vendor/setuptools/package_index.py", "pip/_vendor/setuptools/command/sdist.py",
                     "pip/_vendor/setuptools/wheel.py", "pip/_vendor/pkg_resources/package_index.py"):
            with self.subTest(path=path):
                self.fixture(path)
                with self.assertRaisesRegex(ValueError, "Unexpected setuptools implementation"):
                    module.verify(self.wheel, self.lock)

    def test_extra_retained_code_rejected(self):
        self.fixture("pip/_vendor/pkg_resources/other.py")
        with self.assertRaisesRegex(ValueError, "Unexpected retained setuptools files"):
            module.verify(self.wheel, self.lock)
