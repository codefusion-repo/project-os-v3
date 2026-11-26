import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_os_bridge.core import Policy
from project_os_bridge.github import GitHubReader
from project_os_bridge.github_context import GitHubContext, MAX_CONTEXT_BYTES


class GitHubContextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.reader = GitHubReader(
            Policy([("owner", "github_read", "demo"), ("owner", "github_read", "other")]),
            {"demo": "example/demo", "other": "example/other"}, Path(temp.name).resolve())
        self.grants = {("owner", "demo", "example/demo")}
        self.context = GitHubContext(self.reader, lambda *grant: grant in self.grants)

    def fixture(self, endpoint):
        number = int(endpoint.split("/")[4])
        if "/comments?" in endpoint:
            return {"complete": True, "data": [{"id": number, "body": "Context",
                                                "internal": "DO_NOT_RETURN"}]}
        return {"complete": True, "data": {"number": number, "title": "Issue",
                                            "body": "Requirements", "comments": 1,
                                            "internal": "DO_NOT_RETURN"}}

    def test_batch_projection_and_deduplication(self):
        with patch.object(self.reader, "_request", side_effect=self.fixture) as request:
            result = self.context.read("owner", "demo", [1, 1, 2])
        self.assertTrue(result["complete"])
        self.assertEqual(set(result["issues"]), {1, 2})
        self.assertEqual(request.call_count, 4)
        self.assertNotIn("DO_NOT_RETURN", json.dumps(result))
        self.assertTrue(result["untrusted_content"])
        self.assertTrue(result["retrieved_at"])

    def test_denial_and_invalid_numbers_before_transport(self):
        with patch.object(self.reader, "_request") as request:
            for actor, project in (("other", "demo"), ("owner", "other"), ("owner", "bad/path")):
                with self.assertRaises(PermissionError):
                    self.context.read(actor, project, [1])
            for numbers in ([True], [0], [], [1]*6, ["1"]):
                with self.assertRaises(ValueError):
                    self.context.read("owner", "demo", numbers)
            request.assert_not_called()

    def test_revocation_discards_inflight_data(self):
        def revoke(endpoint):
            self.grants.clear()
            return self.fixture(endpoint)
        with patch.object(self.reader, "_request", side_effect=revoke) as request:
            with self.assertRaises(PermissionError):
                self.context.read("owner", "demo", [1])
            request.assert_called_once()

    def test_secret_and_control_filter_and_mismatch(self):
        def fake(endpoint):
            data = self.fixture(endpoint)
            if "/comments?" in endpoint:
                data["data"][0]["body"] = "password=" + "fixture-only"
            else:
                data["data"]["title"] = "ab\u202ecd"
                data["data"]["comments"] = 2
            return data
        with patch.object(self.reader, "_request", side_effect=fake):
            result = self.context.read("owner", "demo", [1])
        self.assertFalse(result["complete"])
        item = result["issues"][1]
        self.assertTrue(item["content_filtered"])
        self.assertEqual(item["issue"]["data"]["title"], "abcd")
        self.assertEqual(item["comments"][0]["body"], "[REDACTED]")
        self.assertEqual(item["comments_error"], "COUNT_MISMATCH")
        self.assertNotIn("fixture-only", json.dumps(result))

    def test_batch_wire_budget(self):
        def large(endpoint):
            if "/comments?" not in endpoint:
                return self.fixture(endpoint)
            return {"complete": True, "data": [
                {"id": i+1, "body": "\u2603"*16000} for i in range(5)]}
        with patch.object(self.reader, "_request", side_effect=large):
            result = self.context.read("owner", "demo", [1, 2, 3, 4, 5])
        self.assertFalse(result["complete"])
        self.assertTrue(result["omitted_issues"])
        self.assertEqual(result["error"], "BATCH_RESPONSE_LIMIT")
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=True).encode()), MAX_CONTEXT_BYTES)

    def test_failed_transport_is_incomplete(self):
        with patch.object(self.reader, "_request", return_value={"complete": False, "error": "GH_FAILED_OR_TIMEOUT"}):
            result = self.context.read("owner", "demo", [1])
        self.assertFalse(result["complete"])
        self.assertEqual(result["issues"][1]["issue"]["error"], "GH_FAILED_OR_TIMEOUT")
        self.assertEqual(result["issues"][1]["comments"], [])

    def test_session_revoked_during_read_stops_pagination(self):
        active = True

        def check_session():
            if not active:
                raise PermissionError("DENIED")

        def revoke(endpoint):
            nonlocal active
            active = False
            return self.fixture(endpoint)

        with patch.object(self.reader, "_request", side_effect=revoke) as request:
            with self.assertRaises(PermissionError):
                self.context.read("owner", "demo", [1], check_session=check_session)
            request.assert_called_once()

    def test_surrogate_in_comment_is_filtered(self):
        def fake(endpoint):
            result = self.fixture(endpoint)
            if "/comments?" in endpoint:
                result["data"][0]["body"] = "text" + chr(0xd800)
            return result

        with patch.object(self.reader, "_request", side_effect=fake):
            result = self.context.read("owner", "demo", [1])
        self.assertFalse(result["complete"])
        self.assertEqual(result["issues"][1]["comments"][0]["body"], "text")
