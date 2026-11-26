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


    def relocate(self, sha, *, unarchive=False, root=None):
        with upgrade.checkout_guard(self.kit) as (guard, fd):
            upgrade.relocate_backup(self.kit, guard, sha, self.bound, root,
                                    unarchive=unarchive)

    def test_consecutive_offline_upgrades_and_reverse_rollback(self):
        self.replace(self.candidate)
        archive = self.bridge / (upgrade.ARCHIVE_PREFIX + self.sha)
        before = (self.backup / upgrade.TRANSACTION).read_bytes()
        self.relocate(self.sha)
        self.relocate(self.sha)  # idempotent, no new copy
        self.assertEqual((archive / upgrade.TRANSACTION).read_bytes(), before)
        self.assertFalse(self.backup.exists())
        with self.assertRaises(RuntimeError):
            upgrade.check_release(self.kit, self.sha, self.guard, self.bound)

        next_sha, next_wheel = "5" * 40, "6" * 64
        def build(kit, sha, wheel, active, tx, fds):
            self.make_venv(self.venv, "next")
            self.write_receipt(self.venv, sha, wheel)
        with upgrade.checkout_guard(self.kit) as (guard, fd):
            upgrade.replace(self.kit, next_sha, next_wheel, guard, (fd,),
                            self.bound, self.sha, self.wheel, run=build)
        self.assertTrue(archive.is_dir())
        upgrade.check_release(self.kit, next_sha, self.guard, self.bound)
        with self.assertRaises(RuntimeError):
            self.relocate(self.sha, unarchive=True)
        with upgrade.checkout_guard(self.kit):
            self.assertTrue(upgrade.restore(self.venv, self.backup, self.active,
                                            next_sha, self.bound))
        self.assertEqual((self.venv / "identity").read_text(), "new")
        self.relocate(next_sha)
        self.relocate(self.sha, unarchive=True)
        self.relocate(self.sha, unarchive=True)
        self.assertEqual((self.backup / upgrade.TRANSACTION).read_bytes(), before)
        self.assertTrue(self.restore())
        self.assertEqual((self.venv / "identity").read_text(), "old")
        self.assertTrue((self.bridge / (upgrade.ARCHIVE_PREFIX + next_sha)).is_dir())

    def test_archive_refuses_active_writer_conflict_and_identity_change(self):
        self.replace(self.candidate)
        archive = self.bridge / (upgrade.ARCHIVE_PREFIX + self.sha)
        upgrade.save_json(self.active, {})
        with self.assertRaises(RuntimeError):
            self.relocate(self.sha)
        self.active.unlink()
        with patch.object(upgrade, "group_busy", return_value=True):
            with self.assertRaises(RuntimeError):
                self.relocate(self.sha)
        archive.mkdir(mode=0o700)
        with self.assertRaises(RuntimeError):
            self.relocate(self.sha)
        archive.rmdir()
        self.write_receipt(self.backup / "previous", self.sha, self.wheel)
        with self.assertRaises(ValueError):
            self.relocate(self.sha)
        self.assertTrue(self.backup.is_dir())
        self.assertFalse(archive.exists())

    def test_upgrade_rejects_unknown_changed_or_disconnected_archive(self):
        self.replace(self.candidate)
        self.relocate(self.sha)
        archive = self.bridge / (upgrade.ARCHIVE_PREFIX + self.sha)
        next_sha, next_wheel = "5" * 40, "6" * 64
        run = Mock()
        def attempt(sha=next_sha):
            with upgrade.checkout_guard(self.kit) as (guard, fd):
                upgrade.replace(self.kit, sha, next_wheel, guard, (fd,),
                                self.bound, self.sha, self.wheel, run=run)
        foreign = self.bridge / (upgrade.ARCHIVE_PREFIX + "unknown")
        foreign.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            attempt()
        foreign.rmdir()
        with self.assertRaises(ValueError):
            attempt(self.sha)
        tx = upgrade.read_json(archive / upgrade.TRANSACTION)
        changed = dict(tx, candidate_identity={**tx["candidate_identity"], "ino": -1})
        upgrade.save_json(archive / upgrade.TRANSACTION, changed)
        with self.assertRaises(RuntimeError):
            attempt()
        upgrade.save_json(archive / upgrade.TRANSACTION, tx)
        with patch.object(upgrade, "group_busy", return_value=True):
            with self.assertRaises(RuntimeError):
                attempt()
        self.write_receipt(archive / "previous", self.sha, self.wheel)
        with self.assertRaises(ValueError):
            attempt()
        run.assert_not_called()
        self.assertFalse(self.active.exists())
        self.assertFalse(self.backup.exists())
        self.assertEqual((self.venv / "identity").read_text(), "new")

    def test_public_cli_recovers_chain_without_changing_maintenance_checkout(self):
        # Real CLI parser, Git identity, SQLite and filesystem/locks. Mock only
        # host service manager, host-Python selection and package building.
        def git(*args):
            return upgrade.git(self.kit, *args)
        git("init", "-q")
        git("config", "user.email", "fixture@example.invalid")
        git("config", "user.name", "fixture")
        git("remote", "add", "origin", upgrade.ORIGIN)
        (self.kit / ".gitignore").write_text(".venv/\n.venv-install.*/\n")
        (self.kit / "tracked").write_text("first")
        git("add", ".")
        git("commit", "-qm", "first")
        self.sha = git("rev-parse", "HEAD")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name in ("service", "state"):
            (root / name).mkdir(mode=0o700)
        db = root / "state/jobs.sqlite3"
        db.touch(mode=0o600)
        with sqlite3.connect(db) as conn:
            conn.executescript("CREATE TABLE jobs(state TEXT);"
                               "CREATE TABLE fixture_effects(resolved_at TEXT);")
        unit = root / "service" / upgrade.UNIT
        unit.touch(mode=0o600)
        unit.write_text(upgrade.unit_text(root, self.bound))
        loaded = False
        def manager(*args, **kwargs):
            nonlocal loaded
            fenced = unit.read_text() == upgrade.fenced_unit_text(root, self.bound)
            if args == ("daemon-reload",):
                loaded = fenced
                return SimpleNamespace(returncode=0, stdout="")
            self.assertEqual(args[0], "show")
            fields = dict(Id=upgrade.UNIT, LoadState="loaded", FragmentPath=str(unit),
                          DropInPaths="", NeedDaemonReload="no" if loaded == fenced else "yes",
                          ActiveState="inactive", UnitFileState="linked", Job="", MainPID="0",
                          ControlPID="0", RefuseManualStart="yes" if loaded else "no")
            return SimpleNamespace(returncode=0, stdout="\n".join(
                f"{key}={value}" for key, value in fields.items()))
        real_lock = upgrade.lock
        def local_lock(path):
            return real_lock(root / "service/lifecycle.lock" if path.name ==
                             "project-os-bridge-lifecycle.lock" else path)
        def build(kit, sha, wheel, active, tx, fds):
            self.make_venv(self.venv, sha)
            self.write_receipt(self.venv, sha, wheel)
        def cli(action, *args):
            head = git("rev-parse", "HEAD")
            with patch.object(upgrade.sys, "argv",
                              ["upgrade.py", action, head, "--root", str(root),
                               "--bound-python", str(self.bound), *args]):
                upgrade.main()
        with patch.object(upgrade, "__file__", str(self.bridge / "scripts/upgrade.py")), \
             patch.object(upgrade.sys, "prefix", sys.base_prefix), \
             patch.object(upgrade, "systemctl", side_effect=manager), \
             patch.object(upgrade, "lock", side_effect=local_lock), \
             patch.object(upgrade, "build_runner", return_value=build):
            cli("fence")
            cli("upgrade", "--expected-wheel", self.wheel, "--previous-sha",
                self.old_sha, "--previous-wheel", self.old_wheel)
            (self.kit / "tracked").write_text("second")
            git("commit", "-qam", "second")
            next_sha, next_wheel = git("rev-parse", "HEAD"), "6" * 64
            cli("archive", "--rollback-sha", self.sha)
            with self.assertRaises(SystemExit):
                cli("release")
            cli("upgrade", "--expected-wheel", next_wheel, "--previous-sha",
                self.sha, "--previous-wheel", self.wheel)
            cli("restore")
            cli("archive", "--rollback-sha", next_sha)
            cli("unarchive", "--rollback-sha", self.sha)
            cli("restore", "--rollback-sha", self.sha)
            cli("release", "--rollback-sha", self.sha)
            self.assertEqual(git("rev-parse", "HEAD"), next_sha)
            self.assertEqual((self.venv / "identity").read_text(), "old")
            self.assertFalse(loaded)

    def test_archive_rename_interruption_reconciles_same_directory(self):
        self.replace(self.candidate)
        archive = self.bridge / (upgrade.ARCHIVE_PREFIX + self.sha)
        with patch.object(upgrade, "sync_directory", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                self.relocate(self.sha)
        self.assertFalse(self.backup.exists())
        self.assertTrue(archive.is_dir())
        self.relocate(self.sha)
        self.relocate(self.sha, unarchive=True)
        self.assertTrue(self.restore())

    def test_multirepo_profile_restored_with_venv_and_grants_archived(self):
        from project_os_bridge.project_enrollment import next_runtime, record_migration
        root = self.kit / "instance"
        root.mkdir(mode=0o700)
        (root / "service").mkdir(mode=0o700)
        runtime = root / "service/runtime.json"
        locator = str(self.kit / "project/.project-os/config.json")
        original = {"tunnel": "fixture", "tunnel_id": "fixture", "image": None,
                    "project_config": locator}
        binding = ("demo", "example/demo", 123)
        upgrade.save_json(runtime, original)
        with upgrade.checkout_guard(self.kit) as (guard, fd):
            upgrade.replace(self.kit, self.sha, self.wheel, guard, (fd,),
                            self.bound, self.old_sha, self.old_wheel, run=self.candidate, root=root)
        record_migration(root, original, binding, self.backup,
                         {"sha": self.sha, "wheel_sha256": self.wheel})
        migrated, _ = next_runtime(original, config=Path(locator), binding=binding)
        multi, _ = next_runtime(migrated, config=Path("/fixture/other/.project-os/config.json"),
                                binding=("other", "example/other", 456))
        upgrade.save_json(runtime, multi)
        with patch.object(upgrade, "legacy_binding_current", return_value=True):
            migration = (self.backup / upgrade.PROFILE_MIGRATION).read_bytes()
            self.relocate(self.sha, root=root)
            self.assertEqual(upgrade.profile_json(runtime), multi)
            self.relocate(self.sha, unarchive=True, root=root)
            self.assertEqual((self.backup / upgrade.PROFILE_MIGRATION).read_bytes(), migration)
            self.assertFalse((self.backup / upgrade.PROFILE_RESTORE).exists())
            with upgrade.checkout_guard(self.kit):
                self.assertTrue(upgrade.restore(self.venv, self.backup, self.active,
                                                self.sha, self.bound, root))
            self.assertEqual(upgrade.profile_json(runtime), original)
            self.assertEqual((self.venv / "identity").read_text(), "old")
            saved = upgrade.profile_json(self.backup / upgrade.PROFILE_RESTORE)
            self.assertEqual(saved["source"], multi)
            self.assertEqual(saved["target"], original)
            upgrade.check_release(self.kit, self.sha, self.guard, self.bound, root)

    def test_profile_restore_replay_and_no_revoked_legacy_grant(self):
        from project_os_bridge.project_enrollment import next_runtime
        root = self.kit / "instance"
        root.mkdir(mode=0o700)
        (root / "service").mkdir(mode=0o700)
        runtime = root / "service/runtime.json"
        self.backup.mkdir(mode=0o700)
        locator = str(self.kit / "project/.project-os/config.json")
        original = {"tunnel": "fixture", "tunnel_id": "fixture", "image": None,
                    "project_config": locator}
        binding = ("demo", "example/demo", 123)
        tx = {"sha": self.sha, "root": str(root)}
        upgrade.save_json(self.backup / upgrade.PROFILE_MIGRATION,
                          {"format": 1, "sha": self.sha, "root": str(root),
                           "before": original, "binding": list(binding)})
        migrated, _ = next_runtime(original, config=Path(locator), binding=binding)
        multi, _ = next_runtime(migrated, revoke="demo")
        upgrade.save_json(runtime, multi)
        real_save = upgrade.save_json
        def interrupted(path, data):
            if path == runtime:
                raise OSError("fixture interruption")
            real_save(path, data)
        with patch.object(upgrade, "save_json", side_effect=interrupted):
            with self.assertRaises(OSError):
                upgrade.restore_profile(root, self.backup, tx)
        self.assertEqual(upgrade.profile_json(runtime), multi)
        self.assertTrue((self.backup / upgrade.PROFILE_RESTORE).is_file())
        with patch.object(upgrade, "legacy_binding_current") as verify:
            upgrade.restore_profile(root, self.backup, tx)
            upgrade.restore_profile(root, self.backup, tx)
            verify.assert_not_called()
        target = upgrade.profile_json(runtime)
        self.assertNotIn("github_projects", target)
        self.assertNotIn("project_config", target)
        self.assertEqual(upgrade.profile_json(self.backup / upgrade.PROFILE_RESTORE)["source"], multi)
        upgrade.save_json(runtime, {**target, "tunnel": "changed"})
        with self.assertRaises(RuntimeError):
            upgrade.restore_profile(root, self.backup, tx)
        self.assertEqual(upgrade.profile_json(runtime)["tunnel"], "changed")

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

    def test_interpreter_symlink_swap_blocks_restore(self):
        executable = self.venv / "bin/python"
        executable.rename(executable.with_name("python3"))
        executable.symlink_to("python3")
        self.interrupted()
        old = self.backup / "previous"
        self.assertEqual(upgrade.identity(old), upgrade.read_json(self.active)["prior"]["identity"])
        link = old / "bin/python"
        link.unlink()
        alternative = link.with_name("other")
        alternative.write_bytes(b"other interpreter")
        alternative.chmod(0o700)
        link.symlink_to("other")
        with self.assertRaises(ValueError):
            self.restore()
        self.assertFalse(self.venv.exists())

    def test_interpreter_bytes_changed_blocks_restore(self):
        self.interrupted()
        (self.backup / "previous/bin/python").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.restore()
        self.assertFalse(self.venv.exists())

    def test_legacy_fallback_interpreter_change_blocks_restore(self):
        (self.venv / upgrade.RECEIPT).unlink()
        other = self.kit / "separate/local-bridge/.venv"
        other.parent.mkdir(parents=True, mode=0o700)
        self.make_venv(other, "certified")
        bound = other / "bin/python"
        with patch.object(upgrade, "verify_checkout"):
            prior = upgrade.prior_identity(self.venv, bound, self.old_sha, self.old_wheel, True)
            self.backup.mkdir(mode=0o700)
            tx = upgrade.new_transaction(self.venv, self.sha, self.wheel, prior)
            upgrade.save_json(self.active, tx)
            self.venv.rename(self.backup / "previous")
            bound.write_bytes(b"changed fallback")
            with self.assertRaises(ValueError):
                upgrade.restore(self.venv, self.backup, self.active, self.sha, bound)
        self.assertFalse(self.venv.exists())

    def test_host_interpreter_link_identity_survives_relocation(self):
        # Use a trusted system executable as a byte-identity fixture, not
        # the CI toolcache interpreter (its ancestors may be group writable).
        # The identity check never executes this file.
        path = self.venv / "bin/python"
        path.unlink()
        path.symlink_to(Path("/usr/bin/false").resolve(strict=True))
        self.interrupted()
        self.assertTrue(self.restore())

    def test_host_preflight_uses_same_strict_parent_policy(self):
        host = self.trusted_host_fixture()
        launcher = host / "python3"
        launcher.symlink_to(Path("/usr/bin/false").resolve(strict=True))
        upgrade.host_interpreter_identity(launcher)
        host.chmod(0o777)
        with self.assertRaisesRegex(PermissionError, "Unsafe host interpreter parent"):
            upgrade.host_interpreter_identity(launcher)
        self.assertFalse(self.active.exists())
        self.assertFalse(self.backup.exists())

    def test_untrusted_host_interpreter_parent_blocks_before_rename(self):
        path = self.venv / "bin/python"
        path.unlink()
        host = self.trusted_host_fixture()
        target = host / "python"
        target.write_bytes(b"fixture")
        target.chmod(0o700)
        path.symlink_to(target)
        upgrade.identity(self.venv)
        host.chmod(0o777)
        with self.assertRaises(PermissionError):
            self.interrupted()
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.active.exists())
        self.assertTrue(self.venv.exists())

    def trusted_host_fixture(self):
        # Use real permissions under a trusted home rather than masking /tmp
        # with a mock. A writable host ancestor must fail the positive control.
        temp = tempfile.TemporaryDirectory(dir=Path.home())
        self.addCleanup(temp.cleanup)
        return Path(temp.name)

    def directory_alias(self):
        shared = self.trusted_host_fixture()
        (shared / "bin").symlink_to("target", target_is_directory=True)
        (shared / "target").symlink_to("/usr/bin", target_is_directory=True)
        return shared, shared / "bin/false"

    def test_lexical_host_parents_and_every_directory_link(self):
        shared, launcher = self.directory_alias()
        observed = upgrade.host_interpreter_identity(launcher)
        self.assertEqual(observed["resolved"], "host:" + str(Path("/usr/bin/false").resolve()))
        self.assertEqual([entry["path"] for entry in observed["links"]][:2],
                         ["host:" + str(shared / "bin"), "host:" + str(shared / "target")])
        shared.chmod(0o777)
        with self.assertRaisesRegex(PermissionError, "Unsafe host interpreter parent"):
            upgrade.host_interpreter_identity(launcher)
        self.assertFalse(self.active.exists())
        self.assertFalse(self.backup.exists())

    def test_directory_alias_cannot_hide_unsafe_destination(self):
        shared, launcher = self.directory_alias()
        destination = self.trusted_host_fixture()
        (destination / "false").symlink_to("/usr/bin/false")
        (shared / "target").unlink()
        (shared / "target").symlink_to(destination, target_is_directory=True)
        upgrade.host_interpreter_identity(launcher)
        destination.chmod(0o777)
        with self.assertRaisesRegex(PermissionError, "Unsafe host interpreter parent"):
            upgrade.host_interpreter_identity(launcher)

    def test_directory_alias_cycle_rejected(self):
        shared, launcher = self.directory_alias()
        (shared / "target").unlink()
        (shared / "target").symlink_to("bin", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Interpreter link cycle"):
            upgrade.host_interpreter_identity(launcher)

    def test_file_link_preserves_directory_requirements(self):
        root = self.trusted_host_fixture()
        launcher = root / "python"
        for target in ("/usr/bin/false/", "/usr/bin/false/.", "/usr/bin/../bin/false"):
            with self.subTest(target=target):
                launcher.symlink_to(target)
                with self.assertRaisesRegex(ValueError, "Unsupported interpreter link traversal"):
                    upgrade.host_interpreter_identity(launcher)
                launcher.unlink()

    def test_directory_and_file_link_budget(self):
        root = self.trusted_host_fixture()
        for i in range(17):
            (root / str(i)).symlink_to(str(i + 1) if i < 16 else "/usr/bin")
        with self.assertRaisesRegex(ValueError, "Interpreter link limit exceeded"):
            upgrade.host_interpreter_identity(root / "0/false")

    def test_unsafe_venv_ancestor_rejected_before_backup(self):
        self.kit.chmod(0o777)
        with self.assertRaisesRegex(PermissionError, "Unsafe host interpreter parent"):
            self.interrupted()
        self.assertFalse(self.active.exists())
        self.assertFalse(self.backup.exists())
        self.assertTrue(self.venv.exists())

    def test_hidden_writable_ancestor_blocks_backup_restore(self):
        shared, launcher = self.directory_alias()
        self.bound.unlink()
        self.bound.symlink_to(launcher)
        self.interrupted()
        shared.chmod(0o777)
        with self.assertRaisesRegex(PermissionError, "Unsafe host interpreter parent"):
            self.restore()
        self.assertFalse(self.venv.exists())
        self.assertTrue((self.backup / "previous").is_dir())
        self.assertTrue(self.active.exists())

    def test_hidden_writable_ancestor_blocks_legacy_fallback(self):
        shared, launcher = self.directory_alias()
        (self.venv / upgrade.RECEIPT).unlink()
        other = self.kit / "separate/local-bridge/.venv"
        other.parent.mkdir(parents=True, mode=0o700)
        self.make_venv(other, "certified")
        bound = other / "bin/python"
        bound.unlink()
        bound.symlink_to(launcher)
        with patch.object(upgrade, "verify_checkout"):
            prior = upgrade.prior_identity(self.venv, bound, self.old_sha, self.old_wheel, True)
            self.backup.mkdir(mode=0o700)
            tx = upgrade.new_transaction(self.venv, self.sha, self.wheel, prior)
            upgrade.save_json(self.active, tx)
            self.venv.rename(self.backup / "previous")
            shared.chmod(0o777)
            with self.assertRaisesRegex(PermissionError, "Unsafe host interpreter parent"):
                upgrade.restore(self.venv, self.backup, self.active, self.sha, bound)
        self.assertFalse(self.venv.exists())
        self.assertTrue(self.active.exists())

    def test_system_directory_alias_and_venv_relocation(self):
        launcher = Path("/bin/false")
        host = upgrade.host_interpreter_identity(launcher)
        self.assertEqual(host["resolved"], "host:" + str(launcher.resolve(strict=True)))
        if Path("/bin").is_symlink():
            self.assertEqual(host["links"][0]["path"], "host:/bin")
        self.bound.unlink()
        self.bound.symlink_to(launcher)
        self.interrupted()
        self.assertTrue(self.restore())

    def test_host_preflight_cannot_bind_different_running_executable(self):
        launcher = Path("/bin/false")
        expected = upgrade.host_interpreter_identity(launcher)
        with patch.object(upgrade.sys, "executable", str(launcher)):
            with self.assertRaisesRegex(RuntimeError, "Running host interpreter identity mismatch"):
                upgrade.validated_host_python(expected)

    def test_host_preflight_rejects_identity_change(self):
        shared, launcher = self.directory_alias()
        with patch.object(upgrade.sys, "executable", str(launcher)):
            expected = upgrade.host_interpreter_identity()
            (shared / "target").unlink()
            (shared / "target").symlink_to("/bin", target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "Host interpreter identity changed"):
                upgrade.validated_host_python(expected)

    def test_worker_rejects_mismatched_identity_before_build(self):
        expected = upgrade.host_interpreter_identity()
        canonical = upgrade.validated_host_python(expected)
        mismatched = {key: expected[key] for key in upgrade.INTERPRETER_FIELDS}
        mismatched["sha256"] = "0" * 64
        source = Path(__file__).resolve().parents[1] / "scripts/install-build.sh"
        worker = self.bridge / "scripts/install-build.sh"
        worker.parent.mkdir(mode=0o700)
        shutil.copyfile(source, worker)
        result = subprocess.run(
            ["/bin/bash", str(worker), "3", str(canonical), json.dumps(mismatched), self.sha],
            capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Host interpreter identity mismatch", result.stderr)
        self.assertFalse(self.active.exists())
        self.assertFalse(self.backup.exists())

    def test_fence_rejects_legacy_lifecycle_and_requires_loaded_barrier(self):
        from project_os_bridge import lifecycle
        root = self.kit / "instance"
        root.mkdir(mode=0o700)
        service = root / "service"
        service.mkdir(mode=0o700)
        unit = service / upgrade.UNIT
        unit.touch(mode=0o600)
        unit.write_text(render_unit(root, self.bound))
        loaded = {"fenced": False}
        def manager(args, **kwargs):
            if args[-1] == "daemon-reload":
                loaded["fenced"] = unit.read_text() == upgrade.fenced_unit_text(root, self.bound)
                return SimpleNamespace(returncode=0, stdout="")
            on_disk = unit.read_text() == upgrade.fenced_unit_text(root, self.bound)
            fields = dict(Id=upgrade.UNIT, LoadState="loaded", FragmentPath=str(unit),
                          DropInPaths="", NeedDaemonReload="no" if loaded["fenced"] == on_disk else "yes",
                          ActiveState="inactive", UnitFileState="linked", Job="", MainPID="0",
                          ControlPID="0", RefuseManualStart="yes" if loaded["fenced"] else "no")
            return SimpleNamespace(returncode=0, stdout="\n".join(f"{k}={v}" for k,v in fields.items()))
        upgrade.write_unit(root, self.bound, fenced=True)
        with self.assertRaises(RuntimeError):
            upgrade.check_unit(root, self.bound, manager, fenced=True)
        upgrade.fence_unit(root, self.bound, manager)
        self.assertTrue(loaded["fenced"])
        self.assertIn("ExecStart=/usr/bin/false\n", unit.read_text())
        self.assertNotIn("ExecStart=" + str(self.bound), unit.read_text())
        # prepared_unit is unchanged from the legacy lifecycle. Assert that
        # normal CLI entry rejects before reaching operate, not just new guard.
        with patch.object(lifecycle.sys, "executable", str(self.bound)), \
             patch.object(lifecycle.sys, "argv", ["legacy", "--root", str(root), "start"]), \
             patch.object(lifecycle, "operate") as operate, \
             patch.object(lifecycle, "exclusive_lifecycle") as lock:
            with self.assertRaises(SystemExit):
                lifecycle.main()
            operate.assert_not_called()
            lock.assert_not_called()
        self.interrupted()
        with self.assertRaises(RuntimeError):
            upgrade.check_release(self.kit, self.sha, self.guard, self.bound)
        self.assertTrue(loaded["fenced"])
        self.restore()
        upgrade.check_release(self.kit, self.sha, self.guard, self.bound)
        upgrade.release_unit(root, self.bound, manager)
        self.assertFalse(loaded["fenced"])
        self.assertEqual(unit.read_text(), render_unit(root, self.bound))

    def test_restore_waits_for_real_writer_group(self):
        self.interrupted()
        child = subprocess.Popen([sys.executable, "-I", "-c",
            "import sys; sys.stdout.write('ready\\n'); sys.stdout.flush(); sys.stdin.read(1)"],
            start_new_session=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            self.assertEqual(child.stdout.readline(), b"ready\n")
            tx = upgrade.read_json(self.active)
            tx.update(group=child.pid, phase="writing")
            upgrade.save_json(self.active, tx)
            with self.assertRaises(RuntimeError):
                self.restore()
            self.assertFalse(self.venv.exists())
            self.assertTrue((self.backup / "previous").exists())
            child.stdin.write(b"x")
            child.stdin.flush()
            self.assertEqual(child.wait(timeout=5), 0)
            self.assertTrue(self.restore())
            self.assertEqual((self.venv / "identity").read_text(), "old")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()

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
                      UnitFileState="linked", Job="", MainPID="0", ControlPID="0", RefuseManualStart="no")
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
