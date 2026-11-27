"""Bounded single-installation maintenance. The one-shot runner uses host Python.

No tool input selects a command, executable, repository, path, URL, unit or grant.
The runner reuses the reviewed lifecycle and upgrade coordinator. A local
operator remains responsible for recovery if the only MCP transport goes down.
"""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

REPO = "codefusion-repo/project-os-v3"
ORIGIN = "https://github.com/" + REPO + ".git"
REPO_ID = 1456935737
WORKFLOW_ID = 417662346
WORKFLOW_PATH = ".github/workflows/selector-ci.yml"
APP_ID = 15368
FLAG = "allow-remote-maintenance"
FLAGS = ("allow-authenticated-probe", "allow-operational-diagnostics", "allow-github-context")
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
PATH = re.compile(r"/[A-Za-z0-9_./-]+")
RECEIPT = ".project-os-bridge-install.json"
UNIT = "project-os-bridge-maintenance.service"
TERMINAL = {"SUCCEEDED", "BLOCKED"}
STAGES = {"accepted", "preflight", "quiescing", "stopped", "fenced",
          "installing", "restoring", "starting", "complete"}
STATES = {"ACCEPTED", "RUNNING", "SUCCEEDED", "BLOCKED", "LOCAL_RECOVERY_REQUIRED"}


def private_dir(path):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise PermissionError("Unsafe maintenance directory")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError("Unsafe maintenance directory")


def private_bytes(path, limit):
    private_dir(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > limit):
            raise PermissionError("Unsafe maintenance file")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Maintenance file too large")
        return data


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def read_json(path, limit=16384):
    return json.loads(private_bytes(path, limit), object_pairs_hook=unique)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path, data):
    private_dir(path.parent)
    if os.path.lexists(path):
        private_bytes(path, 16384)
    fd, tmp = tempfile.mkstemp(prefix=".request-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def receipt(venv):
    data = read_json(venv / RECEIPT, 1024)
    if (not isinstance(data, dict) or set(data) != {"sha", "wheel_sha256"}
            or not isinstance(data["sha"], str) or not SHA.fullmatch(data["sha"])
            or not isinstance(data["wheel_sha256"], str) or not DIGEST.fullmatch(data["wheel_sha256"])):
        raise ValueError("Invalid receipt")
    return data


def request_id(key):
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError("INVALID_MAINTENANCE_REQUEST")
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def request(action, expected, target, wheel, run_id, ident):
    if (action not in ("update", "rollback") or not isinstance(expected, str)
            or not SHA.fullmatch(expected) or not isinstance(target, str) or not SHA.fullmatch(target)
            or expected == target or not isinstance(wheel, str) or not DIGEST.fullmatch(wheel)
            or not isinstance(ident, str) or not DIGEST.fullmatch(ident)
            or (action == "update" and (type(run_id) is not int or not 0 < run_id < 2**63))
            or (action == "rollback" and run_id is not None)):
        raise ValueError("INVALID_MAINTENANCE_REQUEST")
    return {"id": ident, "action": action, "expected_sha": expected,
            "target_sha": target, "wheel_sha256": wheel, "ci_run_id": run_id}


def validate_record(record):
    if not isinstance(record, dict) or set(record) != {"request", "state", "stage", "flags", "previous", "updated_at"}:
        raise ValueError("Invalid maintenance record")
    req = record["request"]
    if req != request(req["action"], req["expected_sha"], req["target_sha"],
                      req["wheel_sha256"], req["ci_run_id"], req["id"]):
        raise ValueError("Invalid maintenance request")
    if (record["state"] not in STATES or record["stage"] not in STAGES
            or type(record["flags"]) is not list or len(set(record["flags"])) != len(record["flags"])
            or not set(record["flags"]) <= set(FLAGS)
            or not isinstance(record["previous"], dict)
            or set(record["previous"]) != {"sha", "wheel_sha256"}
            or record["previous"]["sha"] != req["expected_sha"]
            or not isinstance(record["previous"]["wheel_sha256"], str)
            or not DIGEST.fullmatch(record["previous"]["wheel_sha256"])
            or not isinstance(record["updated_at"], str)):
        raise ValueError("Invalid maintenance state")
    return record


def public(record):
    # No filesystem paths, request key, principal, markers, logs or exceptions.
    return {**record["request"], "state": record["state"], "stage": record["stage"],
            "updated_at": record["updated_at"],
            "readiness_basis": "local_tls_and_anonymous_401" if record["state"] == "SUCCEEDED" else None}


def clean_env():
    uid = os.getuid()
    return {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LC_ALL": "C",
            "XDG_RUNTIME_DIR": f"/run/user/{uid}",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0"}


def command(*args, timeout=60):
    result = subprocess.run(args, env=clean_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("Maintenance command failed")
    return result.stdout


def git(kit, *args):
    return command("/usr/bin/git", "-C", str(kit), "-c", "core.hooksPath=/dev/null",
                   "-c", "core.fsmonitor=false", "-c", "credential.helper=",
                   "-c", "submodule.recurse=false", *args, timeout=90).decode().strip()


def api(path):
    # Public canonical repository only. No token, redirects, caller URL or proxy.
    conn = http.client.HTTPSConnection("api.github.com", timeout=10)
    try:
        conn.request("GET", "/repos/" + REPO + path, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "Project-OS-maintenance",
            "X-GitHub-Api-Version": "2022-11-28"})
        response = conn.getresponse()
        if response.status != 200 or response.getheader("Link"):
            raise ValueError("Incomplete GitHub evidence")
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Oversized GitHub evidence")
        return json.loads(raw, object_pairs_hook=unique)
    finally:
        conn.close()


def approved_wheel(req, run):
    # The successful probe publishes its validated install receipt under an
    # immutable artifact name containing the attempt and wheel digest.
    # GitHub's public metadata is sufficient; no ZIP download, redirect,
    # credentials or CI log parsing. The archive digest is NOT the wheel digest.
    attempt = run["run_attempt"]
    if type(attempt) is not int or attempt < 1:
        raise ValueError("Invalid CI attempt")
    prefix = f"maintenance-wheel-{attempt}-"
    evidence = api("/actions/runs/" + str(req["ci_run_id"]) + "/artifacts?per_page=100")
    artifacts = evidence["artifacts"]
    if evidence["total_count"] != len(artifacts):
        raise ValueError("Incomplete wheel evidence")
    matches = [a for a in artifacts if a["name"].startswith(prefix)]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous wheel evidence")
    artifact = matches[0]
    identity = artifact["workflow_run"]
    if (artifact["expired"] is not False
            or identity["id"] != req["ci_run_id"]
            or identity["repository_id"] != REPO_ID
            or identity["head_repository_id"] != REPO_ID
            or identity["head_branch"] != "main"
            or identity["head_sha"] != req["target_sha"]
            or artifact["name"] != prefix + req["wheel_sha256"]):
        raise ValueError("Unapproved wheel digest")


def approved_main(req):
    sha = req["target_sha"]
    run = api("/actions/runs/" + str(req["ci_run_id"]))
    if (run["id"] != req["ci_run_id"] or run["workflow_id"] != WORKFLOW_ID
            or run["path"].split("@", 1)[0] != WORKFLOW_PATH
            or run["repository"]["id"] != REPO_ID or run["head_repository"]["id"] != REPO_ID
            or run["event"] != "push" or run["head_branch"] != "main" or run["head_sha"] != sha
            or run["status"] != "completed" or run["conclusion"] != "success"):
        raise ValueError("Unapproved CI run")
    rules = api("/rules/branches/main")
    required = set()
    if not isinstance(rules, list) or not any(r["type"] == "pull_request" for r in rules):
        raise ValueError("Missing branch protection")
    for rule in rules:
        if rule["type"] == "required_status_checks":
            for check in rule["parameters"]["required_status_checks"]:
                required.add((check["context"], check["integration_id"]))
    # The existing CI's tests and installation probe must remain required.
    if not {("tests", APP_ID), ("probe", APP_ID)} <= required:
        raise ValueError("Missing required CI checks")
    result = api("/commits/" + sha + "/check-runs?per_page=100")
    checks = result["check_runs"]
    if result["total_count"] != len(checks):
        raise ValueError("Incomplete checks")
    passed = {(c["name"], c["app"]["id"]) for c in checks
              if c["head_sha"] == sha and c["check_suite"]["id"] == run["check_suite_id"]
              and c["status"] == "completed" and c["conclusion"] == "success"}
    if not required <= passed:
        raise ValueError("Required CI check failed")
    approved_wheel(req, run)
    if api("/git/ref/heads/main")["object"]["sha"] != sha:
        raise ValueError("Target is not current main")


class Maintenance:
    def __init__(self, root, kit):
        self.root, self.kit = root, kit
        self.state = root / "state"
        self.store = root / "service" / "maintenance"
        self.active = self.store / "active.json"
        self.venv = kit / "local-bridge/.venv"
        self.python = self.venv / "bin/python"

    def enabled(self):
        try:
            private_dir(self.root)
            private_dir(self.state)
            return (all(private_bytes(self.state / name, 0) == b""
                        for name in (FLAG, FLAGS[0]))
                    and not any(os.path.lexists(self.state / name)
                                for name in ("fixture-image", "local-fixture-mode", "workspace-grants.json", "workspace-execution.json")))
        except (OSError, ValueError):
            return False

    @contextmanager
    def locked(self):
        private_dir(self.store.parent)
        self.store.mkdir(mode=0o700, exist_ok=True)
        private_dir(self.store)
        fd = os.open(self.store / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
                raise PermissionError("Unsafe maintenance lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def current(self):
        return validate_record(read_json(self.active)) if os.path.lexists(self.active) else None

    def lookup(self, ident):
        active = self.current()
        if active and active["request"]["id"] == ident:
            return active
        path = self.store / (ident + ".json")
        if os.path.lexists(path):
            result = validate_record(read_json(path))
            if result["request"]["id"] != ident:
                raise ValueError("Invalid historical request")
            return result
        return None

    def status(self, key):
        ident = request_id(key)
        try:
            with self.locked():
                record = self.lookup(ident)
                return public(record) if record else {"state": "NOT_FOUND"}
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            raise ValueError("MAINTENANCE_STATUS_UNAVAILABLE") from None

    def transition(self, record, state, stage):
        record.update(state=state, stage=stage, updated_at=datetime.now(timezone.utc).isoformat())
        save(self.active, validate_record(record))

    def launch(self, ident):
        # This is a transient SERVICE, never a scope of the MCP service.
        # Host interpreter and script bytes are loaded before the venv moves.
        for path in (self.root, self.kit, Path(__file__)):
            if not PATH.fullmatch(str(path)) or path.resolve(strict=True) != path:
                raise ValueError("Invalid maintenance installation path")
        env = clean_env()
        command("/usr/bin/systemd-run", "--user", "--collect", "--no-block",
                "--unit=" + UNIT, "--property=Type=exec", "--property=UMask=0077",
                "--property=WorkingDirectory=/", "--property=StandardOutput=null",
                "--property=StandardError=null", "/usr/bin/env", "-i",
                *(key + "=" + value for key, value in env.items()),
                "/usr/bin/python3", "-I", "-B", str(Path(__file__)),
                "--run", str(self.root), str(self.kit), ident, timeout=10)

    def submit(self, action, expected, target, wheel, run_id, key, *, authorize):
        req = request(action, expected, target, wheel, run_id, request_id(key))
        try:
            with self.locked():
                authorize()
                if not self.enabled():
                    raise PermissionError("DENIED")
                existing = self.lookup(req["id"])
                if existing:
                    if existing["request"] != req:
                        raise ValueError("REQUEST_KEY_CONFLICT")
                    return public(existing)
                old = self.current()
                if old and old["state"] not in TERMINAL:
                    raise RuntimeError("MAINTENANCE_BUSY_OR_UNCONFIRMED")
                previous = receipt(self.venv)
                if previous["sha"] != expected:
                    raise ValueError("INSTALLED_SHA_MISMATCH")
                if old:
                    history = self.store / (old["request"]["id"] + ".json")
                    if os.path.lexists(history):
                        raise RuntimeError("Maintenance history conflict")
                    self.active.rename(history)
                    sync_dir(self.store)
                record = {"request": req, "previous": previous, "flags": [],
                          "updated_at": "", "state": "ACCEPTED", "stage": "accepted"}
                self.transition(record, "ACCEPTED", "accepted")
                try:
                    authorize()
                    if not self.enabled():
                        self.transition(record, "BLOCKED", "accepted")
                        return public(record)
                except PermissionError:
                    self.transition(record, "BLOCKED", "accepted")
                    raise
                # A lost reply or systemd timeout is not evidence that launch failed.
                # Leave ACCEPTED durable; runner or local reconciliation may resolve it.
                try:
                    self.launch(req["id"])
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                    pass
                return public(record)
        except PermissionError:
            raise PermissionError("DENIED") from None
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
            raise ValueError("MAINTENANCE_REQUEST_BLOCKED_OR_UNCONFIRMED") from None

    def checkout(self):
        if (git(self.kit, "rev-parse", "--show-toplevel") != str(self.kit)
                or git(self.kit, "config", "--local", "--get", "remote.origin.url") != ORIGIN
                or git(self.kit, "status", "--porcelain", "--untracked-files=normal")
                or any(os.path.lexists(self.kit / ".git" / name) for name in
                       ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG"))):
            raise ValueError("Checkout unavailable")
        branch = git(self.kit, "rev-parse", "--abbrev-ref", "HEAD")
        if branch not in ("HEAD", "main"):
            raise ValueError("Unsupported maintenance branch")
        return git(self.kit, "rev-parse", "HEAD"), branch

    def lifecycle(self, action):
        raw = command(str(self.python), "-I", "-m", "project_os_bridge.lifecycle",
                      "--root", str(self.root), action, timeout=160).decode().strip()
        expected = "inactive" if action == "stop" else "active"
        if raw != f"linked=True active={expected} enabled=False pending_job=False":
            raise RuntimeError("Unexpected lifecycle state")

    def coordinator(self, head, action, *args):
        command("/usr/bin/python3", "-I", "-B", str(self.kit / "local-bridge/scripts/upgrade.py"),
                action, head, "--root", str(self.root), "--bound-python", str(self.python),
                *args, timeout=1800)

    def rollback_tx(self):
        return read_json(self.venv.parent / ".venv-install.rollback/transaction.json")

    def idle_jobs(self):
        # Early read-only check to avoid a predictable service outage. The
        # existing coordinator repeats the authoritative check after stop.
        db = self.state / "jobs.sqlite3"
        info = db.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > 128 * 1024 * 1024):
            raise PermissionError("Unsafe jobs database")
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            if conn.execute("SELECT 1 FROM jobs WHERE state IS NULL OR state NOT IN "
                            "('SUCCEEDED','FAILED','BLOCKED','CANCELLED','INTERRUPTED') LIMIT 1").fetchone():
                raise RuntimeError("Pending jobs")
            if conn.execute("SELECT 1 FROM jobs WHERE json_extract(result,'$.qa_delivery_request.state') IN ('QUEUED','RUNNING') LIMIT 1").fetchone():
                raise RuntimeError("Pending QA delivery")
            if conn.execute("SELECT 1 FROM fixture_effects WHERE resolved_at IS NULL LIMIT 1").fetchone():
                raise RuntimeError("Unresolved effects")

    def preflight(self, record):
        req = record["request"]
        if not self.enabled() or receipt(self.venv) != record["previous"]:
            raise PermissionError("Maintenance admission changed")
        # Only the exact running, linked, disabled non-fixture instance.
        self.lifecycle("status")
        self.idle_jobs()
        head, branch = self.checkout()
        if os.path.lexists(self.venv.parent / ".venv-install.guard/active.json"):
            raise RuntimeError("Unresolved install")
        profile = read_json(self.root / "service/runtime.json", 65536)
        if profile.get("image", "invalid") is not None or "podman_context" in profile:
            raise ValueError("Fixture profile")
        target = req["target_sha"]
        if req["action"] == "update":
            approved_main(req)
            git(self.kit, "fetch", "--no-tags", "--no-recurse-submodules", ORIGIN, "refs/heads/main")
            if git(self.kit, "rev-parse", "FETCH_HEAD") != target:
                raise ValueError("Main moved")
            git(self.kit, "merge-base", "--is-ancestor", head, target)
            git(self.kit, "merge-base", "--is-ancestor", req["expected_sha"], target)
            if os.path.lexists(self.venv.parent / ".venv-install.rollback"):
                tx = self.rollback_tx()
                if tx["sha"] == target:
                    raise ValueError("Retained transaction for target; reconcile locally")
        else:
            # Do not fetch or choose an arbitrary historical revision. The
            # existing transaction identifies the only eligible predecessor.
            tx = self.rollback_tx()
            if (head != req["expected_sha"] or tx["sha"] != head or tx["phase"] != "installed"
                    or tx["root"] != str(self.root) or tx["wheel"] != record["previous"]["wheel_sha256"]
                    or tx["prior"]["eligible"] is not True
                    or tx["prior"]["reviewed"] != {"sha": target, "wheel_sha256": req["wheel_sha256"]}):
                raise ValueError("Rollback identity mismatch")
            # A rollback that removes the remote maintenance API needs local
            # recovery instead; don't strand the operator without status.
            git(self.kit, "cat-file", "-e", target + ":local-bridge/src/project_os_bridge/maintenance.py")
        flags = [name for name in FLAGS if os.path.lexists(self.state / name)]
        for name in flags:
            if private_bytes(self.state / name, 0) != b"":
                raise ValueError("Invalid opt-in")
        if FLAGS[0] not in flags or not self.enabled() or self.checkout() != (head, branch):
            raise PermissionError("Maintenance admission changed")
        record["flags"] = flags
        return head, branch

    def archive_oauth(self, ident):
        path = self.state / "oauth-audit.jsonl"
        if not os.path.lexists(path):
            return
        raw = private_bytes(path, 4 * 1024 * 1024)
        for line in raw.splitlines():
            entry = json.loads(line, object_pairs_hook=unique)
            if (set(entry) != {"at", "event", "status", "auth_outcome"}
                    or entry["event"] != "mcp_http" or type(entry["status"]) is not int
                    or not 200 <= entry["status"] <= 599
                    or not isinstance(entry["auth_outcome"], str)
                    or not re.fullmatch(r"(?:TOKEN_[A-Z_]{1,64}|JWKS_UNAVAILABLE)", entry["auth_outcome"])
                    or datetime.fromisoformat(entry["at"]).utcoffset() is None):
                raise ValueError("Invalid OAuth audit")
        archive = self.store / ("oauth-" + ident + ".jsonl")
        if os.path.lexists(archive):
            raise RuntimeError("OAuth archive exists")
        path.rename(archive)
        sync_dir(self.state)
        sync_dir(self.store)
        if hashlib.sha256(private_bytes(archive, 4 * 1024 * 1024)).digest() != hashlib.sha256(raw).digest():
            raise RuntimeError("OAuth archive mismatch")

    def readiness(self):
        cfg = read_json(self.root / "oauth.json", 16384)
        ca = self.root / "service/ca.pem"
        private_bytes(ca, 65536)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=str(ca))
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            conn = http.client.HTTPSConnection("127.0.0.1", 8765, timeout=2, context=context)
            try:
                conn.request("GET", "/.well-known/oauth-protected-resource/mcp")
                response = conn.getresponse()
                body = response.read(16385)
                if response.status == 200 and len(body) <= 16384:
                    data = json.loads(body)
                    if data.get("resource") == cfg["resource"] and data.get("authorization_servers") == [cfg["issuer"]]:
                        conn.close()
                        conn = http.client.HTTPSConnection("127.0.0.1", 8765, timeout=2, context=context)
                        conn.request("POST", "/mcp", body=b"{}", headers={"Content-Type": "application/json"})
                        if conn.getresponse().status == 401:
                            self.lifecycle("status")
                            return
            except (OSError, ValueError, http.client.HTTPException):
                pass
            finally:
                conn.close()
            time.sleep(0.25)
        raise RuntimeError("Local readiness unconfirmed")

    def run(self, ident):
        # The lock is held only while recording state. ACCEPTED/RUNNING and
        # the fixed systemd service serialize requests through the outage.
        with self.locked():
            record = self.current()
            if not record or record["request"]["id"] != ident or record["state"] != "ACCEPTED":
                raise ValueError("Maintenance request not pending")
            self.transition(record, "RUNNING", "preflight")
        req = record["request"]
        mutated = False
        try:
            head, branch = self.preflight(record)
            self.idle_jobs()
            if not self.enabled() or receipt(self.venv) != record["previous"]:
                raise PermissionError("Maintenance admission changed")
            with self.locked():
                self.transition(record, "RUNNING", "quiescing")
            mutated = True
            for name in record["flags"]:
                # Global first; no new authenticated admissions during stop.
                private_bytes(self.state / name, 0)
                (self.state / name).unlink()
            sync_dir(self.state)
            self.lifecycle("stop")
            with self.locked():
                self.transition(record, "RUNNING", "stopped")
            if self.checkout() != (head, branch):
                raise RuntimeError("Checkout changed")
            # After quiescence the local coordinator must still verify locks,
            # stopped unit, all-principal jobs and the persistent fence.
            if req["action"] == "update":
                target = req["target_sha"]
                if branch == "main":
                    git(self.kit, "merge", "--ff-only", "--no-overwrite-ignore", target)
                else:
                    git(self.kit, "checkout", "--detach", "--no-overwrite-ignore", target)
                if self.checkout() != (target, branch):
                    raise RuntimeError("Unexpected updated checkout")
                head = target
            self.coordinator(head, "fence")
            with self.locked():
                self.transition(record, "RUNNING", "fenced")
            if req["action"] == "update":
                if os.path.lexists(self.venv.parent / ".venv-install.rollback"):
                    tx = self.rollback_tx()
                    self.coordinator(head, "archive", "--rollback-sha", tx["sha"])
                with self.locked():
                    self.transition(record, "RUNNING", "installing")
                self.coordinator(head, "upgrade", "--expected-wheel", req["wheel_sha256"],
                                 "--previous-sha", record["previous"]["sha"],
                                 "--previous-wheel", record["previous"]["wheel_sha256"])
            else:
                with self.locked():
                    self.transition(record, "RUNNING", "restoring")
                # Preserve active audit bytes before invoking the existing restore.
                primary = self.state / "security-audit.jsonl"
                before = private_bytes(primary, 4 * 1024 * 1024)
                self.archive_oauth(ident)
                self.coordinator(head, "restore")
                if private_bytes(primary, 4 * 1024 * 1024) != before:
                    raise RuntimeError("Primary audit changed during restore")
            if receipt(self.venv) != {"sha": req["target_sha"], "wheel_sha256": req["wheel_sha256"]}:
                raise RuntimeError("Installation receipt mismatch")
            self.coordinator(head, "release")
            with self.locked():
                self.transition(record, "RUNNING", "starting")
            self.lifecycle("start")
            self.readiness()
            # Restore only the originally authorized empty markers, global last.
            # An unexpected existing marker is not overwritten.
            for name in reversed(record["flags"]):
                fd = os.open(self.state / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    os.fsync(stream.fileno())
            sync_dir(self.state)
            with self.locked():
                self.transition(record, "SUCCEEDED", "complete")
        except Exception:
            # No guessing at a partial mutation, no second install or restart.
            # Existing coordinator/rollback evidence remains intact for local recovery.
            with self.locked():
                self.transition(record, "LOCAL_RECOVERY_REQUIRED" if mutated else "BLOCKED", record["stage"])
            return False
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", nargs=3, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if os.getuid() == 0 or sys.prefix != sys.base_prefix or sys.version_info[:2] != (3, 12):
            raise PermissionError("Unprivileged host Python required")
        root, kit, ident = args.run
        if not DIGEST.fullmatch(ident) or not all(PATH.fullmatch(p) for p in (root, kit)):
            raise ValueError("Invalid local runner identity")
        service = Maintenance(Path(root), Path(kit))
        if not service.run(ident):
            raise SystemExit(1)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.SubprocessError):
        raise SystemExit("MAINTENANCE_BLOCKED_OR_UNCONFIRMED") from None


if __name__ == "__main__":
    main()
