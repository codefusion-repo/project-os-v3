#!/usr/bin/env bash
# CI-only tests against a disposable checkout. Never run against the operator's kit.
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${GITHUB_SHA:-}" ] || exit 1
cd -- "$(dirname -- "$0")/../.."
[ "$(git rev-parse HEAD)" = "$GITHUB_SHA" ]
[ -z "$(git status --porcelain --untracked-files=normal)" ]
[ ! -e local-bridge/.venv ] && [ ! -L local-bridge/.venv ]
# actions/checkout may use the canonical HTTPS URL without the .git suffix.
origin="$(git config --local --get remote.origin.url)"
case "$origin" in
  https://github.com/codefusion-repo/project-os-v3|https://github.com/codefusion-repo/project-os-v3.git) ;;
  *) echo 'Unexpected CI origin' >&2; exit 1 ;;
esac
git config --local remote.origin.url https://github.com/codefusion-repo/project-os-v3.git
install=local-bridge/scripts/install.sh
expect_block() {
  local reason="$1"; shift
  local output
  if output="$(bash "$install" "$@" 2>&1)"; then
    echo 'Unexpected installer success' >&2; exit 1
  fi
  [[ "$output" == *"$reason"* ]] || { echo 'Unexpected rejection reason' >&2; exit 1; }
  printf 'NEGATIVE PASS: %s\n' "$reason"
}
wrong=0000000000000000000000000000000000000000
expect_block 'HEAD mismatch.' "$wrong"
[ ! -e local-bridge/.venv ]
# Only a new, untracked sentinel owned by this disposable test is removed.
sentinel="$(mktemp ./ci-dirty.XXXXXXXX)"
expect_block 'Dirty checkout; preserved.' "$GITHUB_SHA"
[ -f "$sentinel" ]
rm -- "$sentinel"
[ ! -e local-bridge/.venv ]
PIP_INDEX_URL=http://127.0.0.1:1 PIP_EXTRA_INDEX_URL=http://127.0.0.1:1 PIP_REQUIRE_VIRTUALENV=false bash "$install" "$GITHUB_SHA"
venv=local-bridge/.venv
for cli in project-os-bridge project-os-bridge-http project-os-bridge-fixture project-os-bridge-init; do
  "$venv/bin/$cli" --help >/dev/null
done
"$venv/bin/python" -I - <<'PY'
from importlib.metadata import distributions
from pathlib import Path
import re
norm=lambda s: re.sub(r'[-_.]+','-',s).lower()
expected={}
for file in ('requirements-linux-py312.lock','requirements-build.lock','requirements-bootstrap.lock'):
    for line in (Path('local-bridge')/file).read_text().splitlines():
        if not line or line.startswith('#'): continue
        name,version=line.split()[0].split('==')
        expected[norm(name)]=version
actual={norm(d.metadata['Name']): d.version for d in distributions()}
assert set(actual)==set(expected)|{'project-os-local-bridge'}, 'Unexpected installed distribution set'
assert all(actual[name]==version for name,version in expected.items()), 'Installed version mismatch'
print('INSTALLED LOCK CLOSURE PASS')
PY
before="$(sha256sum "$venv/pyvenv.cfg")"
expect_block 'Existing bridge environment preserved.' "$GITHUB_SHA"
[ "$before" = "$(sha256sum "$venv/pyvenv.cfg")" ]
[ -z "$(git status --porcelain --untracked-files=normal)" ]
echo 'CI INSTALL AND NEGATIVE CONTROLS PASS'
# Compare installed retained source files with the exact publishing commit
# recorded by PyPI. Data only: never import or execute downloaded source.
upstream=191854fba83d1c69534f974564af85632372d995
source_check="$(mktemp -d "$RUNNER_TEMP/bootstrap-source.XXXXXXXX")"
mkdir "$source_check/pkg_resources"
for member in vendor.txt pkg_resources/LICENSE pkg_resources/__init__.py; do
  env -i PATH=/usr/bin:/bin HOME="$source_check" LC_ALL=C curl --disable --fail --silent --show-error --proto '=https' --noproxy '*' --max-time 60 --max-filesize 1000000 -o "$source_check/$member" "https://raw.githubusercontent.com/pypa/pip/$upstream/src/pip/_vendor/$member"
done
"$venv/bin/python" -I - "$source_check" <<'PY'
import hashlib, importlib.util, sys
from pathlib import Path
root = Path(importlib.util.find_spec("pip").origin).parent / "_vendor"
source = Path(sys.argv[1])
for name in ("vendor.txt", "pkg_resources/LICENSE", "pkg_resources/__init__.py"):
    data = (root / name).read_bytes()
    if data != (source / name).read_bytes():
        raise SystemExit("Upstream source mismatch")
    print("BOOTSTRAP_UPSTREAM_MATCH", name, hashlib.sha256(data).hexdigest())
PY

# Audit the actual installed pip and its declared vendored packages separately.
"$venv/bin/python" -I - "$RUNNER_TEMP/bootstrap-audit.txt" <<'PY'
import importlib.metadata as m, pathlib, re, sys, pip
vendor = pathlib.Path(pip.__file__).parent / '_vendor' / 'vendor.txt'
pins = [s.strip() for s in vendor.read_text().splitlines() if s.strip() and not s.lstrip().startswith('#')]
assert len(pins) >= 10 and all(re.fullmatch(r'[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+', p) for p in pins)
pins.insert(0, 'pip==' + m.version('pip'))
pathlib.Path(sys.argv[1]).write_text('\n'.join(pins)+'\n')
print('BOOTSTRAP_VENDOR_INVENTORY', ', '.join(pins))
PY
# Fixed and verified auditor closure, never install unlocked packages.
audit_dir="$(mktemp -d "$RUNNER_TEMP/audit-wheels.XXXXXXXX")"
audit_pins=local-bridge/requirements-audit.txt
audit_lock=local-bridge/requirements-audit.lock
[ -f "$audit_lock" ] || { echo 'Required auditor lock missing'; exit 1; }
mkdir "$audit_dir/home"
clean=(env -i PATH=/usr/bin:/bin HOME="$audit_dir/home" LC_ALL=C PIP_CONFIG_FILE=/dev/null)
"${clean[@]}" "$venv/bin/python" -I -m pip --isolated --disable-pip-version-check --no-cache-dir download --index-url https://pypi.org/simple --only-binary=:all: --require-hashes --no-deps -r "$audit_lock" -d "$audit_dir"
python3 -I local-bridge/scripts/lock_wheels.py "$audit_pins" "$audit_dir" > "$RUNNER_TEMP/audit-candidate.lock"
diff -u <(grep -v '^#' "$audit_lock") "$RUNNER_TEMP/audit-candidate.lock"
python3 -I -m venv --without-pip "$RUNNER_TEMP/bootstrap-audit"
"${clean[@]}" "$venv/bin/python" -I -m pip --isolated --disable-pip-version-check --python "$RUNNER_TEMP/bootstrap-audit/bin/python" install --no-index --find-links "$audit_dir" --only-binary=:all: --require-hashes -r "$audit_lock"
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
  local name="$1" pins="$2" report="$RUNNER_TEMP/$1.json" rc=0
  "${clean[@]}" "$auditor" -I -m pip_audit --no-deps --disable-pip --strict -r "$pins" --format json --output "$report" || rc=$?
  [ -s "$report" ] || { echo "Missing strict report: $name"; return 1; }
  echo "RAW_AUDIT_BEGIN $name"
  cat "$report" || return 1
  echo
  echo "RAW_AUDIT_END $name"
  echo "STRICT_AUDIT_EXIT $name=$rc"
  python3 -I local-bridge/scripts/audit_report.py "$pins" "$report" "$rc" || return 1
  return "$rc"
}
tool_rc=0
strict_audit auditor-dependencies "$audit_pins" || tool_rc=$?
vendor_rc=0
strict_audit bootstrap-vendors "$RUNNER_TEMP/bootstrap-audit.txt" || vendor_rc=$?
if [ "$tool_rc" -ne 0 ] || [ "$vendor_rc" -ne 0 ]; then
  exit 1
fi
echo 'BOOTSTRAP_AUDIT_PASS'
