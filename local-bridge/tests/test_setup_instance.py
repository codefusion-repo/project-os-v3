import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from project_os_bridge.setup_instance import initialize

ISSUER = "https://fixture.authkit.app"
RESOURCE = "https://api.openai.com/v1/mcp/tunnel_fixture"
SUBJECT = "user_fixture"


class SetupTests(unittest.TestCase):
    @unittest.skipIf(os.getuid() == 0, "Positive setup requires an unprivileged user")
    def test_new_private_disabled_instance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / "instance"
            # Model an outside-Git environment independently of TMPDIR and
            # host checkout ancestors. The real filesystem permissions and
            # no-overwrite checks remain active.
            with patch("project_os_bridge.setup_instance.os.path.lexists", return_value=False):
                state = initialize(root, ISSUER, RESOURCE, SUBJECT)
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)
                self.assertEqual(state.stat().st_mode & 0o777, 0o700)
                self.assertEqual((root / "oauth.json").stat().st_mode & 0o777, 0o600)
                self.assertFalse((state / "allow-authenticated-probe").exists())
                with self.assertRaises(FileExistsError):
                    initialize(root, ISSUER, RESOURCE, SUBJECT)

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
        with tempfile.TemporaryDirectory(dir="/tmp") as folder:
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
