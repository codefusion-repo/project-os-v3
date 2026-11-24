import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from project_os_bridge.setup_instance import initialize

class SetupTests(unittest.TestCase):
    def test_new_private_disabled_instance(self):
        with tempfile.TemporaryDirectory() as folder, patch("project_os_bridge.setup_instance.os.getuid",return_value=1000):
            # private_directory checks the real filesystem owner; use actual UID.
            import os
            with patch("project_os_bridge.setup_instance.os.getuid",return_value=Path(folder).stat().st_uid or 1000), patch("project_os_bridge.setup_instance.private_directory"):
                root=Path(folder)/"instance"
                state=initialize(root,"https://fixture.authkit.app","https://api.openai.com/v1/mcp/tunnel_fixture","user_fixture")
                self.assertEqual((root/"oauth.json").stat().st_mode&0o777,0o600)
                self.assertFalse((state/"allow-authenticated-probe").exists())
                with self.assertRaises(FileExistsError):
                    initialize(root,"https://fixture.authkit.app","https://api.openai.com/v1/mcp/tunnel_fixture","user_fixture")

    def test_git_ancestor_denied(self):
        with tempfile.TemporaryDirectory() as folder, patch("project_os_bridge.setup_instance.os.getuid",return_value=1000):
            root=Path(folder)
            (root/".git").mkdir()
            with self.assertRaises(PermissionError):
                initialize(root/"instance","https://fixture.authkit.app","https://api.openai.com/v1/mcp/tunnel_fixture","user_fixture")
            self.assertFalse((root/"instance").exists())
