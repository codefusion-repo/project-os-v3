"""Durable delivery request in the existing QA job, executed by the service worker.

No second daemon or queue database. A running request interrupted by restart is
not replayed; an explicit reconciliation request reads the reserved remote ID.
"""
import json

from .worker import exclusive_worker


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
    try:
        check()
        delivery.run_queued(row["principal"], row["id"], target,
                            check_session=check, reconcile_only=request["reconcile_only"])
        state = "SUCCEEDED"
    except Exception:
        state = "FAILED"
    with jobs.transaction() as conn:
        current = conn.execute("SELECT result FROM jobs WHERE id=?", (row["id"],)).fetchone()
        result = json.loads(current["result"])
        if result.get("qa_delivery_request") != request:
            raise RuntimeError("QA_DELIVERY_REQUEST_CONFLICT")
        result["qa_delivery_request"]["state"] = state
        _write(conn, row["id"], result)
