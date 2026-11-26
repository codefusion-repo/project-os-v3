import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from project_os_bridge.setup_instance import initialize

ISSUER = "https://fixture.authkit.app"
RESOURCE = "https://api.openai.com/v1/mcp/tunnel_fixture"
SUBJECT = "user_fixture"


def outside_git_tempdir(bases=None):
    """Choose a real temporary directory outside host Git ancestors."""
    if bases is None:
        bases = ("/tmp", "/var/tmp", Path.home())
    for entry in bases:
        base = Path(entry).resolve()
        if base.is_dir() and os.access(base, os.W_OK | os.X_OK) and not any(
            os.path.lexists(parent / ".git") for parent in (base, *base.parents)
        ):
            return tempfile.TemporaryDirectory(dir=base)
    raise RuntimeError("Setup tests require a writable temporary base outside Git")


class SetupTests(unittest.TestCase):
    @unittest.skipIf(os.getuid() == 0, "Positive setup requires an unprivileged user")
    def test_new_private_disabled_instance(self):
        with outside_git_tempdir() as folder:
            root = Path(folder).resolve() / "instance"
            state = initialize(root, ISSUER, RESOURCE, SUBJECT)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(state.stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / "oauth.json").stat().st_mode & 0o777, 0o600)
            self.assertFalse((state / "allow-authenticated-probe").exists())
            with self.assertRaises(FileExistsError):
                initialize(root, ISSUER, RESOURCE, SUBJECT)

    @unittest.skipIf(os.getuid() == 0, "Positive setup requires an unprivileged user")
    def test_temporary_base_with_git_ancestor_is_skipped(self):
        with outside_git_tempdir() as folder:
            parent = Path(folder)
            contaminated = parent / "contaminated"
            nested = contaminated / "tmp"
            nested.mkdir(parents=True)
            marker = contaminated / ".git"
            marker.mkdir()
            with outside_git_tempdir((nested, parent)) as fallback:
                self.assertEqual(Path(fallback).parent, parent)
                self.assertTrue(initialize(Path(fallback) / "instance", ISSUER, RESOURCE, SUBJECT).is_dir())
            self.assertTrue(marker.is_dir())
            self.assertEqual(list(nested.iterdir()), [])

    def test_git_ancestor_denied(self):
        for marker_is_file in (False, True):
            with self.subTest(marker_is_file=marker_is_file):
                with tempfile.TemporaryDirectory() as folder, patch(
                    "project_os_bridge.setup_instance.os.getuid", return_value=1000
                ):
                    root = Path(folder).resolve()
                    marker = root / ".git"
                    if marker_is_file:
                        marker.write_text("gitdir: synthetic\n", encoding="utf-8")
                    else:
                        marker.mkdir()
                    nested = root / "nested"
                    nested.mkdir()
                    with self.assertRaisesRegex(PermissionError, "outside Git"):
                        initialize(nested / "instance", ISSUER, RESOURCE, SUBJECT)
                    self.assertFalse((nested / "instance").exists())

    def test_root_denied(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            "project_os_bridge.setup_instance.os.getuid", return_value=0
        ):
            root = Path(folder).resolve() / "instance"
            with self.assertRaisesRegex(PermissionError, "unprivileged"):
                initialize(root, ISSUER, RESOURCE, SUBJECT)
            self.assertFalse(root.exists())

    @unittest.skipIf(os.getuid() == 0, "Requires unprivileged user")
    def test_cli_both_paths(self):
        import json
        import sys
        from project_os_bridge.setup_instance import main
        with outside_git_tempdir() as folder:
            root = Path(folder).resolve() / "instance"
            original_umask = os.umask(0o077)
            try:
                with patch.object(sys, "argv", ["project-os-bridge-init", "--root", str(root)]), patch(
                    "builtins.input", side_effect=[ISSUER, RESOURCE, SUBJECT]
                ):
                    main()
                config = (root / "oauth.json").read_bytes()
                self.assertEqual(json.loads(config)["subject"], SUBJECT)
                self.assertFalse((root / "state" / "allow-authenticated-probe").exists())
                tunnel = Path(folder).resolve() / "tunnel-client"
                tunnel.write_text("#!/bin/sh\nexit 0\n")
                tunnel.chmod(0o700)
                with patch.object(sys, "argv", ["project-os-bridge-init", "--root", str(root), "--prepare-service"]), patch(
                    "builtins.input", side_effect=[str(tunnel), ""]
                ), patch("sys.stdin.isatty", return_value=True), patch("sys.stderr.isatty", return_value=True), patch(
                    "getpass.getpass", return_value="synthetic-only-runtime-key"
                ):
                    main()
                self.assertEqual((root / "oauth.json").read_bytes(), config)
                self.assertTrue((root / "service" / "project-os-bridge.service").is_file())
                self.assertFalse((root / "state" / "allow-authenticated-probe").exists())
            finally:
                os.umask(original_umask)

    def test_cli_help_exposes_service_option(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, "-I", "-m", "project_os_bridge.setup_instance", "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--prepare-service", result.stdout)
        self.assertIn("--no-fixture", result.stdout)

    def test_no_fixture_requires_prepare_service(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "never-created"
            result = subprocess.run(
                [sys.executable, "-I", "-m", "project_os_bridge.setup_instance",
                 "--root", str(root), "--no-fixture"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn("--no-fixture requires --prepare-service", result.stderr)
            self.assertFalse(root.exists())

    @unittest.skipIf(os.getuid() == 0, "Requires unprivileged user")
    def test_no_fixture_preparation_and_partial_recovery(self):
        import json
        import sys
        from project_os_bridge.setup_instance import main
        from project_os_bridge.service_setup import write_new
        with outside_git_tempdir() as folder:
            parent = Path(folder).resolve()
            root = parent / "partial"
            recovered = parent / "recovered"
            tunnel = parent / "tunnel-client"
            tunnel.write_text("#!/bin/sh\nexit 0\n")
            tunnel.chmod(0o700)
            initialize(root, ISSUER, RESOURCE, SUBJECT)
            original = (root / "oauth.json").read_bytes()
            original_umask = os.umask(0o077)

            def fail_after_creation(directory):
                write_new(directory / "partial-marker", b"preserve")
                raise OSError("synthetic interruption")

            def prepare(instance):
                with patch.object(sys, "argv", ["project-os-bridge-init", "--root",
                            str(instance), "--prepare-service", "--no-fixture"]), patch(
                    "builtins.input", side_effect=[str(tunnel)]
                ) as prompt, patch("sys.stdin.isatty", return_value=True), patch(
                    "sys.stderr.isatty", return_value=True
                ), patch("getpass.getpass", return_value="synthetic-only-runtime-key"):
                    main()
                    self.assertEqual(prompt.call_count, 1)

            try:
                with patch("project_os_bridge.service_setup.generate_tls",
                           side_effect=fail_after_creation), self.assertRaises(OSError):
                    prepare(root)
                marker = root / "service" / "partial-marker"
                self.assertEqual(marker.read_bytes(), b"preserve")
                with self.assertRaises(FileExistsError):
                    prepare(root)
                self.assertEqual((root / "oauth.json").read_bytes(), original)
                self.assertFalse((root / "state" / "allow-authenticated-probe").exists())
                initialize(recovered, ISSUER, RESOURCE, SUBJECT)
                prepare(recovered)
                runtime = json.loads((recovered / "service" / "runtime.json").read_text())
                self.assertIsNone(runtime["image"])
                self.assertFalse((recovered / "state" / "fixture-image").exists())
                self.assertFalse((recovered / "state" / "allow-authenticated-probe").exists())
                self.assertTrue((recovered / "service" / "project-os-bridge.service").is_file())
                self.assertEqual(marker.read_bytes(), b"preserve")
                self.assertEqual((root / "oauth.json").read_bytes(), original)
            finally:
                os.umask(original_umask)
