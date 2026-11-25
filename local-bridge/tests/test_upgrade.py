import importlib.util
import json
import os
import shutil
import sys
import signal
import time
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
        self.old_sha = "3" * 40
        self.old_wheel = "4" * 64
        self.write_receipt(self.venv, self.old_sha, self.old_wheel)
        self.guard = self.bridge / upgrade.GUARD
        self.guard.mkdir(mode=0o700)
        self.active = self.guard / upgrade.ACTIVE
        self.bound = self.venv / "bin/python"

    def make_venv(self, path, label):
        path.mkdir(mode=0o700)
        (path / "bin").mkdir(mode=0o700)
        (path / "bin/python").touch(mode=0o700)
        (path / "pyvenv.cfg").touch(mode=0o600)
        (path / "identity").write_text(label)

    def write_receipt(self, path, sha, wheel):
        receipt = path / upgrade.RECEIPT
        receipt.touch(mode=0o600)
        receipt.write_text(json.dumps({"sha": sha, "wheel_sha256": wheel}))

    def candidate(self, kit, sha, wheel, active, tx, fds):
        self.assertEqual((sha, wheel), (self.sha, self.wheel))
        self.assertFalse(self.venv.exists())
        self.assertEqual((self.backup / "previous/identity").read_text(), "old")
        self.make_venv(self.venv, "new")
        self.write_receipt(self.venv, sha, wheel)

    def replace(self, run):
        with upgrade.checkout_guard(self.kit) as (guard, fd):
            upgrade.replace(self.kit, self.sha, self.wheel, guard, (fd,),
                            self.bound, self.old_sha, self.old_wheel, run=run)

    def restore(self):
        with upgrade.checkout_guard(self.kit):
            return upgrade.restore(self.venv, self.backup, self.active, self.sha, self.bound)

    def test_success_and_explicit_restore_at_original_path(self):
        self.replace(self.candidate)
        self.assertEqual((self.venv / "identity").read_text(), "new")
        self.assertEqual((self.backup / "previous/identity").read_text(), "old")
        self.assertTrue(self.restore())
        self.assertEqual((self.venv / "identity").read_text(), "old")
        self.assertEqual((self.backup / "candidate/identity").read_text(), "new")

    def test_build_failure_preserves_partial_and_restores(self):
        def fail(*args):
            self.make_venv(self.venv, "partial")
            raise subprocess.CalledProcessError(1, ["fixture"])
        with self.assertRaises(subprocess.CalledProcessError):
            self.replace(fail)
        self.assertEqual((self.venv / "identity").read_text(), "old")
        self.assertEqual((self.backup / "candidate/identity").read_text(), "partial")

    def test_receipt_mismatch_restores(self):
        def wrong(*args):
            self.candidate(*args)
            (self.venv / upgrade.RECEIPT).write_text("{}")
        with self.assertRaises(ValueError):
            self.replace(wrong)
        self.assertEqual((self.venv / "identity").read_text(), "old")

    def test_rollback_conflict_or_symlink_preserves_original(self):
        self.backup.mkdir(mode=0o700)
        run = Mock()
        with self.assertRaises(FileExistsError):
            self.replace(run)
        run.assert_not_called()
        self.backup.rmdir()
        self.venv.rename(self.bridge / "other")
        self.venv.symlink_to(self.bridge / "other")
        with self.assertRaises(ValueError):
            self.replace(run)
        self.assertTrue(self.venv.is_symlink())
        self.assertEqual((self.bridge / "other/identity").read_text(), "old")

    def interrupted(self):
        prior = upgrade.prior_identity(self.venv, self.bound, self.old_sha,
                                       self.old_wheel, False)
        self.backup.mkdir(mode=0o700)
        tx = upgrade.new_transaction(self.venv, self.sha, self.wheel, prior)
        upgrade.save_json(self.active, tx)
        self.venv.rename(self.backup / "previous")

    def test_interrupted_restore_without_candidate(self):
        self.interrupted()
        self.assertTrue(self.restore())
        self.assertEqual((self.venv / "identity").read_text(), "old")

    def test_interrupted_between_restore_renames(self):
        self.interrupted()
        self.make_venv(self.backup / "candidate", "partial")
        self.assertTrue(self.restore())
        self.assertEqual((self.venv / "identity").read_text(), "old")
        self.assertEqual((self.backup / "candidate/identity").read_text(), "partial")

    def test_foreign_backup_and_mismatched_receipt_block(self):
        self.interrupted()
        old = self.backup / "previous"
        (old / upgrade.RECEIPT).write_text(json.dumps(
            {"sha": self.sha, "wheel_sha256": self.wheel}))
        with self.assertRaises(ValueError):
            self.restore()
        self.assertFalse(self.venv.exists())
        self.write_receipt(old, self.old_sha, self.old_wheel)
        old.rename(self.backup / "other")
        self.make_venv(old, "foreign")
        self.write_receipt(old, self.old_sha, self.old_wheel)
        with self.assertRaises(ValueError):
            self.restore()
        self.assertFalse(self.venv.exists())

    def test_legacy_never_infers_same_path_provenance(self):
        (self.venv / upgrade.RECEIPT).unlink()
        for legacy in (False, True):
            with self.assertRaises(ValueError):
                upgrade.prior_identity(self.venv, self.bound, self.old_sha,
                                       self.old_wheel, legacy)
        other = self.kit / "separate/local-bridge/.venv"
        other.parent.mkdir(parents=True, mode=0o700)
        self.make_venv(other, "certified")
        bound = other / "bin/python"
        with patch.object(upgrade, "verify_checkout") as verify:
            prior = upgrade.prior_identity(self.venv, bound, self.old_sha,
                                           self.old_wheel, True)
            verify.assert_called_once_with(other.parents[1], self.old_sha)
            self.assertFalse(prior["eligible"])
            upgrade.validate_prior(prior, self.venv, self.venv, bound)
            with self.assertRaises(ValueError):
                upgrade.validate_prior(prior, self.venv, self.venv, self.bound)
        self.assertFalse((self.venv / upgrade.RECEIPT).exists())

    def test_active_transaction_blocks_new_runtime_start(self):
        from project_os_bridge.maintenance_guard import require_no_installation
        require_no_installation(self.bound)
        self.interrupted()
        with self.assertRaises(RuntimeError):
            require_no_installation(self.bound)
        self.restore()
        require_no_installation(self.bound)

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

class WriterProcessTests(unittest.TestCase):
    def test_parent_and_worker_death_fences_recovery_and_public_install(self):
        with tempfile.TemporaryDirectory() as temp:
            kit = Path(temp)
            scripts = kit / "local-bridge/scripts"
            scripts.mkdir(parents=True)
            source = Path(__file__).resolve().parents[1] / "scripts"
            for name in ("upgrade.py", "install.sh"):
                shutil.copyfile(source / name, scripts / name)
            # A trusted synthetic worker starts a descendant which deliberately
            # closes inherited lock FDs, then waits for a FIFO release byte.
            # This tests both flock inheritance and the persistent group fence.
            (scripts / "install-build.sh").write_text(
                'set -eu\npython3 -c \'import os, pathlib; '
                'os.closerange(3, 1024); '
                'p=pathlib.Path("ready"); p.write_text(str(os.getpid())); '
                'f=open("release","rb"); f.read(1); '
                'pathlib.Path("done").touch()\' &\nwait\n')
            (kit / ".gitignore").write_text(".venv-install.*/\nready\nrelease\ndone\n")
            def git(*args):
                return subprocess.check_output(["git", "-C", str(kit), *args], text=True).strip()
            git("init", "-q")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "user.name", "fixture")
            git("remote", "add", "origin", upgrade.ORIGIN)
            git("add", ".")
            git("commit", "-qm", "fixture")
            sha = git("rev-parse", "HEAD")
            os.mkfifo(kit / "release", 0o600)
            # Keep a reader/writer open so release never blocks the test.
            release = os.open(kit / "release", os.O_RDWR | os.O_NONBLOCK)
            host = Path(sys._base_executable).parent
            env = {**os.environ, "PATH": str(host) + ":/usr/bin:/bin"}
            cmd = ["/bin/bash", str(scripts / "install.sh"), sha]
            parent = subprocess.Popen(cmd, cwd=kit, env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            group = None
            try:
                deadline = time.monotonic() + 10
                while not (kit / "ready").exists():
                    if parent.poll() is not None or time.monotonic() >= deadline:
                        self.fail("Synthetic installer did not reach barrier")
                    time.sleep(0.01)
                active = kit / "local-bridge" / upgrade.GUARD / upgrade.ACTIVE
                tx = upgrade.read_json(active)
                group = tx["group"]
                self.assertTrue(upgrade.group_busy(group, tx["boot"]))
                # Real public entrypoint must reject while the first writer holds lock.
                other = subprocess.run(cmd, cwd=kit, env=env, capture_output=True, timeout=10)
                self.assertNotEqual(other.returncode, 0)
                parent.kill()
                parent.wait(timeout=5)
                with self.assertRaises(BlockingIOError):
                    with upgrade.checkout_guard(kit):
                        self.fail("Parent death released writer lock")
                # Kill session leader too; the descendant has closed lock FDs.
                os.kill(group, signal.SIGKILL)
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with upgrade.checkout_guard(kit):
                            break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            self.fail("Writer lock not released after worker death")
                        time.sleep(0.01)
                with self.assertRaises(RuntimeError):
                    upgrade.no_writers(upgrade.read_json(active))
                other = subprocess.run(cmd, cwd=kit, env=env, capture_output=True, timeout=10)
                self.assertNotEqual(other.returncode, 0)
                self.assertTrue(active.exists())
                self.assertFalse((kit / "done").exists())
                os.write(release, b"Y")
                deadline = time.monotonic() + 5
                while not (kit / "done").exists():
                    if time.monotonic() >= deadline:
                        self.fail("Surviving writer did not finish")
                    time.sleep(0.01)
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait(timeout=5)
                if group is not None:
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                os.close(release)
