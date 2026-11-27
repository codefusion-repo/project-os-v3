import tempfile
import subprocess
import os
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from project_os_bridge.lifecycle import operate, UNIT, exclusive_lifecycle
from project_os_bridge.authenticated import serve_with_worker


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.unit = Path(directory.name) / UNIT
        self.unit.touch()

    def status(self, *, linked=True, active="inactive", enabled=False, foreign=False, dropins="", pending=False):
        fields = dict(Id=UNIT, LoadState="loaded" if linked else "not-found",
                      FragmentPath=str(self.unit.parent / "foreign") if foreign else str(self.unit) if linked else "",
                      DropInPaths=dropins, NeedDaemonReload="no", ActiveState=active,
                      UnitFileState="enabled" if enabled else "linked" if linked else "",
                      Job="42" if pending else "")
        return SimpleNamespace(returncode=0, stdout="\n".join(f"{k}={v}" for k,v in fields.items()))

    def test_empty_job_status_for_absent_inactive_and_active_units(self):
        for initial in (self.status(linked=False), self.status(),
                        self.status(active="active")):
            with self.subTest(output=initial.stdout):
                call = Mock(return_value=initial)
                self.assertFalse(operate(self.unit, "status", call)["pending_job"])
                self.assertIn("--all", call.call_args.args)

    def test_numeric_job_status(self):
        for value, pending in (("0", False), ("42", True), ("4294967295", True)):
            with self.subTest(value=value):
                initial = self.status()
                initial.stdout = initial.stdout.replace("Job=", "Job=" + value)
                self.assertEqual(operate(self.unit, "status", Mock(return_value=initial))["pending_job"], pending)

    def test_invalid_or_missing_job_status_never_mutates(self):
        for line in ("", "Job= ", "Job=-1", "Job=abc", "Job=１２",
                     "Job=4294967296", "Job=00000000000", "Job=0\nJob=42"):
            with self.subTest(line=line):
                initial = self.status()
                initial.stdout = initial.stdout.replace("Job=", line).rstrip("\n")
                call = Mock(return_value=initial)
                with self.assertRaises(RuntimeError):
                    operate(self.unit, "start", call)
                self.assertEqual(call.call_count, 1)

    def test_enable_existing_stopped_unit_is_noop(self):
        for active in ("inactive", "failed"):
            with self.subTest(active=active):
                call = Mock(return_value=self.status(active=active, enabled=True))
                self.assertTrue(operate(self.unit, "enable", call)["enabled"])
                self.assertEqual(call.call_count, 1)

    def test_enable_stopped_unenabled_unit_still_rejected(self):
        call = Mock(return_value=self.status())
        with self.assertRaisesRegex(RuntimeError, "live health"):
            operate(self.unit, "enable", call)
        self.assertEqual(call.call_count, 1)

    def test_link_idempotent_and_no_implicit_start(self):
        call = Mock(side_effect=[self.status(linked=False), SimpleNamespace(returncode=0),
                                 self.status(), self.status()])
        self.assertTrue(operate(self.unit, "link", call)["linked"])
        self.assertTrue(operate(self.unit, "link", call)["linked"])
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] != "show"],
                         [("link", str(self.unit))])

    def test_start_and_stop_are_explicit(self):
        call = Mock(side_effect=[self.status(), SimpleNamespace(returncode=0),
                                 self.status(active="active"), self.status(active="active"),
                                 SimpleNamespace(returncode=0), self.status()])
        self.assertEqual(operate(self.unit, "start", call)["active"], "active")
        self.assertEqual(operate(self.unit, "stop", call)["active"], "inactive")
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] != "show"],
                         [("start", "--job-mode=fail", UNIT), ("stop", "--job-mode=fail", UNIT)])

    def test_enable_disable_are_separate_and_opt_in(self):
        call = Mock(side_effect=[self.status(active="active"), SimpleNamespace(returncode=0),
                                 self.status(active="active", enabled=True),
                                 self.status(enabled=True), SimpleNamespace(returncode=0),
                                 self.status(linked=False)])
        self.assertTrue(operate(self.unit, "enable", call)["enabled"])
        self.assertFalse(operate(self.unit, "disable", call)["enabled"])
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] != "show"],
                         [("enable", str(self.unit)), ("disable", UNIT)])

    def test_foreign_or_overridden_unit_never_mutated(self):
        foreign = self.unit.parent / "foreign"
        foreign.touch()
        for initial in (self.status(foreign=True), self.status(dropins="/some/override.conf")):
            with self.subTest(initial=initial.stdout):
                call = Mock(return_value=initial)
                with self.assertRaises(PermissionError):
                    operate(self.unit, "stop", call)
                self.assertEqual(call.call_count, 1)

    def test_failed_or_transitioning_unit_not_restarted(self):
        for state in ("failed", "activating", "deactivating"):
            call = Mock(return_value=self.status(active=state))
            with self.assertRaises(RuntimeError):
                operate(self.unit, "start", call)
            self.assertEqual(call.call_count, 1)

    def test_mutation_failure_reconciles_without_retry(self):
        call = Mock(side_effect=[self.status(), SimpleNamespace(returncode=1), self.status()])
        with self.assertRaises(RuntimeError):
            operate(self.unit, "start", call)
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] != "show"], [("start", "--job-mode=fail", UNIT)])

    def test_timeout_reconciles_without_retry(self):
        call = Mock(side_effect=[self.status(), subprocess.TimeoutExpired("start", 1),
                                 self.status(active="active")])
        self.assertEqual(operate(self.unit, "start", call)["active"], "active")
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] != "show"], [("start", "--job-mode=fail", UNIT)])

    def test_timeout_pending_job_never_replayed(self):
        call = Mock(side_effect=[self.status(), subprocess.TimeoutExpired("start", 1),
                                 self.status(active="active", pending=True)])
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            operate(self.unit, "start", call)
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] != "show"],
                         [("start", "--job-mode=fail", UNIT)])
        call = Mock(return_value=self.status(pending=True))
        self.assertTrue(operate(self.unit, "status", call)["pending_job"])
        for action in ("link", "start", "stop", "reset-failed", "enable", "disable"):
            call.reset_mock()
            with self.assertRaisesRegex(RuntimeError, "Transition"):
                operate(self.unit, action, call)
            self.assertEqual(call.call_count, 1)

    def test_reset_failed_is_explicit_and_never_starts(self):
        call = Mock(side_effect=[self.status(active="failed"), SimpleNamespace(returncode=0),
                                 self.status(), self.status()])
        self.assertEqual(operate(self.unit, "reset-failed", call)["active"], "inactive")
        self.assertEqual(operate(self.unit, "reset-failed", call)["active"], "inactive")
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] != "show"],
                         [("reset-failed", UNIT)])

    def test_user_lifecycle_lock_excludes_second_controller(self):
        # Use only temporary synthetic state, not the actual user runtime directory.
        with patch("project_os_bridge.lifecycle.Path", return_value=self.unit.parent):
            with exclusive_lifecycle():
                with self.assertRaises(BlockingIOError):
                    with exclusive_lifecycle():
                        self.fail("second controller admitted")
            with exclusive_lifecycle():
                self.assertTrue((self.unit.parent / "project-os-bridge-lifecycle.lock").is_file())


class WorkerReadinessTests(unittest.TestCase):
    def exercise(self, failure=False):
        entered = threading.Event()
        order = []
        class Server:
            started = True
            should_exit = False
            def run(self):
                if not entered.wait(3):
                    raise RuntimeError("Test worker did not reach readiness")
        server = Server()
        def ready():
            order.append("tls")
            if failure:
                entered.set()
                raise RuntimeError("invalid metadata")
        def dispatch(*args, **kwargs):
            order.append("dispatch")
            server.should_exit = True
            entered.set()
        jobs = Mock()
        jobs.pending_effects.return_value = []
        verifier = Mock()
        verifier.enabled.return_value = True
        with patch("project_os_bridge.authenticated.run_pending", side_effect=dispatch):
            if failure:
                with self.assertRaises(RuntimeError):
                    serve_with_worker(server, jobs, verifier, None, readiness=ready)
            else:
                serve_with_worker(server, jobs, verifier, None, readiness=ready)
        return order

    def test_tls_verified_before_dispatch(self):
        self.assertEqual(self.exercise(), ["tls", "dispatch"])

    def test_invalid_tls_metadata_never_dispatches(self):
        self.assertEqual(self.exercise(failure=True), ["tls"])

    def test_supervised_candidate_reuses_worker_after_tls_and_stops_on_pending_effects(self):
        from project_os_bridge.core import Jobs, Policy
        from project_os_bridge.workspace_jobs import MARKER, RUNTIME
        from project_os_bridge.workspace_podman import WorkspacePodman
        from project_os_bridge.podman_context import PodmanContext
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "workspace"
            state.mkdir(mode=0o700)
            (state / MARKER).touch(mode=0o600)
            (state / RUNTIME).touch(mode=0o600)
            jobs = Jobs(state, Policy([]), workflows=("workspace_prepare", "workspace_execute"))
            verifier = SimpleNamespace(state_dir=root / "auth", enabled=lambda: True)
            context = Mock(spec=PodmanContext)
            context.identity.return_value = "c" * 64
            backend = WorkspacePodman(context, {"flutter-test":
                "localhost/project-os-mobile-ci@sha256:" + "a" * 64})
            entered = threading.Event()
            order = []
            class Server:
                started = True
                should_exit = False
                def run(self):
                    if not entered.wait(3):
                        raise RuntimeError("Test worker did not dispatch")
            server = Server()
            def ready():
                order.append("tls")
            def dispatch(actual_jobs, **kwargs):
                self.assertIs(actual_jobs, jobs)
                self.assertIs(kwargs["workspace_backend"], backend)
                self.assertTrue(kwargs["enabled"]())
                order.append("dispatch")
                entered.set()
            with patch("project_os_bridge.authenticated.run_pending", side_effect=dispatch), \
                 patch.object(jobs, "pending_effects", return_value=[{"synthetic": True}]):
                with self.assertRaises(RuntimeError):
                    serve_with_worker(server, jobs, verifier, None, readiness=ready,
                                      workspace_backend=backend)
            self.assertEqual(order, ["tls", "dispatch"])
            self.assertTrue(server.should_exit)

            with self.assertRaises(ValueError):
                serve_with_worker(server, jobs, verifier, None, workspace_backend=backend)
            with self.assertRaises(ValueError):
                serve_with_worker(server, jobs, verifier, "fixture", readiness=ready,
                                  workspace_backend=backend)
            with self.assertRaises(ValueError):
                serve_with_worker(server, jobs, SimpleNamespace(state_dir=state), None,
                                  readiness=ready, workspace_backend=backend)
            (state / MARKER).unlink()
            with self.assertRaises(PermissionError):
                serve_with_worker(server, jobs, verifier, None, readiness=ready,
                                  workspace_backend=backend)
