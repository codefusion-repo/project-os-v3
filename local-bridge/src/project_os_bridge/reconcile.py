"""Local reconciliation of interrupted trusted WSL jobs; never rerun work."""
import argparse
import json
import os
from pathlib import Path
from .authenticated import exclusive_http_service
from .core import Jobs, Policy
from .worker import exclusive_worker
from .workos_auth import private_directory, private_file


def reconcile(jobs, job_id, *, quiescent=False):
    """Operator confirms job processes stopped in the existing WSL environment."""
    if quiescent is not True:
        raise PermissionError("LOCAL_QUIESCENCE_REQUIRED")
    with exclusive_worker(jobs):
        jobs.recover_interrupted()
        pending = [row for row in jobs.pending_effects() if row["job_id"] == job_id]
        if len(pending) != 1 or not pending[0]["token"] or not pending[0]["context_id"]:
            raise PermissionError("UNKNOWN_EFFECT")
        effect = pending[0]
        with jobs.transaction() as conn:
            row = conn.execute("SELECT workflow FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["workflow"] not in {"workspace_execute", "workspace_git_fetch", "codex_capabilities"}:
                raise PermissionError("HISTORICAL_EFFECT_REQUIRES_LOCAL_REVIEW")
        jobs.resolve_effect(job_id, effect["token"], effect["context_id"])
        # recover_interrupted already records the terminal INTERRUPTED event.
        # Reconciliation releases only the confirmed effect, never replays the job.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--confirm-absent", metavar="JOB_ID")
    parser.add_argument("--confirm-quiescent", action="store_true",
                        help="Operator verified all processes and effects of this job have stopped")
    args = parser.parse_args()
    if args.confirm_quiescent != bool(args.confirm_absent):
        parser.error("Explicit local quiescence required only with --confirm-absent")
    if os.getuid() == 0:
        parser.error("Run as the unprivileged service account")
    os.umask(0o077)
    private_directory(args.state_dir)
    for name in ("jobs.sqlite3", "probe.sqlite3"):
        private_file(args.state_dir / name)
    with exclusive_http_service(args.state_dir):
        jobs = Jobs(args.state_dir, Policy([]))
        if args.list:
            with exclusive_worker(jobs):
                jobs.recover_interrupted()
                print(json.dumps([{"job_id": row["job_id"], "context_known": row["context_id"] is not None}
                                  for row in jobs.pending_effects()]))
        else:
            try:
                reconcile(jobs, args.confirm_absent, quiescent=args.confirm_quiescent)
            except (OSError, ValueError, KeyError, TypeError):
                parser.exit(1, "RECONCILIATION_BLOCKED; preserve state\n")
            print("RECONCILED_OPERATOR_CONFIRMED_QUIESCENCE; no job retried")


if __name__ == "__main__":
    main()
