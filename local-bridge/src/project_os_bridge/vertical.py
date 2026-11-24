"""Locally opted-in deterministic disposable Git workflow, not exposed via MCP."""
import argparse
import json
import os
import re
from pathlib import Path

from .core import Jobs, Policy
from .git_fixture import GitFixture
from .isolated import IMAGE, validate_in_container
from .workos_auth import private_directory
from .worker import run_pending

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


def local_jobs(root):
    private_directory(root)
    # Refuse use of an HTTP service directory or an existing probe DB.
    # A dedicated local marker is created only by the CLI on a new empty directory.
    marker = root / "local-fixture-mode"
    if not marker.exists():
        if any(root.iterdir()):
            raise PermissionError("Use a new empty private directory")
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    from .workos_auth import private_file
    if private_file(marker).st_size != 0 or os.path.lexists(root/"allow-authenticated-probe"):
        raise PermissionError("Dedicated local fixture state required")
    return Jobs(root, Policy(("local-fixture",op,"disposable") for op in OPERATIONS),
                workflows=("git_fixture_check",))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--request-key", required=True)
    parser.add_argument("--image", required=True, help="Locally approved image@sha256:digest; never pulled")
    args = parser.parse_args()
    os.umask(0o077)
    if not IMAGE.fullmatch(args.image):
        parser.error("Digest-pinned image required")
    jobs = local_jobs(args.state_dir)
    job = jobs.submit("local-fixture","disposable","git_fixture_check",args.request_key)
    run_pending(jobs, fixture_image=args.image)
    evidence = jobs.evidence("local-fixture",job)
    print(json.dumps(evidence, indent=2))
    raise SystemExit(0 if evidence["state"] == "SUCCEEDED" else 1)


if __name__ == "__main__":
    main()
