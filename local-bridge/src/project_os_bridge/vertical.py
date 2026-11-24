"""Locally opted-in deterministic disposable Git workflow, not exposed via MCP."""
import argparse
import json
import os
import re
from pathlib import Path

from .core import Jobs, Policy
from .git_fixture import GitFixture
from .isolated import IMAGE, validate_in_container
from .workos_auth import private_directory, private_file
from .worker import run_pending, exclusive_worker

PATCH = "diff --git a/fixture.txt b/fixture.txt\n--- a/fixture.txt\n+++ b/fixture.txt\n@@ -1 +1 @@\n-before\n+after\n"
OPERATIONS = ("submit", "read", "cancel", "git_workflow", "git_prepare",
              "git_read", "git_patch", "fixture_validate")


def run_git_fixture(jobs, row, image):
    principal = row["principal"]
    jobs.policy.require(principal, "git_workflow", "disposable")
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        return "BLOCKED", {"reason":"LOCAL_IMAGE_REQUIRED", "steps":[]}
    if not re.fullmatch(r"[0-9a-f]{32}", row["id"]):
        raise ValueError("Invalid job ID")
    evidence = {"profile":"fixture-python", "image":image, "steps":[]}
    # New private directory for each job. Never reopen or overwrite a partial fixture.
    root = jobs.probe.root / ("fixture-" + row["id"])
    try:
        root.mkdir(mode=0o700)
        repo = GitFixture(root, jobs.policy)
        sha = repo.initialize(principal)
        before = repo.prepare(principal, sha)
        evidence["steps"].append({"step":"prepare","head":sha,"revision":before["revision"]})
        after = repo.apply_patch(principal, sha, before["revision"], PATCH)
        diff = repo.diff(principal)
        if after != {k:diff[k] for k in after} or after["head"] != sha or after["text"] != "after\n":
            raise RuntimeError("Fixture verification failed")
        if (root/"repo"/"fixture.txt").read_text(encoding="utf-8") != "before\n":
            raise RuntimeError("Original fixture changed")
        evidence["steps"].append({"step":"patch","head":sha,"revision":after["revision"],
                                  "diff":diff["diff"],"original_unchanged":True})
        result = validate_in_container(repo, principal, after["revision"], image)
        evidence["steps"].append({"step":"validate", **result})
        state = result["status"]
        if state == "SUCCEEDED" and (result.get("revision") != after["revision"] or result.get("exit_code") != 0):
            raise RuntimeError("Invalid validation evidence")
        return state, evidence
    except Exception:
        evidence["error"] = "FIXTURE_WORKFLOW_FAILED"
        return "FAILED", evidence


def local_jobs(root, *, existing=False):
    private_directory(root)
    # Refuse use of an HTTP service directory or an existing probe DB.
    # A dedicated local marker is created only by the CLI on a new empty directory.
    marker = root / "local-fixture-mode"
    if not marker.exists():
        if existing or any(root.iterdir()):
            raise PermissionError("Use a new empty private directory")
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    if private_file(marker).st_size != 0 or os.path.lexists(root/"allow-authenticated-probe"):
        raise PermissionError("Dedicated local fixture state required")
    if existing:
        private_file(root / "jobs.sqlite3")
        private_file(root / "probe.sqlite3")
    return Jobs(root, Policy(("local-fixture",op,"disposable") for op in OPERATIONS),
                workflows=("git_fixture_check",))


def bind_image(jobs, image):
    """Pin one locally approved profile per state directory before submission."""
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        raise ValueError("Digest-pinned image required")
    path = jobs.probe.root / "fixture-image"
    with exclusive_worker(jobs):
        if not os.path.lexists(path):
            with jobs.transaction() as conn:
                if conn.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():
                    raise PermissionError("Legacy state has no bound image; use a new directory")
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(image + "\n")
                file.flush()
                os.fsync(file.fileno())
        if private_file(path).st_size > 1024 or path.read_text(encoding="utf-8") != image + "\n":
            raise PermissionError("Image profile differs; use a new state directory")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--request-key")
    mode.add_argument("--evidence-job-id", help="Retrieve existing evidence without executing a job")
    parser.add_argument("--image", help="Locally approved image@sha256:digest; never pulled")
    args = parser.parse_args()
    os.umask(0o077)
    if args.evidence_job_id is not None:
        if args.image is not None or not re.fullmatch(r"[0-9a-f]{32}", args.evidence_job_id):
            parser.error("Evidence requires a valid job ID and no image")
        jobs = local_jobs(args.state_dir, existing=True)
        print(json.dumps(jobs.evidence("local-fixture", args.evidence_job_id), indent=2))
        return
    if not args.image or not IMAGE.fullmatch(args.image):
        parser.error("Digest-pinned image required")
    jobs = local_jobs(args.state_dir)
    bind_image(jobs, args.image)
    job = jobs.submit("local-fixture","disposable","git_fixture_check",args.request_key)
    run_pending(jobs, fixture_image=args.image)
    evidence = jobs.evidence("local-fixture",job)
    print(json.dumps(evidence, indent=2))
    raise SystemExit(0 if evidence["state"] == "SUCCEEDED" else 1)


if __name__ == "__main__":
    main()
