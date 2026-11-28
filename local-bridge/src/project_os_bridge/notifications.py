"""Optional Resend terminal mail, sourced from existing durable records.

No mail in a Job transaction, no new daemon/queue. One bounded attempt per
service cycle; provider acceptance is not inbox delivery.
"""
import hashlib
import html
import http.client
import json
import logging
import re
import time
from datetime import datetime, timezone

from .maintenance import read_json, private_dir, validate_record
from .observability import TERMINAL, utc_stamp
from .workspace_profiles import PROFILES, CODEX_PROFILE

LOG = logging.getLogger("project_os.notifications")
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}")
ALIAS = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
KEY = re.compile(r"re_[A-Za-z0-9_-]{8,200}")
TERMINAL_MAINTENANCE = {"SUCCEEDED", "BLOCKED", "LOCAL_RECOVERY_REQUIRED"}
MAX_AGE = 23 * 3600  # Margin within provider's 24h idempotency window.
MAX_ATTEMPTS = 3
COLORS = {"SUCCEEDED": "#047857", "FAILED": "#b91c1c", "BLOCKED": "#b45309",
          "INTERRUPTED": "#b45309", "CANCELLED": "#475569",
          "LOCAL_RECOVERY_REQUIRED": "#b91c1c"}


def record_delivery_event(result, state, at):
    # Stored atomically with the existing delivery state; later reconciliation
    # cannot erase the earlier terminal notification identity.
    history = result.setdefault("qa_delivery_events", [])
    history.append({"state": state, "at": at, "sequence": len(history) + 1})


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def config(root):
    data = read_json(root / "resend.json", 16384)
    if (not isinstance(data, dict) or set(data) != {"api_key", "from", "recipients", "enabled_since"}
            or not isinstance(data["api_key"], str) or not KEY.fullmatch(data["api_key"])
            or not isinstance(data["from"], str) or len(data["from"]) > 254
            or not EMAIL.fullmatch(data["from"])):
        raise ValueError("INVALID_RESEND_CONFIG")
    data["enabled_since"] = utc_stamp(data["enabled_since"])
    recipients = data["recipients"]
    if not isinstance(recipients, dict) or not 1 <= len(recipients) <= 10:
        raise ValueError("INVALID_RESEND_RECIPIENTS")
    for email, projects in recipients.items():
        if (not isinstance(email, str) or len(email) > 254 or not EMAIL.fullmatch(email)
                or not isinstance(projects, list) or not 1 <= len(projects) <= 100
                or any(not isinstance(p, str) or not ALIAS.fullmatch(p) for p in projects)
                or len(set(projects)) != len(projects)):
            raise ValueError("INVALID_RESEND_RECIPIENTS")
    return data


def event(identity, project, operation, state, at, ident, created=None):
    if (not re.fullmatch(r"[0-9a-f]{32}|[0-9a-f]{64}", ident)
            or not ALIAS.fullmatch(project) or state not in COLORS):
        raise ValueError("INVALID_NOTIFICATION_EVENT")
    at = utc_stamp(at)
    duration = None if created is None else max(0, int((datetime.fromisoformat(at)
                  - datetime.fromisoformat(utc_stamp(created))).total_seconds()))
    return {"identity": identity, "project": project, "operation": operation,
            "state": state, "at": at, "id": ident, "duration_seconds": duration}


def email_body(item, sender, recipient):
    state, project, operation = (item[k] for k in ("state", "project", "operation"))
    details = [("Project", project), ("Operation", operation), ("Job / request", item["id"]),
               ("Completed UTC", item["at"])]
    if item["duration_seconds"] is not None:
        details.append(("Elapsed (includes queue)", str(item["duration_seconds"]) + " s"))
    note = ("Recorded terminal outcome of this operation. A successful build or implementation "
            "does not establish review, merge or delivery. Consult authorized Project OS evidence.")
    rows = "".join('<tr><td style="padding:8px 0;color:#64748b;font-size:12px">'
                   + html.escape(k) + '</td></tr><tr><td style="padding:0 0 12px;'
                   'color:#0f172a;word-break:break-word">' + html.escape(v) + '</td></tr>'
                   for k, v in details)
    body = ('<!doctype html><html lang="en"><body style="margin:0;background:#f1f5f9;'
            'font-family:Arial,sans-serif;color:#0f172a"><table role="presentation" width="100%" '
            'style="padding:24px 12px"><tr><td align="center"><table role="presentation" '
            'width="100%" style="max-width:560px;background:#ffffff;border-radius:16px;'
            'border:1px solid #e2e8f0"><tr><td style="padding:28px">'
            '<p style="font-size:12px;font-weight:bold;letter-spacing:2px;color:#475569">PROJECT OS</p>'
            '<span style="font-weight:bold;color:' + COLORS[state] + '">' + html.escape(state)
            + '</span><h1 style="font-size:24px;line-height:1.3">' + html.escape(operation)
            + '</h1><table role="presentation" width="100%">' + rows + '</table><hr style="border:0;'
            'border-top:1px solid #e2e8f0"><p style="font-size:13px;line-height:1.6;color:#475569">'
            + html.escape(note) + '</p></td></tr></table></td></tr></table></body></html>')
    return {"from": sender, "to": [recipient], "subject": "Project OS | " + state + " | " + operation,
            "html": body, "text": "Project OS — " + state + "\n"
            + "\n".join(k + ": " + v for k, v in details) + "\n\n" + note}


def send(api_key, key, payload):
    """Fixed TLS endpoint; no redirects, proxies, arbitrary URL or raw error body."""
    conn = http.client.HTTPSConnection("api.resend.com", timeout=3)
    try:
        conn.request("POST", "/emails", canonical(payload).encode("utf-8"), {
            "Authorization": "Bearer " + api_key, "Content-Type": "application/json",
            "Idempotency-Key": key, "User-Agent": "project-os-bridge"})
        response = conn.getresponse()
        if response.status == 429:
            value = response.getheader("Retry-After", "")
            delay = min(86400, int(value)) if value.isascii() and value.isdecimal() and len(value) <= 6 else 60
            return "RETRY", None, max(60, delay)
        if response.status >= 500 or response.status in {408, 409}:
            return "RETRY", None, 60
        if not 200 <= response.status < 300:
            return "FAILED", None, 0
        raw = response.read(8193)
        if len(raw) > 8192:
            return "RETRY", None, 60
        ident = json.loads(raw).get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", ident):
            return "RETRY", None, 60
        return "ACCEPTED", ident, 0
    except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
        return "RETRY", None, 60
    finally:
        conn.close()


class NotificationSender:
    def __init__(self, jobs, actor, enabled, *, transport=send, clock=time.time):
        self.jobs, self.actor, self.enabled = jobs, actor, enabled
        self.transport, self.clock = transport, clock
        self.next_scan = 0
        self.last_error = None

    def schema(self):
        with self.jobs.transaction() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS notification_receipts (
                key TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL,
                state TEXT NOT NULL, first_attempt REAL NOT NULL, attempts INTEGER NOT NULL,
                next_attempt REAL NOT NULL, provider_id TEXT)""")

    def events(self, since):
        from .workspace_jobs import require_workspace_job
        with self.jobs.transaction() as c:
            rows = [dict(row) for row in c.execute(
                "SELECT j.id,j.created,j.result,j.workflow FROM jobs j "
                "WHERE j.principal=? AND j.resource='workspace' "
                "AND j.workflow IN ('workspace_execute','workspace_prepare') "
                "ORDER BY j.created,j.id", (self.actor,))]
            transitions = [dict(row) for row in c.execute(
                "SELECT e.id,e.job_id,e.state,e.at FROM events e JOIN jobs j ON j.id=e.job_id "
                "WHERE j.principal=? AND j.resource='workspace' "
                "AND e.at>=? AND e.state IN ('SUCCEEDED','FAILED','BLOCKED','INTERRUPTED','CANCELLED') "
                "ORDER BY e.id", (self.actor, since))]
        by_job = {}
        for transition in transitions:
            by_job.setdefault(transition["job_id"], []).append(transition)
        for row in rows:
            result = json.loads(row["result"] or "{}")
            delivery_events = result.get("qa_delivery_events", [])
            finalized_at = result.get("qa_finalization_at")
            if row["id"] not in by_job and not delivery_events and not finalized_at:
                continue
            try:
                request = require_workspace_job(self.jobs, self.actor, row["id"], allow_execute=True)
            except (OSError, ValueError, TypeError, PermissionError):
                continue
            project, profile = request["project"], request["profile"]
            if profile not in {*PROFILES, CODEX_PROFILE} and row["workflow"] != "workspace_prepare":
                continue
            for t in by_job.get(row["id"], []):
                yield event("job/" + row["id"] + "/" + str(t["id"]), project, profile,
                            t["state"], t["at"], row["id"], row["created"])
            if finalized_at and finalized_at >= since:
                yield event("sign/" + row["id"], project, "qa-signing",
                            result["qa_finalization"]["state"], finalized_at, row["id"])
            if delivery_events:
                try:
                    self.jobs.policy.require(self.actor, "workspace_delivery", project)
                except PermissionError:
                    continue
                for t in delivery_events:
                    if t["at"] >= since:
                        yield event("delivery/" + row["id"] + "/" + str(t["sequence"]), project,
                                    "qa-delivery", t["state"], t["at"], row["id"])
        try:
            self.jobs.policy.require(self.actor, "maintenance", "installation")
        except PermissionError:
            return
        directory = self.jobs.probe.root.parent / "service" / "maintenance"
        try:
            private_dir(directory)
        except FileNotFoundError:
            return
        for path in sorted(directory.iterdir()):
            if path.name != "active.json" and not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
                continue
            try:
                record = validate_record(read_json(path))
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if record["state"] not in TERMINAL_MAINTENANCE or record["updated_at"] < since:
                continue
            req = record["request"]
            yield event("maintenance/" + req["id"] + "/" + record["state"], "installation",
                        "maintenance-" + req["action"], record["state"], record["updated_at"], req["id"])

    def deliver(self, cfg, item, recipient):
        key = digest("project-os/v1/" + item["identity"] + "/" + recipient)
        payload = email_body(item, cfg["from"], recipient)
        payload_hash = digest(canonical(payload))
        now = self.clock()
        with self.jobs.transaction() as c:
            row = c.execute("SELECT * FROM notification_receipts WHERE key=?", (key,)).fetchone()
            if row:
                if row["state"] in {"ACCEPTED", "FAILED", "UNCERTAIN"}:
                    return False
                if (row["payload_sha256"] != payload_hash or now < row["first_attempt"]
                        or now - row["first_attempt"] >= MAX_AGE or row["attempts"] >= MAX_ATTEMPTS):
                    c.execute("UPDATE notification_receipts SET state='UNCERTAIN' WHERE key=?", (key,))
                    return False
                if row["next_attempt"] > now:
                    return False
                c.execute("UPDATE notification_receipts SET state='SENDING',attempts=attempts+1 WHERE key=?", (key,))
            else:
                c.execute("INSERT INTO notification_receipts VALUES(?,?, 'SENDING',?,1,?,NULL)",
                          (key, payload_hash, now, now))
        # Re-read config and global opt-in just before network, no DB lock.
        if not self.enabled() or config(self.jobs.probe.root) != cfg:
            return True  # reserved attempt, no external effect; safely reconciled next cycle
        status, provider_id, delay = self.transport(cfg["api_key"], key, payload)
        with self.jobs.transaction() as c:
            c.execute("UPDATE notification_receipts SET state=?,provider_id=?,next_attempt=? WHERE key=?",
                      (status, provider_id, self.clock() + delay, key))
        return True

    def tick(self):
        now = self.clock()
        if now < self.next_scan or not self.enabled():
            return
        self.next_scan = now + 5
        try:
            cfg = config(self.jobs.probe.root)
            self.schema()
            for item in self.events(cfg["enabled_since"]):
                for recipient, projects in cfg["recipients"].items():
                    if item["project"] in projects and self.deliver(cfg, item, recipient):
                        self.last_error = None
                        return
            self.last_error = None
        except FileNotFoundError:
            return  # optional, never required for Job execution
        except Exception:
            if self.last_error != "NOTIFICATION_UNAVAILABLE":
                LOG.warning("NOTIFICATION_UNAVAILABLE; inspect private configuration or delivery receipts")
            self.last_error = "NOTIFICATION_UNAVAILABLE"
