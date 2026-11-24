"""Conservative local isolation inventory; never grants access or prints paths."""
import grp
import os
import pwd
from pathlib import Path

PRIVILEGED = {"sudo","wheel","docker","lxd","libvirt","disk","root","adm","podman","incus","shadow"}


def inspect():
    results = {}
    uid = os.getuid()
    account = pwd.getpwuid(uid)
    results["unprivileged_uid"] = uid != 0 and os.geteuid() == uid
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
    types = [line.split(" - ",1)[1].split()[0] for line in mountinfo.splitlines()]
    results["windows_mounts_absent"] = not any(t in {"9p","drvfs","virtiofs","cifs","smb3"} for t in types)
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
    return 0 if all(v for k,v in results.items() if k!="wsl_boundary_review_required") and not results["wsl_boundary_review_required"] else 1


if __name__=="__main__":
    raise SystemExit(main())
