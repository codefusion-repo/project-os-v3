"""Lifecycle tests for the actual HTTP worker orchestration."""
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch

from project_os_bridge.authenticated import serve_with_worker, exclusive_http_service
from project_os_bridge.core import Jobs, Policy
from project_os_bridge.vertical import OPERATIONS, bind_image
from project_os_bridge.worker import WorkerBusy, run_pending


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
    def test_http_worker_never_adopts_context_replaced_after_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            image = "example/python@sha256:" + "a" * 64
            authorized, replacement = "1" * 64, "2" * 64
            jobs = Jobs(root, Policy(("p", op, "disposable") for op in OPERATIONS),
                        workflows=("probe_check", "git_fixture_check"))
            context = Mock()
            identities = iter([authorized])
            context.identity.side_effect = lambda expected=None: next(identities, replacement)
            identity = context.identity()
            bind_image(jobs, image, identity)
            fixture = jobs.submit("p", "disposable", "git_fixture_check", "drift")
            probe = jobs.submit("p", "disposable", "probe_check", "probe")
            verifier = Mock(state_dir=root)
            verifier.enabled.return_value = True
            server = FakeServer()

            def drain(*args, **kwargs):
                try:
                    return run_pending(*args, **kwargs)
                finally:
                    server.should_exit = True

            with patch("project_os_bridge.authenticated.run_pending", side_effect=drain), \
                    patch("project_os_bridge.vertical.run_git_fixture") as handler:
                serve_with_worker(server, jobs, verifier, image, podman_context=context, context_id=identity)
            handler.assert_not_called()
            self.assertEqual(jobs.get("p", fixture)["state"], "BLOCKED")
            self.assertEqual(jobs.get("p", probe)["state"], "SUCCEEDED")
            self.assertEqual(context.identity.call_args_list[0], call())
            self.assertTrue(all(c == call(authorized) for c in context.identity.call_args_list[1:]))
            with jobs.transaction() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM fixture_effects").fetchone()[0], 0)

    def test_infrastructure_failure_stops_http_and_fails(self):
        server = FakeServer()
        verifier = Mock()
        verifier.enabled.return_value = True
        with patch("project_os_bridge.authenticated.run_pending", side_effect=OSError("private fixture path")):
            with self.assertRaisesRegex(RuntimeError, "^DISPOSABLE_WORKER_FAILED$"):
                serve_with_worker(server, Mock(**{"pending_effects.return_value": []}), verifier, None)
        self.assertTrue(server.should_exit)

    def test_normal_shutdown_waits_for_inflight_cleanup(self):
        entered, release, cleaned = (threading.Event() for _ in range(3))
        verifier = Mock()
        verifier.enabled.return_value = True
        server = Mock(started=False, should_exit=False)
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
            serve_with_worker(server, Mock(**{"pending_effects.return_value": []}), verifier, None)
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
            serve_with_worker(server, Mock(**{"pending_effects.return_value": []}), verifier, None)
        self.assertTrue(server.should_exit)

    def test_startup_failure_never_dispatches(self):
        server = Mock(started=False, should_exit=False)
        verifier = Mock()
        verifier.enabled.return_value = True
        with patch("project_os_bridge.authenticated.run_pending") as drain:
            with self.assertRaisesRegex(RuntimeError, "HTTP_STARTUP_FAILED"):
                serve_with_worker(server, Mock(**{"pending_effects.return_value": []}), verifier, None)
            drain.assert_not_called()

    def test_other_blocking_io_failure_is_fatal(self):
        server = FakeServer()
        verifier = Mock()
        verifier.enabled.return_value = True
        with patch("project_os_bridge.authenticated.run_pending", side_effect=BlockingIOError()):
            with self.assertRaisesRegex(RuntimeError, "DISPOSABLE_WORKER_FAILED"):
                serve_with_worker(server, Mock(**{"pending_effects.return_value": []}), verifier, None)

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

    def test_real_uvicorn_port_conflict_preserves_queue(self):
        import socket
        import uvicorn
        from starlette.applications import Starlette
        from project_os_bridge.core import Jobs, Policy
        with tempfile.TemporaryDirectory() as folder, socket.socket() as listener:
            root = Path(folder).resolve()
            jobs = Jobs(root, Policy(("test", op, "disposable") for op in ("submit", "read")))
            job = jobs.submit("test", "disposable", "probe_check", "port-conflict")
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            server = uvicorn.Server(uvicorn.Config(Starlette(), host="127.0.0.1",
                                    port=listener.getsockname()[1], lifespan="off", log_config=None))
            verifier = Mock()
            verifier.enabled.return_value = True
            with patch("project_os_bridge.authenticated.run_pending") as drain:
                with self.assertRaises((SystemExit, RuntimeError)):
                    serve_with_worker(server, jobs, verifier, None)
                drain.assert_not_called()
            self.assertFalse(server.started)
            self.assertEqual(jobs.get("test", job)["state"], "QUEUED")

    def test_real_uvicorn_worker_failure_requests_shutdown(self):
        import uvicorn
        from starlette.applications import Starlette
        server = uvicorn.Server(uvicorn.Config(Starlette(), host="127.0.0.1",
                                port=0, lifespan="off", log_config=None))
        verifier = Mock()
        verifier.enabled.return_value = True
        # Bound this loopback-only regression test even if shutdown propagation breaks.
        watchdog = threading.Timer(5, lambda: setattr(server, "should_exit", True))
        watchdog.start()
        try:
            with patch("project_os_bridge.authenticated.run_pending",
                       side_effect=OSError("synthetic failure")) as drain:
                with self.assertRaisesRegex(RuntimeError, "DISPOSABLE_WORKER_FAILED"):
                    serve_with_worker(server, Mock(**{"pending_effects.return_value": []}), verifier, None)
                drain.assert_called_once()
            self.assertTrue(server.started)
            self.assertTrue(server.should_exit)
        finally:
            watchdog.cancel()
            watchdog.join()

    def test_uncertain_effect_stops_http_after_drain(self):
        server = FakeServer()
        verifier = Mock()
        verifier.enabled.return_value = True
        jobs = Mock()
        jobs.pending_effects.return_value = [{"job_id":"synthetic","token":"synthetic"}]
        with patch("project_os_bridge.authenticated.run_pending") as drain:
            with self.assertRaisesRegex(RuntimeError, "DISPOSABLE_WORKER_FAILED"):
                serve_with_worker(server,jobs,verifier,None)
            drain.assert_called_once()
        self.assertTrue(server.should_exit)
