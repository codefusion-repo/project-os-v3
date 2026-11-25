"""Local-only maintenance of the one permanent Bridge checkout.

Never start, stop, rebind, grant access, or migrate state here. The operator
must first stop the exact supervised instance using its reviewed lifecycle.
Run with host Python, not the venv that will be moved.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys

ORIGIN = "https://github.com/codefusion-repo/project-os-v3.git"
UNIT = "project-os-bridge.service"
BACKUP = ".venv-install.rollback"
RECEIPT = ".project-os-bridge-install.json"
STATES = ("SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED", "INTERRUPTED")
PROPERTIES = ("Id", "LoadState", "FragmentPath", "DropInPaths",
              "NeedDaemonReload", "ActiveState", "UnitFileState", "Job",
              "MainPID", "ControlPID")
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./-]+")
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")


def directory(path, *, private=True):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("Canonical directory required")
    info = path.lstat()
    mask = 0o077 if private else 0o022
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & mask:
        raise PermissionError("Unsafe directory")
    return info


def file_info(path, *, limit=None):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_mode & 0o077
            or (limit is not None and info.st_size > limit)):
        raise PermissionError("Unsafe private file")
    return info


@contextmanager
def lock(path):
    directory(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise PermissionError("Unsafe maintenance lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def git(kit, *args):
    return subprocess.check_output(["git", "-C", str(kit), *args],
                                   text=True, timeout=30).strip()


def verify_checkout(kit, sha):
    directory(kit, private=False)
    directory(kit / ".git", private=False)
    directory(kit / "local-bridge", private=False)
    if (not SHA.fullmatch(sha) or git(kit, "rev-parse", "--show-toplevel") != str(kit)
            or git(kit, "config", "--local", "--get", "remote.origin.url") != ORIGIN
            or git(kit, "rev-parse", "HEAD") != sha
            or git(kit, "status", "--porcelain", "--untracked-files=normal")):
        raise ValueError("Checkout identity or cleanliness unverified")
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG"):
        if os.path.lexists(kit / ".git" / name):
            raise ValueError("Git operation in progress")
    # Do not allow tracked files under the maintenance paths, even if ignored.
    for path in ("local-bridge/.venv", "local-bridge/" + BACKUP):
        if git(kit, "ls-files", "--", path):
            raise ValueError("Runtime path tracked in Git")


def unit_text(root, python):
    # Keep identical to service_setup.render_unit; regression tested against it.
    return f"""[Unit]
Description=Project OS disposable authenticated bridge
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=3

[Service]
Type=simple
ExecStart={python} -I -m project_os_bridge.supervised --root {root}
UMask=0077
KillMode=mixed
TimeoutStopSec=120
Restart=no
Delegate=yes

[Install]
WantedBy=default.target
"""


def check_unit(root, python, call=subprocess.run):
    if not SAFE_PATH.fullmatch(str(root)) or not SAFE_PATH.fullmatch(str(python)):
        raise ValueError("Unsupported unit paths")
    if (python.name != "python" or python.parent.name != "bin"
            or python.parent.parent.name != ".venv"
            or python.parent.parent.parent.name != "local-bridge"):
        raise ValueError("Expected exact reviewed Bridge Python path")
    unit = root / "service" / UNIT
    file_info(unit, limit=8192)
    if unit.read_text(encoding="utf-8") != unit_text(root, python):
        raise PermissionError("Unexpected prepared unit")
    uid = os.getuid()
    runtime = f"/run/user/{uid}"
    result = call(["/usr/bin/systemctl", "--user", "--no-pager", "show", "--all",
                   *("--property=" + p for p in PROPERTIES), UNIT],
                  env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LC_ALL": "C",
                       "XDG_RUNTIME_DIR": runtime, "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + runtime + "/bus"},
                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                  text=True, timeout=30, check=False)
    fields = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key not in PROPERTIES or key in fields:
            raise RuntimeError("Invalid unit status")
        fields[key] = value
    if (result.returncode or set(fields) != set(PROPERTIES)
            or fields["Id"] != UNIT or fields["LoadState"] != "loaded"
            or not fields["FragmentPath"] or Path(fields["FragmentPath"]).resolve(strict=True) != unit
            or fields["DropInPaths"] or fields["NeedDaemonReload"] != "no"
            or fields["ActiveState"] != "inactive" or fields["UnitFileState"] not in ("linked", "disabled")
            or fields["Job"] not in ("", "0") or fields["MainPID"] != "0" or fields["ControlPID"] != "0"):
        raise RuntimeError("Exact unit must be stopped, linked, disabled and quiescent")


def check_jobs(state):
    db = state / "jobs.sqlite3"
    file_info(db, limit=128 * 1024 * 1024)
    # A lingering journal may require recovery, which maintenance must not do.
    for suffix in ("-wal", "-shm", "-journal"):
        if os.path.lexists(str(db) + suffix):
            raise RuntimeError("SQLite recovery or active connection possible")
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        marks = ",".join("?" for _ in STATES)
        if conn.execute(f"SELECT count(*) FROM jobs WHERE state IS NULL OR state NOT IN ({marks})",
                        STATES).fetchone()[0]:
            raise RuntimeError("Pending or unknown jobs")
        if conn.execute("SELECT count(*) FROM fixture_effects WHERE resolved_at IS NULL").fetchone()[0]:
            raise RuntimeError("Unresolved effects")


@contextmanager
def maintenance(root, bound_python):
    directory(root)
    if any(os.path.lexists(p / ".git") for p in (root, *root.parents)):
        raise PermissionError("Instance must be outside Git")
    state, service = root / "state", root / "service"
    directory(state)
    directory(service)
    with ExitStack() as stack:
        # Same locks as the integrated lifecycle, supervisor, HTTP and worker.
        for path in (Path(f"/run/user/{os.getuid()}") / "project-os-bridge-lifecycle.lock",
                     service / "supervisor.lock", state / "http-service.lock", state / "worker.lock"):
            stack.enter_context(lock(path))
        check_unit(root, bound_python)
        for name in ("allow-authenticated-probe", "allow-operational-diagnostics",
                     "fixture-image", "local-fixture-mode"):
            if os.path.lexists(state / name):
                raise PermissionError("Opt-ins or fixture binding present")
        check_jobs(state)
        yield


def validate_venv(path):
    directory(path)
    # A legacy environment is not treated as reviewed merely because it exists.
    # The operator must independently retain its prior install evidence.
    file_info(path / "pyvenv.cfg", limit=8192)
    if not (path / "bin/python").is_file():
        raise ValueError("Incomplete virtual environment")


def validate_receipt(venv, sha, wheel):
    path = venv / RECEIPT
    file_info(path, limit=1024)
    if json.loads(path.read_text(encoding="utf-8")) != {"sha": sha, "wheel_sha256": wheel}:
        raise ValueError("Installation receipt mismatch")


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def move(source, target):
    if os.path.lexists(target):
        raise FileExistsError("Maintenance destination already exists")
    source.rename(target)
    sync_directory(source.parent)
    if source.parent != target.parent:
        sync_directory(target.parent)


def restore(venv, backup):
    directory(backup)
    previous = backup / "previous"
    validate_venv(previous)
    failed = backup / "candidate"
    if os.path.lexists(failed):
        raise FileExistsError("Candidate already retained; inspect interruption")
    if os.path.lexists(venv):
        directory(venv)
        move(venv, failed)
    # Do not execute a relocated venv; only return it to its original path.
    move(previous, venv)


def replace(kit, sha, wheel, run=subprocess.run):
    venv = kit / "local-bridge" / ".venv"
    backup = venv.parent / BACKUP
    validate_venv(venv)
    backup.mkdir(mode=0o700)  # exclusive; unresolved prior attempt blocks
    sync_directory(backup.parent)
    move(venv, backup / "previous")
    try:
        run(["/bin/bash", str(kit / "local-bridge/scripts/install.sh"), sha, wheel],
            check=True)
        validate_venv(venv)
        validate_receipt(venv, sha, wheel)
    except BaseException:
        restore(venv, backup)
        print("BRIDGE UPGRADE ROLLED BACK; inspect retained attempt", flush=True)
        raise
    print("BRIDGE UPGRADE PASS; previous venv retained offline; service not started", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("upgrade", "restore"))
    parser.add_argument("reviewed_sha")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--bound-python", required=True, type=Path,
                        help="Exact Python already named in the reviewed prepared unit")
    parser.add_argument("--expected-wheel")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if (os.getuid() == 0 or sys.prefix != sys.base_prefix
                or sys.version_info[:2] != (3, 12) or sys.platform != "linux"):
            raise PermissionError("Unprivileged host Python 3.12 required")
        kit = Path(__file__).resolve().parents[2]
        verify_checkout(kit, args.reviewed_sha)
        if args.action == "upgrade" and not DIGEST.fullmatch(args.expected_wheel or ""):
            raise ValueError("Expected CI wheel SHA-256 required")
        if args.action == "restore" and args.expected_wheel is not None:
            raise ValueError("Restore does not install a wheel")
        with maintenance(args.root, args.bound_python):
            verify_checkout(kit, args.reviewed_sha)
            if args.action == "upgrade":
                replace(kit, args.reviewed_sha, args.expected_wheel)
            else:
                # Rollback to an earlier runtime must not ignore the active
                # supplemental audit budget. Archive it intact offline first.
                if os.path.lexists(args.root / "state/oauth-audit.jsonl"):
                    raise RuntimeError("Archive OAuth sidecar before restore")
                restore(kit / "local-bridge/.venv", kit / "local-bridge" / BACKUP)
                print("BRIDGE VENV RESTORED; service not started")
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError, KeyboardInterrupt):
        print("BRIDGE MAINTENANCE BLOCKED OR INTERRUPTED; preserve files and inspect locally",
              file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
