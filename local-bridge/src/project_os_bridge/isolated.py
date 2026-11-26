"""Fail-closed rootless Podman gate for trusted disposable data only."""
import json
import os
import re
import socket
import subprocess
import tempfile
from pathlib import Path

from .git_fixture import GitFixture
from .isolation_profile import ISOLATION_CHECKS, MOUNT_CHECK, challenge

IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]{0,511}@sha256:[0-9a-f]{64}")
# Fixed trusted program. No repository code, external network probes or actual secrets.
SCRIPT = r"""
import errno, json, os, re, socket, sys
from pathlib import Path
""" + MOUNT_CHECK + r"""

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
spec = json.loads(sys.argv[3])
require(all(os.readlink('/proc/self/ns/' + name) != identity
            for name, identity in spec['namespaces'].items()), 17)
violation = mount_violation([parse_mount(line) for line in Path('/proc/self/mountinfo').read_text().splitlines()], spec)
if violation:
    print(violation)
    sys.exit(18)
require(all(not os.path.lexists(path) for path in spec['forbidden']), 19)
"""
CHECKS = ["exact_content","fixture_write_denied","synthetic_host_path_absent",
          "standard_sockets_absent","loopback_only","no_new_privileges",
          "seccomp_filter","zero_capabilities","root_read_only","cgroup_limits"]


def container_name(token):
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Invalid fixture identity")
    return "project-os-fixture-" + token


def container_absent(context, identity, token):
    # Exact name AND unique ownership label, including renamed containers.
    name = container_name(token)
    exists = context.run(identity, "container", "exists", name)
    owned = context.run(identity, "ps", "--all", "--filter", "label=io.project-os.fixture=" + token,
                        "--format", "{{.ID}}", capture=True)
    return exists.returncode == 1 and owned.returncode == 0 and owned.stdout == b""


def validate_in_container(repo: GitFixture, principal, expected_revision, image, *, token, context, identity):
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
        host = context.host(identity)
        security = host["security"]
        context.require_import(identity, image)
        with tempfile.TemporaryDirectory() as folder, socket.socket(socket.AF_UNIX) as fake_socket:
            path = Path(folder)
            mount = path / "export"
            mount.mkdir(mode=0o700)
            (mount / "fixture.txt").write_text(snapshot["text"], encoding="utf-8")
            sentinel = path / "private-synthetic-marker"
            sentinel.write_text("synthetic only", encoding="utf-8")
            for category in ("exchange", "credentials"):
                directory = path / category
                directory.mkdir(mode=0o700)
                (directory / "synthetic-marker").write_text("synthetic only", encoding="utf-8")
            socket_path = path / "synthetic.sock"
            fake_socket.bind(str(socket_path))
            probes = json.loads(challenge(mount, context.root, sentinel, socket_path))
            for category in ("exchange", "credentials"):
                probes["forbidden"].append(str(path / category / "synthetic-marker"))
            args = ["run", "--rm", "--name", name, "--label", "io.project-os.fixture=" + token, "--pull=never",
                    "--network=none", "--read-only", "--read-only-tmpfs=false",
                    "--cap-drop=ALL", "--security-opt=no-new-privileges", "--http-proxy=false",
                    "--image-volume=ignore", "--pid=private", "--ipc=private", "--cgroupns=private", "--uts=private",
                    "--pids-limit=64", "--memory=128m", "--cpus=1", "--userns=keep-id", "--passwd=false",
                    "--volume", f"{mount}:/fixture:ro", "--entrypoint", "python", image, "-I", "-B", "-c", SCRIPT,
                    str(sentinel), f"/run/user/{os.getuid()}/podman/podman.sock", json.dumps(probes)]
            attempted=True
            result = context.run(identity, *args, timeout=30, capture=True)
            if not container_absent(context, identity, token):
                return {"status":"BLOCKED","reason":"CLEANUP_UNVERIFIED"}
            observed = {"status":"SUCCEEDED" if result.returncode==0 else "FAILED",
                    "exit_code":result.returncode,"revision":expected_revision,
                    "profile":"fixture-python","cleanup_verified":True,
                    "checks":CHECKS if result.returncode==0 else [],
                    "isolation_checks":ISOLATION_CHECKS if result.returncode==0 else [],
                    "host_lsm":{"apparmor":security.get("apparmorEnabled") is True,
                                "selinux":security.get("selinuxEnabled") is True}}
            if result.returncode == 18 and isinstance(result.stdout, bytes) and len(result.stdout) <= 96:
                diagnostic = result.stdout.strip().decode("ascii", errors="replace")
                if re.fullmatch(r"(?:missing-required-mount|(?:duplicate|host-filesystem|denied):[/.a-z_-]+:[a-z0-9_.-]+)", diagnostic):
                    observed["mount_check"] = diagnostic
            return observed
    except (OSError,subprocess.TimeoutExpired,ValueError,KeyError,TypeError,AttributeError):
        return {"status":"BLOCKED","reason":"CLEANUP_UNVERIFIED" if attempted else "ISOLATION_UNAVAILABLE_OR_TIMEOUT", "container_absent":not attempted}
