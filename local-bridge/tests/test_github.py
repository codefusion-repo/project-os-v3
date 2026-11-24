import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from project_os_bridge.core import Policy
from project_os_bridge.github import GitHubReader


class GitHubTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.reader = GitHubReader(Policy([("local","github_read","demo")]),
                                   {"demo":"example/demo"},Path(temp.name).resolve())

    def test_denied_before_process(self):
        with patch.object(self.reader,"_request") as request:
            with self.assertRaises(PermissionError):
                self.reader.batch_issues("unknown","demo",[1])
            with self.assertRaises(ValueError):
                self.reader.batch_issues("local","demo",[True])
            request.assert_not_called()

    def test_batch_deduplicates_and_reports_partial(self):
        def fake(endpoint):
            if "/comments?" in endpoint:
                if "/2/" in endpoint:
                    return {"complete":False,"error":"GH_FAILED_OR_TIMEOUT"}
                return {"complete":True,"data":[]}
            return {"complete":True,"data":{"number":1}}
        with patch.object(self.reader,"_request",side_effect=fake) as request:
            result = self.reader.batch_issues("local","demo",[1,1,2])
        self.assertFalse(result["complete"])
        self.assertEqual(set(result["issues"]),{1,2})
        self.assertEqual(request.call_count,4)

    def test_pagination_limit(self):
        def fake(endpoint):
            return {"complete":True,"data":[{}]*100 if "/comments?" in endpoint else {}}
        with patch.object(self.reader,"_request",side_effect=fake):
            result = self.reader.issue_context("local","demo",1)
        self.assertFalse(result["complete"])
        self.assertEqual(result["comments_error"],"PAGE_LIMIT")
