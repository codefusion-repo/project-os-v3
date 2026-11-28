"""Read-only authorized Job observation; no persistent wait state or replay."""
import asyncio
import re
import time
from datetime import datetime, timezone
from .github_context import PROJECT

TERMINAL = frozenset({"SUCCEEDED", "FAILED", "BLOCKED", "INTERRUPTED", "CANCELLED"})
# Browser #67: 60 s server wait completed in 68.594 s end-to-end.
# Use half the observed successful server wait, not an assumed transport ceiling.
WAIT_LIMIT_SECONDS = 30
MEASUREMENT_SECONDS = (1, 5, 15, 30, 45, 60, 90, 120, 180, 240, 300, 450, 600)


def utc_stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("INVALID_JOB_TIME")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("INVALID_JOB_TIME")
    return stamp.astimezone(timezone.utc).isoformat()


def list_authorized(jobs, actor, access, check, *, project=None, resource=None,
                    state=None, since=None, cursor=None, limit=20):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("INVALID_JOB_LIMIT")
    if project is not None and (not isinstance(project, str) or
                                not PROJECT.fullmatch(project)):
        raise ValueError("INVALID_JOB_PROJECT")
    if cursor is not None:
        if not isinstance(cursor, str) or len(cursor) > 80:
            raise ValueError("INVALID_JOB_CURSOR")
        stamp, sep, ident = cursor.partition("|")
        if not sep or not re.fullmatch(r"[0-9a-f]{32}", ident):
            raise ValueError("INVALID_JOB_CURSOR")
        before = (utc_stamp(stamp), ident)
    else:
        before = None
    check()
    rows = jobs.list_candidates(actor, resource=resource, state=state,
                               since=utc_stamp(since) if since is not None else None,
                               before=before)
    visible = []
    for row in rows:
        check()
        # Internal capability/fetch records lack the workspace reader contract.
        if row["workflow"] not in {"probe_check", "fixture_package",
                                    "workspace_prepare", "workspace_execute"}:
            continue
        try:
            jobs.policy.require(actor, "read", row["resource"])
            request = access(row["id"])
        except PermissionError:
            continue
        alias = request.get("project") if isinstance(request, dict) else None
        if project is not None and alias != project:
            continue
        operation = request.get("profile") if isinstance(request, dict) else row["workflow"]
        elapsed = (datetime.fromisoformat(row["updated"]) if row["state"] in TERMINAL
                   else datetime.now(timezone.utc)) - datetime.fromisoformat(row["created"])
        visible.append({**row, "project": alias, "operation": operation,
                        "elapsed_seconds": max(0, int(elapsed.total_seconds()))})
        if len(visible) > limit:
            break
    more = len(visible) > limit
    page = visible[:limit]
    # Revalidate all returned rows, not just the last row; on revocation
    # abort the page rather than expose stale authorization or a hidden cursor.
    for row in page:
        check()
        jobs.policy.require(actor, "read", row["resource"])
        request = access(row["id"])
        alias = request.get("project") if isinstance(request, dict) else None
        operation = request.get("profile") if isinstance(request, dict) else row["workflow"]
        if alias != row["project"] or operation != row["operation"]:
            raise PermissionError("DENIED")
    check()
    return {"jobs": page, "next_cursor": (page[-1]["created"] + "|" + page[-1]["id"]
                                         if more else None), "snapshot": "observed"}


async def measure_wait(seconds, check):
    if type(seconds) is not int or seconds not in MEASUREMENT_SECONDS:
        raise ValueError("INVALID_MEASUREMENT_DURATION")
    check()
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        await asyncio.sleep(min(0.25, max(0, seconds - (time.monotonic() - start))))
        check()
    return {"requested_seconds": seconds, "server_elapsed_seconds": round(time.monotonic()-start, 3),
            "status": "completed", "job_created": False}


async def wait_for_job(read_job, check, seconds, *, max_seconds):
    if type(seconds) is not int or not 0 <= seconds <= max_seconds:
        raise ValueError("WAIT_DURATION_UNAVAILABLE")
    start = time.monotonic()
    while True:
        check()
        result = await asyncio.to_thread(read_job)
        check()
        elapsed = time.monotonic() - start
        if result["state"] in TERMINAL or elapsed >= seconds:
            return {"job": result, "terminal": result["state"] in TERMINAL,
                    "wait_expired": result["state"] not in TERMINAL,
                    "elapsed_seconds": round(elapsed, 3)}
        await asyncio.sleep(min(0.5, max(0, seconds-elapsed)))
