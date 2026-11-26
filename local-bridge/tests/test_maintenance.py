"""Disposable maintenance contract tests. No real systemd or network calls."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from project_os_bridge import maintenance as m

OLD = "1" * 40
NEW = "2" * 40
WHEEL = "3" * 64
PREVIOUS = {"sha": OLD, "wheel_sha256": "4" * 64}
TARGET = {"sha": NEW, "wheel_sha256": WHEEL}


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / "instance"
        self.kit = Path(tmp.name).resolve() / "kit"
        self.service = m.Maintenance(self.root, self.kit)
        for path in (self.root, self.service.state, self.root / "service", self.kit,
                     self.kit / "local-bridge", self.service.venv):
            path.mkdir(mode=0o700)
        m.save(self.service.venv / m.RECEIPT, PREVIOUS)
        for name in (m.FLAG, m.FLAGS[0], m.FLAGS[2]):
            (self.service.state / name).touch(mode=0o600)
        self.authorize = Mock()
        self.launch = patch.object(self.service, "launch").start()
        self.addCleanup(patch.stopall)

    def submit(self, key="request-1", **kw):
        args = dict(action="update", expected=OLD, target=NEW, wheel=WHEEL,
                    run_id=123, key=key, authorize=self.authorize)
        return self.service.submit(**{**args, **kw})

    def test_admission_replay_conflict_and_revocation(self):
        first = self.submit()
        self.assertEqual(first["state"], "ACCEPTED")
        self.assertEqual(first, self.submit())
        self.assertEqual(first, self.service.status("request-1"))
        self.launch.assert_called_once_with(m.request_id("request-1"))
        for kw in ({"key": "other"}, {"target": "5" * 40},
                   {"wheel": "../secret"}, {"run_id": True}, {"key": "../private"}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.submit(**kw)
        self.assertEqual(self.service.status("unknown"), {"state": "NOT_FOUND"})
        self.assertNotIn("request-1", json.dumps(first))
        self.assertNotIn(str(self.root), json.dumps(first))
        (self.service.state / m.FLAG).unlink()
        with self.assertRaises(PermissionError):
            self.submit()
        self.launch.assert_called_once()

    def test_revocation_at_dispatch_and_ambiguous_launch(self):
        self.authorize.side_effect = [None, PermissionError("DENIED")]
        with self.assertRaises(PermissionError):
            self.submit()
        self.assertEqual(self.service.status("request-1")["state"], "BLOCKED")
        self.launch.assert_not_called()
        self.authorize.side_effect = None
        self.launch.side_effect = subprocess.TimeoutExpired("systemd", 10)
        self.assertEqual(self.submit("next")["state"], "ACCEPTED")
        self.assertEqual(self.submit("next")["state"], "ACCEPTED")
        self.launch.assert_called_once()
        self.assertEqual(self.service.status("request-1")["state"], "BLOCKED")

    def test_default_deny_and_unsafe_marker(self):
        marker = self.service.state / m.FLAG
        marker.unlink()
        for make in (lambda: marker.symlink_to(self.service.state / m.FLAGS[0]),
                     lambda: marker.touch(mode=0o644)):
            make()
            self.assertFalse(self.service.enabled())
            with self.assertRaises(PermissionError):
                self.submit()
            marker.unlink()
        marker.touch(mode=0o600)
        (self.service.state / "fixture-image").touch(mode=0o600)
        self.assertFalse(self.service.enabled())
        self.launch.assert_not_called()

    def test_jobs_preflight_no_mutation(self):
        db = self.service.state / "jobs.sqlite3"
        db.touch(mode=0o600)
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE jobs (state TEXT)")
            conn.execute("CREATE TABLE fixture_effects (resolved_at TEXT)")
            conn.execute("INSERT INTO jobs VALUES ('QUEUED')")
        before = db.read_bytes()
        with self.assertRaises(RuntimeError):
            self.service.idle_jobs()
        self.assertEqual(db.read_bytes(), before)
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE jobs SET state='SUCCEEDED'")
            conn.execute("INSERT INTO fixture_effects VALUES (NULL)")
        with self.assertRaises(RuntimeError):
            self.service.idle_jobs()
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE fixture_effects SET resolved_at='fixture'")
        self.service.idle_jobs()

    def run_fixture(self, *, rollback=False, fail=None, revoke=False):
        if rollback:
            m.save(self.service.venv / m.RECEIPT, TARGET)
            result = self.submit(action="rollback", expected=NEW, target=OLD,
                                 wheel=PREVIOUS["wheel_sha256"], run_id=None)
            head = NEW
        else:
            result = self.submit()
            head = OLD
        events = []
        service = self.service
        flags = [m.FLAGS[0], m.FLAGS[2]]
        head_now = [head]

        def preflight(record):
            record["flags"] = flags
            if revoke:
                (service.state / m.FLAG).unlink()
            return head, "main"

        def lifecycle(action):
            events.append(action)
            self.assertFalse((service.state / m.FLAGS[0]).exists())
            if action == fail:
                raise RuntimeError("fixture failure")

        def git(kit, *args):
            self.assertEqual(kit, self.kit)
            self.assertEqual(args[:3], ("merge", "--ff-only", "--no-overwrite-ignore"))
            head_now[0] = NEW
            events.append("fast-forward")
            return ""

        def coordinator(revision, action, *args):
            self.assertEqual(revision, NEW)
            self.assertFalse((service.state / m.FLAGS[0]).exists())
            events.append(action)
            if action == fail:
                raise RuntimeError("fixture failure")
            if action in ("upgrade", "restore"):
                m.save(service.venv / m.RECEIPT, PREVIOUS if rollback else TARGET)

        def ready():
            events.append("readiness")
            self.assertFalse((service.state / m.FLAGS[0]).exists())
            if fail == "readiness":
                raise RuntimeError("fixture failure")

        primary = service.state / "security-audit.jsonl"
        primary.touch(mode=0o600)
        primary.write_bytes(b'{"at":"fixture","event":"mcp_http","status":200}\n')
        oauth = service.state / "oauth-audit.jsonl"
        oauth.touch(mode=0o600)
        audit = b'{"at":"2026-01-01T00:00:00+00:00","event":"mcp_http","status":200,"auth_outcome":"TOKEN_ACCEPTED"}\n'
        oauth.write_bytes(audit)
        with patch.object(service, "preflight", side_effect=preflight), \
                patch.object(service, "idle_jobs"), \
                patch.object(service, "checkout", side_effect=lambda: (head_now[0], "main")), \
                patch.object(service, "lifecycle", side_effect=lifecycle), \
                patch.object(service, "coordinator", side_effect=coordinator), \
                patch.object(service, "readiness", side_effect=ready), \
                patch.object(m, "git", side_effect=git):
            ok = service.run(result["id"])
        # Reconstruct a fresh object to simulate the service's new process.
        fresh = m.Maintenance(self.root, self.kit)
        status = fresh.status("request-1")
        if revoke:
            self.assertFalse(ok)
            self.assertEqual(status["state"], "BLOCKED")
            self.assertEqual(events, [])
            self.assertTrue((service.state / m.FLAGS[0]).exists())
        elif fail:
            self.assertFalse(ok)
            self.assertEqual(status["state"], "LOCAL_RECOVERY_REQUIRED")
            self.assertFalse((service.state / m.FLAGS[0]).exists())
            self.assertEqual(events[-1], fail)
            with self.assertRaises(ValueError):
                service.run(result["id"])
        else:
            self.assertTrue(ok)
            self.assertEqual(status["state"], "SUCCEEDED")
            self.assertEqual(status["readiness_basis"], "local_tls_and_anonymous_401")
            self.assertEqual(events, ["stop", "fence", "restore", "release", "start", "readiness"]
                             if rollback else ["stop", "fast-forward", "fence", "upgrade",
                                               "release", "start", "readiness"])
            self.assertEqual(m.receipt(service.venv), PREVIOUS if rollback else TARGET)
            for name in flags:
                self.assertEqual(m.private_bytes(service.state / name, 0), b"")
            self.assertFalse((service.state / m.FLAGS[1]).exists())
            if rollback:
                self.assertFalse(oauth.exists())
                self.assertEqual((service.store / ("oauth-" + result["id"] + ".jsonl")).read_bytes(), audit)
            else:
                self.assertEqual(oauth.read_bytes(), audit)
            self.assertEqual(primary.read_bytes(), b'{"at":"fixture","event":"mcp_http","status":200}\n')

    def test_update_order_and_persistence(self):
        self.run_fixture()

    def test_rollback_order_and_audit_preservation(self):
        self.run_fixture(rollback=True)

    def test_failure_after_fence_requires_local_recovery(self):
        self.run_fixture(fail="upgrade")

    def test_readiness_failure_does_not_restore_opt_ins(self):
        self.run_fixture(fail="readiness")

    def test_revoked_before_quiescence(self):
        self.run_fixture(revoke=True)

    def test_fixed_transient_service_command(self):
        # Inspect the real launch argv without calling the host's service manager.
        with patch.object(m, "command") as cmd:
            m.Maintenance.launch(self.service, m.request_id("request-1"))
        args = cmd.call_args.args
        self.assertEqual(args[:5], ("/usr/bin/systemd-run", "--user", "--collect",
                                    "--no-block", "--unit=" + m.UNIT))
        self.assertIn("--property=Type=exec", args)
        self.assertIn("/usr/bin/python3", args)
        self.assertNotIn("--scope", args)
        self.assertNotIn("request-1", args)

    def test_corrupt_status_is_sanitized(self):
        self.submit()
        self.service.active.write_text("private-payload")
        with self.assertRaisesRegex(ValueError, "^MAINTENANCE_STATUS_UNAVAILABLE$"):
            self.service.status("request-1")


class ApprovalTests(unittest.TestCase):
    def evidence(self):
        run = {"id": 123, "workflow_id": m.WORKFLOW_ID, "path": m.WORKFLOW_PATH,
               "repository": {"id": m.REPO_ID}, "head_repository": {"id": m.REPO_ID},
               "event": "push", "head_branch": "main", "head_sha": NEW,
               "status": "completed", "conclusion": "success", "check_suite_id": 456}
        required = [{"context": name, "integration_id": m.APP_ID} for name in ("tests", "probe", "other")]
        rules = [{"type": "pull_request"},
                 {"type": "required_status_checks", "parameters": {"required_status_checks": required}}]
        checks = [{"name": row["context"], "app": {"id": m.APP_ID}, "head_sha": NEW,
                   "check_suite": {"id": 456}, "status": "completed", "conclusion": "success"} for row in required]
        return [run, rules, {"total_count": len(checks), "check_runs": checks}, {"object": {"sha": NEW}}]

    def check(self, evidence):
        req = m.request("update", OLD, NEW, WHEEL, 123, m.request_id("test"))
        with patch.object(m, "api", side_effect=evidence):
            m.approved_main(req)

    def test_approved_and_wrong_run_check_suite_or_main(self):
        self.check(self.evidence())
        for index, field, value in ((0, "event", "pull_request"), (0, "head_sha", OLD),
                                    (0, "conclusion", "failure"), (2, "total_count", 4),
                                    (3, "object", {"sha": OLD})):
            evidence = self.evidence()
            evidence[index][field] = value
            with self.assertRaises(ValueError):
                self.check(evidence)
        for field, value in (("check_suite", {"id": 789}), ("conclusion", "failure"),
                             ("app", {"id": 1})):
            evidence = self.evidence()
            evidence[2]["check_runs"][0][field] = value
            with self.assertRaises(ValueError):
                self.check(evidence)
