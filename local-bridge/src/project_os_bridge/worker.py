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


def run_pending(jobs: Jobs, *, fixture_image=None, podman_context=None, context_id=None,
                enabled=lambda: True, fixture_allowed=lambda: True, workspace_executor=None):
    """Drain queued disposable jobs, no shell, no repo access."""
    from .vertical import bound_context, run_git_fixture

    def fixture_ready():
        if context_id is None or podman_context is None or not fixture_image or not fixture_allowed():
            return False
        try:
            return (bound_context(jobs.probe.root, fixture_image) == context_id
                    and podman_context.identity(context_id) == context_id)
        except (OSError, ValueError):
            return False

    with exclusive_worker(jobs):
        jobs.recover_interrupted()
        if jobs.pending_effects():
            return
        while enabled():
            row = jobs.claim(fixture_context=context_id if fixture_ready() else None)
            if row is None:
                return
            if not enabled():
                jobs.finish(row["id"], "BLOCKED", {"reason": "DISPATCH_DISABLED"}, fixture_absent=True, fixture_context=context_id)
                return
            fixture_absent = False
            try:
                if row["resource"] != "disposable":
                    raise ValueError("Unknown resource")
                if row["workflow"] == "probe_check":
                    result = jobs.probe.read()
                    state = "SUCCEEDED"
                elif row["workflow"] in {"workspace_prepare", "workspace_execute"}:
                    from .workspace_jobs import run_workspace
                    state, result = run_workspace(jobs, row, executor=workspace_executor)
                elif row["workflow"] == "fixture_package":
                    from .workspace_fixture import run_package
                    state, result = run_package(jobs, row)
                elif row["workflow"] == "git_fixture_check":
                    if row["effect_context"] != context_id or not fixture_ready():
                        state, result = "BLOCKED", {"reason": "FIXTURE_BINDING_UNAVAILABLE"}
                        fixture_absent = True
                    else:
                        state, result = run_git_fixture(jobs, row, fixture_image, podman_context)
                        fixture_absent = result.get("container_absent") is True
                else:
                    raise ValueError("Unknown handler")
            except Exception:
                jobs.finish(row["id"], "FAILED", {"error": "HANDLER_FAILED"})
            else:
                jobs.finish(row["id"], state, result, fixture_absent=fixture_absent, fixture_context=context_id)
