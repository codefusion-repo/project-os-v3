import tempfile
import unittest
from pathlib import Path
from project_os_bridge.core import Policy
from project_os_bridge.repository import FixtureRepository


class FixtureTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name).resolve()
        self.path=self.root/"fixture.txt"
        self.path.touch(mode=0o600)
        self.path.write_text("before")
        self.repo=FixtureRepository(self.root,Policy(("local",op,"disposable") for op in ("fixture_read","fixture_write")))

    def test_guarded_change(self):
        old=self.repo.read("local")
        result=self.repo.replace("local",old["revision"],"after")
        self.assertEqual(self.repo.read("local"),{"text":"after","revision":result["revision"]})
        with self.assertRaises(ValueError):
            self.repo.replace("local",old["revision"],"stale")
        self.assertEqual(self.path.read_text(),"after")

    def test_denial(self):
        with self.assertRaises(PermissionError):
            self.repo.read("other")
        with self.assertRaises(PermissionError):
            self.repo.replace("other","0"*64,"bad")

    def test_symlink(self):
        target=self.root/"target"
        target.write_text("safe")
        self.path.unlink()
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            self.repo.read("local")
        self.assertEqual(target.read_text(),"safe")
