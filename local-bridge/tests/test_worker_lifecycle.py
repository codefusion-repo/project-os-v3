"""Lifecycle tests for the actual HTTP worker orchestration."""
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from project_os_bridge.authenticated import serve_with_worker, exclusive_http_service
from project_os_bridge.worker import WorkerBusy


class FakeServer:
    def __init__(self):
        self.should_exit = False
        self.started = False
        self.entered = threading.Event()

    def run(self):
        self.started = True
        self.entered.set()
        # Bounded wait for the worker to request shutdown.
        import time
        deadline = time.monotonic() + 3
        while not self.should_exit and time.monotonic() < deadline:
            time.sleep(0.005)
        if not self.should_exit:
            raise AssertionError("HTTP server did not receive shutdown request")


class WorkerLifecycleTests(unittest.TestCase):
    def test_infrastructure_failure_stops_http_and_fails(self):
        server = FakeServer()
        verifier = Mock()
        verifier.enabled.return_value = True
        with patch("project_os_bridge.authenticated.run_pending", side_effect=OSError("private fixture path")):
            with self.assertRaisesRegex(RuntimeError, "^DISPOSABLE_WORKER_FAILED$"):
                serve_with_worker(server, Mock(), verifier, None)
        self.assertTrue(server.should_exit)

    def test_normal_shutdown_waits_for_inflight_cleanup(self):
        entered, release, cleaned = (threading.Event() for _ in range(3))
        verifier = Mock()
        verifier.enabled.return_value = True
        server = Mock(started=False)
        def drain(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("cleanup not released")
            cleaned.set()
        def serve():
            server.started = True
            if not entered.wait(3):
                raise AssertionError("worker not started")
            release.set()
        server.run.side_effect = serve
        with patch("project_os_bridge.authenticated.run_pending", side_effect=drain):
            serve_with_worker(server, Mock(), verifier, None)
        self.assertTrue(cleaned.is_set())

    def test_lock_contention_is_not_fatal(self):
        verifier = Mock()
        verifier.enabled.return_value = True
        server = FakeServer()
        def drain(*args, **kwargs):
            if not server.entered.wait(3):
                raise AssertionError("server not started")
            server.should_exit = True
            raise WorkerBusy()
        with patch("project_os_bridge.authenticated.run_pending", side_effect=drain):
            serve_with_worker(server, Mock(), verifier, None)
        self.assertTrue(server.should_exit)

    def test_startup_failure_never_dispatches(self):
        server = Mock(started=False)
        verifier = Mock()
        verifier.enabled.return_value = True
        with patch("project_os_bridge.authenticated.run_pending") as drain:
            with self.assertRaisesRegex(RuntimeError, "HTTP_STARTUP_FAILED"):
                serve_with_worker(server, Mock(), verifier, None)
            drain.assert_not_called()

    def test_other_blocking_io_failure_is_fatal(self):
        server = FakeServer()
        verifier = Mock()
        verifier.enabled.return_value = True
        with patch("project_os_bridge.authenticated.run_pending", side_effect=BlockingIOError()):
            with self.assertRaisesRegex(RuntimeError, "DISPOSABLE_WORKER_FAILED"):
                serve_with_worker(server, Mock(), verifier, None)

    def test_exclusive_http_lock_released_on_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with exclusive_http_service(root):
                with self.assertRaises(BlockingIOError):
                    with exclusive_http_service(root):
                        self.fail("Second HTTP process admitted")
            with exclusive_http_service(root):
                self.assertTrue((root / "http-service.lock").is_file())

    def test_unsafe_http_lock_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / "sentinel"
            target.write_text("unchanged")
            (root / "http-service.lock").symlink_to(target)
            with self.assertRaises(OSError):
                with exclusive_http_service(root):
                    self.fail("Symlink accepted")
            self.assertEqual(target.read_text(), "unchanged")
