import unittest
from unittest.mock import Mock

from project_os_bridge.qa_drive_operational import require_live_pr
from project_os_bridge.drive_delivery import DriveDeliveryError


class DrivePRGuardTests(unittest.TestCase):
    def setUp(self):
        self.ctx = Mock()
        self.ctx.require.return_value = "example/private"
        self.metadata = {"id": 123, "private": True, "full_name": "example/private"}
        self.pr = {"number": 4, "state": "open", "head": {"sha": "a" * 40, "repo": {"id": 123}},
                   "base": {"repo": {"id": 123}}}
        self.check = Mock()
        self.ctx.reader._authorized_request.side_effect = self.get

    def get(self, actor, project, path, check):
        check()
        return {"complete": True, "data": self.pr if "/pulls/" in path else self.metadata}

    def guard(self):
        return require_live_pr(self.ctx, "operator", "demo", 123, 4, "a" * 40, check_access=self.check)

    def test_exact_live_private_pr(self):
        self.guard()
        self.assertEqual(self.ctx.reader._authorized_request.call_count, 2)
        self.assertTrue(self.check.called)

    def test_public_or_retargeted_repository_denied(self):
        for patch in ({"private": False}, {"id": 124}):
            saved = dict(self.metadata)
            self.metadata.update(patch)
            with self.assertRaises(PermissionError):
                self.guard()
            self.metadata = saved

    def test_stale_or_fork_pr_denied(self):
        self.pr["head"]["sha"] = "b" * 40
        with self.assertRaises(PermissionError):
            self.guard()
        self.pr["head"] = {"sha": "a" * 40, "repo": {"id": 124}}
        with self.assertRaises(PermissionError):
            self.guard()

    def test_unavailable_read_fails_closed(self):
        self.ctx.reader._authorized_request.side_effect = None
        self.ctx.reader._authorized_request.return_value = {"complete": False}
        with self.assertRaises(DriveDeliveryError):
            self.guard()
