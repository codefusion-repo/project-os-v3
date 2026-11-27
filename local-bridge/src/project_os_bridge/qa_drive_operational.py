"""Supervised private Drive binding, with the existing GitHub read provider."""
import json
import re

from .drive_delivery import DrivePublisher, DriveDeliveryError, drive_id
from .github_operational import MultiProjectContext, _private_bytes, _unique_object
from .qa_drive_job import deliver_qa
from .workspace_jobs import SupervisedWorkspacePolicy, require_workspace_job

SHA = re.compile(r"[0-9a-f]{40}")


def require_live_pr(context, actor, project, repository_id, pr, head, *, check_access):
    if (type(pr) is not int or not 0 < pr <= 2147483647
            or type(repository_id) is not int or repository_id <= 0
            or not isinstance(head, str) or not SHA.fullmatch(head)):
        raise ValueError("QA_PR_INVALID")
    repo = context.require(actor, project)

    def check():
        check_access()
        if context.require(actor, project) != repo:
            raise PermissionError("QA_PR_GRANT_CHANGED")

    def get(path):
        result = context.reader._authorized_request(actor, project, path, check)
        if result.get("complete") is not True or not isinstance(result.get("data"), dict):
            raise DriveDeliveryError("QA_PR_READ_UNAVAILABLE")
        return result["data"]

    metadata = get(f"repos/{repo}")
    if (metadata.get("id") != repository_id or metadata.get("private") is not True
            or not isinstance(metadata.get("full_name"), str)
            or metadata["full_name"].casefold() != repo.casefold()):
        raise PermissionError("QA_REPOSITORY_IDENTITY_CHANGED")
    pull = get(f"repos/{repo}/pulls/{pr}")
    if (pull.get("number") != pr or pull.get("state") != "open"
            or pull.get("head", {}).get("sha") != head
            or (pull.get("head", {}).get("repo") or {}).get("id") != repository_id
            or (pull.get("base", {}).get("repo") or {}).get("id") != repository_id):
        raise PermissionError("QA_PR_HEAD_CHANGED")
    check()


class SupervisedDriveDelivery:
    def __init__(self, jobs, github_provider):
        if (type(jobs.policy) is not SupervisedWorkspacePolicy
                or type(github_provider) is not MultiProjectContext
                or jobs.policy.backend is None or jobs.policy.verifier is not github_provider.verifier
                or jobs.probe.root != github_provider.state):
            raise ValueError("QA_SUPERVISED_DELIVERY_REQUIRED")
        self.jobs = jobs
        self.github = github_provider
        self.root = jobs.probe.root / "drive-delivery"

    def _binding(self):
        raw = _private_bytes(self.root / "binding.json", 16384)
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if (not isinstance(data, dict) or set(data) != {"folder_id", "owner_permission_id", "state"}
                or data["state"] != "READY"):
            raise ValueError("QA_DRIVE_ENROLLMENT_REQUIRED")
        return raw, drive_id(data["folder_id"]), drive_id(data["owner_permission_id"])

    def available(self, actor):
        try:
            self._binding()
            # Check presence and privacy only, never disclose content or contact Google here.
            from .workos_auth import private_file
            private_file(self.root / "credentials.json")
            for project in self.jobs.policy.initial:
                try:
                    self.jobs.policy.require(actor, "workspace_delivery", project)
                    self.github.open_project(actor, project)
                    return True
                except PermissionError:
                    continue
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return False

    def deliver(self, actor, job_id, project, head, pr, *, check_session, reconcile_only=False):
        check_session()
        self.jobs.policy.require(actor, "workspace_delivery", project)
        request = require_workspace_job(self.jobs, actor, job_id, allow_execute=True)
        if request["project"] != project or request["expected_sha"] != head:
            raise PermissionError("QA_JOB_TARGET_CHANGED")
        entry = self.jobs.policy.initial_entries.get(project)
        if entry is None:
            raise PermissionError("QA_REPOSITORY_UNAVAILABLE")
        repository_id = entry["repository_id"]
        raw, folder, owner = self._binding()
        context, _ = self.github.open_project(actor, project)

        def check():
            check_session()
            self.jobs.policy.require(actor, "workspace_delivery", project)
            if self._binding() != (raw, folder, owner):
                raise PermissionError("QA_DRIVE_BINDING_CHANGED")
            if context.require(actor, project) != entry["repository"]:
                raise PermissionError("QA_REPOSITORY_BINDING_CHANGED")
            if require_workspace_job(self.jobs, actor, job_id, allow_execute=True) != request:
                raise PermissionError("QA_JOB_TARGET_CHANGED")

        def target(expected_project, expected_repo, expected_pr, expected_head):
            if (expected_project, expected_repo, expected_pr, expected_head) != (project, repository_id, pr, head):
                raise PermissionError("QA_PR_TARGET_CHANGED")
            require_live_pr(context, actor, project, repository_id, pr, head, check_access=check)

        check()
        publisher = DrivePublisher(self.root / "credentials.json", folder, owner, check_access=check)
        try:
            result = deliver_qa(self.jobs, actor, job_id, project=project, head=head,
                repository_id=repository_id, pr=pr, publisher=publisher,
                check_target=target, reconcile_only=reconcile_only)
            check()
            return {"state": result["state"], "job_id": job_id, "head": head, "pr": pr,
                    "repository_id": repository_id, "artifact": result["artifact"],
                    "remote": result["remote"]}
        finally:
            publisher.close()
