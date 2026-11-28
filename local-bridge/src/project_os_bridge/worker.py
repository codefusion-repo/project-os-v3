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


def run_pending(jobs: Jobs, *, enabled=lambda: True, workspace_backend=None):
    """Drain registered jobs sequentially; preserve uncertain effects."""
    if workspace_backend is not None:
        from .execution import WorkspaceWSL
        if type(workspace_backend) is not WorkspaceWSL:
            raise ValueError("DIRECT_WSL_BACKEND_REQUIRED")
    with exclusive_worker(jobs):
        jobs.recover_interrupted()
        if jobs.pending_effects():
            return
        while enabled():
            if workspace_backend is not None and workspace_backend.qa_signers:
                from .android_qa import finalize_pending_locked
                finalize_pending_locked(jobs, workspace_backend, enabled=enabled)
                if not enabled() or jobs.pending_effects():
                    return
            workspace_contexts = workspace_backend.identities() if workspace_backend is not None else None
            row = jobs.claim(workspace_contexts=workspace_contexts)
            if row is None:
                return
            if not enabled():
                jobs.finish(row["id"], "BLOCKED", {"reason": "DISPATCH_DISABLED"}, fixture_absent=True,
                            fixture_context=row.get("effect_context"))
                return
            fixture_absent = False
            try:
                if row["resource"] != "disposable":
                    from .workspace_jobs import workspace_resource
                    if (row["workflow"] not in {"workspace_prepare", "workspace_execute"}
                            or row["resource"] != workspace_resource(jobs.policy)):
                        raise ValueError("Unknown resource")
                if row["workflow"] == "probe_check":
                    result = jobs.probe.read()
                    state = "SUCCEEDED"
                elif row["workflow"] in {"workspace_prepare", "workspace_execute"}:
                    from .workspace_jobs import run_workspace, authorize_request

                    def execution_enabled():
                        try:
                            if not enabled():
                                return False
                            authorize_request(jobs.policy, row["principal"], row["workspace"], execute=True)
                            return True
                        except (OSError, ValueError, TypeError):
                            return False

                    executor = None
                    if workspace_backend is not None:
                        def executor(workspace, claimed, snapshot):
                            return workspace_backend.execute(workspace, claimed, snapshot,
                                                             enabled=execution_enabled)
                    state, result = run_workspace(jobs, row, executor=executor)
                    if row.get("effect_context") is not None:
                        fixture_absent = result.get("execution", {}).get("cleanup_verified") is True
                elif row["workflow"] == "fixture_package":
                    from .workspace_fixture import run_package
                    state, result = run_package(jobs, row)
                else:
                    raise ValueError("Unknown handler")
            except Exception:
                jobs.finish(row["id"], "FAILED", {"error": "HANDLER_FAILED"})
            else:
                jobs.finish(row["id"], state, result, fixture_absent=fixture_absent,
                            fixture_context=row.get("effect_context"))
            if jobs.pending_effects():
                return
