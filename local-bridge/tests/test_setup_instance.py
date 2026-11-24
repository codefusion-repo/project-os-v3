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
