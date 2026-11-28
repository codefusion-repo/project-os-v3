import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import threading

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
        self.sender.authorized = Mock(return_value=True)

    def test_acceptance_is_deduplicated_across_restart(self):
        self.sender.tick()
        self.assertEqual(self.transport.call_count, 1)
        another = NotificationSender(self.jobs, "actor", lambda: True,
                                      transport=self.transport, clock=lambda: self.now)
        another.events = Mock(return_value=[self.item])
        another.authorized = Mock(return_value=True)
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

    def test_rejection_after_ambiguous_attempt_is_not_definite_failure(self):
        self.transport.return_value = ("RETRY", None, 60)
        self.sender.tick()
        self.now += 61
        self.transport.return_value = ("FAILED", None, 0)
        self.sender.tick()
        with self.jobs.transaction() as c:
            self.assertEqual(c.execute("SELECT state FROM notification_receipts").fetchone()[0], "UNCERTAIN")

    def test_rate_limit_delays_other_events_and_survives_restart(self):
        self.transport.return_value = ("RATE_LIMITED", None, 60)
        self.sender.tick()
        self.now += 10
        self.sender.events.return_value = [{**self.item, "identity": "second"}]
        self.sender.tick()
        self.assertEqual(self.transport.call_count, 1)

    def test_credential_rotation_does_not_replay_uncertain_send(self):
        self.transport.return_value = ("RETRY", None, 60)
        self.sender.tick()
        self.now += 61
        self.cfg["api_key"] = "re_other_fixture"
        self.path.write_text(json.dumps(self.cfg))
        self.sender.tick()
        self.assertEqual(self.transport.call_count, 1)
        with self.jobs.transaction() as c:
            self.assertEqual(c.execute("SELECT state FROM notification_receipts").fetchone()[0], "UNCERTAIN")

    def test_grant_revoked_between_selection_and_send(self):
        self.sender.authorized.side_effect = [True, False]
        self.sender.tick()
        self.transport.assert_not_called()

    def test_network_io_does_not_hold_job_transaction(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("fixture timed out")
            return "ACCEPTED", "a"*36, 0
        self.sender.transport = slow
        thread = threading.Thread(target=self.sender.tick)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.jobs.transaction() as c:
                self.assertEqual(c.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_terminal_event_sources_and_exclusion(self):
        self.jobs.policy = Policy([("actor", "maintenance", "installation")])
        terminal = ("SUCCEEDED", "FAILED", "BLOCKED", "INTERRUPTED", "CANCELLED")
        at = self.item["at"]
        result = {"qa_finalization_at": at, "qa_finalization": {"state": "SUCCEEDED"},
                  "qa_delivery_events": [{"sequence": 1, "state": "FAILED", "at": at},
                                         {"sequence": 2, "state": "SUCCEEDED", "at": at}]}
        with self.jobs.transaction() as c:
            for i, state in enumerate(terminal):
                ident = format(i+1, "032x")
                c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                          (ident,"actor","workspace","workspace_execute",ident,state,
                           json.dumps(result if i == 0 else {}),at,at))
                c.execute("INSERT INTO events(job_id,state,at) VALUES(?,?,?)",(ident,state,at))
            for i, (owner, resource, workflow, state, stamp) in enumerate((
                    ("actor","disposable","probe_check","SUCCEEDED",at),
                    ("actor","workspace","codex_capabilities","SUCCEEDED",at),
                    ("other","workspace","workspace_execute","SUCCEEDED",at),
                    ("actor","workspace","workspace_execute","SUCCEEDED","2025-01-01T00:00:00+00:00"),
                    ("actor","workspace","workspace_execute","RUNNING",at))):
                ident = format(i+10,"032x")
                c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                          (ident,owner,resource,workflow,ident,state,"{}",stamp,stamp))
                c.execute("INSERT INTO events(job_id,state,at) VALUES(?,?,?)",(ident,state,stamp))
        self.jobs.policy = Policy([("actor","workspace_delivery","demo")])
        del self.sender.events
        with patch("project_os_bridge.workspace_jobs.require_workspace_job",
                   return_value={"project":"demo","profile":"expo-test"}):
            items = list(self.sender.events(self.cfg["enabled_since"]))
        self.assertEqual(len(items), 8)
        self.assertEqual({x["state"] for x in items if x["operation"] == "expo-test"}, set(terminal))
        self.assertEqual([x["state"] for x in items if x["operation"] == "qa-delivery"],
                         ["FAILED", "SUCCEEDED"])
        self.assertEqual([x["state"] for x in items if x["operation"] == "qa-signing"], ["SUCCEEDED"])


    def test_maintenance_sources_and_live_grant(self):
        from project_os_bridge.maintenance import request, save, FLAG
        # Use the real instance layout and schema; no maintenance is dispatched.
        state = self.root / "state"
        state.mkdir(mode=0o700)
        directory = self.root / "service" / "maintenance"
        directory.parent.mkdir(mode=0o700)
        directory.mkdir(mode=0o700)
        jobs = Jobs(state, Policy([("actor", "maintenance", "installation")]))
        sender = NotificationSender(jobs, "actor", lambda: True)
        (state / FLAG).touch(mode=0o600)
        for i, (outcome, at) in enumerate((
                ("SUCCEEDED", self.item["at"]),
                ("BLOCKED", self.item["at"]),
                ("LOCAL_RECOVERY_REQUIRED", self.item["at"]),
                ("RUNNING", self.item["at"]),
                ("SUCCEEDED", "2025-01-01T00:00:00+00:00"))):
            ident = format(i+1, "064x")
            req = request("update", "a"*40, "b"*40, "c"*64, 123, ident)
            save(directory / ("active.json" if i == 2 else ident + ".json"),
                 {"request": req, "state": outcome, "stage": "complete",
                  "flags": [], "previous": {"sha": "a"*40, "wheel_sha256": "d"*64},
                  "updated_at": at})
        items = list(sender.events(self.cfg["enabled_since"]))
        self.assertEqual({v["state"] for v in items}, {"SUCCEEDED", "BLOCKED", "LOCAL_RECOVERY_REQUIRED"})
        self.assertEqual(len(items), 3)
        self.assertTrue(all(sender.authorized(v) for v in items))
        (state / FLAG).unlink()
        self.assertFalse(sender.authorized(items[0]))
        self.assertEqual(list(sender.events(self.cfg["enabled_since"])), [])

    def test_fixed_https_transport_statuses(self):
        from project_os_bridge.notifications import send
        payload = email_body(self.item, self.cfg["from"], "operator@example.test")
        with patch("project_os_bridge.notifications.http.client.HTTPSConnection") as https:
            conn = https.return_value
            response = conn.getresponse.return_value
            for status, body, expected in (
                (200, b'{"id":"12345678-1234-1234-1234-123456789abc"}', "ACCEPTED"),
                (401, b'{}', "FAILED"),
                (409, b'{"name":"invalid_idempotent_request"}', "UNCERTAIN"),
                (409, b'{"name":"concurrent_idempotent_requests"}', "RETRY"),
                (429, b'{}', "RATE_LIMITED"),
                (503, b'{}', "RETRY"),
                (200, b'{"unexpected":true}', "RETRY")):
                response.status = status
                response.read.return_value = body
                response.getheader.return_value = "120"
                self.assertEqual(send("re_fixture_only", "a"*64, payload)[0], expected)
            https.assert_called_with("api.resend.com", timeout=3)
            args = conn.request.call_args.args
            self.assertEqual(args[:2], ("POST", "/emails"))
            self.assertEqual(args[3]["Idempotency-Key"], "a"*64)
            conn.getresponse.side_effect = TimeoutError()
            self.assertEqual(send("re_fixture_only", "a"*64, payload)[0], "RETRY")
