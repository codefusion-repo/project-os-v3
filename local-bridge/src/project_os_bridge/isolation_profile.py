"""Fixed in-container observations and synthetic host-side challenges."""
import json
import os
import pwd
import re
from pathlib import Path

NAMESPACES = ("user", "mnt", "pid", "ipc", "net", "cgroup", "uts")
HOST_FILESYSTEMS = {"9p", "drvfs", "virtiofs", "cifs", "smb3"}
CREDENTIAL_PATHS = (".ssh", ".aws", ".gnupg", ".docker", ".kube", ".git-credentials",
                    ".config/gh", ".config/gcloud", ".config/containers/auth.json")
ISOLATION_CHECKS = ["private_namespaces", "allowed_mounts_only", "host_backed_mounts_absent",
                    "synthetic_exchange_absent", "synthetic_credentials_absent",
                    "synthetic_socket_absent", "unapproved_paths_absent"]

# Embedded unchanged as the fixed Python program. No caller-supplied code.
MOUNT_CHECK = r"""
def decode_mount(field):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), field)


def parse_mount(line):
    left, right = line.split(' - ', 1)
    fields = left.split()
    return fields[2], decode_mount(fields[3]), decode_mount(fields[4]), fields[5].split(','), right.split()[0]


def mount_violation(mounts, spec):
    pseudo = {'/proc': 'proc', '/sys': 'sysfs', '/sys/fs/cgroup': 'cgroup2',
              '/dev': 'tmpfs', '/dev/pts': 'devpts', '/dev/shm': 'tmpfs',
              '/dev/mqueue': 'mqueue', '/run/secrets': 'tmpfs'}
    readonly = {'/proc/asound', '/proc/bus', '/proc/fs', '/proc/irq', '/proc/sys', '/proc/sysrq-trigger'}
    masked = {'/proc/acpi', '/proc/asound', '/proc/kcore', '/proc/keys', '/proc/latency_stats',
              '/proc/sched_debug', '/proc/scsi', '/proc/timer_list', '/proc/timer_stats',
              '/sys/devices/virtual/powercap', '/sys/firmware', '/sys/fs/selinux'}
    generated = {'/etc/hosts': 'hosts', '/etc/hostname': 'hostname', '/etc/resolv.conf': 'resolv.conf',
                 '/run/.containerenv': '.containerenv'}
    devices = {'/dev/null': (1, 3), '/dev/zero': (1, 5), '/dev/full': (1, 7),
               '/dev/random': (1, 8), '/dev/urandom': (1, 9), '/dev/tty': (5, 0)}
    known = (set(pseudo) | readonly | masked | set(generated) | set(devices) | {'/', '/fixture', '/etc/passwd', '/etc/group',
             '/proc/interrupts', '/proc/schedstat', '/proc/self/fd', '/run', '/tmp', '/var/tmp', '/dev/null',
             '/dev/ptmx', '/dev/console', '/sys/fs/cgroup/systemd'})
    seen = set()
    for device, root, target, options, fs in mounts:
        target_label = target if target in known else 'unlisted'
        filesystem = fs if fs in {'overlay', 'fuse.overlayfs', 'proc', 'sysfs', 'cgroup2', 'tmpfs', 'devtmpfs',
                                   'devpts', 'mqueue', 'ext4', 'xfs', 'btrfs'} else 'other'
        if target in seen:
            return f'duplicate:{target_label}:{filesystem}'
        if fs in spec['host_filesystems']:
            return f'host-filesystem:{target_label}:{filesystem}'
        seen.add(target)
        if target == '/':
            ok = fs in {'overlay', 'fuse.overlayfs'} and root == '/' and 'ro' in options
        elif target == '/fixture':
            ok = [device, root, fs] == spec['fixture'] and 'ro' in options
        elif target in pseudo:
            ok = fs == pseudo[target] and (root == '/' or fs == 'cgroup2')
        elif target in readonly and fs == 'proc':
            ok = root == target[5:] and 'ro' in options
        elif target in masked:
            ok = fs in {'tmpfs', 'devtmpfs'} and root in {'/', '/null'}
        elif target in devices:
            node = Path(target).lstat()
            ok = (fs in {'tmpfs', 'devtmpfs'} and root == target[4:] and stat.S_ISCHR(node.st_mode)
                  and (os.major(node.st_rdev), os.minor(node.st_rdev)) == devices[target])
        elif target in generated:
            path = Path(root)
            ok = (fs in {'ext4', 'xfs', 'btrfs', 'tmpfs'} and path.name == generated[target]
                  and any(device == dev and path.is_relative_to(base) for dev, base in spec['generated']))
        else:
            ok = False
        if not ok:
            return f'denied:{target_label}:{filesystem}'
    return None if {'/', '/fixture', '/proc', '/sys/fs/cgroup'} <= seen else 'missing-required-mount'


def allowed_mounts(mounts, spec):
    return mount_violation(mounts, spec) is None
"""


def _decode_mount(field):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), field)


def challenge(export, context_root, sentinel, private_socket):
    """Map the exact export and context to mountinfo roots without reading host data."""
    lines = Path("/proc/self/mountinfo").read_text().splitlines()
    if not 0 < len(lines) <= 4096:
        raise ValueError("Invalid host mount inventory")
    mounts = []
    for line in lines:
        left, right = line.split(" - ", 1)
        a, b = left.split(), right.split()
        mounts.append((a[2], Path(_decode_mount(a[3])), Path(_decode_mount(a[4])), b[0]))

    def backing(path):
        device, root, target, fs = max((m for m in mounts if path.is_relative_to(m[2])),
                                       key=lambda m: len(m[2].parts))
        return [device, str(root / path.relative_to(target)), fs]

    fixture = backing(export)
    if fixture[2] in HOST_FILESYSTEMS:
        raise ValueError("Fixture export must be on a native private filesystem")
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    forbidden = {str(m[2]) for m in mounts if m[3] in HOST_FILESYSTEMS}
    forbidden.update(str(base / name) for base in (home, Path("/root")) for name in CREDENTIAL_PATHS)
    forbidden.update(str(context_root / name) for name in ("auth.json", "graph", "runtime", "home"))
    forbidden.update((str(sentinel), str(private_socket), "/run/docker.sock", "/run/containerd/containerd.sock",
                      f"/run/user/{os.getuid()}/bus", f"/run/user/{os.getuid()}/docker.sock"))
    data = {"namespaces": {name: os.readlink(f"/proc/self/ns/{name}") for name in NAMESPACES},
            "fixture": fixture, "generated": [backing(context_root / name)[:2]
                                               for name in ("graph", "runroot", "libpod")],
            "host_filesystems": sorted(HOST_FILESYSTEMS), "forbidden": sorted(forbidden)}
    payload = json.dumps(data, separators=(",", ":"))
    if len(payload.encode()) > 32768:
        raise ValueError("Isolation challenge too large")
    return payload
