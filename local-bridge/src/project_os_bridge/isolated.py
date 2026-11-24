"""Fail-closed rootless Podman gate for trusted disposable data only."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .git_fixture import GitFixture

IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]{0,511}@sha256:[0-9a-f]{64}")
# Fixed trusted program. No repository code, external network probes or actual secrets.
SCRIPT = r"""
import errno, os, socket, sys
from pathlib import Path

def require(condition, code):
    if not condition:
        sys.exit(code)

fixture = Path('/fixture/fixture.txt')
require(fixture.read_bytes() == b'after\n', 10)
try:
    fd = os.open(fixture, os.O_WRONLY)
except OSError as exc:
    require(exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM), 11)
else:
    os.close(fd)
    sys.exit(11)
require(not os.path.lexists(sys.argv[1]), 12)
require(not os.path.lexists('/run/podman/podman.sock'), 12)
require(not os.path.lexists('/var/run/docker.sock'), 12)
require(not os.path.lexists(sys.argv[2]), 12)
require(set(name for _, name in socket.if_nameindex()) <= {'lo'}, 13)
status = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
require(status['NoNewPrivs'].strip() == '1', 14)
require(status['Seccomp'].strip() == '2', 14)
require(all(int(status[k].strip(),16) == 0 for k in ('CapEff','CapPrm','CapBnd','CapAmb')), 14)
mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
require(any(m[4] == '/' and 'ro' in m[5].split(',') for m in mounts), 15)
cg = Path('/sys/fs/cgroup')
require(int((cg/'memory.max').read_text()) <= 134217728, 16)
require(int((cg/'pids.max').read_text()) <= 64, 16)
quota, period = (cg/'cpu.max').read_text().split()
require(int(quota) <= int(period), 16)
"""
CHECKS = ["exact_content","fixture_write_denied","synthetic_host_path_absent",
          "standard_sockets_absent","loopback_only","no_new_privileges",
          "seccomp_filter","zero_capabilities","root_read_only","cgroup_limits"]


def container_name(token):
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Invalid fixture identity")
    return "project-os-fixture-" + token


def podman_run(*args, timeout=10, capture=False):
    env = {"PATH":"/usr/bin:/bin","HOME":os.environ.get("HOME",""),
           "XDG_RUNTIME_DIR":f"/run/user/{os.getuid()}","LC_ALL":"C"}
    return subprocess.run(["/usr/bin/podman",*args],env=env,stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL,timeout=timeout)


def rootless_host():
    if os.getuid() == 0:
        raise PermissionError("Rootless required")
    info = podman_run("info","--format","json",capture=True)
    if info.returncode or len(info.stdout)>262144:
        raise ValueError("Podman info failed")
    host = json.loads(info.stdout)["host"]
    if host["security"].get("rootless") is not True:
        raise PermissionError("Rootless required")
    return host


def container_absent(token):
    # Check both the exact name and the unique ownership label (including renamed
    # containers). Never remove a container by name or accept a failed query.
    name = container_name(token)
    exists = podman_run("container","exists",name)
    owned = podman_run("ps","--all","--filter","label=io.project-os.fixture="+token,
                       "--format","{{.ID}}",capture=True)
    return exists.returncode == 1 and owned.returncode == 0 and owned.stdout == b""


def validate_in_container(repo: GitFixture, principal, expected_revision, image, *, token):
    repo.policy.require(principal,"fixture_validate","disposable")
    if not isinstance(image,str) or not IMAGE.fullmatch(image):
        raise ValueError("Locally approved digest-pinned image required")
    snapshot=repo.snapshot(principal)
    if snapshot["revision"] != expected_revision:
        return {"status":"BLOCKED","reason":"REVISION_CONFLICT","container_absent":True}
    if os.getuid()==0:
        return {"status":"BLOCKED","reason":"ROOTLESS_REQUIRED","container_absent":True}
    name=container_name(token)
    attempted=False
    try:
        info=podman_run("info","--format","json",capture=True)
        if info.returncode or len(info.stdout)>262144:
            return {"status":"BLOCKED","reason":"PODMAN_INFO_FAILED","container_absent":True}
        host=json.loads(info.stdout)["host"]
        security=host["security"]
        if security.get("rootless") is not True:
            return {"status":"BLOCKED","reason":"ROOTLESS_UNAVAILABLE","container_absent":True}
        if security.get("seccompEnabled") is not True or host.get("cgroupVersion")!="v2":
            return {"status":"BLOCKED","reason":"SECURITY_PREFLIGHT_FAILED","container_absent":True}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            mount=path/"export"
            mount.mkdir(mode=0o700)
            (mount/"fixture.txt").write_text(snapshot["text"],encoding="utf-8")
            sentinel=path/"private-synthetic-marker"
            sentinel.write_text("synthetic only",encoding="utf-8")
            args=["run","--rm","--name",name,"--label","io.project-os.fixture="+token,"--pull=never",
                  "--network=none","--read-only","--read-only-tmpfs=false",
                  "--cap-drop=ALL","--security-opt=no-new-privileges",
                  "--http-proxy=false","--image-volume=ignore","--pid=private",
                  "--ipc=private","--cgroupns=private",
                  "--pids-limit=64","--memory=128m","--cpus=1","--userns=keep-id",
                  "--volume",f"{mount}:/fixture:ro","--entrypoint","python",image,"-I","-B","-c",SCRIPT,
                  str(sentinel),f"/run/user/{os.getuid()}/podman/podman.sock"]
            attempted=True
            result=podman_run(*args,timeout=30)
            if not container_absent(token):
                return {"status":"BLOCKED","reason":"CLEANUP_UNVERIFIED"}
            return {"status":"SUCCEEDED" if result.returncode==0 else "FAILED",
                    "exit_code":result.returncode,"revision":expected_revision,
                    "profile":"fixture-python","cleanup_verified":True,
                    "checks":CHECKS if result.returncode==0 else [],
                    "host_lsm":{"apparmor":security.get("apparmorEnabled") is True,
                                "selinux":security.get("selinuxEnabled") is True}}
    except (OSError,subprocess.TimeoutExpired,ValueError,KeyError,TypeError,AttributeError):
        return {"status":"BLOCKED","reason":"CLEANUP_UNVERIFIED" if attempted else "ISOLATION_UNAVAILABLE_OR_TIMEOUT", "container_absent":not attempted}
