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

    def status(self, *, linked=True, active="inactive", enabled=False, foreign=False, dropins=""):
        fields = dict(Id=UNIT, LoadState="loaded" if linked else "not-found",
                      FragmentPath=str(self.unit.parent / "foreign") if foreign else str(self.unit) if linked else "",
                      DropInPaths=dropins, NeedDaemonReload="no", ActiveState=active,
                      UnitFileState="enabled" if enabled else "linked" if linked else "")
        return SimpleNamespace(returncode=0, stdout="\n".join(f"{k}={v}" for k,v in fields.items()))

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
                         [("start", UNIT), ("stop", UNIT)])

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
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] != "show"], [("start", UNIT)])

    def test_timeout_reconciles_without_retry(self):
        call = Mock(side_effect=[self.status(), subprocess.TimeoutExpired("start", 1),
                                 self.status(active="active")])
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            operate(self.unit, "start", call)
        self.assertEqual([c.args for c in call.call_args_list if c.args[0] != "show"], [("start", UNIT)])

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
