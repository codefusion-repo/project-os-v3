"""Exclusive local worker, one registered harmless handler."""
import fcntl
import os
from contextlib import contextmanager

from .core import Jobs


class WorkerBusy(BlockingIOError):
    """Only an occupied worker lock is a recoverable contention event."""


@contextmanager
def exclusive_worker(jobs: Jobs):
    jobs.probe._check_directory()
    path = jobs.probe.root / "worker.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        jobs.probe._check_file(path)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkerBusy("Worker lock occupied") from exc
        yield
    finally:
        os.close(fd)


def run_pending(jobs: Jobs, *, fixture_image=None, enabled=lambda: True, fixture_allowed=lambda: True):
    """Drain queued disposable jobs, no shell, no repo access."""
    with exclusive_worker(jobs):
        jobs.recover_interrupted()
        while enabled():
            row = jobs.claim()
            if row is None:
                return
            if not enabled():
                jobs.finish(row["id"], "BLOCKED", {"reason": "DISPATCH_DISABLED"}, fixture_absent=True)
                return
            fixture_absent = False
            try:
                if row["resource"] != "disposable":
                    raise ValueError("Unknown resource")
                if row["workflow"] == "probe_check":
                    result = jobs.probe.read()
                    state = "SUCCEEDED"
                elif row["workflow"] == "git_fixture_check":
                    if not fixture_allowed():
                        state, result = "BLOCKED", {"reason":"FIXTURE_ACCESS_REVOKED"}
                        fixture_absent = True
                    else:
                        from .vertical import run_git_fixture
                        state, result = run_git_fixture(jobs, row, fixture_image)
                        fixture_absent = result.get("container_absent") is True
                else:
                    raise ValueError("Unknown handler")
            except Exception:
                jobs.finish(row["id"], "FAILED", {"error": "HANDLER_FAILED"})
            else:
                jobs.finish(row["id"], state, result, fixture_absent=fixture_absent)
