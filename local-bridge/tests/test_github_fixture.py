import tempfile
import unittest
from pathlib import Path
from project_os_bridge.core import Policy
from project_os_bridge.github_fixture import SyntheticGitHubReader


class SyntheticTests(unittest.TestCase):
    def test_batch_is_labelled_and_authorized(self):
        with tempfile.TemporaryDirectory() as folder:
            reader=SyntheticGitHubReader(Policy([("owner","github_read","disposable")]),Path(folder).resolve())
            result=reader.batch_issues("owner","disposable",[1,2,1])
            self.assertEqual(result["source"],"synthetic-fixture")
            self.assertEqual(set(result["issues"]),{1,2})
            self.assertTrue(result["complete"])
            with self.assertRaises(PermissionError):
                reader.batch_issues("other","disposable",[1])
