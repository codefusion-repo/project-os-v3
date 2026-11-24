import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

script=Path(__file__).resolve().parents[1]/"scripts"/"lock_wheels.py"
spec=importlib.util.spec_from_file_location("lock_wheels",script)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WheelLockTests(unittest.TestCase):
    def test_hashes_bytes_and_rejects_incomplete_set(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            pins=root/"pins"
            pins.write_text("example-package==1.2\n")
            with self.assertRaises(ValueError):
                module.generate(pins,root)
            wheel=root/"example_package-1.2-py3-none-any.whl"
            with zipfile.ZipFile(wheel,"w") as z:
                z.writestr("example_package-1.2.dist-info/METADATA","Name: example-package\nVersion: 1.2\n")
            digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
            self.assertEqual(module.generate(pins,root),f"example-package==1.2 --hash=sha256:{digest}\n")
            pins.write_text("example-package==1.3\n")
            with self.assertRaises(ValueError):
                module.generate(pins,root)

    def test_ignore_vendored_metadata_but_reject_two_top_level_records(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            pins=root/"pins"
            pins.write_text("example-package==1.2\n")
            wheel=root/"example_package-1.2-py3-none-any.whl"
            with zipfile.ZipFile(wheel,"w") as z:
                z.writestr("example_package-1.2.dist-info/METADATA","Name: example-package\nVersion: 1.2\n")
                z.writestr("example/_vendor/other-1.dist-info/METADATA","Name: other\nVersion: 1\n")
            self.assertIn("example-package==1.2 --hash=sha256:",module.generate(pins,root))
            with zipfile.ZipFile(wheel,"a") as z:
                z.writestr("other-1.dist-info/METADATA","Name: other\nVersion: 1\n")
            with self.assertRaises(ValueError):
                module.generate(pins,root)
