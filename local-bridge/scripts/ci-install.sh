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
python3 -I -m venv --without-pip "$RUNNER_TEMP/bootstrap-audit"
"$venv/bin/python" -I -m pip --isolated --python "$RUNNER_TEMP/bootstrap-audit/bin/python" install --index-url https://pypi.org/simple pip-audit==2.10.1
"$RUNNER_TEMP/bootstrap-audit/bin/python" -I -m pip_audit --no-deps --disable-pip --strict -r "$RUNNER_TEMP/bootstrap-audit.txt"
echo 'BOOTSTRAP_AUDIT_PASS'
