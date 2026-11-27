"""Durable delivery extension of the existing successful QA job.

Local trusted orchestration only; no automatic replay after an uncertain effect.
A live PR guard and project-specific delivery grant are required at every effect.
"""
import hashlib
import json

from .android_qa import _verified_qa_delivery_locked
from .worker import exclusive_worker
from .drive_delivery import drive_id


def _store(jobs, job_id, previous, delivery):
    with jobs.transaction() as conn:
        row = conn.execute("SELECT state,result FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["state"] != "SUCCEEDED":
            raise ValueError("QA_DELIVERY_JOB_UNAVAILABLE")
        result = json.loads(row["result"])
        if result.get("qa_delivery") != previous:
            raise RuntimeError("QA_DELIVERY_RECORD_CONFLICT")
        result["qa_delivery"] = delivery
        conn.execute("UPDATE jobs SET result=? WHERE id=?",
                     (json.dumps(result, sort_keys=True), job_id))


def deliver_qa(jobs, principal, job_id, *, project, head, repository_id, pr,
               publisher, check_target, reconcile_only=False):
    """Caller supplies a reviewed private publisher and live target guard.

    A reserved ID is committed before upload. After an ambiguous create, only
    read-back reconciliation is allowed; a missing file does not prove absence.
    Successful replay re-verifies bytes and never creates a second file.
    """
    if type(pr) is not int or not 0 < pr <= 2147483647:
        raise ValueError("QA_DELIVERY_PR_INVALID")
    with exclusive_worker(jobs):
        def guard():
            jobs.policy.require(principal, "workspace_delivery", project)
            check_target(project, repository_id, pr, head)
        guard()
        raw, receipt = _verified_qa_delivery_locked(jobs, principal, job_id,
            expected_project=project, expected_sha=head, expected_repository_id=repository_id)
        artifact = receipt["artifact"]
        properties = {"job_id": job_id, "repo_id": str(repository_id),
                      "head": head, "snapshot": receipt["workspace_sha256"],
                      "sha256": artifact["sha256"], "pr": str(pr)}
        base = {"binding": publisher.binding, "properties": properties, "artifact": artifact}
        current = jobs.evidence(principal, job_id)["result"].get("qa_delivery")
        if current is None:
            if reconcile_only:
                raise ValueError("QA_DELIVERY_NOT_RESERVED")
            guard()
            file_id = drive_id(publisher.reserve())
            current = {**base, "file_id": file_id, "state": "RESERVED"}
            _store(jobs, job_id, None, current)
        elif (any(current.get(key) != value for key, value in base.items())
                or current.get("state") not in {"RESERVED", "UNCERTAIN", "SUCCEEDED"}):
            raise PermissionError("QA_DELIVERY_BINDING_CHANGED")
        file_id = drive_id(current["file_id"])
        if current["state"] == "RESERVED" and not reconcile_only:
            guard()
            if hashlib.sha256(raw).hexdigest() != artifact["sha256"] or len(raw) != artifact["size"]:
                raise ValueError("QA_DELIVERY_BYTES_CHANGED")
            # Persist uncertainty before any create; a crash cannot cause replay.
            uncertain = {**base, "file_id": file_id, "state": "UNCERTAIN"}
            _store(jobs, job_id, current, uncertain)
            current = uncertain
            publisher.upload(file_id, raw, properties)
        guard()
        remote = publisher.verify(file_id, artifact, properties)
        guard()
        if (remote.get("file_id") != file_id or remote.get("sha256") != artifact["sha256"]
                or remote.get("size") != artifact["size"]
                or remote.get("url") != "https://drive.google.com/file/d/" + file_id + "/view"):
            raise ValueError("QA_DELIVERY_REMOTE_IDENTITY")
        outcome = {**base, "file_id": file_id, "state": "SUCCEEDED", "remote": remote}
        _store(jobs, job_id, current, outcome)
        return outcome
