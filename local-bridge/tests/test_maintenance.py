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

    def test_wrong_approved_digest_blocks_before_quiescence(self):
        # Real preflight and run state machine; only external dependencies are
        # doubled. A syntactically valid but different digest must not cause
        # service, checkout, fence, rollback, or opt-in changes.
        result = self.submit(wheel="5" * 64)
        m.save(self.root / "service/runtime.json", {"image": None})
        markers = {name: (self.service.state / name).read_bytes()
                   for name in (m.FLAG, m.FLAGS[0], m.FLAGS[2])}
        evidence = approval_evidence()
        with patch.object(self.service, "lifecycle") as lifecycle, \
                patch.object(self.service, "idle_jobs"), \
                patch.object(self.service, "checkout", return_value=(OLD, "main")), \
                patch.object(self.service, "coordinator") as coordinator, \
                patch.object(m, "git") as git, \
                patch.object(m, "api", side_effect=evidence):
            self.assertFalse(self.service.run(result["id"]))
        lifecycle.assert_called_once_with("status")
        coordinator.assert_not_called()
        git.assert_not_called()
        self.assertEqual(self.service.status("request-1")["state"], "BLOCKED")
        self.assertEqual(self.service.status("request-1")["stage"], "preflight")
        self.assertEqual(self.service.status("request-1")["diagnostic"]["step"], "wheel_evidence")
        self.assertEqual(m.receipt(self.service.venv), PREVIOUS)
        for name, before in markers.items():
            self.assertEqual((self.service.state / name).read_bytes(), before)
        self.assertFalse((self.service.state / m.FLAGS[1]).exists())
        self.assertFalse((self.service.venv.parent / ".venv-install.rollback").exists())
        self.assertFalse((self.service.venv.parent / ".venv-install.guard").exists())

    def test_rate_limit_blocks_before_quiescence_with_durable_diagnostic(self):
        result = self.submit()
        m.save(self.root / "service/runtime.json", {"image": None})
        with patch.object(self.service, "lifecycle") as lifecycle, \
                patch.object(self.service, "idle_jobs"), \
                patch.object(self.service, "checkout", return_value=(OLD, "main")), \
                patch.object(self.service, "coordinator") as coordinator, \
                patch.object(m, "gh_request", return_value={
                    "complete": False, "error": "GH_RATE_LIMIT", "http_status": 403}) as request:
            self.assertFalse(self.service.run(result["id"]))
        lifecycle.assert_called_once_with("status")
        request.assert_called_once()
        coordinator.assert_not_called()
        self.assertEqual(self.service.status("request-1")["diagnostic"],
                         {"step": "github_run", "code": "GITHUB_RATE_LIMIT", "exit_code": 403})
        self.assertEqual(m.receipt(self.service.venv), PREVIOUS)

    def test_default_deny_and_unsafe_marker(self):
        marker = self.service.state / m.FLAG
        marker.unlink()
        def unsafe_mode():
            marker.touch(mode=0o600)
            # Installer tests run under umask 077; force the negative mode.
            marker.chmod(0o644)
        for make in (lambda: marker.symlink_to(self.service.state / m.FLAGS[0]), unsafe_mode):
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
            conn.execute("CREATE TABLE jobs (state TEXT, result TEXT)")
            conn.execute("CREATE TABLE fixture_effects (resolved_at TEXT)")
            conn.execute("INSERT INTO jobs(state) VALUES ('QUEUED')")
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
        for delivery_state in ("QUEUED", "RUNNING"):
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE jobs SET result=?", (json.dumps({"qa_delivery_request":
                    {"state": delivery_state}}),))
            before = db.read_bytes()
            with self.assertRaises(RuntimeError):
                self.service.idle_jobs()
            self.assertEqual(before, db.read_bytes())
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE jobs SET result=?", (json.dumps({"qa_delivery_request":
                {"state": "INTERRUPTED"}}),))
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

    def test_preflight_failure_persists_safe_code_and_exit_status(self):
        result = self.submit()
        with patch.object(self.service, "lifecycle", side_effect=m.CommandFailure("COMMAND_FAILED", 17)), \
                self.assertLogs(m.LOG, "WARNING") as logs:
            self.assertFalse(self.service.run(result["id"]))
        status = self.service.status("request-1")
        self.assertEqual(status["diagnostic"], {"step": "lifecycle", "code": "COMMAND_FAILED", "exit_code": 17})
        self.assertIn("step=lifecycle", " ".join(logs.output))
        self.assertEqual(m.Maintenance(self.root, self.kit).status("request-1"), status)
        self.assertEqual(m.receipt(self.service.venv), PREVIOUS)

    def test_failure_does_not_disclose_exception_or_raw_command(self):
        result = self.submit()
        with patch.object(self.service, "lifecycle", side_effect=RuntimeError("secret-fixture-payload")), \
                self.assertLogs(m.LOG, "WARNING") as logs:
            self.assertFalse(self.service.run(result["id"]))
        self.assertNotIn("secret-fixture-payload", json.dumps(self.service.status("request-1")))
        self.assertNotIn("secret-fixture-payload", self.service.active.read_text())
        self.assertNotIn("secret-fixture-payload", (self.service.store / (result["id"] + ".diagnostic.json")).read_text())
        self.assertNotIn("secret-fixture-payload", " ".join(logs.output))
        with patch.object(m.subprocess, "run", return_value=subprocess.CompletedProcess([], 23, b"secret")):
            with self.assertRaises(m.CommandFailure) as caught:
                m.command("/private/path", "secret-fixture-payload")
        self.assertEqual(caught.exception.exit_code, 23)
        self.assertNotIn("secret", str(caught.exception))

    def test_diagnostics_preserve_legacy_record_schema_and_history(self):
        result = self.submit()
        with patch.object(self.service, "lifecycle", side_effect=m.CommandFailure("COMMAND_FAILED", 17)):
            self.assertFalse(self.service.run(result["id"]))
        record = m.read_json(self.service.active)
        # Exact schema used by the previous runtime, including rollback readers.
        self.assertEqual(set(record), {"request", "state", "stage", "flags", "previous", "updated_at"})
        diagnostic = self.service.status("request-1")["diagnostic"]
        self.submit("next")
        self.assertEqual(self.service.status("request-1")["diagnostic"], diagnostic)
        self.assertNotIn("diagnostic", self.service.status("next"))
        path = self.service.store / (result["id"] + ".diagnostic.json")
        evidence = m.read_json(path)
        evidence["updated_at"] = "stale"
        m.save(path, evidence)
        self.assertNotIn("diagnostic", self.service.status("request-1"))
        self.assertEqual(self.service.status("request-1")["state"], "BLOCKED")

    def test_empty_git_ancestor_reports_specific_cause_without_mutation(self):
        result = self.submit()
        git_marker = self.root.parent / ".git"
        git_marker.mkdir()
        with patch.object(self.service, "lifecycle") as lifecycle:
            self.assertFalse(self.service.run(result["id"]))
        lifecycle.assert_not_called()
        self.assertEqual(self.service.status("request-1")["diagnostic"],
                         {"step": "lifecycle", "code": "INSTANCE_INSIDE_GIT", "exit_code": None})
        self.assertTrue(git_marker.is_dir())
        self.assertEqual(m.receipt(self.service.venv), PREVIOUS)

    def test_corrupt_status_is_sanitized(self):
        self.submit()
        self.service.active.write_text("private-payload")
        with self.assertRaisesRegex(ValueError, "^MAINTENANCE_STATUS_UNAVAILABLE$"):
            self.service.status("request-1")


def approval_evidence():
    run = {"id": 123, "workflow_id": m.WORKFLOW_ID, "path": m.WORKFLOW_PATH,
           "repository": {"id": m.REPO_ID}, "head_repository": {"id": m.REPO_ID},
           "event": "push", "head_branch": "main", "head_sha": NEW,
           "status": "completed", "conclusion": "success", "check_suite_id": 456,
           "run_attempt": 2}
    required = [{"context": name, "integration_id": m.APP_ID} for name in ("tests", "probe", "other")]
    rules = [{"type": "pull_request"},
             {"type": "required_status_checks", "parameters": {"required_status_checks": required}}]
    checks = [{"name": row["context"], "app": {"id": m.APP_ID}, "head_sha": NEW,
               "check_suite": {"id": 456}, "status": "completed", "conclusion": "success"} for row in required]
    artifact = {"name": "maintenance-wheel-2-" + WHEEL, "expired": False,
                "workflow_run": {"id": 123, "repository_id": m.REPO_ID,
                                 "head_repository_id": m.REPO_ID,
                                 "head_branch": "main", "head_sha": NEW}}
    return [run, rules, {"total_count": len(checks), "check_runs": checks},
            {"total_count": 1, "artifacts": [artifact]}, {"object": {"sha": NEW}}]


class TransportTests(unittest.TestCase):
    def test_standalone_host_python_loads_shared_transport(self):
        import sys
        script = Path(m.__file__).resolve()
        result = subprocess.run([sys.executable, "-I", "-B", str(script), "--help"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=15, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"--run", result.stdout)

    def test_canonical_authenticated_get_and_no_anonymous_fallback(self):
        config = Path("/fixture/gh")
        with patch.object(m, "gh_request", return_value={"complete": True, "data": {"ok": True}}) as call:
            self.assertEqual(m.api("/actions/runs/123", config), {"ok": True})
            call.assert_called_once_with(config, "repos/" + m.REPO + "/actions/runs/123", strict=True)
            for path in ("https://other.example", "/issues/1", "/actions/runs/123?other=1", "/../private"):
                with self.assertRaises(ValueError):
                    m.api(path, config)
            call.assert_called_once()
        for error, status, expected in (
                ("GH_RATE_LIMIT", 403, "GITHUB_RATE_LIMIT"),
                ("GH_RATE_LIMIT", 429, "GITHUB_RATE_LIMIT"),
                ("GH_AUTH_REQUIRED", 401, "GITHUB_AUTH_REQUIRED"),
                ("GH_HTTP_ERROR", 403, "GITHUB_HTTP_ERROR"),
                ("GH_CONFIG_UNAVAILABLE", None, "GITHUB_CONFIG_UNAVAILABLE"),
                ("GH_INCOMPLETE_RESPONSE", 200, "GITHUB_EVIDENCE_INVALID")):
            with patch.object(m, "gh_request", return_value={
                    "complete": False, "error": error, "http_status": status,
                    "private": "secret-fixture-payload"}) as call:
                with self.assertRaises(m.CommandFailure) as caught:
                    m.api("/actions/runs/123", config)
                self.assertEqual(caught.exception.code, expected)
                self.assertEqual(caught.exception.exit_code, status)
                self.assertNotIn("secret-fixture-payload", str(caught.exception))
                call.assert_called_once()

    def test_shared_transport_strict_headers_and_json(self):
        from project_os_bridge.github_transport import _http_result
        for raw, error in (
                (b"HTTP/2.0 403 Forbidden\r\nX-RateLimit-Remaining: 0\r\n\r\nprivate", "GH_RATE_LIMIT"),
                (b"HTTP/2.0 429 Too Many Requests\r\n\r\nprivate", "GH_RATE_LIMIT"),
                (b"HTTP/2.0 401 Unauthorized\r\n\r\nprivate", "GH_AUTH_REQUIRED"),
                (b'HTTP/2.0 200 OK\r\nLink: private\r\n\r\n{"id":1}', "GH_INCOMPLETE_RESPONSE"),
                (b'HTTP/2.0 200 OK\r\n\r\n{"id":1,"id":2}', "GH_UNAVAILABLE_OR_INVALID_JSON")):
            result = _http_result(raw, 0, strict=True)
            self.assertFalse(result["complete"])
            self.assertEqual(result["error"], error)
            self.assertNotIn("private", str(result))

    def test_shared_transport_uses_only_private_cli_profile(self):
        from project_os_bridge import github_transport as transport
        import io
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder).resolve()
            proc = Mock()
            proc.stdout = io.BytesIO(b'HTTP/2.0 200 OK\r\n\r\n{"id":1}')
            proc.wait.return_value = 0
            context = Mock()
            context.__enter__ = Mock(return_value=proc)
            context.__exit__ = Mock(return_value=False)
            with patch.dict(os.environ, {"GH_TOKEN": "secret", "GH_DEBUG": "api"}), \
                    patch.object(transport.subprocess, "Popen", return_value=context) as launch:
                self.assertEqual(transport.gh_request(config, "repos/" + m.REPO + "/actions/runs/123",
                                                     strict=True), {"complete": True, "data": {"id": 1}})
            self.assertEqual(launch.call_args.kwargs["env"]["GH_CONFIG_DIR"], str(config))
            self.assertEqual(launch.call_args.kwargs["env"]["HOME"], str(config))
            self.assertNotIn("GH_TOKEN", launch.call_args.kwargs["env"])
            self.assertNotIn("GH_DEBUG", launch.call_args.kwargs["env"])
            self.assertIn("GET", launch.call_args.args[0])
            self.assertNotIn("secret", str(launch.call_args))
            config.chmod(0o755)
            with patch.object(transport.subprocess, "Popen") as launch:
                self.assertEqual(transport.gh_request(config, "repos/" + m.REPO + "/actions/runs/123",
                                                     strict=True)["error"], "GH_CONFIG_UNAVAILABLE")
                launch.assert_not_called()


class ApprovalTests(unittest.TestCase):
    def evidence(self):
        return approval_evidence()

    def check(self, evidence):
        req = m.request("update", OLD, NEW, WHEEL, 123, m.request_id("test"))
        with patch.object(m, "api", side_effect=evidence):
            m.approved_main(req, Path('/fixture/gh'))

    def test_approved_and_wrong_run_check_suite_or_main(self):
        self.check(self.evidence())
        for index, field, value in ((0, "event", "pull_request"), (0, "head_sha", OLD),
                                    (0, "conclusion", "failure"), (2, "total_count", 4),
                                    (4, "object", {"sha": OLD})):
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

    def test_wheel_evidence_must_be_unique_current_and_exact(self):
        for field, value in (("name", "maintenance-wheel-1-" + WHEEL),
                             ("name", "maintenance-wheel-2-" + "5" * 64),
                             ("expired", True)):
            evidence = self.evidence()
            evidence[3]["artifacts"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.check(evidence)
        for field, value in (("id", 124), ("repository_id", 1),
                             ("head_repository_id", 1), ("head_branch", "other"),
                             ("head_sha", OLD)):
            evidence = self.evidence()
            evidence[3]["artifacts"][0]["workflow_run"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(evidence)
        for count in (0, 2):
            evidence = self.evidence()
            evidence[3]["artifacts"] *= count
            evidence[3]["total_count"] = count
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.check(evidence)
        evidence = self.evidence()
        evidence[3]["total_count"] = 2
        with self.assertRaises(ValueError):
            self.check(evidence)
