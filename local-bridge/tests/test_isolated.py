import json
import subprocess
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from project_os_bridge.isolated import (
    ALPINE_BASELINE, ALPINE_FIXTURE_ONLY, CHECKS, ISOLATION_CHECKS, PACKAGE_ABSENCE,
    RUNTIME_COMPATIBILITY, SCRIPT, validate_in_container,
)
from project_os_bridge.isolation_profile import MOUNT_CHECK

IMAGE = "python@sha256:" + "a" * 64
IDENTITY = "b" * 64
TOKEN = "c" * 32


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.repo = Mock()
        self.repo.snapshot.return_value = {"revision": "expected", "text": "after\n"}
        self.context = Mock(root=Path("/unused-test-context"))
        self.context.host.return_value = {"security": {"rootless": True, "seccompEnabled": True}}
        patcher = patch("project_os_bridge.isolated.challenge", return_value='{"forbidden": []}')
        patcher.start()
        self.addCleanup(patcher.stop)

    def invoke(self, image=IMAGE):
        return validate_in_container(self.repo, "local", "expected", image, token=TOKEN,
                                     context=self.context, identity=IDENTITY)

    def test_revision_conflict(self):
        self.repo.snapshot.return_value = {"revision": "other"}
        self.assertEqual(self.invoke()["reason"], "REVISION_CONFLICT")
        self.context.host.assert_not_called()

    def test_no_root_execution(self):
        with patch("project_os_bridge.isolated.os.getuid", return_value=0):
            self.assertEqual(self.invoke()["reason"], "ROOTLESS_REQUIRED")
        self.context.host.assert_not_called()

    def test_no_unpinned_image(self):
        for image in ("python:latest", "--evil@sha256:" + "a" * 64):
            with self.assertRaises(ValueError):
                self.invoke(image)

    def test_validation_command_and_exact_bytes(self):
        compile(SCRIPT, "<fixture>", "exec")
        self.assertIn("== b'after\\n'", SCRIPT)
        self.context.run.side_effect = [Mock(returncode=0), Mock(returncode=1), Mock(returncode=0, stdout=b"")]
        with patch("project_os_bridge.isolated.os.getuid", return_value=1000):
            result = self.invoke()
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["checks"], CHECKS)
        self.assertEqual(result["isolation_checks"], ISOLATION_CHECKS)
        self.assertTrue(result["cleanup_verified"])
        self.context.host.assert_called_once_with(IDENTITY)
        self.context.require_import.assert_called_once_with(IDENTITY, IMAGE)
        args = self.context.run.call_args_list[0].args
        for flag in ("--pull=never", "--network=none", "--read-only", "--read-only-tmpfs=false", "--cap-drop=ALL",
                     "--http-proxy=false", "--image-volume=ignore", "--pid=private", "--ipc=private", "--cgroupns=private",
                     "--passwd=false", "--userns=keep-id"):
            self.assertIn(flag, args)
        denied = json.loads(args[-1])["forbidden"]
        self.assertTrue(any(path.endswith("/exchange/synthetic-marker") for path in denied))
        self.assertTrue(any(path.endswith("/credentials/synthetic-marker") for path in denied))
        self.assertTrue(all(call.args[0] == IDENTITY for call in self.context.run.call_args_list))

    def test_preflight_blocks_before_run(self):
        self.context.host.side_effect = PermissionError("wrong context or disabled Seccomp")
        with patch("project_os_bridge.isolated.os.getuid", return_value=1000):
            self.assertEqual(self.invoke()["status"], "BLOCKED")
        self.context.run.assert_not_called()

    def test_cleanup_is_required(self):
        self.context.run.side_effect = [Mock(returncode=0), Mock(returncode=0), Mock(returncode=0, stdout=b"")]
        with patch("project_os_bridge.isolated.os.getuid", return_value=1000):
            self.assertEqual(self.invoke()["reason"], "CLEANUP_UNVERIFIED")

    def test_negative_probe_failure(self):
        self.context.run.side_effect = [Mock(returncode=18), Mock(returncode=1), Mock(returncode=0, stdout=b"")]
        with patch("project_os_bridge.isolated.os.getuid", return_value=1000):
            result = self.invoke()
        self.assertEqual((result["status"], result["exit_code"]), ("FAILED", 18))
        self.assertFalse(result["checks"] or result["isolation_checks"])

    def test_compatibility_profiles_share_the_named_container_and_absence_checks(self):
        for digest, packages in ((ALPINE_BASELINE, ()), (ALPINE_FIXTURE_ONLY, PACKAGE_ABSENCE)):
            with self.subTest(digest=digest):
                self.context.run.reset_mock()
                self.context.run.side_effect = [Mock(returncode=0), Mock(returncode=1),
                                                Mock(returncode=0, stdout=b"")]
                result = self.invoke("localhost/project-os-alpine-ci@" + digest)
                self.assertEqual(result["compatibility_checks"], list(RUNTIME_COMPATIBILITY + packages))
                self.assertEqual(result["checks"], CHECKS)
                self.assertEqual(result["isolation_checks"], ISOLATION_CHECKS)
                calls = self.context.run.call_args_list
                self.assertEqual([c.args[1] for c in calls], ["run", "container", "ps"])
                args = calls[0].args
                program = args[args.index("-c") + 1]
                compile(program, "<fixture-with-compatibility>", "exec")
                self.assertTrue(program.startswith(SCRIPT))
                self.assertTrue(program.endswith(f"check_compatibility({bool(packages)})\n"))
                self.assertIn("project-os-fixture-" + TOKEN, args)
                self.assertIn("io.project-os.fixture=" + TOKEN, args)
                self.assertTrue(result["cleanup_verified"])

    def test_compatibility_exit_with_proven_cleanup_is_a_persistable_failure(self):
        self.context.run.side_effect = [Mock(returncode=20), Mock(returncode=1), Mock(returncode=0, stdout=b"")]
        result = self.invoke("localhost/project-os-alpine-ci@" + ALPINE_FIXTURE_ONLY)
        self.assertEqual((result["status"], result["reason"], result["exit_code"]),
                         ("FAILED", "IMAGE_COMPATIBILITY_FAILED", 20))
        self.assertTrue(result["cleanup_verified"])
        self.assertEqual(result["compatibility_checks"], [])

    def test_timeouts_and_context_drift_after_dispatch_require_reconciliation(self):
        cases = ([subprocess.TimeoutExpired("podman", 30)],
                 [Mock(returncode=0), subprocess.TimeoutExpired("podman", 10)],
                 [Mock(returncode=0), PermissionError("context changed")])
        for responses in cases:
            with self.subTest(responses=responses):
                self.context.run.side_effect = responses
                with patch("project_os_bridge.isolated.os.getuid", return_value=1000):
                    result = self.invoke()
                self.assertEqual(result["reason"], "CLEANUP_UNVERIFIED")
                self.assertFalse(result["container_absent"])

    def test_mount_allowlist_rejects_relabelled_and_unexpected_mounts(self):
        import os
        import re
        import stat
        methods = {"Path": Path, "os": os, "re": re, "stat": stat}
        exec(MOUNT_CHECK, methods)
        mounts = [("0:1", "/", "/", ["ro"], "overlay"), ("0:2", "/", "/proc", ["rw"], "proc"),
                  ("0:3", "/", "/sys/fs/cgroup", ["ro"], "cgroup2"),
                  ("8:1", "/synthetic/export", "/fixture", ["ro"], "ext4")]
        settings = {"host_filesystems": ["9p"], "fixture": ["8:1", "/synthetic/export", "ext4"], "generated": []}
        verify = methods["allowed_mounts"]
        null = ("0:4", "/null", "/dev/null", ["rw"], "devtmpfs")
        self.assertTrue(verify(mounts, settings))
        with patch.object(Path, "lstat", return_value=Mock(st_mode=stat.S_IFCHR, st_rdev=os.makedev(1, 3))):
            self.assertTrue(verify(mounts + [null], settings))
        with patch.object(Path, "lstat", return_value=Mock(st_mode=stat.S_IFCHR, st_rdev=os.makedev(1, 5))):
            self.assertFalse(verify(mounts + [null], settings))
        self.assertFalse(verify(mounts + [("8:1", "/synthetic/credentials", "/elsewhere", ["ro"], "ext4")], settings))
        self.assertFalse(verify(mounts + [("0:4", "/", "/dev/shm", ["ro"], "9p")], settings))
        mask = ("0:5", "/", "/sys/dev/block", ["ro"], "tmpfs")
        with patch.object(Path, "iterdir", return_value=iter(())):
            self.assertTrue(verify(mounts + [mask], settings))
        with patch.object(Path, "iterdir", return_value=iter((Path("unexpected"),))):
            self.assertFalse(verify(mounts + [mask], settings))
        self.assertFalse(verify(mounts[:-1] + [("8:1", "/synthetic/alias", "/fixture", ["ro"], "ext4")], settings))
