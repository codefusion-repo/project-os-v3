#!/usr/bin/env bash
# Internal build worker. Invoke only through the checked transaction coordinator.
set -euo pipefail
umask 077
[ "$(id -u)" -ne 0 ] || { echo 'Run as an unprivileged operator.' >&2; exit 1; }
# The coordinator passes its locked checkout descriptor, not a bypass flag.
# Verify the same open file description holds the lock and matches the durable
# transaction group before any writes. This is coordination, not a UID sandbox.
lock_fd="${1-}"
host_python="${2-}"
expected_host="${3-}"
shift 3
[[ "$host_python" = /* ]] || exit 1
KIT="$(cd -- "$(dirname -- "$0")/../.." && pwd -P)"
"$host_python" -I - "$KIT" "$lock_fd" "$expected_host" "${1-}" "${2-}" <<'PY'
import fcntl, hashlib, json, os, stat, sys
from pathlib import Path
kit, raw_fd, expected_host, sha, wheel = sys.argv[1:]
# Check the executable actually running this worker before any build writes.
# Later invocations use the same canonical, checked host path.
with open("/proc/self/exe", "rb") as stream:
    before = os.fstat(stream.fileno())
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = os.fstat(stream.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise SystemExit("Host interpreter changed during worker inspection")
observed = {"dev": before.st_dev, "ino": before.st_ino, "uid": before.st_uid,
            "mode": stat.S_IMODE(before.st_mode), "size": before.st_size, "sha256": digest}
if observed != json.loads(expected_host):
    raise SystemExit("Host interpreter identity mismatch")
fd = int(raw_fd)
guard = Path(kit) / "local-bridge/.venv-install.guard"
info = os.fstat(fd)
path = guard / "lock"
current = path.lstat()
assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1 and not info.st_mode & 0o077
assert (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino)
other = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
try:
    try:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        raise SystemExit("Maintenance lock not held")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
finally:
    os.close(other)
active = guard / "active.json"
st = active.lstat()
assert stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and st.st_nlink == 1 and not st.st_mode & 0o077 and st.st_size <= 16384
tx = json.loads(active.read_text())
assert tx["path"] == str(Path(kit) / "local-bridge/.venv") and tx["sha"] == sha and tx["wheel"] == (wheel or None)
assert tx["phase"] == "writing" and tx["group"] == os.getpgrp() and tx["boot"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
PY
{ [ "$#" -eq 1 ] || [ "$#" -eq 2 ]; } && [[ "$1" =~ ^[0-9a-f]{40}$ ]] || { echo 'Usage: install.sh REVIEWED_FULL_SHA [EXPECTED_WHEEL_SHA256]' >&2; exit 1; }
expected_wheel="${2-}"
if [ "$#" -eq 2 ] && ! [[ "$expected_wheel" =~ ^[0-9a-f]{64}$ ]]; then
  echo 'Invalid expected wheel digest.' >&2; exit 1
fi
[ "$(git -C "$KIT" rev-parse HEAD)" = "$1" ] || { echo 'HEAD mismatch.' >&2; exit 1; }
[ "$(git -C "$KIT" config --local --get remote.origin.url)" = https://github.com/codefusion-repo/project-os-v3.git ] || { echo 'Unexpected origin.' >&2; exit 1; }
checkout_status="$(git -C "$KIT" status --porcelain --untracked-files=normal)"
[ -z "$checkout_status" ] || { echo 'Dirty checkout; preserved.' >&2; exit 1; }
"$host_python" -I -c 'import sys,platform; sys.exit(not (sys.version_info[:2]==(3,12) and sys.platform=="linux" and platform.machine()=="x86_64"))'
VENV="$KIT/local-bridge/.venv"
if [ -e "$VENV" ] || [ -L "$VENV" ]; then
  echo 'Existing bridge environment preserved. Use the reviewed upgrade runbook for maintenance.' >&2
  exit 1
fi
# Create at final path (venv entrypoints are not relocatable).
# Do not execute the host's unreviewed bundled pip from ensurepip.
"$host_python" -I - "$VENV" <<'PY'
import os, sys
os.mkdir(sys.argv[1],0o700)
PY
"$host_python" -I -m venv --without-pip "$VENV"
work="$(mktemp -d /tmp/project-os-install.XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT
mkdir "$work/wheels" "$work/source" "$work/source-repeat" "$work/home" "$work/project-wheel" "$work/project-repeat"
source_epoch="$(git -C "$KIT" show -s --format=%ct "$1")"
if ! [[ "$source_epoch" =~ ^[0-9]+$ ]] || [ "$source_epoch" -lt 315532800 ]; then
  echo "Invalid source timestamp" >&2; exit 1
fi
# Build and test from the reviewed Git tree, not ignored files in the checkout.
git -C "$KIT" archive "$1" local-bridge | tar -xf - -C "$work/source"
source_dir="$work/source/local-bridge"
source "$source_dir/scripts/bootstrap.sh"
bootstrap_install "$VENV/bin/python" "$work/wheels" "$source_dir" "$work/home"
clean=(env -i PATH="$VENV/bin:/usr/bin:/bin" HOME="$work/home" LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH="$source_epoch" PIP_CONFIG_FILE=/dev/null)
pip_run() {
  "${clean[@]}" "$VENV/bin/python" -I -m pip --isolated --disable-pip-version-check --no-input --no-cache-dir "$@"
}
pip_run --version
pip_run download --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r "$source_dir/requirements-linux-py312.lock" -r "$source_dir/requirements-build.lock" -d "$work/wheels"
pip_run install --no-index --find-links "$work/wheels" --only-binary=:all: --require-hashes -r "$source_dir/requirements-linux-py312.lock" -r "$source_dir/requirements-build.lock"
# Independent source trees, same reviewed commit and deterministic build inputs.
git -C "$KIT" archive "$1" local-bridge | tar -xf - -C "$work/source-repeat"
pip_run wheel --no-index --no-build-isolation --no-deps "$source_dir" -w "$work/project-wheel"
pip_run wheel --no-index --no-build-isolation --no-deps "$work/source-repeat/local-bridge" -w "$work/project-repeat"
"$VENV/bin/python" -I "$source_dir/scripts/wheel_identity.py" "$work/project-wheel" "$work/project-repeat"
project_wheels=("$work/project-wheel/"*.whl)
[ "${#project_wheels[@]}" = 1 ]
wheel_sha="$("$VENV/bin/python" -I -c 'import hashlib,sys; print(hashlib.file_digest(open(sys.argv[1],"rb"),"sha256").hexdigest())' "${project_wheels[0]}")"
if [ -n "$expected_wheel" ] && [ "$wheel_sha" != "$expected_wheel" ]; then
  echo 'Expected project wheel digest mismatch.' >&2; exit 1
fi
pip_run install --no-index --no-deps "${project_wheels[0]}"
pip_run check
"$VENV/bin/python" -I -m unittest discover -s "$source_dir/tests" -v
# A receipt is evidence of this successful installation, not a signature or
# a substitute for reviewed Git/CI and host provenance.
"$VENV/bin/python" -I - "$VENV" "$1" "$wheel_sha" <<'PY'
import json, os, sys
from pathlib import Path
path = Path(sys.argv[1]) / ".project-os-bridge-install.json"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as stream:
    json.dump({"sha": sys.argv[2], "wheel_sha256": sys.argv[3]}, stream)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
PY
printf '%s\n' 'BRIDGE BUILD PASS; coordinator validation pending.'
