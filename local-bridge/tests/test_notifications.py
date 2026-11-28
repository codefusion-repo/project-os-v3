import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from project_os_bridge.core import Jobs, Policy
from project_os_bridge.notifications import (NotificationSender, config, email_body,
    event, record_delivery_event, MAX_AGE)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.jobs = Jobs(self.root, Policy([]))
        self.path = self.root / "resend.json"
        self.cfg = {"api_key": "re_fixture_only", "from": "sender@example.test",
                    "recipients": {"operator@example.test": ["demo"]},
                    "enabled_since": "2026-01-01T00:00:00+00:00"}
        self.path.write_text(json.dumps(self.cfg))
        self.path.chmod(0o600)
        self.item = event("job/fixture/1", "demo", "expo-test", "SUCCEEDED",
                          "2026-01-02T00:00:00+00:00", "a"*32)
        self.now = 1000
        self.transport = Mock(return_value=("ACCEPTED", "a"*36, 0))
        self.sender = NotificationSender(self.jobs, "actor", lambda: True,
                                         transport=self.transport, clock=lambda: self.now)
        self.sender.schema()
        self.sender.events = Mock(return_value=[self.item])

    def test_acceptance_is_deduplicated_across_restart(self):
        self.sender.tick()
        self.assertEqual(self.transport.call_count, 1)
        another = NotificationSender(self.jobs, "actor", lambda: True,
                                      transport=self.transport, clock=lambda: self.now)
        another.events = Mock(return_value=[self.item])
        another.tick()
        self.assertEqual(self.transport.call_count, 1)
        with self.jobs.transaction() as c:
            self.assertEqual(c.execute("SELECT state FROM notification_receipts").fetchone()[0], "ACCEPTED")
            self.assertEqual(c.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_retry_same_key_and_payload_and_expiry(self):
        self.transport.return_value = ("RETRY", None, 60)
        self.sender.tick()
        self.now += 61
        self.sender.tick()
        self.assertEqual(self.transport.call_args_list[0], self.transport.call_args_list[1])
        self.now += MAX_AGE
        self.sender.tick()
        self.assertEqual(self.transport.call_count, 2)
        with self.jobs.transaction() as c:
            self.assertEqual(c.execute("SELECT state FROM notification_receipts").fetchone()[0], "UNCERTAIN")

    def test_configuration_scope_and_disable(self):
        self.cfg["recipients"] = {"operator@example.test": ["another"]}
        self.path.write_text(json.dumps(self.cfg))
        self.sender.tick()
        self.assertEqual(self.transport.call_count, 0)
        self.path.unlink()
        self.now += 10
        self.sender.tick()
        self.assertEqual(self.transport.call_count, 0)

    def test_delivery_history_and_html(self):
        result = {}
        record_delivery_event(result, "FAILED", self.item["at"])
        record_delivery_event(result, "SUCCEEDED", self.item["at"])
        self.assertEqual([v["sequence"] for v in result["qa_delivery_events"]], [1, 2])
        body = email_body({**self.item, "operation": "<script>"}, self.cfg["from"], "operator@example.test")
        self.assertIn("&lt;script&gt;", body["html"])
        self.assertNotIn("<script>", body["html"])
        self.assertIn("Project OS", body["text"])

    def test_invalid_config_is_optional(self):
        self.path.chmod(0o644)
        with self.assertRaises(PermissionError):
            config(self.root)
        self.sender.tick()
        self.transport.assert_not_called()
