import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from project_os_bridge.diagnostics import (
    Diagnostics, FLAG, bounded_text, listener_counts, mount_counts, process_observations,
)
from project_os_bridge.core import Jobs, Policy


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.verifier = SimpleNamespace(state_dir=self.state, subject="user_fixture")
        self.diagnostics = Diagnostics(self.verifier, self.root)

    def test_marker_denies_missing_unsafe_and_fixture(self):
        flag = self.state / FLAG
        self.assertFalse(self.diagnostics.enabled())
        flag.symlink_to(self.root / "missing")
        self.assertFalse(self.diagnostics.enabled())
        flag.unlink()
        flag.touch(mode=0o600)
        self.assertTrue(self.diagnostics.enabled())
        flag.chmod(0o644)
        self.assertFalse(self.diagnostics.enabled())
        flag.chmod(0o600)
        flag.write_text("not empty")
        self.assertFalse(self.diagnostics.enabled())
        flag.write_text("")
        (self.state / "fixture-image").touch(mode=0o600)
        self.assertFalse(self.diagnostics.enabled())

    def test_private_read_limits_and_no_follow(self):
        path = self.state / "data"
        path.touch(mode=0o600)
        path.write_text("12345")
        self.assertEqual(bounded_text(path, 5, private=True), "12345")
        with self.assertRaises(ValueError):
            bounded_text(path, 4, private=True)
        alias = self.state / "alias"
        alias.symlink_to(path)
        with self.assertRaises(OSError):
            bounded_text(alias, private=True)

    def test_mount_aggregation_never_returns_paths_or_sources(self):
        raw = "\n".join((
            "1 0 0:1 / / rw - ext4 synthetic-root rw",
            "2 1 0:2 / /usr/lib/wsl/drivers ro - 9p private-source ro",
            "3 1 0:2 /private /secret-path rw shared:7 - 9p private-source rw",
        ))
        result = mount_counts(raw)
        self.assertEqual(result["host_backed_count"], 2)
        self.assertEqual(result["host_device_mount_count"], 2)
        self.assertEqual(result["host_subroot_count"], 1)
        self.assertEqual(result["host_shared_count"], 1)
        self.assertTrue(result["wsl_driver_path_seen"])
        self.assertNotIn("private-source", json.dumps(result))
        self.assertNotIn("secret-path", json.dumps(result))
        with self.assertRaises(ValueError):
            mount_counts("malformed")

    def test_process_capabilities_are_observations(self):
        raw = "CapPrm: 0\nCapEff: 1\nCapAmb: 0\nNoNewPrivs: 0\nSeccomp: 2"
        result = process_observations(raw)
        self.assertFalse(result["capabilities_absent"])
        self.assertFalse(result["no_new_privileges"])
        self.assertEqual(result["seccomp_mode"], 2)
        with self.assertRaises(ValueError):
            process_observations(raw + "\nCapEff: 0")

    def test_listener_scope_and_no_addresses(self):
        raw = ("sl local_address rem_address st\n"
               "0: 0100007F:223D 00000000:0000 0A\n"
               "1: 00000000:223D 00000000:0000 0A\n"
               "2: 00000000:0050 00000000:0000 0A\n"
               "3: 0100007F:223D 00000000:0000 01\n")
        self.assertEqual(listener_counts(raw), (1, 1))
        ipv6 = "sl local_address rem_address st\n0: " + "0" * 32 + ":223D " + "0" * 32 + ":0000 0A"
        self.assertEqual(listener_counts(ipv6, ipv6=True), (0, 1))

    def test_jobs_read_only_and_caller_scoped(self):
        self.assertEqual(self.diagnostics.jobs(), {"database": "not_created"})
        self.assertFalse((self.state / "jobs.sqlite3").exists())
        jobs = Jobs(self.state, Policy((actor, "submit", "disposable")
                    for actor in ("user_fixture", "user_other")))
        first = jobs.submit("user_fixture", "disposable", "probe_check", "private-key-one")
        second = jobs.submit("user_other", "disposable", "probe_check", "private-key-two")
        before = jobs.db.read_bytes()
        result = self.diagnostics.jobs()
        self.assertEqual(result["counts"]["QUEUED"], 1)
        self.assertEqual(result["unresolved_effects"], 0)
        self.assertEqual(jobs.db.read_bytes(), before)
        for secret in (first, second, "private-key", "user_fixture", "user_other"):
            self.assertNotIn(secret, json.dumps(result))
        jobs.db.unlink()
        jobs.db.symlink_to(self.root / "missing")
        self.assertEqual(self.diagnostics.collect("jobs")["status"], "unavailable")

    def test_jobs_include_workspace_without_other_caller_data(self):
        jobs = Jobs(self.state, Policy([("user_fixture", "submit", "disposable")]))
        own = jobs.submit("user_fixture", "disposable", "probe_check", "probe")
        with jobs.transaction() as conn:
            for job_id, actor, resource in (("workspace-own", "user_fixture", "workspace"),
                                            ("workspace-other", "user_other", "workspace")):
                conn.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                             (job_id, actor, resource, "workspace_execute", job_id,
                              "RUNNING", None, "stamp", "stamp"))
                conn.execute("INSERT INTO fixture_effects(job_id,token,context_id) VALUES(?,?,?)",
                             (job_id, "token", "context"))
        before = jobs.db.read_bytes()
        result = self.diagnostics.jobs()
        self.assertEqual(result["counts"]["QUEUED"], 1)
        self.assertEqual(result["counts"]["RUNNING"], 1)
        self.assertEqual(result["unresolved_effects"], 1)
        self.assertEqual(jobs.db.read_bytes(), before)
        for private in (own, "workspace-own", "workspace-other", "user_fixture", "user_other"):
            self.assertNotIn(private, json.dumps(result))

    def test_audit_aggregates_without_raw_records(self):
        path = self.state / "security-audit.jsonl"
        self.assertEqual(self.diagnostics.audit(), {"audit": "not_created"})
        path.touch(mode=0o600)
        path.write_text(json.dumps({"at": "private-time", "event": "mcp_http", "status": 403}) + "\n")
        self.assertEqual(self.diagnostics.audit()["http_status_counts"], {"403": 1})
        # The exact legacy collector schema remains usable even after the
        # new runtime writes an OAuth observation to its separate file.
        from project_os_bridge.security import Audit
        from project_os_bridge.workos_auth import AuthOutcome
        audit = Audit(self.state)
        audit.record(401, outcome=AuthOutcome.TOKEN_EXPIRED)
        self.assertEqual(self.diagnostics.audit(), {"audit": "observed",
                                                   "http_status_counts": {"403": 1, "401": 1}})
        self.assertEqual(set(json.loads(path.read_text().splitlines()[-1])),
                         {"at", "event", "status"})
        self.assertNotIn("TOKEN_EXPIRED", json.dumps(self.diagnostics.audit()))
        path.write_text(json.dumps({"at": "private-time", "event": "mcp_http", "status": 403, "secret": "private"}) + "\n")
        self.assertEqual(self.diagnostics.collect("audit")["status"], "unavailable")

    def test_failure_and_invalid_section_do_not_leak(self):
        with patch.object(self.diagnostics, "service", side_effect=PermissionError("/private/path")):
            result = self.diagnostics.collect("service")
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("private", json.dumps(result))
        with self.assertRaises(ValueError):
            self.diagnostics.collect("../../etc/shadow")

    def test_service_uses_exact_unit_read_only(self):
        from unittest.mock import Mock
        result = {"linked": True, "active": "active", "enabled": False, "pending_job": False}
        with patch("project_os_bridge.diagnostics.prepared_unit", return_value=Path("/fixed")) as prepare, \
                patch("project_os_bridge.diagnostics.snapshot", return_value=result) as snap:
            self.assertEqual(self.diagnostics.service(), result)
            prepare.assert_called_once_with(self.root)
            with patch("project_os_bridge.diagnostics.systemctl", return_value=Mock()) as call:
                snap.call_args.args[1]("show", "fixed")
                call.assert_called_once_with("show", "fixed", timeout=3)

    def test_network_only_fixed_loopback_with_verified_metadata(self):
        from unittest.mock import Mock
        self.diagnostics.context = Mock()
        with patch("project_os_bridge.diagnostics.bounded_text", return_value="inventory"), \
                patch("project_os_bridge.diagnostics.listener_counts", side_effect=[(1, 0), (0, 0)]), \
                patch("project_os_bridge.diagnostics.read_metadata", return_value={"resource": "fixture"}) as read, \
                patch("project_os_bridge.diagnostics.verify_metadata") as verify, \
                patch("project_os_bridge.diagnostics.http.client.HTTPSConnection") as https:
            https.return_value.getresponse.return_value.status = 401
            result = self.diagnostics.network()
            self.assertTrue(result["metadata_verified"])
            self.assertTrue(result["unauthenticated_401"])
            read.assert_called_once_with(self.diagnostics.context)
            verify.assert_called_once_with({"resource": "fixture"}, self.verifier)
            https.assert_called_once_with("127.0.0.1", 8765, timeout=2, context=self.diagnostics.context)
            https.return_value.close.assert_called_once()
        with patch("project_os_bridge.diagnostics.bounded_text", return_value="inventory"), \
                patch("project_os_bridge.diagnostics.listener_counts", side_effect=[(1, 1), (0, 0)]), \
                patch("project_os_bridge.diagnostics.read_metadata") as read:
            self.assertFalse(self.diagnostics.network()["metadata_verified"])
            read.assert_not_called()
