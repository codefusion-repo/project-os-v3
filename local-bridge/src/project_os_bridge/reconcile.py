"""Local-only read-only proof of absence; no removal or automatic retry."""
import argparse
import json
import os
import subprocess
from pathlib import Path
from .authenticated import exclusive_http_service
from .core import Jobs, Policy
from .worker import exclusive_worker
from .isolated import container_absent, container_name
from .podman_context import PodmanContext
from .workos_auth import private_directory, private_file


def reconcile(jobs, job_id, context):
    with exclusive_worker(jobs):
        jobs.recover_interrupted()
        pending = [row for row in jobs.pending_effects() if row["job_id"] == job_id]
        if len(pending) != 1 or pending[0]["token"] is None or pending[0]["context_id"] is None:
            raise PermissionError("Unknown or legacy fixture identity; preserve state")
        token = pending[0]["token"]
        identity = pending[0]["context_id"]
        context.host(identity)
        if not container_absent(context, identity, token):
            raise PermissionError("Container absence not verified")
        jobs.resolve_effect(job_id, token, identity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--confirm-absent", metavar="JOB_ID")
    parser.add_argument("--podman-context", type=Path, help="Prepared context associated with the effect")
    parser.add_argument("--confirm-quiescent", action="store_true", help="Operator verified no prior Podman or fixture operation can still create containers")
    args = parser.parse_args()
    if args.confirm_quiescent != bool(args.confirm_absent):
        parser.error("Explicit quiescence confirmation required only with --confirm-absent")
    if (args.podman_context is None) == bool(args.confirm_absent):
        parser.error("Explicit Podman context required only with --confirm-absent")
    if os.getuid() == 0:
        parser.error("Run as dedicated unprivileged service account")
    os.umask(0o077)
    private_directory(args.state_dir)
    for name in ("jobs.sqlite3", "probe.sqlite3"):
        private_file(args.state_dir / name)
    with exclusive_http_service(args.state_dir):
        jobs = Jobs(args.state_dir, Policy([]))
        if args.list:
            with exclusive_worker(jobs):
                jobs.recover_interrupted()
                print(json.dumps([{"job_id": row["job_id"], "container": container_name(row["token"]) if row["token"] else None,
                                   "label": "io.project-os.fixture="+row["token"] if row["token"] else None,
                                   "context_known": row["context_id"] is not None}
                                  for row in jobs.pending_effects()]))
        else:
            try:
                reconcile(jobs, args.confirm_absent, PodmanContext(args.podman_context))
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                parser.exit(1, "FIXTURE_RECONCILIATION_BLOCKED; preserve state and context\n")
            print("RECONCILED_ABSENCE; no job retried")


if __name__ == "__main__":
    main()
