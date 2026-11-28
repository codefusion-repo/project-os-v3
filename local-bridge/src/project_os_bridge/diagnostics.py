"""Bounded, sanitized operational observations, not host certification."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from importlib.metadata import version
import http.client
import json
import os
import re
import sqlite3
import ssl
import stat
import sys
import time
from pathlib import Path
from typing import Literal, get_args

from .lifecycle import prepared_unit, snapshot, systemctl
from .readiness import read_metadata, verify_metadata
from .workos_auth import load_config, private_directory, private_file
from .security import MAX_AUDIT_BYTES

Section = Literal["host", "security", "runtime", "service", "network", "jobs", "audit"]
SECTIONS = get_args(Section)
FLAG = "allow-operational-diagnostics"
HOST_TYPES = {"9p", "drvfs", "virtiofs", "cifs", "smb3"}
STATES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED", "INTERRUPTED")
MAX_PROC = 1024 * 1024
MAX_DB = 128 * 1024 * 1024


def bounded_text(path, limit=MAX_PROC, *, private=False):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if private:
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise PermissionError("Regular file required")
        if private and (info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1):
            raise PermissionError("Private regular file required")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Inventory exceeds limit")
        return data.decode("utf-8")


def mount_counts(raw):
    mounts = []
    for line in raw.splitlines():
        left, sep, right = line.partition(" - ")
        a, b = left.split(), right.split()
        if not sep or len(a) < 6 or len(b) < 3 or not a[4].startswith("/"):
            raise ValueError("Invalid mount inventory")
        mounts.append((a[2], a[3], a[4], a[6:], b[0]))
    if not mounts:
        raise ValueError("Empty mount inventory")
    host = [m for m in mounts if m[4] in HOST_TYPES]
    devices = {m[0] for m in host}
    aliases = [m for m in mounts if m[0] in devices]
    return {"mount_count": len(mounts), "host_backed_count": len(host),
            "host_device_mount_count": len(aliases),
            "host_subroot_count": sum(m[1] != "/" for m in aliases),
            "host_shared_count": sum(any(x.startswith("shared:") for x in m[3]) for m in host),
            "wsl_driver_path_seen": any(m[2] == "/usr/lib/wsl/drivers" for m in host)}


def process_observations(raw):
    fields = {}
    for line in raw.splitlines():
        key, sep, value = line.partition(":")
        if sep and key in {"CapPrm", "CapEff", "CapAmb", "NoNewPrivs", "Seccomp"}:
            if key in fields:
                raise ValueError("Duplicate process field")
            fields[key] = value.strip()
    for key in ("CapPrm", "CapEff", "CapAmb"):
        if not re.fullmatch(r"[0-9a-fA-F]{1,16}", fields[key]):
            raise ValueError("Invalid capability field")
    if fields["NoNewPrivs"] not in ("0", "1") or fields["Seccomp"] not in ("0", "1", "2"):
        raise ValueError("Invalid process flags")
    return {"unprivileged": os.getuid() != 0 and os.geteuid() == os.getuid(),
            "capabilities_absent": all(int(fields[k], 16) == 0 for k in ("CapPrm", "CapEff", "CapAmb")),
            "no_new_privileges": fields["NoNewPrivs"] == "1",
            "seccomp_mode": int(fields["Seccomp"])}


def codex_process_observations(proc=Path("/proc"), *, uid=None):
    """Same-UID name observations only; never infer ownership or signal a PID."""
    uid = os.getuid() if uid is None else uid
    result = {"name_candidates": 0, "parent_one_candidates": 0,
              "zombie_candidates": 0, "inventory_complete": True,
              "job_attribution": "not_established"}
    with os.scandir(proc) as entries:
        for index, entry in enumerate(entries):
            if index >= 8192:
                result["inventory_complete"] = False
                break
            if not entry.name.isascii() or not entry.name.isdecimal():
                continue
            try:
                raw = bounded_text(Path(entry.path) / "status", 65536)
                fields = dict(line.split(":", 1) for line in raw.splitlines()
                              if ":" in line)
                if int(fields["Uid"].split()[0]) != uid:
                    continue
                name = fields["Name"].strip()
                if name != "codex" and not name.startswith("codex-"):
                    continue
                parent = int(fields["PPid"].strip())
                state = fields["State"].split()[0]
                result["name_candidates"] += 1
                result["parent_one_candidates"] += int(parent == 1)
                result["zombie_candidates"] += int(state == "Z")
            except (OSError, ValueError, KeyError, IndexError):
                result["inventory_complete"] = False
    return result


def listener_counts(raw, *, ipv6=False):
    rows = raw.splitlines()
    if not rows or "local_address" not in rows[0]:
        raise ValueError("Invalid TCP inventory")
    loopback = other = 0
    for line in rows[1:]:
        fields = line.split()
        if len(fields) < 4:
            raise ValueError("Invalid TCP row")
        address, port = fields[1].split(":")
        if not re.fullmatch(r"[0-9A-Fa-f]{32}" if ipv6 else r"[0-9A-Fa-f]{8}", address) or not re.fullmatch(r"[0-9A-Fa-f]{4}", port):
            raise ValueError("Invalid TCP address")
        if fields[3] == "0A" and int(port, 16) == 8765:
            if not ipv6 and address.upper() == "0100007F":
                loopback += 1
            else:
                other += 1
    return loopback, other


def numeric_version(value):
    return value if isinstance(value, str) and re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,6}){1,3}", value) else "unavailable"


class Diagnostics:
    def __init__(self, verifier, root, *, tls_context=None):
        private_directory(root)
        if verifier.state_dir != root / "state":
            raise ValueError("Instance identity mismatch")
        private_directory(verifier.state_dir)
        self.verifier = verifier
        self.root = root
        self.state = verifier.state_dir
        self.context = tls_context

    def enabled(self):
        try:
            private_directory(self.root)
            private_directory(self.state)
            return (not os.path.lexists(self.state / "fixture-image")
                    and private_file(self.state / FLAG).st_size == 0)
        except (OSError, ValueError):
            return False

    def host(self):
        kernel = bounded_text(Path("/proc/sys/kernel/osrelease"), 4096).lower()
        return {"platform": "linux", "wsl": "microsoft" in kernel or "wsl" in kernel,
                "cpu_count": os.cpu_count(), "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").is_file(),
                "interop_observed": Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists()
                    or bool(os.environ.get("WSL_INTEROP")),
                "codex_process_observations": codex_process_observations()}

    def subordinate_ids(self):
        import pwd
        uid = os.getuid()
        username = pwd.getpwuid(uid).pw_name
        result = {}
        for kind in ("subuid", "subgid"):
            entries = []
            for line in bounded_text(Path("/etc") / kind, 65536).splitlines():
                if not line or line.startswith("#"):
                    continue
                owner, start, count = line.split(":")
                start, count = int(start), int(count)
                if not 0 < start < start + count <= 2**32:
                    raise ValueError("Invalid subordinate range")
                entries.append((owner, start, start + count))
            own = [i for i, row in enumerate(entries) if row[0] in (username, str(uid))]
            overlap = any(entries[i][1] < row[2] and row[1] < entries[i][2]
                          for i in own for j, row in enumerate(entries) if i != j)
            result[kind] = {"assigned_ranges": len(own), "overlap_observed": overlap}
        return result

    def security(self):
        from grp import getgrgid
        privileged = {"sudo", "wheel", "docker", "lxd", "libvirt", "disk", "root", "adm", "podman", "incus", "shadow"}
        home = Path.home()
        h = home.lstat()
        return {"process": process_observations(bounded_text(Path("/proc/self/status"), 65536)),
                "mounts": mount_counts(bounded_text(Path("/proc/self/mountinfo"))),
                "private_home": stat.S_ISDIR(h.st_mode) and h.st_uid == os.getuid() and not h.st_mode & 0o077,
                "privileged_group_observed": bool(privileged.intersection(
                    getgrgid(g).gr_name for g in set(os.getgroups()) | {os.getgid(), os.getegid()})),
                "privileged_socket_writable": any(os.access(p, os.W_OK, effective_ids=True) for p in
                    ("/run/docker.sock", "/run/podman/podman.sock", "/run/containerd/containerd.sock")),
                "sudo_polkit_effective_policy": "not_assessed",
                "windows_acl_firewall": "not_assessed",
                "job_isolation": "not_assessed",
                "subordinate_ids": self.subordinate_ids()}

    def runtime(self):
        return {"python": ".".join(map(str, sys.version_info[:3])),
                "bridge_version": numeric_version(version("project-os-local-bridge")),
                "mcp_version": numeric_version(version("mcp")),
                "sqlite_version": numeric_version(sqlite3.sqlite_version),
                "dedicated_venv": sys.prefix != sys.base_prefix,
                "artifact_provenance": "requires_reviewed_install_evidence"}

    def service(self):
        # Reuse exact-unit validation; no lifecycle locks, mutations or raw status.
        unit = prepared_unit(self.root)
        return snapshot(unit, lambda *args: systemctl(*args, timeout=3))

    def network(self):
        lo, other = listener_counts(bounded_text(Path("/proc/net/tcp")))
        lo6, other6 = listener_counts(bounded_text(Path("/proc/net/tcp6")), ipv6=True)
        result = {"ipv4_loopback_listeners": lo, "other_listeners_on_bridge_port": other + other6,
                  "metadata_verified": False, "unauthenticated_401": False,
                  "external_reachability": "not_assessed"}
        if self.context is None or lo != 1 or other + other6:
            return result
        verify_metadata(read_metadata(self.context), self.verifier)
        result["metadata_verified"] = True
        connection = http.client.HTTPSConnection("127.0.0.1", 8765, timeout=2, context=self.context)
        try:
            connection.request("POST", "/mcp", body=b"{}", headers={"Content-Type": "application/json"})
            result["unauthenticated_401"] = connection.getresponse().status == 401
        finally:
            connection.close()
        return result

    def jobs(self):
        private_directory(self.state)
        db = self.state / "jobs.sqlite3"
        if not os.path.lexists(db):
            return {"database": "not_created"}
        if private_file(db).st_size > MAX_DB:
            raise ValueError("Database exceeds inventory limit")
        counts = dict.fromkeys(STATES, 0)
        deadline = time.monotonic() + 2
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            conn.execute("BEGIN")
            unknown = 0
            actor = self.verifier.subject
            for state, count in conn.execute("SELECT state,count(*) FROM jobs WHERE principal=? AND resource IN ('disposable','workspace') GROUP BY state", (actor,)):
                if state in counts:
                    counts[state] = count
                else:
                    unknown += count
            unresolved = conn.execute(
                "SELECT count(*) FROM fixture_effects e JOIN jobs j ON e.job_id=j.id WHERE e.resolved_at IS NULL AND j.principal=? AND j.resource IN ('disposable','workspace')",
                (actor,)).fetchone()[0]
        return {"database": "observed", "counts": counts, "unknown_states": unknown,
                "unresolved_effects": unresolved, "scope": "current_instance_caller_only"}

    def audit(self):
        private_directory(self.state)
        path = self.state / "security-audit.jsonl"
        if not os.path.lexists(path):
            return {"audit": "not_created"}
        counts = Counter()
        for line in bounded_text(path, MAX_AUDIT_BYTES, private=True).splitlines():
            event = json.loads(line)
            if (not isinstance(event, dict) or set(event) != {"at", "event", "status"}
                    or event["event"] != "mcp_http" or type(event["status"]) is not int
                    or not 100 <= event["status"] <= 599):
                raise ValueError("Unexpected audit event")
            counts[str(event["status"])] += 1
        return {"audit": "observed", "http_status_counts": dict(counts)}

    def collect(self, section):
        if section not in SECTIONS:
            raise ValueError("Unknown diagnostic section")
        stamp = datetime.now(timezone.utc).isoformat()
        try:
            private_directory(self.root)
            private_directory(self.state)
            # Dispatch only known internal methods; no caller-controlled paths.
            collectors = {"host": self.host, "security": self.security, "runtime": self.runtime,
                          "service": self.service, "network": self.network, "jobs": self.jobs, "audit": self.audit}
            data = collectors[section]()
        except Exception:
            # No exception messages, filenames, subprocess output or raw records.
            return {"section": section, "observed_at": stamp, "status": "unavailable"}
        return {"section": section, "observed_at": stamp, "status": "observed", "data": data}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--section", choices=(*SECTIONS, "all"), default="all")
    args = parser.parse_args()
    try:
        if os.getuid() == 0:
            raise PermissionError("Unprivileged operator required")
        root = args.root
        private_directory(root)
        verifier = load_config(root / "oauth.json", root / "state")
        ca = root / "service" / "ca.pem"
        private_directory(ca.parent)
        private_file(ca)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=str(ca))
        diagnostics = Diagnostics(verifier, root, tls_context=context)
        sections = SECTIONS if args.section == "all" else (args.section,)
        print(json.dumps([diagnostics.collect(section) for section in sections], sort_keys=True))
    except Exception:
        print("DIAGNOSTICS_UNAVAILABLE", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
