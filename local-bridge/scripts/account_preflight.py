"""Conservative local isolation inventory; never grants access or prints paths."""
import grp
import os
import pwd
from pathlib import Path

PRIVILEGED = {"sudo","wheel","docker","lxd","libvirt","disk","root","adm","podman","incus","shadow"}


HOST_MOUNT_TYPES = {"9p", "drvfs", "virtiofs", "cifs", "smb3"}
WSL_DRIVER_PATH = "/usr/lib/wsl/drivers"


def mount_inventory(mountinfo):
    """Classify visible mount targets for diagnosis, not trust or authorization."""
    driver_path_seen = other_host_mount_seen = False
    lines = mountinfo.splitlines()
    if not lines:
        raise ValueError("Empty mount inventory")
    for line in lines:
        left, separator, right = line.partition(" - ")
        fields, filesystem = left.split(), right.split()
        if not separator or len(fields) < 6 or len(filesystem) < 3:
            raise ValueError("Malformed mount inventory")
        if not fields[4].startswith("/"):
            raise ValueError("Invalid mount target")
        if filesystem[0] in HOST_MOUNT_TYPES:
            # Exact path label only: never an allowlist or a provenance assertion.
            if fields[4] == WSL_DRIVER_PATH:
                driver_path_seen = True
            else:
                other_host_mount_seen = True
    return {
        "windows_mounts_absent": not (driver_path_seen or other_host_mount_seen),
        "wsl_driver_path_mount_absent": not driver_path_seen,
        "other_host_mounts_absent": not other_host_mount_seen,
    }


def process_privilege_inventory(status):
    """Report current capabilities, not future elevation or sudo policy."""
    keys = {"CapPrm", "CapEff", "CapAmb", "NoNewPrivs"}
    values = {}
    for line in status.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in keys:
            if key in values:
                raise ValueError("Duplicate process privilege field")
            values[key] = value.strip()
    if set(values) != keys or values["NoNewPrivs"] not in {"0", "1"}:
        raise ValueError("Incomplete process privilege inventory")
    for key in ("CapPrm", "CapEff", "CapAmb"):
        value = values[key]
        if not value or any(c not in "0123456789abcdefABCDEF" for c in value):
            raise ValueError("Invalid process capability field")
    return {
        "process_capabilities_absent": all(
            int(values[key], 16) == 0 for key in ("CapPrm", "CapEff", "CapAmb")),
        "no_new_privileges_enabled": values["NoNewPrivs"] == "1",
    }


def inspect():
    results = {}
    uid = os.getuid()
    account = pwd.getpwuid(uid)
    results["unprivileged_uid"] = uid != 0 and os.geteuid() == uid
    results.update(process_privilege_inventory(Path("/proc/self/status").read_text()))
    results["privileged_groups_absent"] = not PRIVILEGED.intersection(
        grp.getgrgid(g).gr_name for g in set(os.getgroups()) | {os.getgid(),os.getegid()})
    home = Path(account.pw_dir)
    results["private_home"] = (not home.is_symlink() and home.is_dir()
                               and home.stat().st_uid == uid and not home.stat().st_mode & 0o077)
    # Check effective access without reading other users' files.
    others = {Path(p.pw_dir) for p in pwd.getpwall() if p.pw_uid != uid and p.pw_uid >= 1000 and p.pw_uid < 65534}
    results["other_homes_not_traversable"] = all(not os.access(p,os.X_OK,effective_ids=True) for p in others)
    sockets = (Path("/run/docker.sock"),Path("/run/podman/podman.sock"),Path("/run/containerd/containerd.sock"))
    results["privileged_sockets_inaccessible"] = all(not os.access(p,os.W_OK,effective_ids=True) for p in sockets)
    # Mount inventory is conservative; unknown mount types require manual review.
    mountinfo = Path("/proc/self/mountinfo").read_text()
    results.update(mount_inventory(mountinfo))
    kernel = Path("/proc/sys/kernel/osrelease").read_text().lower()
    wsl = "microsoft" in kernel or "wsl" in kernel
    interop = Path("/proc/sys/fs/binfmt_misc/WSLInterop")
    # Absence in one namespace is not proof of WSL boundary; always require review.
    results["interop_not_observed"] = not interop.exists() and not os.environ.get("WSL_INTEROP")
    results["wsl_boundary_review_required"] = wsl
    return results


def main():
    try:
        results=inspect()
    except (OSError,KeyError,ValueError,IndexError):
        print("ACCOUNT_PREFLIGHT: BLOCKED")
        return 1
    for name,value in results.items():
        print(name+": "+("YES" if value else "NO"))
    print("Inventory only: sudo policy, ACLs, network, credential scopes and host boundary require independent review.")
    # NoNewPrivs is an observation here, not proof of a restricted job.
    # The strict inventory remains blocking on WSL and all known host mounts.
    observations = {"wsl_boundary_review_required", "no_new_privileges_enabled"}
    return 0 if all(v for k,v in results.items() if k not in observations) and not results["wsl_boundary_review_required"] else 1


if __name__=="__main__":
    raise SystemExit(main())
