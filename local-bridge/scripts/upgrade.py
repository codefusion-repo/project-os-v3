"""Local-only maintenance of the one permanent Bridge checkout.

Never start, stop, rebind, grant access, or migrate state here. The operator
must first stop the exact supervised instance using its reviewed lifecycle.
Run with host Python, not the venv that will be moved.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile

ORIGIN = "https://github.com/codefusion-repo/project-os-v3.git"
UNIT = "project-os-bridge.service"
BACKUP = ".venv-install.rollback"
GUARD = ".venv-install.guard"
ACTIVE = "active.json"
TRANSACTION = "transaction.json"
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
        yield fd
    finally:
        os.close(fd)


def git(kit, *args):
    return subprocess.check_output(["git", "-C", str(kit), *args],
                                   text=True, timeout=30).strip()


def verify_checkout(kit, sha):
    directory(kit, private=False)
    directory(kit / ".git", private=False)
    directory(kit / "local-bridge", private=False)
    if not SHA.fullmatch(sha) or git(kit, "rev-parse", "HEAD") != sha:
        raise ValueError("HEAD mismatch.")
    if git(kit, "rev-parse", "--show-toplevel") != str(kit) or git(kit, "config", "--local", "--get", "remote.origin.url") != ORIGIN:
        raise ValueError("Unexpected origin.")
    if git(kit, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Dirty checkout; preserved.")
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG"):
        if os.path.lexists(kit / ".git" / name):
            raise ValueError("Git operation in progress")
    # Do not allow tracked files under the maintenance paths, even if ignored.
    for path in ("local-bridge/.venv", "local-bridge/" + BACKUP, "local-bridge/" + GUARD):
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
        fds = []
        for path in (Path(f"/run/user/{os.getuid()}") / "project-os-bridge-lifecycle.lock",
                     service / "supervisor.lock", state / "http-service.lock", state / "worker.lock"):
            fds.append(stack.enter_context(lock(path)))
        check_unit(root, bound_python)
        for name in ("allow-authenticated-probe", "allow-operational-diagnostics",
                     "fixture-image", "local-fixture-mode"):
            if os.path.lexists(state / name):
                raise PermissionError("Opt-ins or fixture binding present")
        check_jobs(state)
        yield tuple(fds)


def validate_venv(path):
    directory(path)
    file_info(path / "pyvenv.cfg", limit=8192)
    directory(path / "bin", private=False)
    executable = path / "bin/python"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Incomplete virtual environment")


def identity(path):
    # Bind the directory inode and receipt/config bytes without executing a
    # relocated interpreter. Not tamper resistance against the trusted UID.
    validate_venv(path)
    st = path.lstat()
    receipt = path / RECEIPT
    value = None
    if os.path.lexists(receipt):
        file_info(receipt, limit=1024)
        value = json.loads(receipt.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or set(value) != {"sha", "wheel_sha256"}
                or not isinstance(value["sha"], str) or not SHA.fullmatch(value["sha"])
                or not isinstance(value["wheel_sha256"], str) or not DIGEST.fullmatch(value["wheel_sha256"])):
            raise ValueError("Invalid previous installation receipt")
    return {"dev": st.st_dev, "ino": st.st_ino,
            "config_sha256": hashlib.sha256((path / "pyvenv.cfg").read_bytes()).hexdigest(),
            "receipt": value}


def prior_identity(venv, bound_python, previous_sha, previous_wheel, legacy):
    if not SHA.fullmatch(previous_sha or "") or not DIGEST.fullmatch(previous_wheel or ""):
        raise ValueError("Reviewed previous SHA and wheel required")
    bound_venv = bound_python.parent.parent
    previous = identity(venv)
    expected = {"sha": previous_sha, "wheel_sha256": previous_wheel}
    if legacy:
        # Consolidation only: the original environment is quarantined, not
        # certified. The separately bound runtime is the operational fallback.
        if bound_venv == venv or previous["receipt"] is not None:
            raise ValueError("Legacy consolidation requires separate bound runtime and no original receipt")
        bound = identity(bound_venv)
        verify_checkout(bound_venv.parents[1], previous_sha)
        if bound["receipt"] is not None and bound["receipt"] != expected:
            raise ValueError("Bound runtime receipt mismatch")
        return {"identity": previous, "eligible": False, "reviewed": expected,
                "bound_path": str(bound_venv), "bound_identity": bound}
    if bound_venv != venv or previous["receipt"] != expected:
        raise ValueError("Previous runtime receipt or binding mismatch")
    return {"identity": previous, "eligible": True, "reviewed": expected,
            "bound_path": str(venv), "bound_identity": previous}


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


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def group_busy(group, boot):
    if group is None:
        return False
    if type(group) is not int or group <= 1 or not isinstance(boot, str):
        raise ValueError("Invalid writer identity")
    if boot != boot_id():
        return False  # no processes survive a kernel reboot
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    return True  # includes zombies / PID reuse: block conservatively


def no_writers(tx):
    if group_busy(tx["group"], tx["boot"]):
        raise RuntimeError("Installation process group still exists")


def read_json(path):
    file_info(path, limit=16384)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid transaction")
    return data


def save_json(path, data):
    fd, name = tempfile.mkstemp(prefix=".txn-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


@contextmanager
def checkout_guard(kit):
    parent = kit / "local-bridge"
    directory(parent, private=False)
    guard = parent / GUARD
    try:
        guard.mkdir(mode=0o700)
    except FileExistsError:
        pass
    directory(guard)
    with lock(guard / "lock") as fd:
        yield guard, fd


def new_transaction(venv, sha, wheel, prior=None):
    return {"format": 1, "path": str(venv), "sha": sha, "wheel": wheel,
            "prior": prior, "phase": "prepared", "group": None, "boot": boot_id()}


def verify_transaction(tx, venv, sha):
    if (set(tx) != {"format", "path", "sha", "wheel", "prior", "phase", "group", "boot"}
            or tx["format"] != 1 or tx["path"] != str(venv) or tx["sha"] != sha
            or not isinstance(tx["boot"], str)
            or tx["phase"] not in ("prepared", "writing", "installed", "restoring", "restored")
            or (tx["wheel"] is not None and (not isinstance(tx["wheel"], str)
                                             or not DIGEST.fullmatch(tx["wheel"])))):
        raise ValueError("Transaction identity mismatch")
    no_writers(tx)


def launch_build(kit, sha, wheel, active, tx, fds):
    # The session leader waits for a byte until the group identity is durable.
    # If the coordinator dies before that, EOF prevents any installation.
    # If it dies later, inherited flock descriptions and the recorded process
    # group fence recovery. Reviewed build descendants must not daemonize or
    # leave the session/process group; this is not a sandbox against same UID.
    reader, writer = os.pipe()
    child = None
    try:
        cmd = ["/bin/bash", "-c",
               'IFS= read -r -n 1 -u "$1" permit && [ "$permit" = Y ] || exit 1; '
               'shift; exec /bin/bash "$@"',
               "bridge-build", str(reader), str(kit / "local-bridge/scripts/install-build.sh"),
               str(fds[0]), sha]
        if wheel is not None:
            cmd.append(wheel)
        child = subprocess.Popen(cmd, start_new_session=True,
                                 pass_fds=(*fds, reader))
        os.close(reader)
        reader = None
        tx.update(group=child.pid, phase="writing")
        save_json(active, tx)
        os.write(writer, b"Y")
    finally:
        os.close(writer)
        if reader is not None:
            os.close(reader)
    code = child.wait()
    no_writers(tx)
    if code:
        raise subprocess.CalledProcessError(code, cmd[:1])


def validate_prior(prior, venv, path, bound_python):
    if (not isinstance(prior, dict)
            or set(prior) != {"identity", "eligible", "reviewed", "bound_path", "bound_identity"}
            or type(prior["eligible"]) is not bool or identity(path) != prior["identity"]):
        raise ValueError("Rollback identity mismatch")
    reviewed = prior["reviewed"]
    if (not isinstance(reviewed, dict) or set(reviewed) != {"sha", "wheel_sha256"}
            or not SHA.fullmatch(reviewed["sha"]) or not DIGEST.fullmatch(reviewed["wheel_sha256"])):
        raise ValueError("Rollback review identity mismatch")
    if prior["eligible"]:
        if prior["bound_path"] != str(venv) or prior["identity"]["receipt"] != reviewed:
            raise ValueError("Rollback receipt mismatch")
    else:
        bound = Path(prior["bound_path"])
        # Legacy backup is never eligible for service activation. Preserve
        # independently reviewed bound runtime until cutover is certified.
        if (bound == venv or prior["identity"]["receipt"] is not None
                or identity(bound) != prior["bound_identity"]):
            raise ValueError("Legacy fallback identity mismatch")
        verify_checkout(bound.parents[1], reviewed["sha"])
        if prior["bound_identity"]["receipt"] not in (None, reviewed):
            raise ValueError("Legacy fallback receipt mismatch")
        # If the candidate has already been rebound, explicitly rebind to the
        # certified fallback before restoring the quarantined original.
        if bound_python != bound / "bin/python":
            raise ValueError("Rebind certified legacy fallback before physical restore")


def finish(active, tx, backup=None):
    if backup is not None:
        save_json(backup / TRANSACTION, tx)
    active.unlink()
    sync_directory(active.parent)


def restore(venv, backup, active, sha, bound_python):
    directory(backup)
    tx = read_json(active if os.path.lexists(active) else backup / TRANSACTION)
    verify_transaction(tx, venv, sha)
    prior = tx["prior"]
    if prior is None:
        raise ValueError("Initial installation has no rollback")
    previous = backup / "previous"
    candidate = backup / "candidate"
    # Recognize both interruption boundaries, including a completed physical
    # rename before the journal was finalized. Never move an unknown backup.
    if os.path.lexists(previous):
        validate_prior(prior, venv, previous, bound_python)
        if os.path.lexists(candidate) and os.path.lexists(venv):
            raise ValueError("Ambiguous candidate paths")
        if os.path.lexists(candidate):
            directory(candidate)
        if os.path.lexists(venv):
            directory(venv)
        tx["phase"] = "restoring"
        save_json(active, tx)
        if os.path.lexists(venv):
            move(venv, candidate)
        move(previous, venv)
    else:
        validate_prior(prior, venv, venv, bound_python)
        tx["phase"] = "restoring"
        save_json(active, tx)
    validate_prior(prior, venv, venv, bound_python)
    tx["phase"] = "restored"
    finish(active, tx, backup)
    return prior["eligible"]


def replace(kit, sha, wheel, guard, fds, bound_python,
            previous_sha, previous_wheel, legacy=False, run=launch_build):
    venv = kit / "local-bridge" / ".venv"
    backup = venv.parent / BACKUP
    active = guard / ACTIVE
    if os.path.lexists(active) or os.path.lexists(backup):
        raise FileExistsError("Unresolved maintenance or retained backup")
    prior = prior_identity(venv, bound_python, previous_sha, previous_wheel, legacy)
    tx = new_transaction(venv, sha, wheel, prior)
    # Journal must be durable before the first destructive rename.
    backup.mkdir(mode=0o700)
    sync_directory(backup.parent)
    save_json(active, tx)
    move(venv, backup / "previous")
    try:
        run(kit, sha, wheel, active, tx, fds)
        no_writers(tx)
        validate_venv(venv)
        validate_receipt(venv, sha, wheel)
    except BaseException:
        # Do not claim rollback while any installation descendant can write.
        eligible = restore(venv, backup, active, sha, bound_python)
        print("BRIDGE VENV PHYSICALLY RESTORED; prior runtime requires start review"
              if eligible else "LEGACY VENV QUARANTINE RESTORED; use certified bound fallback only",
              flush=True)
        raise
    tx["phase"] = "installed"
    finish(active, tx, backup)
    print("BRIDGE UPGRADE PASS; previous venv retained offline; service not started", flush=True)


def initial_install(kit, sha, wheel, guard, fd):
    venv = kit / "local-bridge" / ".venv"
    active = guard / ACTIVE
    if os.path.lexists(active) or os.path.lexists(venv.parent / BACKUP):
        raise RuntimeError("Unresolved maintenance or retained backup")
    if os.path.lexists(venv):
        raise ValueError("Existing bridge environment preserved.")
    tx = new_transaction(venv, sha, wheel)
    save_json(active, tx)
    launch_build(kit, sha, wheel, active, tx, (fd,))
    observed = identity(venv)["receipt"]
    if observed is None or observed["sha"] != sha or (wheel is not None and observed["wheel_sha256"] != wheel):
        raise ValueError("Installation receipt mismatch")
    finish(active, tx)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "upgrade", "restore"))
    parser.add_argument("reviewed_sha")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--bound-python", type=Path)
    parser.add_argument("--expected-wheel")
    parser.add_argument("--previous-sha")
    parser.add_argument("--previous-wheel")
    parser.add_argument("--legacy-consolidation", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if (os.getuid() == 0 or sys.prefix != sys.base_prefix
                or sys.version_info[:2] != (3, 12) or sys.platform != "linux"):
            raise PermissionError("Unprivileged host Python 3.12 required")
        kit = Path(__file__).resolve().parents[2]
        verify_checkout(kit, args.reviewed_sha)
        if args.expected_wheel is not None and not DIGEST.fullmatch(args.expected_wheel):
            raise ValueError("Invalid expected wheel digest")
        with checkout_guard(kit) as (guard, fd):
            verify_checkout(kit, args.reviewed_sha)
            if args.action == "install":
                if any((args.root, args.bound_python, args.previous_sha, args.previous_wheel, args.legacy_consolidation)):
                    raise ValueError("Initial install has no maintenance parameters")
                initial_install(kit, args.reviewed_sha, args.expected_wheel, guard, fd)
                return
            if args.root is None or args.bound_python is None:
                raise ValueError("Exact instance and bound Python required")
            with maintenance(args.root, args.bound_python) as service_fds:
                verify_checkout(kit, args.reviewed_sha)
                if args.action == "upgrade":
                    if not DIGEST.fullmatch(args.expected_wheel or ""):
                        raise ValueError("Expected CI wheel SHA-256 required")
                    replace(kit, args.reviewed_sha, args.expected_wheel, guard,
                            (fd, *service_fds), args.bound_python, args.previous_sha,
                            args.previous_wheel, args.legacy_consolidation)
                else:
                    if any((args.expected_wheel, args.previous_sha, args.previous_wheel, args.legacy_consolidation)):
                        raise ValueError("Restore uses recorded transaction")
                    if os.path.lexists(args.root / "state/oauth-audit.jsonl"):
                        raise RuntimeError("Archive OAuth sidecar before restore")
                    venv = kit / "local-bridge/.venv"
                    eligible = restore(venv, venv.parent / BACKUP, guard / ACTIVE,
                                       args.reviewed_sha, args.bound_python)
                    print("BRIDGE VENV PHYSICALLY RESTORED; no service started"
                          if eligible else "LEGACY VENV QUARANTINE RESTORED; use certified bound fallback only")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error,
            subprocess.SubprocessError, KeyboardInterrupt) as exc:
        # Stable existing CI rejection messages; do not print exception data.
        for message in ("HEAD mismatch.", "Unexpected origin.", "Dirty checkout; preserved.",
                        "Existing bridge environment preserved."):
            if type(exc) is ValueError and str(exc) == message:
                print(message, file=sys.stderr)
        print("BRIDGE MAINTENANCE BLOCKED OR INTERRUPTED; preserve files and inspect locally",
              file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
