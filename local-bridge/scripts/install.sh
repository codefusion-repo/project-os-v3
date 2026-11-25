#!/usr/bin/env bash
# Public first-install entrypoint. All writers use the same coordinator.
set -euo pipefail
umask 077
{ [ "$#" -eq 1 ] || [ "$#" -eq 2 ]; } || { echo 'Usage: install.sh REVIEWED_FULL_SHA [EXPECTED_WHEEL_SHA256]' >&2; exit 1; }
KIT="$(cd -- "$(dirname -- "$0")/../.." && pwd -P)"
args=(install "$1")
if [ "$#" -eq 2 ]; then args+=(--expected-wheel "$2"); fi
exec python3 -I "$KIT/local-bridge/scripts/upgrade.py" "${args[@]}"
