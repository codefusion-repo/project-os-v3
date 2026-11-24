import tempfile
import unittest
from pathlib import Path
from project_os_bridge.core import Policy
from project_os_bridge.repository import FixtureRepository
from project_os_bridge.execution import validate_fixture


class ValidationTests(unittest.TestCase):
    def test_fixed_validation(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root).resolve()
            path=root/"fixture.txt"
            path.touch(mode=0o600)
            path.write_text("safe data")
            repo=FixtureRepository(root,Policy(("local",op,"disposable") for op in ("fixture_read","fixture_write","fixture_validate")))
            revision=repo.read("local")["revision"]
            self.assertTrue(validate_fixture(repo,"local",revision)["passed"])
            self.assertEqual(validate_fixture(repo,"local","0"*64)["status"],"BLOCKED")
            with self.assertRaises(PermissionError):
                validate_fixture(repo,"other",revision)
            new=repo.replace("local",revision," ")
            self.assertEqual(validate_fixture(repo,"local",new["revision"])["status"],"FAILED")
