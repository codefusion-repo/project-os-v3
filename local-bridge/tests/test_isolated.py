import unittest
from unittest.mock import Mock, patch
from project_os_bridge.isolated import validate_in_container


class IsolationTests(unittest.TestCase):
    def test_revision_conflict(self):
        repo=Mock()
        repo.snapshot.return_value={"revision":"other"}
        with patch("project_os_bridge.isolated.subprocess.run") as run:
            result=validate_in_container(repo,"local","expected","python@sha256:"+"a"*64)
            self.assertEqual(result["status"],"BLOCKED")
            run.assert_not_called()

    def test_no_root_execution(self):
        repo=Mock()
        repo.snapshot.return_value={"revision":"expected"}
        with patch("project_os_bridge.isolated.os.getuid",return_value=0), patch("project_os_bridge.isolated.subprocess.run") as run:
            self.assertEqual(validate_in_container(repo,"local","expected","python@sha256:"+"a"*64)["reason"],"ROOTLESS_REQUIRED")
            run.assert_not_called()

    def test_no_unpinned_image(self):
        with self.assertRaises(ValueError):
            validate_in_container(Mock(),"local","expected","python:latest")
