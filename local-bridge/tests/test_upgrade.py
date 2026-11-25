import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from project_os_bridge.service_setup import render_unit

spec = importlib.util.spec_from_file_location(
    "upgrade", Path(__file__).resolve().parents[1] / "scripts/upgrade.py")
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.kit = Path(temp.name)
        self.bridge = self.kit / "local-bridge"
        self.bridge.mkdir(mode=0o700)
        self.venv = self.bridge / ".venv"
        self.backup = self.bridge / upgrade.BACKUP
        self.sha = "1" * 40
        self.wheel = "2" * 64
        self.make_venv(self.venv, "old")

    def make_venv(self, path, label):
        path.mkdir(mode=0o700)
        (path / "bin").mkdir(mode=0o700)
        (path / "bin/python").touch(mode=0o600)
        (path / "pyvenv.cfg").touch(mode=0o600)
        (path / "identity").write_text(label)

    def candidate(self, args, check):
        self.assertEqual(args[-2:], [self.sha, self.wheel])
        self.assertTrue(check)
        self.assertFalse(self.venv.exists())
        self.assertEqual((self.backup / "previous/identity").read_text(), "old")
        self.make_venv(self.venv, "new")
        path = self.venv / upgrade.RECEIPT
        path.touch(mode=0o600)
        path.write_text(json.dumps({"sha": self.sha, "wheel_sha256": self.wheel}))

    def test_success_and_explicit_restore_at_original_path(self):
        upgrade.replace(self.kit, self.sha, self.wheel, self.candidate)
        self.assertEqual((self.venv / "identity").read_text(), "new")
        self.assertEqual((self.backup / "previous/identity").read_text(), "old")
        upgrade.restore(self.venv, self.backup)
        self.assertEqual((self.venv / "identity").read_text(), "old")
        self.assertEqual((self.backup / "candidate/identity").read_text(), "new")

    def test_build_failure_preserves_partial_and_restores(self):
        def fail(args, check):
            self.make_venv(self.venv, "partial")
            raise subprocess.CalledProcessError(1, args)
        with self.assertRaises(subprocess.CalledProcessError):
            upgrade.replace(self.kit, self.sha, self.wheel, fail)
        self.assertEqual((self.venv / "identity").read_text(), "old")
        self.assertEqual((self.backup / "candidate/identity").read_text(), "partial")

    def test_receipt_mismatch_restores(self):
        def wrong(args, check):
            self.candidate(args, check)
            (self.venv / upgrade.RECEIPT).write_text("{}")
        with self.assertRaises(ValueError):
            upgrade.replace(self.kit, self.sha, self.wheel, wrong)
        self.assertEqual((self.venv / "identity").read_text(), "old")

    def test_rollback_conflict_or_symlink_preserves_original(self):
        self.backup.mkdir(mode=0o700)
        run = Mock()
        with self.assertRaises(FileExistsError):
            upgrade.replace(self.kit, self.sha, self.wheel, run)
        run.assert_not_called()
        self.backup.rmdir()
        self.venv.rename(self.bridge / "other")
        self.venv.symlink_to(self.bridge / "other")
        with self.assertRaises(ValueError):
            upgrade.replace(self.kit, self.sha, self.wheel, run)
        self.assertTrue(self.venv.is_symlink())
        self.assertEqual((self.bridge / "other/identity").read_text(), "old")

    def test_interrupted_restore_without_candidate(self):
        self.backup.mkdir(mode=0o700)
        self.venv.rename(self.backup / "previous")
        upgrade.restore(self.venv, self.backup)
        self.assertEqual((self.venv / "identity").read_text(), "old")

    def test_exact_unit_and_quiescence(self):
        root = self.kit / "instance"
        root.mkdir(mode=0o700)
        service = root / "service"
        service.mkdir(mode=0o700)
        unit = service / upgrade.UNIT
        unit.touch(mode=0o600)
        python = self.venv / "bin/python"
        self.assertEqual(upgrade.unit_text(root, python), render_unit(root, python))
        unit.write_text(render_unit(root, python))
        fields = dict(Id=upgrade.UNIT, LoadState="loaded", FragmentPath=str(unit),
                      DropInPaths="", NeedDaemonReload="no", ActiveState="inactive",
                      UnitFileState="linked", Job="", MainPID="0", ControlPID="0")
        def response(**changes):
            return SimpleNamespace(returncode=0, stdout="\n".join(
                f"{k}={v}" for k, v in (fields | changes).items()))
        upgrade.check_unit(root, python, Mock(return_value=response()))
        for changes in ({"ActiveState": "active"}, {"UnitFileState": "enabled"},
                        {"Job": "42"}, {"MainPID": "42"}, {"ControlPID": "42"},
                        {"DropInPaths": "/tmp/other"}, {"NeedDaemonReload": "yes"}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                upgrade.check_unit(root, python, Mock(return_value=response(**changes)))
        unit.write_text("foreign")
        with self.assertRaises(PermissionError):
            upgrade.check_unit(root, python, Mock())

    def test_all_jobs_and_effects_are_checked_read_only(self):
        db = self.kit / "jobs.sqlite3"
        db.touch(mode=0o600)
        with sqlite3.connect(db) as conn:
            conn.executescript("CREATE TABLE jobs(state TEXT);"
                               "CREATE TABLE fixture_effects(resolved_at TEXT);"
                               "INSERT INTO jobs VALUES('SUCCEEDED');")
        before = db.read_bytes()
        upgrade.check_jobs(self.kit)
        self.assertEqual(before, db.read_bytes())
        for state in ("RUNNING", "QUEUED", "unexpected", None):
            with sqlite3.connect(db) as conn:
                conn.execute("INSERT INTO jobs VALUES(?)", (state,))
            with self.assertRaises(RuntimeError):
                upgrade.check_jobs(self.kit)
            with sqlite3.connect(db) as conn:
                conn.execute("DELETE FROM jobs WHERE state IS NOT 'SUCCEEDED'")
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO fixture_effects VALUES(NULL)")
        with self.assertRaises(RuntimeError):
            upgrade.check_jobs(self.kit)

    def test_lock_contention(self):
        path = self.kit / "maintenance.lock"
        with upgrade.lock(path):
            with self.assertRaises(BlockingIOError):
                with upgrade.lock(path):
                    self.fail("Concurrent maintenance admitted")
