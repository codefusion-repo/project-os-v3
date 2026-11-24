import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from project_os_bridge.probe import MARKER, Probe


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.flag = self.root / "allow-probe-write"
        self.probe = Probe(self.root)

    def enable(self):
        self.flag.touch(mode=0o600)

    def test_default_deny(self):
        self.assertEqual(self.probe.write()["status"], "BLOCKED")
        self.assertFalse(self.probe.read()["present"])

    def test_persistence_and_replay(self):
        self.enable()
        self.assertTrue(self.probe.write()["created"])
        self.assertFalse(Probe(self.root).write()["created"])
        self.assertEqual(Probe(self.root).read(), {"present": True, "marker": MARKER})

    def test_revocation(self):
        self.enable()
        self.probe.write()
        self.flag.unlink()
        self.assertEqual(self.probe.write()["status"], "BLOCKED")
        self.assertTrue(self.probe.read()["present"])

    def test_concurrent_replay(self):
        self.enable()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.probe.write(), range(8)))
        self.assertEqual(sum(r["created"] for r in results), 1)

    def test_symlink_flag_denied(self):
        target = self.root / "target"
        target.touch(mode=0o600)
        self.flag.symlink_to(target)
        self.assertEqual(self.probe.write()["status"], "BLOCKED")

    def test_insecure_state_dir_denied(self):
        self.root.chmod(0o755)
        with self.assertRaises(PermissionError):
            Probe(self.root)

    def test_symlink_database_denied(self):
        other = self.root / "other"
        other.mkdir(mode=0o700)
        (other / "probe.sqlite3").symlink_to(self.probe.db)
        with self.assertRaises(PermissionError):
            Probe(other)

    def test_insecure_flag_denied(self):
        self.enable()
        self.flag.chmod(0o644)
        self.assertEqual(self.probe.write()["status"], "BLOCKED")
