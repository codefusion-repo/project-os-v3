"""Exclusive local worker, one registered harmless handler."""
import fcntl
import os
from contextlib import contextmanager

from .core import Jobs


@contextmanager
def exclusive_worker(jobs: Jobs):
    jobs.probe._check_directory()
    path = jobs.probe.root / "worker.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        jobs.probe._check_file(path)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def run_pending(jobs: Jobs):
    """Drain queued disposable jobs, no shell, no repo access."""
    with exclusive_worker(jobs):
        jobs.recover_interrupted()
        while True:
            row = jobs.claim()
            if row is None:
                return
            try:
                if row["workflow"] != "probe_check" or row["resource"] != "disposable":
                    raise ValueError("Unknown handler")
                result = jobs.probe.read()
            except Exception:
                jobs.finish(row["id"], "FAILED", {"error": "HANDLER_FAILED"})
            else:
                jobs.finish(row["id"], "SUCCEEDED", result)
