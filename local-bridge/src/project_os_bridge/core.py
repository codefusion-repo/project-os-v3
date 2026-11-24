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


class Jobs:
    """Single-host SQLite queue; no automatic retry of interrupted side effects."""
    def __init__(self, root: Path, policy: Policy, *, workflows=("probe_check",)):
        self.probe = Probe(root)
        self.policy = policy
        self.workflows = frozenset(workflows)
        if not self.workflows <= {"probe_check", "git_fixture_check"}:
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

    def submit(self, principal, resource, workflow, request_key):
        self.policy.require(principal, "submit", resource)
        if resource != "disposable" or workflow not in self.workflows:
            raise ValueError("Unknown workflow or resource")
        if workflow == "git_fixture_check":
            self.policy.require(principal, "git_workflow", resource)
        if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_key):
            raise ValueError("Invalid request key")
        with self.transaction() as c:
            row = c.execute("SELECT * FROM jobs WHERE principal=? AND resource=? AND request_key=?",
                            (principal,resource,request_key)).fetchone()
            if row:
                if row["workflow"] != workflow:
                    raise ValueError("Idempotency conflict")
                return row["id"]
            job_id = uuid.uuid4().hex
            stamp = now()
            c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                      (job_id,principal,resource,workflow,request_key,"QUEUED",None,stamp,stamp))
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

    def claim(self):
        with self.transaction() as c:
            while True:
                row = c.execute("SELECT * FROM jobs WHERE state='QUEUED' ORDER BY created,id LIMIT 1").fetchone()
                if not row:
                    return None
                try:
                    self.policy.require(row["principal"], "submit", row["resource"])
                    if row["workflow"] not in self.workflows:
                        raise PermissionError("Workflow disabled")
                    if row["workflow"] == "git_fixture_check":
                        self.policy.require(row["principal"], "git_workflow", row["resource"])
                except PermissionError:
                    self.transition(c,row["id"],"QUEUED","BLOCKED")
                    continue
                self.transition(c,row["id"],"QUEUED","RUNNING")
                return dict(row)

    def transition(self,c,job_id,old,new,result=None):
        cur = c.execute("UPDATE jobs SET state=?,result=?,updated=? WHERE id=? AND state=?",
                        (new,json.dumps(result) if result is not None else None,now(),job_id,old))
        if cur.rowcount != 1:
            raise RuntimeError("State conflict")
        self.event(c,job_id,new)

    def finish(self,job_id,state,result):
        if state not in {"SUCCEEDED","FAILED","BLOCKED"}:
            raise ValueError("Invalid terminal state")
        with self.transaction() as c:
            self.transition(c,job_id,"RUNNING",state,result)

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
