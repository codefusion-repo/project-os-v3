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
# Public installer must reject a writable host interpreter parent before any
# venv or active transaction is created, even if the executable itself is safe.
bad_python="$(mktemp -d "$RUNNER_TEMP/bridge-untrusted-python.XXXXXXXX")"
ln -s "$(command -v python3)" "$bad_python/python3"
chmod 0777 "$bad_python"
PATH="$bad_python:$PATH" expect_block 'BRIDGE INTERPRETER REJECTED: Unsafe host interpreter parent' "$GITHUB_SHA"
unlink "$bad_python/python3"
rmdir "$bad_python"
[ ! -e local-bridge/.venv ] && [ ! -L local-bridge/.venv ]
[ ! -e local-bridge/.venv-install.guard/active.json ] && [ ! -L local-bridge/.venv-install.guard/active.json ]
echo 'HOST INTERPRETER PREFLIGHT NEGATIVE PASS'
# Directory aliases must not hide an unsafe lexical parent. Establish that
# the identical alias is accepted while its origin remains trusted.
bad_alias="$(mktemp -d "$RUNNER_TEMP/bridge-directory-alias.XXXXXXXX")"
ln -s /usr/bin "$bad_alias/bin"
python3 -I -B - "$bad_alias/bin/python3" <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("upgrade", Path("local-bridge/scripts/upgrade.py"))
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)
host = upgrade.host_interpreter_identity(Path(sys.argv[1]))
assert host["resolved"] == "host:" + str(Path("/usr/bin/python3").resolve(strict=True))
PY
chmod 0777 "$bad_alias"
PATH="$bad_alias/bin:$PATH" expect_block 'BRIDGE INTERPRETER REJECTED: Unsafe host interpreter parent' "$GITHUB_SHA"
unlink "$bad_alias/bin"
rmdir "$bad_alias"
[ ! -e local-bridge/.venv ] && [ ! -L local-bridge/.venv ]
[ ! -e local-bridge/.venv-install.guard/active.json ] && [ ! -L local-bridge/.venv-install.guard/active.json ]
echo 'HOST DIRECTORY ALIAS PREFLIGHT NEGATIVE PASS'
PIP_INDEX_URL=http://127.0.0.1:1 PIP_EXTRA_INDEX_URL=http://127.0.0.1:1 PIP_REQUIRE_VIRTUALENV=false bash "$install" "$GITHUB_SHA"
venv=local-bridge/.venv
# Check the actual installed interpreter, not a substitute executable, and
# prove the public coordinator completed its durable transaction.
python3 -I -B - <<'PY'
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("upgrade", Path("local-bridge/scripts/upgrade.py"))
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)
host = upgrade.host_interpreter_identity()
kit = Path.cwd()
installed = upgrade.identity(kit / "local-bridge/.venv")["interpreter"]
for key in ("dev", "ino", "uid", "mode", "size", "sha256"):
    assert host[key] == installed[key], key
with upgrade.checkout_guard(kit) as (guard, fd):
    assert not (guard / upgrade.ACTIVE).exists()
    assert not (guard / upgrade.ACTIVE).is_symlink()
    assert not (guard.parent / upgrade.BACKUP).exists()
    assert not (guard.parent / upgrade.BACKUP).is_symlink()
print("PUBLIC_INSTALL_TRANSACTION_PASS", "interpreter_sha256=" + host["sha256"])
PY
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
"$venv/bin/python" -I - "$GITHUB_SHA" <<'PY'
import json, re, sys
from pathlib import Path
receipt = json.loads(Path("local-bridge/.venv/.project-os-bridge-install.json").read_text())
assert set(receipt) == {"sha", "wheel_sha256"} and receipt["sha"] == sys.argv[1]
assert re.fullmatch(r"[0-9a-f]{64}", receipt["wheel_sha256"])
print("INSTALL_RECEIPT_PASS")
PY
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
bash local-bridge/scripts/ci-locked-audit.sh "$venv/bin/python" bootstrap-vendors "$RUNNER_TEMP/bootstrap-audit.txt"
echo 'BOOTSTRAP_AUDIT_PASS'
