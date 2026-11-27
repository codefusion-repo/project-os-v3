"""Trusted GitHub Actions delivery contract for a finalized QA APK.

This module constructs a bounded publication request and verifies the completed
remote effect. It does not register runners, dispatch jobs, or grant access.
The caller must retain the plan in the existing durable job before dispatch,
admit the exact private repository and trusted workflow, and reconcile uncertain
effects rather than resubmit. Runner labels alone are not an authorization gate.
"""
from dataclasses import dataclass
import re

from .android_qa import verify_qa_artifact_zip

WORKFLOW = ".github/workflows/project-os-qa-delivery.yml"
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
HEX32 = re.compile(r"[0-9a-f]{32}")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")


def _id(value):
    return type(value) is int and 0 < value <= 2**63 - 1


def _hex(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


@dataclass(frozen=True)
class DeliveryPlan:
    repository: str
    repository_id: int
    pr: int
    head: str
    workflow_id: int
    workflow_sha: str
    default_branch: str
    job_id: str
    apk_sha256: str
    apk_size: int
    snapshot_sha256: str

    def __post_init__(self):
        if (not _hex(REPO, self.repository)
                or any(part in {".", ".."} for part in self.repository.split("/"))
                or not all(_id(x) for x in (self.repository_id, self.pr, self.workflow_id))
                or not _hex(HEX40, self.head) or not _hex(HEX40, self.workflow_sha)
                or not _hex(BRANCH, self.default_branch)
                or not _hex(HEX32, self.job_id) or not _hex(HEX64, self.apk_sha256)
                or not _hex(HEX64, self.snapshot_sha256)
                or type(self.apk_size) is not int or not 0 < self.apk_size <= 256 * 1024 * 1024):
            raise ValueError("QA_DELIVERY_PLAN_INVALID")

    @property
    def label(self):
        return "project-os-qa-" + self.job_id

    @property
    def artifact_name(self):
        return self.label

    def require_target(self, repository, pr):
        if (repository.get("id") != self.repository_id
                or repository.get("full_name") != self.repository
                or repository.get("private") is not True
                or repository.get("default_branch") != self.default_branch
                or pr.get("number") != self.pr or pr.get("state") != "open"
                or pr.get("head", {}).get("sha") != self.head
                or pr.get("head", {}).get("repo", {}).get("id") != self.repository_id
                or pr.get("base", {}).get("repo", {}).get("id") != self.repository_id):
            raise PermissionError("QA_DELIVERY_TARGET_CHANGED")

    def require_receipt(self, receipt):
        if (receipt.get("job_id") != self.job_id
                or receipt.get("repository_id") != self.repository_id
                or receipt.get("head") != self.head
                or receipt.get("workspace_sha256") != self.snapshot_sha256
                or receipt.get("signature_verified") is not True
                or receipt.get("published") is not False
                or "changes_sha256" in receipt
                or receipt.get("artifact") != {
                    "kind": "apk", "artifact": "app-qa.apk",
                    "sha256": self.apk_sha256, "size": self.apk_size}):
            raise ValueError("QA_DELIVERY_RECEIPT_CHANGED")

    def dispatch_inputs(self):
        """Only fixed workflow inputs; never supply a command, path, or URL."""
        return {"runner_label": self.label, "apk_sha256": self.apk_sha256,
                "apk_size": str(self.apk_size)}

    def runner_request(self, runner_group_id):
        if not _id(runner_group_id):
            raise ValueError("QA_DELIVERY_RUNNER_GROUP_INVALID")
        return {"name": self.label, "runner_group_id": runner_group_id,
                "labels": [self.label], "work_folder": "_work"}

    def dispatch_request(self):
        # The trusted default-branch revision must be independently checked
        # before dispatch and against the returned run, before starting runner.
        return {"ref": self.default_branch, "inputs": self.dispatch_inputs(),
                "return_run_details": True}

    def require_run(self, run, run_id, *, finished=False):
        if (not _id(run_id) or run.get("id") != run_id
                or run.get("workflow_id") != self.workflow_id
                or run.get("path") not in {WORKFLOW, WORKFLOW + "@refs/heads/" + self.default_branch}
                or run.get("head_branch") != self.default_branch
                or run.get("head_sha") != self.workflow_sha
                or run.get("repository", {}).get("id") != self.repository_id
                or run.get("head_repository", {}).get("id") != self.repository_id
                or run.get("event") != "workflow_dispatch"
                or run.get("display_title") != self.label or run.get("run_attempt") != 1):
            raise ValueError("QA_DELIVERY_RUN_MISMATCH")
        if finished:
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                raise ValueError("QA_DELIVERY_RUN_NOT_SUCCESSFUL")
        elif run.get("status") not in {"queued", "in_progress", "waiting", "pending", "requested"}:
            raise ValueError("QA_DELIVERY_RUN_NOT_ACTIVE")

    def verify_completed(self, *, repository, pr, run, run_id, runner_id, jobs,
                         artifacts, archive, receipt):
        """Return a verified remote delivery record; never publish a PR comment."""
        self.require_target(repository, pr)
        self.require_receipt(receipt)
        self.require_run(run, run_id, finished=True)
        if not _id(runner_id) or not isinstance(jobs, list) or len(jobs) != 1:
            raise ValueError("QA_DELIVERY_JOB_MISMATCH")
        job = jobs[0]
        if (not _id(job.get("id")) or job.get("run_id") != run_id
                or job.get("name") != "publish-qa" or job.get("runner_id") != runner_id
                or job.get("runner_name") != self.label or job.get("conclusion") != "success"
                or job.get("status") != "completed" or self.label not in job.get("labels", [])):
            raise ValueError("QA_DELIVERY_JOB_MISMATCH")
        if not isinstance(artifacts, list) or len(artifacts) != 1:
            raise ValueError("QA_DELIVERY_ARTIFACT_AMBIGUOUS")
        artifact = artifacts[0]
        artifact_id = artifact.get("id")
        digest = artifact.get("digest")
        observed = artifact.get("workflow_run") or {}
        if (not _id(artifact_id) or artifact.get("name") != self.artifact_name
                or artifact.get("expired") is not False
                or not isinstance(digest, str) or not digest.startswith("sha256:")
                or not _hex(HEX64, digest[7:])
                or observed.get("id") != run_id
                or observed.get("repository_id") != self.repository_id
                or observed.get("head_repository_id") != self.repository_id
                or observed.get("head_sha") != self.workflow_sha
                or observed.get("head_branch") != self.default_branch):
            raise ValueError("QA_DELIVERY_ARTIFACT_MISMATCH")
        identity = verify_qa_artifact_zip(archive, receipt, expected_zip_sha256=digest[7:])
        if artifact.get("size_in_bytes") != identity["size"]:
            raise ValueError("QA_DELIVERY_ZIP_SIZE_MISMATCH")
        return {"repository_id": self.repository_id, "pr": self.pr, "head": self.head,
                "workspace_sha256": self.snapshot_sha256, "job_id": self.job_id,
                "run_id": run_id, "runner_id": runner_id, "artifact_id": artifact_id,
                "workflow_sha": self.workflow_sha, "apk": receipt["artifact"],
                "zip": identity, "artifact_url":
                f"https://github.com/{self.repository}/actions/runs/{run_id}/artifacts/{artifact_id}"}
