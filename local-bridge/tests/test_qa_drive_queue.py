import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from project_os_bridge.core import Jobs, Policy
from project_os_bridge.qa_drive_queue import submit, recover, process_one
from project_os_bridge.android_qa import finalize_pending_locked


class DriveQueueTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.jobs = Jobs(Path(tmp.name), Policy([]))
        self.target = {"project": "demo", "head": "a" * 40, "repository_id": 123,
                       "pr": 5, "binding_sha256": "b" * 64}
        result = {"head": self.target["head"], "repository_id": 123,
                  "qa_finalization": {"state": "SUCCEEDED"}}
        with self.jobs.transaction() as c:
            c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                      ("job", "owner", "workspace", "workspace_execute", "key",
                       "SUCCEEDED", json.dumps(result), "now", "now"))

    def state(self):
        with self.jobs.transaction() as c:
            result = json.loads(c.execute("SELECT result FROM jobs WHERE id='job'").fetchone()[0])
        return result["qa_delivery_request"]["state"]

    def test_finalization_queues_delivery_atomically_only_on_success(self):
        # Exercise the actual finalizer transition and existing queue consumer.
        with self.jobs.transaction() as c:
            c.execute("CREATE TABLE IF NOT EXISTS workspace_inputs (job_id TEXT PRIMARY KEY, request TEXT)")
            result = {"head": self.target["head"], "repository_id": 123}
            c.execute("UPDATE jobs SET result=? WHERE id='job'", (json.dumps(result),))
            request = {"project": "demo", "profile": "expo-apk-qa",
                       "qa_signer_sha256": "c" * 64, "qa_plan_sha256": "d" * 64,
                       "delivery_target": self.target}
            c.execute("INSERT INTO workspace_inputs VALUES(?,?)", ("job", json.dumps(request)))
        backend = Mock()
        signer = Mock()
        signer.digest = "c" * 64
        signer.finalize_locked.return_value = {"signature_verified": True}
        backend.qa_signers = {"route": signer}
        backend.route.return_value = "route"
        backend.plan_digest.return_value = "d" * 64
        finalize_pending_locked(self.jobs, backend, enabled=lambda: True)
        self.assertEqual(self.state(), "QUEUED")
        finalize_pending_locked(self.jobs, backend, enabled=lambda: True)
        signer.finalize_locked.assert_called_once()
        delivery = Mock()
        process_one(self.jobs, delivery, enabled=lambda: True)
        self.assertEqual(self.state(), "SUCCEEDED")
        process_one(self.jobs, delivery, enabled=lambda: True)
        delivery.run_queued.assert_called_once()

    def test_submit_returns_before_effect_and_worker_runs_once(self):
        delivery = Mock()
        self.assertEqual(submit(self.jobs, "owner", "job", self.target), "QUEUED")
        delivery.run_queued.assert_not_called()
        self.assertEqual(submit(self.jobs, "owner", "job", self.target), "QUEUED")
        process_one(self.jobs, delivery, enabled=lambda: True)
        self.assertEqual(self.state(), "SUCCEEDED")
        process_one(self.jobs, delivery, enabled=lambda: True)
        delivery.run_queued.assert_called_once()
        self.assertEqual(submit(self.jobs, "owner", "job", self.target), "SUCCEEDED")

    def test_failure_and_explicit_reconciliation(self):
        delivery = Mock()
        delivery.run_queued.side_effect = RuntimeError("fixture")
        submit(self.jobs, "owner", "job", self.target)
        process_one(self.jobs, delivery, enabled=lambda: True)
        self.assertEqual(self.state(), "FAILED")
        self.assertEqual(submit(self.jobs, "owner", "job", self.target), "FAILED")
        self.assertEqual(submit(self.jobs, "owner", "job", self.target, reconcile_only=True), "QUEUED")

    def test_durable_delivery_failure_code_is_allowlisted(self):
        from project_os_bridge.drive_delivery import DriveDeliveryError
        delivery = Mock()
        delivery.run_queued.side_effect = DriveDeliveryError("DRIVE_HTTP_403")
        submit(self.jobs, "owner", "job", self.target)
        process_one(self.jobs, delivery, enabled=lambda: True)
        with self.jobs.transaction() as c:
            result = json.loads(c.execute("SELECT result FROM jobs WHERE id='job'").fetchone()[0])
        self.assertEqual(result["qa_delivery_request"]["error_code"], "DRIVE_HTTP_403")
        submit(self.jobs, "owner", "job", self.target, reconcile_only=True)
        delivery.run_queued.side_effect = RuntimeError("PRIVATE_TOKEN_DO_NOT_DISCLOSE")
        process_one(self.jobs, delivery, enabled=lambda: True)
        with self.jobs.transaction() as c:
            result = json.loads(c.execute("SELECT result FROM jobs WHERE id='job'").fetchone()[0])
        self.assertEqual(result["qa_delivery_request"]["error_code"], "QA_DELIVERY_FAILED")
        self.assertNotIn("PRIVATE_TOKEN_DO_NOT_DISCLOSE", json.dumps(result))

    def test_recovery_preserves_interruption(self):
        submit(self.jobs, "owner", "job", self.target)
        with self.jobs.transaction() as c:
            result = json.loads(c.execute("SELECT result FROM jobs WHERE id='job'").fetchone()[0])
            result["qa_delivery_request"]["state"] = "RUNNING"
            c.execute("UPDATE jobs SET result=? WHERE id='job'", (json.dumps(result),))
        recover(self.jobs)
        self.assertEqual(self.state(), "INTERRUPTED")
        delivery = Mock()
        process_one(self.jobs, delivery, enabled=lambda: True)
        delivery.run_queued.assert_not_called()
        with self.assertRaises(PermissionError):
            submit(self.jobs, "owner", "job", {**self.target, "pr": 6}, reconcile_only=True)
