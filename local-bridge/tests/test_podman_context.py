import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess, TimeoutExpired

from project_os_bridge.podman_context import PodmanContext, FIXTURE_TAG

DIGEST = "sha256:" + "a" * 64
IMAGE_ID = "b" * 64


class PodmanContextTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="lbc.", dir="/tmp")
        self.addCleanup(directory.cleanup)
        old = os.umask(0o077)
        self.addCleanup(os.umask, old)
        self.parent = Path(directory.name).resolve()
        self.context = PodmanContext(self.parent / "first")
        self.identity = self.prepare(self.context)

    def prepare(self, context):
        def fake_host():
            (context.root / "graph/db.sql").touch(mode=0o644)
            pause = context.root / "runtime/libpod/tmp/pause.pid"
            pause.parent.mkdir(parents=True)
            pause.write_text(str(os.getpid()))
        with patch.object(context, "_host", side_effect=fake_host):
            return context.prepare()

    def test_scoped_environment_and_local_flags(self):
        with patch.dict(os.environ, {"CONTAINER_HOST": "untrusted", "CONTAINERS_STORAGE_CONF": "foreign"}), patch(
                "project_os_bridge.podman_context.subprocess.run", return_value=CompletedProcess([], 0)) as run:
            self.context.run(self.identity, "container", "exists", "test")
        args, env = run.call_args.args[0], run.call_args.kwargs["env"]
        self.assertEqual(args[0], "/usr/bin/podman")
        self.assertIn("--remote=false", args)
        self.assertNotIn("CONTAINER_HOST", env)
        self.assertEqual(env["XDG_RUNTIME_DIR"], str(self.context.root / "runtime"))
        self.assertEqual(env["HOME"], str(self.context.root / "home"))
        for flag, path in (("--root", "graph"), ("--runroot", "runroot"), ("--tmpdir", "libpod")):
            self.assertEqual(args[args.index(flag)+1], self.context.root / path)

    def test_podman_runroot_length_is_checked_before_any_call(self):
        with self.assertRaisesRegex(PermissionError, "50 bytes"):
            PodmanContext(self.parent / ("x" * 50))

    def test_reopened_context_matches_and_wrong_store_does_not_call_podman(self):
        reopened = PodmanContext(self.context.root)
        self.assertEqual(reopened.identity(), self.identity)
        other = PodmanContext(self.parent / "second")
        self.assertNotEqual(self.prepare(other), self.identity)
        with patch.object(other, "_run") as run, self.assertRaises(PermissionError):
            other.host(self.identity)
        run.assert_not_called()

    def test_replaced_state_database_is_not_the_same_context(self):
        db = self.context.root / "graph/db.sql"
        db.rename(db.with_suffix(".saved"))
        db.touch()
        with patch.object(self.context, "_run") as run, self.assertRaises(PermissionError):
            self.context.run(self.identity, "ps", "--all")
        run.assert_not_called()

    def test_layout_import_pins_digest_in_same_context(self):
        layout = self.parent / "layout"
        layout.mkdir()
        (layout / "index.json").write_text(json.dumps({"manifests": [{"digest": DIGEST}]}))
        result = lambda output=b"": CompletedProcess([], 0, output)
        with patch.object(self.context, "_host"), patch.object(self.context, "_run", side_effect=[
                result(IMAGE_ID.encode()), result(DIGEST.encode()), result(), result(DIGEST.encode()),
                result(DIGEST.encode()), result(DIGEST.encode())]) as podman:
            image = self.context.import_layout(layout, DIGEST)
            self.assertEqual(self.context.import_layout(layout, DIGEST), image)
            self.assertEqual(image, FIXTURE_TAG.split(":")[0] + "@" + DIGEST)
            self.assertEqual(sum(call.args[0] == "pull" for call in podman.call_args_list), 1)
            self.assertEqual(podman.call_args_list[0].kwargs["timeout"], 120)
        with patch.object(self.context, "_run") as podman, self.assertRaises(PermissionError):
            self.context.require_import(self.identity, image.replace("a" * 64, "c" * 64))
        podman.assert_not_called()

    def test_mobile_import_has_bounded_budget_and_timeout_never_pins(self):
        layout = self.parent / "layout"
        layout.mkdir()
        (layout / "index.json").write_text(json.dumps({"manifests": [{"digest": DIGEST}]}))
        with patch.object(self.context, "_host"), patch.object(
                self.context, "_run", side_effect=TimeoutExpired("podman", 600)) as podman:
            with self.assertRaises(TimeoutExpired):
                self.context.import_layout(layout, DIGEST, kind="mobile-validation")
            self.assertEqual(podman.call_args.kwargs["timeout"], 600)
            self.assertFalse((self.context.root / "image").exists())
        result = lambda output=b"": CompletedProcess([], 0, output)
        with patch.object(self.context, "_host"), patch.object(self.context, "_run", side_effect=[
                result(IMAGE_ID.encode()), result(DIGEST.encode()), result(), result(DIGEST.encode()),
                result(DIGEST.encode())]) as podman:
            image = self.context.import_layout(layout, DIGEST, kind="mobile-validation")
            self.assertEqual(image, "localhost/project-os-mobile-ci@" + DIGEST)
            self.assertEqual(podman.call_args_list[0].kwargs["timeout"], 600)
            self.assertEqual((self.context.root / "image").read_text(), image + "\n")

    def test_empty_engine_home_directories_do_not_supply_host_data(self):
        (self.context.root / "home/.config/containers").mkdir(parents=True)
        self.assertEqual(self.context.identity(), self.identity)

    def test_rpm_metadata_is_distinct_from_authentication_material(self):
        rpm = self.context.root / "home/.rpmdb"
        rpm.mkdir()
        for name in ("rpmdb.sqlite", "rpmdb.sqlite-shm", "rpmdb.sqlite-wal"):
            (rpm / name).touch()
        self.assertEqual(self.context.identity(), self.identity)
        (rpm / "auth.json").touch()
        with self.assertRaises(PermissionError):
            self.context.identity()

    def test_host_data_and_context_layout_drift_fail_closed(self):
        (self.context.root / "home/foreign").touch()
        with patch.object(self.context, "_run") as run, self.assertRaises(PermissionError):
            self.context.host(self.identity)
        run.assert_not_called()
