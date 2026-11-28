"""Local-only durable job core. Never register these operations on unauthenticated MCP."""
import json
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .probe import Probe


def now():
    return datetime.now(timezone.utc).isoformat()


class Policy:
    """Explicit local grants; caller identity must come from trusted transport, not tool input."""
    def __init__(self, grants):
        self.grants = frozenset(grants)

    def require(self, principal, operation, resource):
        if not principal or (principal, operation, resource) not in self.grants:
            raise PermissionError("DENIED")


class QueueLimitError(RuntimeError):
    pass


class Jobs:
    """Single-host SQLite queue; no automatic retry of interrupted side effects."""
    def __init__(self, root: Path, policy: Policy, *, workflows=("probe_check",)):
        self.probe = Probe(root)
        self.policy = policy
        self.workflows = frozenset(workflows)
        if not self.workflows <= {"probe_check", "fixture_package", "workspace_prepare", "workspace_execute"}:
            raise ValueError("Unknown workflow configuration")
        self.db = root / "jobs.sqlite3"
        import os
        try:
            fd = os.open(self.db, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        with self.transaction() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, principal TEXT NOT NULL, resource TEXT NOT NULL,
                workflow TEXT NOT NULL, request_key TEXT NOT NULL, state TEXT NOT NULL,
                result TEXT, created TEXT NOT NULL, updated TEXT NOT NULL,
                UNIQUE(principal, resource, request_key))""")
            c.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, state TEXT NOT NULL,
                at TEXT NOT NULL)""")

            # Parameters are scoped to the disposable package profile. Keep the
            # existing jobs schema readable/writable by retained older runtimes.
            if "fixture_package" in self.workflows:
                c.execute("""CREATE TABLE IF NOT EXISTS package_inputs (
                    job_id TEXT PRIMARY KEY, expected_sha TEXT NOT NULL)""")

            if self.workflows & {"workspace_prepare", "workspace_execute"}:
                c.execute("""CREATE TABLE IF NOT EXISTS workspace_inputs (
                    job_id TEXT PRIMARY KEY, request TEXT NOT NULL)""")

            # Legacy interrupted/uncertain fixtures have no recorded identity.
            # Do not infer absence or silently migrate their external effects.
            exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fixture_effects'").fetchone()
            c.execute("""CREATE TABLE IF NOT EXISTS fixture_effects (
                job_id TEXT PRIMARY KEY, token TEXT, resolved_at TEXT,
                context_id TEXT)""")
            if "context_id" not in {column["name"] for column in c.execute("PRAGMA table_info(fixture_effects)")}:
                c.execute("ALTER TABLE fixture_effects ADD COLUMN context_id TEXT")
            if not exists:
                for row in c.execute("SELECT id,state,result FROM jobs WHERE workflow='git_fixture_check' AND state NOT IN ('QUEUED','CANCELLED')").fetchall():
                    result = json.loads(row["result"] or "{}")
                    steps = result.get("steps", [])
                    if row["state"] == "SUCCEEDED" and steps and steps[-1].get("cleanup_verified") is True:
                        continue
                    c.execute("INSERT INTO fixture_effects(job_id) VALUES(?)", (row["id"],))

    def pending_effects(self):
        with self.transaction() as c:
            return [dict(row) for row in c.execute("SELECT job_id,token,context_id FROM fixture_effects WHERE resolved_at IS NULL ORDER BY job_id")]

    def resolve_effect(self, job_id, token, context_id):
        """Local reconciliation caller must hold exclusive worker lock and prove absence."""
        if not isinstance(context_id, str) or not re.fullmatch(r"[0-9a-f]{64}", context_id):
            raise PermissionError("Unknown fixture context")
        with self.transaction() as c:
            cur = c.execute("UPDATE fixture_effects SET resolved_at=? WHERE job_id=? AND token=? "
                            "AND context_id=? AND resolved_at IS NULL", (now(),job_id,token,context_id))
            if cur.rowcount != 1:
                raise RuntimeError("Reconciliation identity conflict")

    @contextmanager
    def transaction(self):
        self.probe._check_directory()
        self.probe._check_file(self.db)
        with closing(sqlite3.connect(self.db, timeout=5)) as c, c:
            c.row_factory = sqlite3.Row
            c.execute("BEGIN IMMEDIATE")
            yield c

    def event(self, c, job_id, state):
        c.execute("INSERT INTO events(job_id,state,at) VALUES(?,?,?)", (job_id,state,now()))

    def submit(self, principal, resource, workflow, request_key, *, expected_sha=None, workspace=None):
        self.policy.require(principal, "submit", resource)
        expected_resource = "disposable"
        if workflow in {"workspace_prepare", "workspace_execute"}:
            from .workspace_jobs import workspace_resource
            expected_resource = workspace_resource(self.policy)
        if resource != expected_resource or workflow not in self.workflows:
            raise ValueError("Unknown workflow or resource")
        if workflow == "fixture_package":
            self.policy.require(principal, "fixture_package", resource)
            if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
                raise ValueError("Full fixture SHA required")
        elif expected_sha is not None:
            raise ValueError("Unexpected revision parameter")
        if workflow in {"workspace_prepare", "workspace_execute"}:
            from .workspace_jobs import authorize_request
            authorize_request(self.policy, principal, workspace, execute=workflow == "workspace_execute")
            workspace = json.dumps(workspace, sort_keys=True, separators=(",", ":"))
        elif workspace is not None:
            raise ValueError("Unexpected workspace parameters")
        if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_key):
            raise ValueError("Invalid request key")
        with self.transaction() as c:
            row = c.execute("SELECT * FROM jobs WHERE principal=? AND resource=? AND request_key=?",
                            (principal,resource,request_key)).fetchone()
            if row:
                if row["workflow"] != workflow:
                    raise ValueError("Idempotency conflict")
                if workflow == "fixture_package":
                    parameters = c.execute("SELECT expected_sha FROM package_inputs WHERE job_id=?",
                                           (row["id"],)).fetchone()
                    if not parameters or parameters["expected_sha"] != expected_sha:
                        raise ValueError("Idempotency conflict")
                if workflow in {"workspace_prepare", "workspace_execute"}:
                    parameters = c.execute("SELECT request FROM workspace_inputs WHERE job_id=?",
                                           (row["id"],)).fetchone()
                    if not parameters or parameters["request"] != workspace:
                        raise ValueError("Idempotency conflict")
                return row["id"]
            # An active workspace execution owns a journaled effect until cleanup.
            # Admit other workspace jobs to the queue only; claim still fences all
            # unresolved effects and the exclusive worker remains unchanged.
            if workflow in {"workspace_prepare", "workspace_execute"}:
                unresolved = c.execute(
                    "SELECT 1 FROM fixture_effects e WHERE e.resolved_at IS NULL "
                    "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.id=e.job_id "
                    "AND j.state='RUNNING' AND j.workflow='workspace_execute' "
                    "AND e.token IS NOT NULL AND e.context_id IS NOT NULL) LIMIT 1"
                ).fetchone()
            else:
                unresolved = c.execute("SELECT 1 FROM fixture_effects WHERE resolved_at IS NULL LIMIT 1").fetchone()
            if unresolved:
                raise QueueLimitError("RECONCILIATION_REQUIRED")
            # Bound total retained rows and active work; no implicit deletion.
            if c.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 10000:
                raise QueueLimitError("JOB_STORAGE_LIMIT")
            if c.execute("SELECT count(*) FROM jobs WHERE principal=? AND state IN ('QUEUED','RUNNING')",
                         (principal,)).fetchone()[0] >= 32:
                raise QueueLimitError("ACTIVE_JOB_LIMIT")
            if workflow == "fixture_package" and c.execute(
                    "SELECT count(*) FROM jobs WHERE workflow='fixture_package'").fetchone()[0] >= 8:
                raise QueueLimitError("FIXTURE_STORAGE_LIMIT")
            if workflow in {"workspace_prepare", "workspace_execute"} and c.execute(
                    "SELECT count(*) FROM jobs WHERE workflow IN ('workspace_prepare','workspace_execute')").fetchone()[0] >= 8:
                raise QueueLimitError("WORKSPACE_STORAGE_LIMIT")
            job_id = uuid.uuid4().hex
            stamp = now()
            c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                      (job_id,principal,resource,workflow,request_key,"QUEUED",None,stamp,stamp))
            if workflow == "fixture_package":
                c.execute("INSERT INTO package_inputs VALUES(?,?)", (job_id, expected_sha))
            if workflow in {"workspace_prepare", "workspace_execute"}:
                c.execute("INSERT INTO workspace_inputs VALUES(?,?)", (job_id, workspace))
            self.event(c, job_id, "QUEUED")
            return job_id

    def get(self, principal, job_id):
        with self.transaction() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["principal"] != principal:
                raise PermissionError("DENIED")
            self.policy.require(principal, "read", row["resource"])
            return {"id": row["id"], "state": row["state"],
                    "result": json.loads(row["result"]) if row["result"] else None}

    def evidence(self, principal, job_id):
        with self.transaction() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["principal"] != principal:
                raise PermissionError("DENIED")
            self.policy.require(principal, "read", row["resource"])
            events = c.execute("SELECT state,at FROM events WHERE job_id=? ORDER BY id",
                               (job_id,)).fetchall()
            return {"id":row["id"], "workflow":row["workflow"], "state":row["state"],
                    "result":json.loads(row["result"]) if row["result"] else None,
                    "events":[dict(event) for event in events]}

    def claim(self, *, workspace_contexts=None):
        if workspace_contexts is not None:
            if (not isinstance(workspace_contexts, dict)
                    or any(not isinstance(key, str) or not isinstance(value, str)
                           or not re.fullmatch(r"[0-9a-f]{64}", value)
                           for key, value in workspace_contexts.items())):
                raise ValueError("Invalid workspace contexts")
        with self.transaction() as c:
            if c.execute("SELECT 1 FROM fixture_effects WHERE resolved_at IS NULL LIMIT 1").fetchone():
                return None
            while True:
                row = c.execute("SELECT * FROM jobs WHERE state='QUEUED' ORDER BY created,id LIMIT 1").fetchone()
                if not row:
                    return None
                try:
                    self.policy.require(row["principal"], "submit", row["resource"])
                    if row["workflow"] not in self.workflows:
                        raise PermissionError("Workflow disabled")
                    if row["workflow"] == "fixture_package":
                        self.policy.require(row["principal"], "fixture_package", row["resource"])
                        parameters = c.execute("SELECT expected_sha FROM package_inputs WHERE job_id=?",
                                               (row["id"],)).fetchone()
                        if not parameters or not re.fullmatch(r"[0-9a-f]{40}", parameters["expected_sha"]):
                            raise PermissionError("Missing package revision")
                    if row["workflow"] in {"workspace_prepare", "workspace_execute"}:
                        from .workspace_jobs import authorize_request
                        parameters = c.execute("SELECT request FROM workspace_inputs WHERE job_id=?",
                                               (row["id"],)).fetchone()
                        if not parameters:
                            raise PermissionError("Missing workspace request")
                        try:
                            workspace = json.loads(parameters["request"])
                            authorize_request(self.policy, row["principal"], workspace,
                                              execute=row["workflow"] == "workspace_execute")
                        except (ValueError, TypeError):
                            raise PermissionError("Invalid workspace request") from None
                    selected_context = None
                    if row["workflow"] == "workspace_execute":
                        if workspace_contexts is not None:
                            from .workspace_profiles import execution_route
                            key = execution_route(workspace["profile"], workspace["project"])
                            selected_context = workspace_contexts.get(key)
                            if selected_context is None:
                                raise PermissionError("Workspace profile context unavailable")
                        if workspace.get("context_id") != selected_context:
                            raise PermissionError("Workspace context unavailable")
                except PermissionError:
                    self.transition(c,row["id"],"QUEUED","BLOCKED")
                    continue
                self.transition(c,row["id"],"QUEUED","RUNNING")
                claimed = dict(row)
                if row["workflow"] in {"workspace_prepare", "workspace_execute"}:
                    claimed["workspace"] = workspace
                if row["workflow"] == "fixture_package":
                    claimed["expected_sha"] = parameters["expected_sha"]
                if row["workflow"] == "workspace_execute" and selected_context is not None:
                    effect_context = selected_context
                    token = uuid.uuid4().hex
                    c.execute("INSERT INTO fixture_effects(job_id,token,context_id) VALUES(?,?,?)",
                              (row["id"],token,effect_context))
                    claimed.update(effect_token=token, effect_context=effect_context)
                return claimed

    def transition(self,c,job_id,old,new,result=None):
        cur = c.execute("UPDATE jobs SET state=?,result=?,updated=? WHERE id=? AND state=?",
                        (new,json.dumps(result) if result is not None else None,now(),job_id,old))
        if cur.rowcount != 1:
            raise RuntimeError("State conflict")
        self.event(c,job_id,new)

    def finish(self,job_id,state,result, *, fixture_absent=False, fixture_context=None):
        if state not in {"SUCCEEDED","FAILED","BLOCKED"}:
            raise ValueError("Invalid terminal state")
        with self.transaction() as c:
            self.transition(c,job_id,"RUNNING",state,result)
            if fixture_absent is True:
                c.execute("UPDATE fixture_effects SET resolved_at=? WHERE job_id=? AND context_id=? AND resolved_at IS NULL",
                          (now(),job_id,fixture_context))

    def cancel(self,principal,job_id):
        with self.transaction() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["principal"] != principal:
                raise PermissionError("DENIED")
            self.policy.require(principal,"cancel",row["resource"])
            if row["state"] != "QUEUED":
                return False
            self.transition(c,job_id,"QUEUED","CANCELLED")
            return True

    def recover_interrupted(self):
        """Only call after exclusive worker lock is acquired."""
        with self.transaction() as c:
            rows = c.execute("SELECT id FROM jobs WHERE state='RUNNING'").fetchall()
            for row in rows:
                self.transition(c,row["id"],"RUNNING","INTERRUPTED")
            return len(rows)
