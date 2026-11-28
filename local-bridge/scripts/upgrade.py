"""Local-only maintenance of the one permanent Bridge checkout.

Never start, stop, rebind, grant access, or migrate state here. The operator
must first stop the exact supervised instance using its reviewed lifecycle.
Explicit fence/release operations change only the exact stopped unit definition
and reload the user manager, never start it. Run with host Python.
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
ARCHIVE_PREFIX = ".venv-install.archive-"
GUARD = ".venv-install.guard"
ACTIVE = "active.json"
TRANSACTION = "transaction.json"
RECEIPT = ".project-os-bridge-install.json"
STATES = ("SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED", "INTERRUPTED")
PROPERTIES = ("Id", "LoadState", "FragmentPath", "DropInPaths",
              "NeedDaemonReload", "ActiveState", "UnitFileState", "Job",
              "MainPID", "ControlPID", "RefuseManualStart")
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./-]+")
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
INTERPRETER_FIELDS = ("dev", "ino", "uid", "mode", "size", "sha256")


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
    for path in ("local-bridge/.venv", "local-bridge/" + BACKUP, "local-bridge/" + GUARD,
                 "local-bridge/" + ARCHIVE_PREFIX + "*"):
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


def fenced_unit_text(root, python):
    # Legacy lifecycle rejects the changed definition. Even dependency
    # activation cannot run Bridge: the only ExecStart is a failing command.
    return unit_text(root, python).replace(
        "StartLimitBurst=3\n", "StartLimitBurst=3\nRefuseManualStart=yes\n").replace(
        f"ExecStart={python} -I -m project_os_bridge.supervised --root {root}\n",
        f"# Maintenance binding: {python}\nExecStart=/usr/bin/false\n")


def systemctl(*args, call=subprocess.run):
    uid = os.getuid()
    runtime = f"/run/user/{uid}"
    return call(["/usr/bin/systemctl", "--user", "--no-pager", *args],
                env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LC_ALL": "C",
                     "XDG_RUNTIME_DIR": runtime, "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + runtime + "/bus"},
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=30, check=False)


def check_unit(root, python, call=subprocess.run, *, fenced=False, pending_reload=False):
    if not SAFE_PATH.fullmatch(str(root)) or not SAFE_PATH.fullmatch(str(python)):
        raise ValueError("Unsupported unit paths")
    if (python.name != "python" or python.parent.name != "bin"
            or python.parent.parent.name != ".venv"
            or python.parent.parent.parent.name != "local-bridge"):
        raise ValueError("Expected exact reviewed Bridge Python path")
    unit = root / "service" / UNIT
    file_info(unit, limit=8192)
    expected = fenced_unit_text(root, python) if fenced else unit_text(root, python)
    if unit.read_text(encoding="utf-8") != expected:
        raise PermissionError("Unexpected prepared unit")
    result = systemctl("show", "--all", *("--property=" + p for p in PROPERTIES), UNIT, call=call)
    fields = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key not in PROPERTIES or key in fields:
            raise RuntimeError("Invalid unit status")
        fields[key] = value
    if (result.returncode or set(fields) != set(PROPERTIES)
            or fields["Id"] != UNIT or fields["LoadState"] != "loaded"
            or not fields["FragmentPath"] or Path(fields["FragmentPath"]).resolve(strict=True) != unit
            or fields["DropInPaths"]
            or (fields["NeedDaemonReload"] != "no" and not
                (pending_reload and fields["NeedDaemonReload"] == "yes"))
            or (fields["RefuseManualStart"] != ("yes" if fenced else "no") and not
                (pending_reload and fields["NeedDaemonReload"] == "yes"
                 and fields["RefuseManualStart"] in ("yes", "no")))
            or fields["ActiveState"] != "inactive" or fields["UnitFileState"] not in ("linked", "disabled")
            or fields["Job"] not in ("", "0") or fields["MainPID"] != "0" or fields["ControlPID"] != "0"):
        raise RuntimeError("Exact unit must be stopped, linked, disabled and quiescent")


def write_unit(root, python, *, fenced):
    unit = root / "service" / UNIT
    data = fenced_unit_text(root, python) if fenced else unit_text(root, python)
    fd, name = tempfile.mkstemp(prefix=".maintenance-unit-", dir=unit.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, unit)
        sync_directory(unit.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def reload_unit(root, python, fenced, call=subprocess.run):
    if systemctl("daemon-reload", call=call).returncode:
        raise RuntimeError("Unit reload unconfirmed")
    check_unit(root, python, call, fenced=fenced)


def fence_unit(root, python, call=subprocess.run):
    unit = root / "service" / UNIT
    file_info(unit, limit=8192)
    fenced = unit.read_text(encoding="utf-8") == fenced_unit_text(root, python)
    check_unit(root, python, call, fenced=fenced, pending_reload=True)
    if not fenced:
        write_unit(root, python, fenced=True)
    reload_unit(root, python, True, call)


def release_unit(root, python, call=subprocess.run):
    check_unit(root, python, call, fenced=True)
    write_unit(root, python, fenced=False)
    reload_unit(root, python, False, call)


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
        if conn.execute("SELECT 1 FROM jobs WHERE json_extract(result,'$.qa_delivery_request.state') IN ('QUEUED','RUNNING') LIMIT 1").fetchone():
            raise RuntimeError("Pending QA delivery")
        # A successful build can still be awaiting signature finalization.
        # Historical or non-QA jobs without a frozen signer are unaffected.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_inputs'").fetchone():
            if conn.execute("SELECT 1 FROM jobs JOIN workspace_inputs ON jobs.id=workspace_inputs.job_id "
                            "WHERE jobs.workflow='workspace_execute' AND jobs.state='SUCCEEDED' "
                            "AND json_extract(workspace_inputs.request,'$.qa_signer_sha256') IS NOT NULL "
                            "AND json_extract(jobs.result,'$.qa_finalization') IS NULL LIMIT 1").fetchone():
                raise RuntimeError("Pending QA finalization")
        if conn.execute("SELECT count(*) FROM fixture_effects WHERE resolved_at IS NULL").fetchone()[0]:
            raise RuntimeError("Unresolved effects")


@contextmanager
def maintenance(root, bound_python, *, action):
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
        if action == "fence":
            unit = service / UNIT
            file_info(unit, limit=8192)
            check_unit(root, bound_python, fenced=unit.read_text(encoding="utf-8") ==
                       fenced_unit_text(root, bound_python), pending_reload=True)
        else:
            check_unit(root, bound_python, fenced=True)
        for name in ("allow-authenticated-probe", "allow-operational-diagnostics",
                     "fixture-image", "local-fixture-mode", "allow-github-context"):
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


def interpreter_identity(venv, *, executable=None):
    # Use relative labels inside the venv: a backup rename must not change
    # the recorded identity. Never execute a relocated interpreter.
    def label(path):
        return ("venv:" + str(path.relative_to(venv)) if venv is not None and path.is_relative_to(venv)
                else "host:" + str(path))

    def parent_policy(item, info, in_venv):
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()):
            raise PermissionError("Unsafe host interpreter parent")
        if info.st_mode & 0o022:
            # A root-owned sticky ancestor of the canonical private venv
            # (e.g. /tmp in tests) protects existing trusted-owned children.
            # Each child is checked before following it. Never extend this
            # exception to host interpreter paths or directories in the venv.
            if not (in_venv and item != venv and venv.is_relative_to(item)
                    and info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
                raise PermissionError("Unsafe host interpreter parent")

    path = venv / "bin/python" if executable is None else executable
    links = []
    seen = set()
    while True:
        if path.anchor != "/" or ".." in path.parts or len(path.parts) < 2:
            raise ValueError("Absolute interpreter path required without traversal")
        in_venv = venv is not None and path.is_relative_to(venv)
        parent = Path("/")
        parent_policy(parent, parent.lstat(), in_venv)
        # Inspect each lexical component before traversing it. On every
        # directory or file link, restart at root for the destination chain.
        parts = path.parts[1:]
        for index, part in enumerate(parts):
            actual = parent / part
            info = actual.lstat()
            remaining = parts[index + 1:]
            if stat.S_ISLNK(info.st_mode):
                if info.st_uid not in (0, os.getuid()):
                    raise PermissionError("Untrusted interpreter owner")
                if remaining and in_venv:
                    if actual == venv:
                        raise ValueError("Canonical directory required")
                    raise PermissionError("Unexpected venv interpreter parent link")
                if actual in seen:
                    raise ValueError("Interpreter link cycle")
                if len(links) >= 16:
                    raise ValueError("Interpreter link limit exceeded")
                seen.add(actual)
                target = os.readlink(actual)
                target_path = Path(target)
                if (".." in target_path.parts or target_path.anchor not in ("", "/")
                        or (not remaining and target.rsplit("/", 1)[-1] in ("", "."))):
                    raise ValueError("Unsupported interpreter link traversal")
                next_path = target_path if target_path.is_absolute() else parent / target_path
                path = next_path.joinpath(*remaining)
                if (venv is not None and path.is_relative_to(venv)
                        and (target_path.is_absolute() or not actual.is_relative_to(venv))):
                    raise ValueError("Absolute or external link into relocated venv")
                links.append({"path": label(actual), "resolved_parent": label(parent),
                              "target": target, "uid": info.st_uid})
                break
            if remaining:
                parent_policy(actual, info, in_venv)
                parent = actual
                continue
            if info.st_uid not in (0, os.getuid()):
                raise PermissionError("Untrusted interpreter owner")
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o6022
                    or not info.st_mode & 0o111 or info.st_size > 128 * 1024 * 1024):
                raise PermissionError("Unsafe interpreter executable")
            fd = os.open(actual, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if before != info:
                    raise RuntimeError("Interpreter changed during inspection")
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                after = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise RuntimeError("Interpreter changed during inspection")
            return {"links": links, "path": label(actual), "resolved": label(actual),
                    "dev": info.st_dev, "ino": info.st_ino, "uid": info.st_uid,
                    "mode": stat.S_IMODE(info.st_mode), "size": info.st_size, "sha256": digest}


def host_interpreter_identity(executable=None):
    # Same policy as the installed venv target, before creating a journal or
    # moving the previous environment. Do not resolve away launcher links.
    return interpreter_identity(None, executable=Path(sys.executable) if executable is None else executable)


def validated_host_python(expected):
    # Revalidate the original launcher and canonical target, and bind both
    # to the running coordinator. The trusted root/current UID boundary
    # excludes concurrent mutation by those principals.
    if host_interpreter_identity() != expected:
        raise RuntimeError("Host interpreter identity changed")
    canonical = Path(expected["resolved"].removeprefix("host:"))
    current = host_interpreter_identity(canonical)
    if current["links"] or any(current[key] != expected[key] for key in INTERPRETER_FIELDS):
        raise RuntimeError("Host interpreter identity changed")
    running = os.stat("/proc/self/exe")
    if (running.st_dev, running.st_ino, running.st_uid, stat.S_IMODE(running.st_mode), running.st_size) != (
            expected["dev"], expected["ino"], expected["uid"], expected["mode"], expected["size"]):
        raise RuntimeError("Running host interpreter identity mismatch")
    return canonical


def build_runner():
    expected = host_interpreter_identity()
    validated_host_python(expected)

    def run(kit, sha, wheel, active, tx, fds):
        launch_build(kit, sha, wheel, active, tx, fds, host=expected)

    return run


def identity(path):
    # Bind the directory inode and receipt/config bytes without executing a
    # relocated interpreter. Not tamper resistance against the trusted UID.
    interpreter = interpreter_identity(path)
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
            "receipt": value, "interpreter": interpreter}


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


def new_transaction(venv, sha, wheel, prior=None, root=None):
    return {"format": 1, "path": str(venv), "sha": sha, "wheel": wheel,
            "prior": prior, "candidate_identity": None, "root": str(root) if root is not None else None,
            "phase": "prepared", "group": None, "boot": boot_id()}


def verify_transaction(tx, venv, sha, root=None):
    if (set(tx) != {"format", "path", "sha", "wheel", "prior", "candidate_identity", "root", "phase", "group", "boot"}
            or tx["format"] != 1 or tx["path"] != str(venv) or tx["sha"] != sha
            or tx["root"] != (str(root) if root is not None else None)
            or not isinstance(tx["boot"], str)
            or tx["phase"] not in ("prepared", "writing", "installed", "restoring", "restored")
            or (tx["wheel"] is not None and (not isinstance(tx["wheel"], str)
                                             or not DIGEST.fullmatch(tx["wheel"])))):
        raise ValueError("Transaction identity mismatch")
    no_writers(tx)


def launch_build(kit, sha, wheel, active, tx, fds, *, host):
    # The session leader waits for a byte until the group identity is durable.
    # If the coordinator dies before that, EOF prevents any installation.
    # If it dies later, inherited flock descriptions and the recorded process
    # group fence recovery. Reviewed build descendants must not daemonize or
    # leave the session/process group; this is not a sandbox against same UID.
    host_python = validated_host_python(host)
    expected_host = json.dumps({key: host[key] for key in INTERPRETER_FIELDS}, sort_keys=True)
    reader, writer = os.pipe()
    child = None
    try:
        cmd = ["/bin/bash", "-c",
               'IFS= read -r -n 1 -u "$1" permit && [ "$permit" = Y ] || exit 1; '
               'shift; exec /bin/bash "$@"',
               "bridge-build", str(reader), str(kit / "local-bridge/scripts/install-build.sh"),
               str(fds[0]), str(host_python), expected_host, sha]
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
        if (prior["bound_path"] != str(venv) or bound_python != venv / "bin/python"
                or prior["identity"]["receipt"] != reviewed):
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



PROFILE_MIGRATION = "profile-migration.json"
PROFILE_RESTORE = "profile-restore.json"


def profile_json(path, limit=256 * 1024):
    directory(path.parent)
    expected = file_info(path, limit=limit)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
                expected.st_dev, expected.st_ino, expected.st_size, expected.st_mtime_ns):
            raise RuntimeError("Profile changed")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        current = file_info(path, limit=limit)
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) or len(raw) > limit:
            raise RuntimeError("Profile changed")
    finally:
        os.close(fd)

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate profile key")
            value[key] = item
        return value

    data = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError("Invalid profile")
    return data


def legacy_binding_current(locator, binding):
    # A changed, missing, tracked or invalid binding is never resurrected.
    try:
        path = Path(locator)
        if (not path.is_absolute() or path.name != "config.json"
                or path.parent.name != ".project-os"):
            return False
        directory(path.parent)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(path.parent), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0",
               "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1"}
        def check(*args):
            return subprocess.run(["git", "-C", str(path.parent.parent), "-c", "core.fsmonitor=false", *args],
                                  env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, timeout=5, check=False)
        tracked = check("ls-files", "--", ".project-os/")
        ignored = check("check-ignore", "--", ".project-os/config.json")
        if tracked.returncode or tracked.stdout or ignored.returncode:
            return False
        data = profile_json(path, 64 * 1024)
        project, repository, repository_id = binding
        return (type(data.get("version")) is int and data["version"] == 2
                and data.get("github_context") == {"project": project, "repository": repository,
                                                    "repository_id": repository_id}
                and isinstance(data.get("repositories"), list)
                and all(isinstance(item, str) for item in data["repositories"])
                and repository.casefold() in {item.casefold() for item in data["repositories"]})
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return False


def restore_profile(root, backup, tx, *, check_only=False):
    """Restore a legacy-readable profile; archive multi grants, never silently reactivate them."""
    migration = backup / PROFILE_MIGRATION
    archive = backup / PROFILE_RESTORE
    if not os.path.lexists(migration):
        if os.path.lexists(archive):
            raise RuntimeError("Missing profile migration evidence")
        return
    if root is None:
        raise ValueError("Profile migration requires exact instance")
    record = profile_json(migration)
    if (set(record) != {"format", "sha", "root", "before", "binding"}
            or record["format"] != 1 or record["sha"] != tx["sha"]
            or record["root"] != str(root) or tx["root"] != str(root)):
        raise ValueError("Profile migration identity mismatch")
    old, binding = record["before"], record["binding"]
    required = {"tunnel", "tunnel_id", "image"}
    if (not isinstance(old, dict) or not required <= set(old)
            or set(old) - required - {"podman_context", "project_config"}
            or old["image"] is not None or old.get("podman_context") is not None
            or not isinstance(binding, list) or len(binding) != 3
            or not isinstance(binding[0], str) or not isinstance(binding[1], str)
            or type(binding[2]) is not int or binding[2] <= 0):
        raise ValueError("Invalid legacy profile evidence")
    runtime = root / "service" / "runtime.json"
    current = profile_json(runtime, 64 * 1024)
    locator = old.get("project_config")

    def plan(source):
        if source == old:
            # Migration was interrupted before its atomic profile replacement.
            return old
        grants = source.get("github_projects")
        if (not isinstance(grants, dict) or len(grants) > 32
                or {k: v for k, v in source.items() if k != "github_projects"}
                   != {k: v for k, v in old.items() if k != "project_config"}):
            raise RuntimeError("Unrelated service settings changed; reconcile before rollback")
        target = {k: v for k, v in old.items() if k != "project_config"}
        if locator is not None and grants.get(binding[0]) == {
                "config": locator, "repository": binding[1], "repository_id": binding[2]}:
            if legacy_binding_current(locator, binding):
                target["project_config"] = locator
        return target

    if os.path.lexists(archive):
        saved = profile_json(archive)
        if (set(saved) != {"format", "sha", "root", "source", "target"}
                or saved["format"] != 1 or saved["sha"] != tx["sha"]
                or saved["root"] != str(root) or not isinstance(saved["source"], dict)
                or not isinstance(saved["target"], dict)):
            raise ValueError("Profile restore identity mismatch")
        source, target = saved["source"], saved["target"]
        if plan(source) != target or current not in (source, target):
            raise RuntimeError("Profile changed during rollback; preserve evidence")
    else:
        source, target = current, plan(current)
        if source == target:
            return
        saved = {"format": 1, "sha": tx["sha"], "root": str(root),
                 "source": source, "target": target}
        if len(json.dumps(target).encode()) + 1 > 4096:
            raise ValueError("Legacy service configuration exceeds limit")
        if not check_only:
            save_json(archive, saved)
    if check_only:
        return
    if current != target:
        if profile_json(runtime, 64 * 1024) != source:
            raise RuntimeError("Profile changed before rollback")
        save_json(runtime, target)
    if profile_json(runtime, 64 * 1024) != target:
        raise RuntimeError("Legacy profile restore unconfirmed")


def restore(venv, backup, active, sha, bound_python, root=None):
    directory(backup)
    tx = read_json(active if os.path.lexists(active) else backup / TRANSACTION)
    verify_transaction(tx, venv, sha, root)
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
        restore_profile(root, backup, tx)
        if os.path.lexists(venv):
            move(venv, candidate)
        move(previous, venv)
    else:
        validate_prior(prior, venv, venv, bound_python)
        tx["phase"] = "restoring"
        save_json(active, tx)
        restore_profile(root, backup, tx)
    validate_prior(prior, venv, venv, bound_python)
    tx["phase"] = "restored"
    finish(active, tx, backup)
    return prior["eligible"]


def replace(kit, sha, wheel, guard, fds, bound_python,
            previous_sha, previous_wheel, legacy=False, run=None, root=None):
    if run is None:
        run = build_runner()
    venv = kit / "local-bridge" / ".venv"
    backup = venv.parent / BACKUP
    active = guard / ACTIVE
    if os.path.lexists(active) or os.path.lexists(backup):
        raise FileExistsError("Unresolved maintenance or retained backup")
    prior = prior_identity(venv, bound_python, previous_sha, previous_wheel, legacy)
    validate_archives(venv, bound_python, root, prior["identity"], next_sha=sha)
    tx = new_transaction(venv, sha, wheel, prior, root)
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
        tx["candidate_identity"] = identity(venv)
    except BaseException:
        # Do not claim rollback while any installation descendant can write.
        eligible = restore(venv, backup, active, sha, bound_python, root)
        print("BRIDGE VENV PHYSICALLY RESTORED; prior runtime requires start review"
              if eligible else "LEGACY VENV QUARANTINE RESTORED; use certified bound fallback only",
              flush=True)
        raise
    tx["phase"] = "installed"
    finish(active, tx, backup)
    print("BRIDGE UPGRADE PASS; previous venv retained offline; unit remains fenced", flush=True)


def initial_install(kit, sha, wheel, guard, fd, run=None):
    if run is None:
        run = build_runner()
    venv = kit / "local-bridge" / ".venv"
    active = guard / ACTIVE
    if (os.path.lexists(active) or os.path.lexists(venv.parent / BACKUP)
            or any(venv.parent.glob(ARCHIVE_PREFIX + "*"))):
        raise RuntimeError("Unresolved maintenance or retained backup")
    if os.path.lexists(venv):
        raise ValueError("Existing bridge environment preserved.")
    tx = new_transaction(venv, sha, wheel)
    save_json(active, tx)
    run(kit, sha, wheel, active, tx, (fd,))
    observed = identity(venv)["receipt"]
    if observed is None or observed["sha"] != sha or (wheel is not None and observed["wheel_sha256"] != wheel):
        raise ValueError("Installation receipt mismatch")
    finish(active, tx)
    print("BRIDGE INSTALL PASS; existing wizard available; no service started.", flush=True)


def check_release(kit, sha, guard, bound_python, root=None):
    if os.path.lexists(guard / ACTIVE):
        raise RuntimeError("Unresolved maintenance")
    venv = kit / "local-bridge/.venv"
    backup = venv.parent / BACKUP
    if not os.path.lexists(backup):
        # An archived-only transaction must not be followed by enrollment or
        # activation without its rollback metadata at the original location.
        if any(venv.parent.glob(ARCHIVE_PREFIX + "*")):
            raise RuntimeError("Restore rollback slot before release or complete upgrade")
        return
    tx = validate_completed(venv, backup, sha, bound_python, root)
    validate_archives(venv, bound_python, root, tx["prior"]["identity"])


def validate_completed(venv, backup, sha, bound_python, root):
    directory(backup)
    tx = read_json(backup / TRANSACTION)
    verify_transaction(tx, venv, sha, root)
    if tx["phase"] == "installed":
        validate_receipt(venv, sha, tx["wheel"])
        if identity(venv) != tx["candidate_identity"]:
            raise ValueError("Candidate identity mismatch")
        validate_prior(tx["prior"], venv, backup / "previous", bound_python)
    elif tx["phase"] == "restored":
        validate_prior(tx["prior"], venv, venv, bound_python)
        if os.path.lexists(backup / PROFILE_RESTORE):
            saved = profile_json(backup / PROFILE_RESTORE)
            if root is None or profile_json(root / "service/runtime.json", 64 * 1024) != saved.get("target"):
                raise RuntimeError("Restored service profile changed; reconcile before release")
    else:
        raise RuntimeError("Incomplete maintenance")
    return tx


def archive_transaction(venv, location, sha, bound_python, root):
    """Check retained bytes and journal identity without executing a backup."""
    directory(location)
    tx = profile_json(location / TRANSACTION, 16384)
    verify_transaction(tx, venv, sha, root)
    prior = tx["prior"]
    if (not isinstance(prior, dict)
            or set(prior) != {"identity", "eligible", "reviewed", "bound_path", "bound_identity"}
            or prior["eligible"] is not True or prior["bound_path"] != str(venv)
            or bound_python != venv / "bin/python"
            or prior["identity"] != prior["bound_identity"]
            or prior["identity"]["receipt"] != prior["reviewed"]
            or not SHA.fullmatch(prior["reviewed"]["sha"])
            or not DIGEST.fullmatch(prior["reviewed"]["wheel_sha256"])):
        raise ValueError("Archived rollback provenance mismatch")
    candidate = tx["candidate_identity"]
    if (not isinstance(candidate, dict)
            or not DIGEST.fullmatch(tx["wheel"] or "")
            or candidate.get("receipt") != {"sha": sha, "wheel_sha256": tx["wheel"]}):
        raise ValueError("Archived candidate lacks completed identity")
    previous, saved = location / "previous", location / "candidate"
    if any(os.path.ismount(path) for path in (location, previous, saved)):
        raise RuntimeError("Rollback mount present")
    if tx["phase"] == "installed":
        if os.path.lexists(saved) or os.path.lexists(location / PROFILE_RESTORE):
            raise RuntimeError("Ambiguous installed rollback")
        validate_prior(prior, venv, previous, bound_python)
    elif tx["phase"] == "restored":
        if os.path.lexists(previous) or identity(saved) != candidate:
            raise RuntimeError("Ambiguous restored rollback")
    else:
        raise RuntimeError("Incomplete archived maintenance")
    for name in (PROFILE_MIGRATION, PROFILE_RESTORE):
        path = location / name
        if os.path.lexists(path):
            record = profile_json(path)
            fields = ({"before", "binding"} if name == PROFILE_MIGRATION
                      else {"source", "target"})
            if (set(record) != {"format", "sha", "root"} | fields
                    or record["format"] != 1 or record["sha"] != sha
                    or root is None or record["root"] != str(root)):
                raise ValueError("Archived profile identity mismatch")
    if (os.path.lexists(location / PROFILE_RESTORE)
            and not os.path.lexists(location / PROFILE_MIGRATION)):
        raise RuntimeError("Missing profile migration evidence")
    return tx


def validate_archives(venv, bound_python, root, current, *, next_sha=None):
    # Installed archives form a linear recovery chain; restored archives are
    # retained history, not active fallback edges. No separate registry.
    pending = []
    for path in venv.parent.glob(ARCHIVE_PREFIX + "*"):
        sha = path.name[len(ARCHIVE_PREFIX):]
        if not SHA.fullmatch(sha) or sha == next_sha:
            raise ValueError("Unknown or conflicting archived transaction")
        tx = archive_transaction(venv, path, sha, bound_python, root)
        if tx["phase"] == "installed":
            pending.append(tx)
    while pending:
        matches = [tx for tx in pending if tx["candidate_identity"] == current]
        if len(matches) != 1:
            raise RuntimeError("Disconnected or ambiguous rollback chain")
        tx = matches[0]
        pending.remove(tx)
        current = tx["prior"]["identity"]
    # Also persists a preceding same-parent archive rename after interruption.
    sync_directory(venv.parent)


def relocate_backup(kit, guard, rollback_sha, bound_python, root, *, unarchive=False):
    """Move the entire completed transaction, not an executable environment."""
    if not SHA.fullmatch(rollback_sha or ""):
        raise ValueError("Exact rollback transaction SHA required")
    if os.path.lexists(guard / ACTIVE):
        raise RuntimeError("Unresolved maintenance")
    venv = kit / "local-bridge/.venv"
    backup = venv.parent / BACKUP
    archived = venv.parent / (ARCHIVE_PREFIX + rollback_sha)
    source, target = (archived, backup) if unarchive else (backup, archived)
    present = [path for path in (source, target) if os.path.lexists(path)]
    if len(present) != 1:
        raise RuntimeError("Missing or conflicting rollback locations")
    location = present[0]
    tx = validate_completed(venv, location, rollback_sha, bound_python, root)
    archive_transaction(venv, location, rollback_sha, bound_python, root)
    restore_profile(root, location, tx, check_only=True)
    if location == source:
        move(source, target)
    # A retry after a completed rename (including a failed fsync) verifies the
    # destination again and makes the same-directory rename durable.
    validate_completed(venv, target, rollback_sha, bound_python, root)
    archive_transaction(venv, target, rollback_sha, bound_python, root)
    restore_profile(root, target, tx, check_only=True)
    sync_directory(target.parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "fence", "upgrade", "restore", "release",
                                           "archive", "unarchive"))
    parser.add_argument("reviewed_sha")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--bound-python", type=Path)
    parser.add_argument("--expected-wheel")
    parser.add_argument("--previous-sha")
    parser.add_argument("--previous-wheel")
    parser.add_argument("--legacy-consolidation", action="store_true")
    parser.add_argument("--rollback-sha")
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
        if (args.action in ("archive", "unarchive") and args.rollback_sha is None
                or args.rollback_sha is not None and
                (args.action not in ("archive", "unarchive", "restore", "release")
                 or not SHA.fullmatch(args.rollback_sha))):
            raise ValueError("Invalid rollback transaction selection")
        transaction_sha = args.rollback_sha or args.reviewed_sha
        run = build_runner() if args.action in ("install", "upgrade") else None
        with checkout_guard(kit) as (guard, fd):
            verify_checkout(kit, args.reviewed_sha)
            if args.action == "install":
                if any((args.root, args.bound_python, args.previous_sha, args.previous_wheel, args.legacy_consolidation)):
                    raise ValueError("Initial install has no maintenance parameters")
                initial_install(kit, args.reviewed_sha, args.expected_wheel, guard, fd, run=run)
                return
            if args.root is None or args.bound_python is None:
                raise ValueError("Exact instance and bound Python required")
            with maintenance(args.root, args.bound_python, action=args.action) as service_fds:
                verify_checkout(kit, args.reviewed_sha)
                if args.action in ("fence", "release"):
                    if any((args.expected_wheel, args.previous_sha, args.previous_wheel, args.legacy_consolidation)):
                        raise ValueError("Unexpected fence parameters")
                    if args.action == "fence":
                        fence_unit(args.root, args.bound_python)
                        print("BRIDGE UNIT FENCED; no service started")
                    else:
                        if (args.rollback_sha is not None and
                                not os.path.lexists(kit / "local-bridge" / BACKUP)):
                            raise RuntimeError("Explicit rollback transaction missing")
                        check_release(kit, transaction_sha, guard, args.bound_python, args.root)
                        release_unit(args.root, args.bound_python)
                        print("BRIDGE UNIT RELEASED; no service started")
                elif args.action in ("archive", "unarchive"):
                    if any((args.expected_wheel, args.previous_sha, args.previous_wheel, args.legacy_consolidation)):
                        raise ValueError("Archive uses recorded transaction")
                    relocate_backup(kit, guard, args.rollback_sha, args.bound_python, args.root,
                                    unarchive=args.action == "unarchive")
                    print("BRIDGE ROLLBACK RECONCILED; unit remains fenced")
                elif args.action == "upgrade":
                    if not DIGEST.fullmatch(args.expected_wheel or ""):
                        raise ValueError("Expected CI wheel SHA-256 required")
                    replace(kit, args.reviewed_sha, args.expected_wheel, guard,
                            (fd, *service_fds), args.bound_python, args.previous_sha,
                            args.previous_wheel, args.legacy_consolidation, run=run, root=args.root)
                else:
                    if any((args.expected_wheel, args.previous_sha, args.previous_wheel, args.legacy_consolidation)):
                        raise ValueError("Restore uses recorded transaction")
                    if os.path.lexists(args.root / "state/oauth-audit.jsonl"):
                        raise RuntimeError("Archive OAuth sidecar before restore")
                    venv = kit / "local-bridge/.venv"
                    eligible = restore(venv, venv.parent / BACKUP, guard / ACTIVE,
                                       transaction_sha, args.bound_python, args.root)
                    print("BRIDGE VENV PHYSICALLY RESTORED; unit remains fenced"
                          if eligible else "LEGACY VENV QUARANTINE RESTORED; use certified bound fallback only")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error,
            subprocess.SubprocessError, KeyboardInterrupt) as exc:
        # Stable existing CI rejection messages; do not print exception data.
        for message in ("HEAD mismatch.", "Unexpected origin.", "Dirty checkout; preserved.",
                        "Existing bridge environment preserved."):
            if type(exc) is ValueError and str(exc) == message:
                print(message, file=sys.stderr)
        # Fixed diagnostic categories only; no paths or exception payloads.
        if isinstance(exc, PermissionError) and str(exc) in (
                "Unsafe host interpreter parent", "Untrusted interpreter owner",
                "Unsafe interpreter executable", "Unexpected venv interpreter parent link"):
            print("BRIDGE INTERPRETER REJECTED: " + str(exc), file=sys.stderr)
        print("BRIDGE MAINTENANCE BLOCKED OR INTERRUPTED; preserve files and inspect locally",
              file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
