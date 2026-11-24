#!/usr/bin/env bash
# Explicit optional bridge installation, no system changes or service activation.
set -euo pipefail
umask 077
[ "$(id -u)" -ne 0 ] || { echo 'Run as an unprivileged operator.' >&2; exit 1; }
[ "$#" -eq 1 ] && [[ "$1" =~ ^[0-9a-f]{40}$ ]] || { echo 'Usage: install.sh REVIEWED_FULL_SHA' >&2; exit 1; }
KIT="$(cd -- "$(dirname -- "$0")/../.." && pwd -P)"
[ "$(git -C "$KIT" rev-parse HEAD)" = "$1" ] || { echo 'HEAD mismatch.' >&2; exit 1; }
[ "$(git -C "$KIT" config --local --get remote.origin.url)" = https://github.com/codefusion-repo/project-os-v3.git ] || { echo 'Unexpected origin.' >&2; exit 1; }
[ -z "$(git -C "$KIT" status --porcelain --untracked-files=normal)" ] || { echo 'Dirty checkout; preserved.' >&2; exit 1; }
python3 -I -c 'import sys,platform; sys.exit(not (sys.version_info[:2]==(3,12) and sys.platform=="linux" and platform.machine()=="x86_64"))'
VENV="$KIT/local-bridge/.venv"
if [ -e "$VENV" ] || [ -L "$VENV" ]; then
  echo 'Existing bridge environment preserved. Use a fresh reviewed checkout for independent installation.' >&2
  exit 1
fi
# Create at final path (venv entrypoints are not relocatable).
# Do not execute the host's unreviewed bundled pip from ensurepip.
python3 -I - "$VENV" <<'PY'
import os, sys
os.mkdir(sys.argv[1],0o700)
PY
python3 -I -m venv --without-pip "$VENV"
work="$(mktemp -d /tmp/project-os-install.XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT
mkdir "$work/wheels" "$work/source" "$work/home"
# Build and test from the reviewed Git tree, not ignored files in the checkout.
git -C "$KIT" archive "$1" local-bridge | tar -xf - -C "$work/source"
source_dir="$work/source/local-bridge"
wheel="$work/wheels/pip-26.3-py3-none-any.whl"
curl --disable --fail --silent --show-error --proto '=https' --noproxy '*' --max-time 120 --max-filesize 5000000 -o "$wheel" 'https://files.pythonhosted.org/packages/07/25/ee8c38ae72d66b844ce8eb9711ba905dba21ca1a8a0c960057c41cd23337/pip-26.3-py3-none-any.whl'
# Verify bytes before importing ANY code from the downloaded wheel.
"$VENV/bin/python" -I "$source_dir/scripts/bootstrap_verify.py" "$wheel" "$source_dir/requirements-bootstrap.lock"
clean=(env -i PATH="$VENV/bin:/usr/bin:/bin" HOME="$work/home" LC_ALL=C PIP_CONFIG_FILE=/dev/null)
"${clean[@]}" "$VENV/bin/python" -I -c 'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("pip",run_name="__main__")' "$wheel" --isolated --disable-pip-version-check --no-input --no-cache-dir install --no-index --find-links "$work/wheels" --only-binary=:all: --require-hashes --no-deps -r "$source_dir/requirements-bootstrap.lock"
pip_run() {
  "${clean[@]}" "$VENV/bin/python" -I -m pip --isolated --disable-pip-version-check --no-input --no-cache-dir "$@"
}
pip_run --version
pip_run download --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r "$source_dir/requirements-linux-py312.lock" -r "$source_dir/requirements-build.lock" -d "$work/wheels"
pip_run install --no-index --find-links "$work/wheels" --only-binary=:all: --require-hashes -r "$source_dir/requirements-linux-py312.lock" -r "$source_dir/requirements-build.lock"
pip_run install --no-index --no-build-isolation --no-deps "$source_dir"
pip_run check
"$VENV/bin/python" -I -m unittest discover -s "$source_dir/tests" -v
printf '%s\n' 'BRIDGE INSTALL PASS; existing wizard available; no service started.'
