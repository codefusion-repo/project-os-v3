"""Local-only user-systemd lifecycle for the exact prepared private unit."""
import argparse
import fcntl
import stat
from contextlib import contextmanager
import os
import subprocess
import sys
from pathlib import Path

from .service_setup import checked_path, render_unit
from .workos_auth import private_directory, private_file

UNIT = "project-os-bridge.service"
PROPERTIES = ("Id", "LoadState", "FragmentPath", "DropInPaths",
              "NeedDaemonReload", "ActiveState", "UnitFileState", "Job")


def systemctl(*args):
    uid = os.getuid()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LC_ALL": "C",
           "XDG_RUNTIME_DIR": f"/run/user/{uid}",
           "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"}
    return subprocess.run(
        ["/usr/bin/systemctl", "--user", "--no-pager", *args],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, timeout=150, check=False)


@contextmanager
def exclusive_lifecycle():
    # The unit name is shared by all instances for this user, so lock at user scope.
    directory = Path(f"/run/user/{os.getuid()}")
    private_directory(directory)
    fd = os.open(directory / "project-os-bridge-lifecycle.lock",
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise PermissionError("Unsafe lifecycle lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def prepared_unit(root):
    if os.getuid() == 0:
        raise PermissionError("Unprivileged account required")
    checked_path(root)
    private_directory(root)
    if any(os.path.lexists(p / ".git") for p in (root, *root.parents)):
        raise PermissionError("Instance must be outside Git")
    directory = root / "service"
    private_directory(directory)
    unit = checked_path(directory / UNIT)
    if private_file(unit).st_size > 8192:
        raise ValueError("Invalid prepared unit")
    if unit.read_text(encoding="utf-8") != render_unit(root, Path(sys.executable)):
        raise PermissionError("Prepared unit differs from reviewed definition")
    return unit


def snapshot(unit, call=systemctl):
    result = call("show", *("--property=" + key for key in PROPERTIES), UNIT)
    fields = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key not in PROPERTIES or key in fields:
            raise RuntimeError("Unexpected unit status")
        fields[key] = value
    if set(fields) != set(PROPERTIES) or fields["Id"] != UNIT:
        raise RuntimeError("Unconfirmed unit status")
    if not fields["Job"].isascii() or not fields["Job"].isdecimal():
        raise RuntimeError("Unconfirmed systemd job status")
    pending = int(fields["Job"]) != 0
    if (fields["LoadState"] == "not-found" and not fields["FragmentPath"]
            and not fields["DropInPaths"] and fields["ActiveState"] == "inactive"
            and fields["UnitFileState"] in ("", "not-found") and not pending):
        return {"linked": False, "active": "inactive", "enabled": False, "pending_job": False}
    if result.returncode or fields["LoadState"] != "loaded" or not fields["FragmentPath"]:
        raise RuntimeError("Unit unavailable")
    fragment = Path(fields["FragmentPath"])
    if (not fragment.is_absolute() or fragment.resolve(strict=True) != unit
            or fields["DropInPaths"] or fields["NeedDaemonReload"] != "no"):
        raise PermissionError("Foreign or changed unit; no operation")
    if fields["UnitFileState"] not in ("linked", "enabled", "disabled"):
        raise RuntimeError("Unsupported unit file state")
    if fields["ActiveState"] not in ("active", "inactive", "failed", "activating", "deactivating"):
        raise RuntimeError("Unsupported active state")
    return {"linked": True, "active": fields["ActiveState"],
            "enabled": fields["UnitFileState"] == "enabled", "pending_job": pending}


def operate(unit, action, call=systemctl):
    before = snapshot(unit, call)
    if action == "status":
        return before
    if before["pending_job"] or before["active"] in ("activating", "deactivating"):
        raise RuntimeError("Transition in progress; inspect status")
    if action == "link":
        if before["linked"]:
            return before
        args = ("link", str(unit))
        check = lambda state: state["linked"] and not state["enabled"] and state["active"] == "inactive"
    elif action == "start":
        if not before["linked"] or before["active"] == "failed":
            raise RuntimeError("Link first; inspect failed service before recovery")
        if before["active"] == "active":
            return before
        args = ("start", "--job-mode=fail", UNIT)
        check = lambda state: state["linked"] and state["active"] == "active"
    elif action == "stop":
        if before["active"] == "inactive":
            return before
        args = ("stop", "--job-mode=fail", UNIT)
        check = lambda state: state["active"] == "inactive"
    elif action == "reset-failed":
        if not before["linked"] or before["active"] == "active":
            raise RuntimeError("Only a stopped, identified unit can be reset")
        if before["active"] == "inactive":
            return before
        args = ("reset-failed", UNIT)
        check = lambda state: state["linked"] and state["active"] == "inactive"
    elif action == "enable":
        if not before["linked"] or before["active"] != "active":
            raise RuntimeError("Explicit successful start and live health review required before enable")
        if before["enabled"]:
            return before
        args = ("enable", str(unit))
        check = lambda state: state["linked"] and state["enabled"]
    elif action == "disable":
        if not before["enabled"]:
            return before
        if before["active"] != "inactive":
            raise RuntimeError("Stop explicitly before disable")
        args = ("disable", UNIT)
        check = lambda state: not state["enabled"] and state["active"] == "inactive"
    else:
        raise ValueError("Unknown lifecycle operation")
    # No retry, no restart, no --now, no mutation of another unit.
    try:
        result = call(*args)
    except subprocess.TimeoutExpired:
        # A timeout does not mean systemd did not apply the operation.
        after = snapshot(unit, call)
        if not after["pending_job"] and check(after):
            return after
        raise RuntimeError("Lifecycle outcome unconfirmed; inspect status before retry") from None
    after = snapshot(unit, call)
    if result.returncode or after["pending_job"] or not check(after):
        raise RuntimeError("Lifecycle outcome unconfirmed; inspect status before retry")
    return after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("action", choices=("link", "start", "stop", "status", "reset-failed", "enable", "disable"))
    args = parser.parse_args()
    try:
        unit = prepared_unit(args.root)
        with exclusive_lifecycle():
            state = operate(unit, args.action)
        print(f"linked={state['linked']} active={state['active']} enabled={state['enabled']} pending_job={state['pending_job']}")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print("LIFECYCLE_BLOCKED_OR_UNCONFIRMED; inspect local status", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
