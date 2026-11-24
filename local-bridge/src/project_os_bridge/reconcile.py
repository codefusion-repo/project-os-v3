"""Local-only read-only proof of absence; no removal or automatic retry."""
import argparse
import json
import os
from pathlib import Path
from .authenticated import exclusive_http_service
from .core import Jobs, Policy
from .worker import exclusive_worker
from .isolated import container_absent, rootless_host, container_name
from .workos_auth import private_directory, private_file


def reconcile(jobs, job_id):
    with exclusive_worker(jobs):
        jobs.recover_interrupted()
        pending = [row for row in jobs.pending_effects() if row["job_id"] == job_id]
        if len(pending) != 1 or pending[0]["token"] is None:
            raise PermissionError("Unknown or legacy fixture identity; preserve state")
        token = pending[0]["token"]
        rootless_host()
        if not container_absent(token):
            raise PermissionError("Container absence not verified")
        jobs.resolve_effect(job_id, token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--confirm-absent", metavar="JOB_ID")
    parser.add_argument("--confirm-quiescent", action="store_true", help="Operator verified no prior Podman or fixture operation can still create containers")
    args = parser.parse_args()
    if args.confirm_quiescent != bool(args.confirm_absent):
        parser.error("Explicit quiescence confirmation required only with --confirm-absent")
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
                                   "label": "io.project-os.fixture="+row["token"] if row["token"] else None}
                                  for row in jobs.pending_effects()]))
        else:
            reconcile(jobs, args.confirm_absent)
            print("RECONCILED_ABSENCE; no job retried")


if __name__ == "__main__":
    main()
