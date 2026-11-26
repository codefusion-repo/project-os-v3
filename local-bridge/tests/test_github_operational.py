import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from project_os_bridge.github import _http_result
from project_os_bridge.github_operational import (
    AUDIT_NAME, BINDING, CONFIG_DIR, FLAG, GitHubContextAudit, load_operational_provider,
)


class OperationalGitHubTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        (self.root / CONFIG_DIR).mkdir(mode=0o700)
        self.verifier = SimpleNamespace(state_dir=self.state, subject="user_fixture", enabled=lambda: True)
        self.config = {"principal": "user_fixture", "project": "demo", "repository": "example/demo",
                       "repository_id": 123}
        self.binding = self.state / BINDING
        self.flag = self.state / FLAG

    def configure(self):
        self.binding.touch(mode=0o600)
        self.binding.write_text(json.dumps(self.config))

    def provider(self):
        self.configure()
        provider = load_operational_provider(self.verifier, supervised=True)
        self.flag.touch(mode=0o600)
        return provider

    def response(self, endpoint):
        base = "https://api.github.com/repos/example/demo"
        if endpoint == "repos/example/demo":
            return {"complete": True, "data": {"id": 123, "full_name": "example/demo"}}
        if "/comments?" in endpoint:
            return {"complete": True, "data": []}
        return {"complete": True, "data": {"number": 1, "title": "fixture", "body": None,
                                           "state": "open", "comments": 0,
                                           "repository_url": base, "url": base + "/issues/1"}}

    def test_default_disabled_profile_and_startup_opt_in(self):
        self.assertIsNone(load_operational_provider(self.verifier, supervised=False))
        self.configure()
        with self.assertRaises(PermissionError):
            load_operational_provider(self.verifier, supervised=False)
        provider = load_operational_provider(self.verifier, supervised=True)
        with patch.object(provider.reader, "_request") as request:
            with self.assertRaises(PermissionError):
                provider.read("user_fixture", "demo", [1])
            request.assert_not_called()
        self.flag.touch(mode=0o600)
        with self.assertRaises(PermissionError):
            load_operational_provider(self.verifier, supervised=True)
        self.flag.unlink()
        self.binding.write_text('{"principal":"user_fixture","principal":"other"}')
        with self.assertRaises(ValueError):
            load_operational_provider(self.verifier, supervised=True)

    def test_positive_and_revocation_before_next_request(self):
        provider = self.provider()
        with patch.object(provider.reader, "_request", side_effect=self.response) as request:
            result = provider.read("user_fixture", "demo", [1])
            self.assertTrue(result["complete"])
            self.assertEqual(request.call_count, 6)
        def revoke(endpoint):
            result = self.response(endpoint)
            self.flag.unlink()
            return result
        with patch.object(provider.reader, "_request", side_effect=revoke) as request:
            with self.assertRaises(PermissionError):
                provider.read("user_fixture", "demo", [1])
            request.assert_called_once()

    def test_binding_change_and_other_project_denied(self):
        provider = self.provider()
        with patch.object(provider.reader, "_request") as request:
            with self.assertRaises(PermissionError):
                provider.read("user_fixture", "other", [1])
            self.binding.write_text(json.dumps({**self.config, "repository_id": 456}))
            with self.assertRaises(PermissionError):
                provider.read("user_fixture", "demo", [1])
            request.assert_not_called()

    def test_identity_before_and_after_payload(self):
        provider = self.provider()
        for when in (1, 2):
            metadata = 0
            def wrong(endpoint):
                nonlocal metadata
                result = self.response(endpoint)
                if endpoint == "repos/example/demo":
                    metadata += 1
                    if metadata == when:
                        result["data"]["id"] = 999
                return result
            with patch.object(provider.reader, "_request", side_effect=wrong) as request:
                result = provider.read("user_fixture", "demo", [1, 2])
            self.assertFalse(result["complete"])
            self.assertEqual(result["error"], "RESOURCE_MISMATCH")
            self.assertEqual(result["issues"], {})
            self.assertEqual(result["omitted_issues"], [1, 2])
            self.assertEqual(request.call_count, 1 if when == 1 else 3)

    def test_rate_limit_discards_batch(self):
        provider = self.provider()
        with patch.object(provider.reader, "_request",
                          return_value={"complete": False, "error": "GH_RATE_LIMIT"}) as request:
            result = provider.read("user_fixture", "demo", [1, 2])
        self.assertEqual(result["error"], "GH_RATE_LIMIT")
        self.assertEqual(result["issues"], {})
        request.assert_called_once()

    def test_audit_closed_schema_and_capacity(self):
        audit = GitHubContextAudit(self.state)
        audit.record("admitted")
        audit.record("complete")
        records = [json.loads(line) for line in (self.state / AUDIT_NAME).read_text().splitlines()]
        self.assertEqual([r["outcome"] for r in records], ["admitted", "complete"])
        self.assertTrue(all(set(r) == {"at", "event", "outcome"} for r in records))
        with self.assertRaises(ValueError):
            audit.record("arbitrary text")
        with patch("project_os_bridge.github_operational.MAX_AUDIT", 1):
            with self.assertRaises(OSError):
                audit.record("partial")
        self.assertEqual(len((self.state / AUDIT_NAME).read_text().splitlines()), 2)

    def test_http_rate_limit_and_generic_error(self):
        for raw in (
                b"HTTP/2.0 429 Too Many Requests\r\nRetry-After: 10\r\n\r\n{}",
                b"HTTP/2.0 403 Forbidden\r\nX-Ratelimit-Remaining: 0\r\n\r\n{}",
                b"HTTP/1.1 403 Forbidden\nRetry-After: 10\n\n{}",
                b'HTTP/2.0 403 Forbidden\r\nContent-Type: application/json\r\n\r\n{"message":"secondary rate limit exceeded"}'):
            self.assertEqual(_http_result(raw, 1), {"complete": False, "error": "GH_RATE_LIMIT"})
        self.assertEqual(_http_result(b"HTTP/2.0 403 Forbidden\r\n\r\nprivate", 1),
                         {"complete": False, "error": "GH_HTTP_ERROR"})
        self.assertEqual(_http_result(b'HTTP/2.0 200 OK\r\nX-Test: private\r\n\r\n{"id": 1}', 0),
                         {"complete": True, "data": {"id": 1}})
