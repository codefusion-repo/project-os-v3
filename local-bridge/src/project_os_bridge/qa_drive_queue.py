"""Durable delivery request in the existing QA job, executed by the service worker.

No second daemon or queue database. A running request interrupted by restart is
not replayed; an explicit reconciliation request reads the reserved remote ID.
"""
import json

from .worker import exclusive_worker




_DELIVERY_ERROR_CODE = frozenset(["DRIVE_APK_INVALID","DRIVE_BYTES_MISMATCH","DRIVE_CREDENTIAL_CHANGED","DRIVE_CREDENTIAL_INVALID","DRIVE_FILE_CHANGED","DRIVE_FILE_IDENTITY_MISMATCH","DRIVE_FOLDER_UNAVAILABLE","DRIVE_ID_INVALID","DRIVE_ID_UNAVAILABLE","DRIVE_NOT_OWNER_PRIVATE","DRIVE_RESPONSE_INVALID","DRIVE_RESPONSE_LIMIT","DRIVE_SESSION_INVALID","DRIVE_TOKEN_INVALID","DRIVE_TRANSPORT_UNCERTAIN","QA_DELIVERY_BINDING_CHANGED","QA_DELIVERY_BYTES_CHANGED","QA_DELIVERY_JOB_NOT_FINALIZED","QA_DELIVERY_JOB_UNAVAILABLE","QA_DELIVERY_NOT_REQUESTED","QA_DELIVERY_NOT_RESERVED","QA_DELIVERY_PR_INVALID","QA_DELIVERY_RECORD_CONFLICT","QA_DELIVERY_REMOTE_IDENTITY","QA_DELIVERY_REQUEST_CONFLICT","QA_DELIVERY_REQUEST_UNAVAILABLE","QA_DELIVERY_RESULT_UNAVAILABLE","QA_DELIVERY_REVOKED","QA_DELIVERY_TARGET_CHANGED","QA_DRIVE_BINDING_CHANGED","QA_DRIVE_ENROLLMENT_REQUIRED","QA_JOB_TARGET_CHANGED","QA_PR_GRANT_CHANGED","QA_PR_HEAD_CHANGED","QA_PR_INVALID","QA_PR_READ_UNAVAILABLE","QA_PR_TARGET_CHANGED","QA_REPOSITORY_BINDING_CHANGED","QA_REPOSITORY_IDENTITY_CHANGED","QA_REPOSITORY_UNAVAILABLE","QA_SUPERVISED_DELIVERY_REQUIRED"])


def delivery_error_code(exc, fallback):
    # Only known fixed literals, never arbitrary exception text.
    value = exc.args[0] if len(exc.args) == 1 else None
    return value if type(value) is str and value in _DELIVERY_ERROR_CODE else fallback


def _write(conn, job, result):
    conn.execute("UPDATE jobs SET result=? WHERE id=?", (json.dumps(result, sort_keys=True), job))


def submit(jobs, actor, job, target, *, reconcile_only=False):
    with jobs.transaction() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=? AND principal=?", (job, actor)).fetchone()
        if (not row or row["workflow"] != "workspace_execute" or row["state"] != "SUCCEEDED"):
            raise PermissionError("QA_DELIVERY_JOB_UNAVAILABLE")
        result = json.loads(row["result"])
        if (result.get("qa_finalization", {}).get("state") != "SUCCEEDED"
                or result.get("head") != target["head"]
                or result.get("repository_id") != target["repository_id"]):
            raise ValueError("QA_DELIVERY_JOB_NOT_FINALIZED")
        previous = result.get("qa_delivery_request")
        if previous is not None:
            if previous["target"] != target:
                raise PermissionError("QA_DELIVERY_TARGET_CHANGED")
            if previous["state"] in {"QUEUED", "RUNNING"} or not reconcile_only:
                return previous["state"]
        if reconcile_only and previous is None:
            raise ValueError("QA_DELIVERY_NOT_REQUESTED")
        # A failed attempt before ID reservation is also safe to requeue:
        # the underlying delivery record is authoritative about remote effects.
        result["qa_delivery_request"] = {"target": target, "state": "QUEUED",
            "reconcile_only": bool(reconcile_only and result.get("qa_delivery") is not None)}
        _write(conn, job, result)
        return "QUEUED"


def recover(jobs):
    with exclusive_worker(jobs):
        with jobs.transaction() as conn:
            for row in conn.execute("SELECT id,result FROM jobs WHERE "
                    "json_extract(result,'$.qa_delivery_request.state')='RUNNING'").fetchall():
                result = json.loads(row["result"])
                result["qa_delivery_request"]["state"] = "INTERRUPTED"
                _write(conn, row["id"], result)


def process_one(jobs, delivery, *, enabled):
    if not enabled() or jobs.pending_effects():
        return
    # The normal worker is the only consumer; claim under its existing lock.
    with exclusive_worker(jobs):
        with jobs.transaction() as conn:
            row = conn.execute("SELECT id,principal,result FROM jobs WHERE "
                "state='SUCCEEDED' AND json_extract(result,'$.qa_delivery_request.state')='QUEUED' "
                "ORDER BY updated,id LIMIT 1").fetchone()
            if row is None or not enabled():
                return
            result = json.loads(row["result"])
            request = result["qa_delivery_request"]
            request["state"] = "RUNNING"
            _write(conn, row["id"], result)
    # deliver_qa acquires the same lock itself. The sole consumer cannot claim
    # another request until this returns; submit never executes the transfer.
    def check():
        if not enabled():
            raise PermissionError("QA_DELIVERY_REVOKED")
    target = request["target"]
    error_code = None
    try:
        check()
        delivery.run_queued(row["principal"], row["id"], target,
                            check_session=check, reconcile_only=request["reconcile_only"])
        state = "SUCCEEDED"
    except Exception as exc:
        state = "FAILED"
        error_code = delivery_error_code(exc, "QA_DELIVERY_FAILED")
        from .drive_delivery import DriveDeliveryError
        if isinstance(exc, DriveDeliveryError) and len(exc.args) == 1:
            value = exc.args[0]
            if type(value) is str and value in {f"DRIVE_HTTP_{n}" for n in range(400, 600)}:
                error_code = value
    with jobs.transaction() as conn:
        current = conn.execute("SELECT result FROM jobs WHERE id=?", (row["id"],)).fetchone()
        result = json.loads(current["result"])
        if result.get("qa_delivery_request") != request:
            raise RuntimeError("QA_DELIVERY_REQUEST_CONFLICT")
        result["qa_delivery_request"]["state"] = state
        if error_code is not None:
            result["qa_delivery_request"]["error_code"] = error_code
        _write(conn, row["id"], result)
