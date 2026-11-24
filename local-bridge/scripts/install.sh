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
python3 - "$VENV" <<'PY'
import os, sys
os.mkdir(sys.argv[1],0o700)
PY
python3 -I -m venv "$VENV"
"$VENV/bin/python" -I -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r "$KIT/local-bridge/requirements-linux-py312.lock"
"$VENV/bin/python" -I -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r "$KIT/local-bridge/requirements-build.lock"
"$VENV/bin/python" -I -m pip --isolated install --no-index --no-build-isolation --no-deps "$KIT/local-bridge"
"$VENV/bin/python" -I -m pip check
"$VENV/bin/python" -I -m unittest discover -s "$KIT/local-bridge/tests" -v
printf '%s\n' 'BRIDGE INSTALL PASS; existing wizard available; no service started.'
