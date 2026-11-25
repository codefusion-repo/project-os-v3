#!/usr/bin/env bash
# CI-only common auditor for the bootstrap, runtime and build backend.
set -euo pipefail
umask 077
[ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${GITHUB_SHA:-}" ] || exit 1
cd -- "$(dirname -- "$0")/../.."
[ "$(git rev-parse HEAD)" = "$GITHUB_SHA" ]
[ "$#" = 3 ]
bootstrap_python="$1"
target_name="$2"
target_pins="$3"
case "$target_name" in bootstrap-vendors|runtime-dependencies|build-backend) ;; *) exit 1 ;; esac
[ -x "$bootstrap_python" ] && [ -f "$target_pins" ] || exit 1
# Fixed and verified auditor closure, never install unlocked packages.
audit_dir="$(mktemp -d "$RUNNER_TEMP/audit-wheels.XXXXXXXX")"
audit_pins=local-bridge/requirements-audit.txt
audit_lock=local-bridge/requirements-audit.lock
[ -f "$audit_lock" ] || { echo 'Required auditor lock missing'; exit 1; }
mkdir "$audit_dir/home"
clean=(env -i PATH=/usr/bin:/bin HOME="$audit_dir/home" LC_ALL=C PIP_CONFIG_FILE=/dev/null)
"${clean[@]}" "$bootstrap_python" -I -m pip --isolated --disable-pip-version-check --no-cache-dir download --index-url https://pypi.org/simple --only-binary=:all: --require-hashes --no-deps -r "$audit_lock" -d "$audit_dir"
python3 -I local-bridge/scripts/lock_wheels.py "$audit_pins" "$audit_dir" > "$RUNNER_TEMP/audit-candidate.lock"
diff -u <(grep -v '^#' "$audit_lock") "$RUNNER_TEMP/audit-candidate.lock"
python3 -I -m venv --without-pip "$RUNNER_TEMP/bootstrap-audit"
"${clean[@]}" "$bootstrap_python" -I -m pip --isolated --disable-pip-version-check --python "$RUNNER_TEMP/bootstrap-audit/bin/python" install --no-index --find-links "$audit_dir" --only-binary=:all: --require-hashes -r "$audit_lock"
auditor="$RUNNER_TEMP/bootstrap-audit/bin/python"
"${clean[@]}" "$auditor" -I -m pip check
"$auditor" -I - "$audit_pins" <<'PY'
from importlib.metadata import distributions
from pathlib import Path
import re, sys
norm=lambda s: re.sub(r'[-_.]+','-',s).lower()
expected=dict(line.split("==") for line in Path(sys.argv[1]).read_text().splitlines() if line and not line.startswith("#"))
actual=[(norm(d.metadata["Name"]),d.version) for d in distributions()]
if len(actual)!=len(dict(actual)) or dict(actual)!=expected:
    raise SystemExit("Auditor dependency closure mismatch")
print("AUDITOR_LOCK_CLOSURE_PASS",len(actual))
PY
"$auditor" -I -m pip_audit --version
python3 -I -c 'import platform,ssl,sys; print("HOST_TRUST_INPUTS",sys.version.split()[0],platform.platform(),ssl.OPENSSL_VERSION)'
git --version
curl --version
strict_audit() {
  local name="$1" pins="$2" report="$audit_dir/$1.json" diagnostics="$audit_dir/$1.stderr" rc=0
  "${clean[@]}" "$auditor" -I -m pip_audit --no-deps --disable-pip --strict -r "$pins" --format json --output "$report" 2>"$diagnostics" || rc=$?
  cat "$diagnostics" || return 1
  echo "STRICT_AUDIT_EXIT $name=$rc"
  [ -s "$report" ] || { echo "Missing strict report: $name"; return 1; }
  echo "RAW_AUDIT_BEGIN $name"
  cat "$report" || return 1
  echo
  echo "RAW_AUDIT_END $name"
  python3 -I local-bridge/scripts/audit_report.py "$pins" "$report" "$rc" || return 1
  if [ "$name" = bootstrap-vendors ]; then
    # Separate, explicitly authorized artifact-specific evaluation; never change the raw report.
    local installed
    installed="$("$bootstrap_python" -I -c 'import importlib.util,pathlib; print(pathlib.Path(importlib.util.find_spec("pip").origin).parent)')" || return 1
    python3 -I local-bridge/scripts/bootstrap_applicability.py "$audit_dir/pip-26.3-py3-none-any.whl" local-bridge/requirements-bootstrap.lock "$installed" "$pins" "$report" "$diagnostics" "$rc" || return 1
    return 0
  fi
  return "$rc"
}
tool_rc=0
strict_audit auditor-dependencies "$audit_pins" || tool_rc=$?
vendor_rc=0
strict_audit "$target_name" "$target_pins" || vendor_rc=$?
if [ "$tool_rc" -ne 0 ] || [ "$vendor_rc" -ne 0 ]; then
  exit 1
fi
echo "LOCKED_AUDIT_PASS $target_name"
