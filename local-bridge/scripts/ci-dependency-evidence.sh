#!/usr/bin/env bash
# Separate hosted-runner evidence, no host ensurepip or floating auditor install.
set -euo pipefail
umask 077
[ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${GITHUB_SHA:-}" ] || exit 1
cd -- "$(dirname -- "$0")/../.."
[ "$(git rev-parse HEAD)" = "$GITHUB_SHA" ]
checkout_status="$(git status --porcelain --untracked-files=normal)"
[ -z "$checkout_status" ]
[ "$#" = 1 ]
mode="$1"
case "$mode" in
  runtime) lock=local-bridge/requirements-linux-py312.lock; target=runtime-dependencies ;;
  build) lock=local-bridge/requirements-build.lock; target=build-backend ;;
  *) exit 1 ;;
esac
work="$(mktemp -d "$RUNNER_TEMP/dependency-chain.XXXXXXXX")"
mkdir "$work/source" "$work/bootstrap" "$work/home" "$work/wheels" "$work/project-wheel"
git archive "$GITHUB_SHA" local-bridge | tar -xf - -C "$work/source"
source_dir="$work/source/local-bridge"
python3 -I -m venv --without-pip "$work/venv"
python="$work/venv/bin/python"
source "$source_dir/scripts/bootstrap.sh"
bootstrap_install "$python" "$work/bootstrap" "$source_dir" "$work/home"
source_epoch="$(git show -s --format=%ct "$GITHUB_SHA")"
if ! [[ "$source_epoch" =~ ^[0-9]+$ ]] || [ "$source_epoch" -lt 315532800 ]; then exit 1; fi
clean=(env -i PATH=/usr/bin:/bin HOME="$work/home" LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH="$source_epoch" PIP_CONFIG_FILE=/dev/null)
pip_run() {
  "${clean[@]}" "$python" -I -m pip --isolated --disable-pip-version-check --no-input --no-cache-dir "$@"
}
pip_run download --index-url https://pypi.org/simple --only-binary=:all: --require-hashes --no-deps -r "$lock" -d "$work/wheels"
grep -v '^#' "$lock" | cut -d ' ' -f1 > "$work/pins.txt"
python3 -I local-bridge/scripts/lock_wheels.py "$work/pins.txt" "$work/wheels" > "$work/candidate.lock"
diff -u <(grep -v '^#' "$lock") "$work/candidate.lock"
pip_run install --no-index --find-links "$work/wheels" --only-binary=:all: --require-hashes -r "$lock"
pip_run check
"$python" -I - "$work/pins.txt" local-bridge/requirements-bootstrap.lock <<'PY'
from importlib.metadata import distributions
from pathlib import Path
import re,sys
norm=lambda s:re.sub(r'[-_.]+','-',s).lower()
expected={}
for path in sys.argv[1:]:
    for line in Path(path).read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            name,version=line.split()[0].split("==")
            key=norm(name)
            if key in expected:
                raise SystemExit("Duplicate lock entry")
            expected[key]=version
actual=[(norm(d.metadata["Name"]),d.version) for d in distributions()]
if len(actual)!=len(dict(actual)) or dict(actual)!=expected:
    raise SystemExit("Dependency closure mismatch")
print("DEPENDENCY_CHAIN_CLOSURE_PASS",len(actual))
PY
if [ "$mode" = build ]; then
  pip_run wheel --no-index --no-build-isolation --no-deps "$source_dir" -w "$work/project-wheel"
  wheels=("$work/project-wheel/"*.whl)
  [ "${#wheels[@]}" = 1 ] && [ -f "${wheels[0]}" ] || exit 1
  sha256sum "${wheels[0]}"
fi
bash local-bridge/scripts/ci-locked-audit.sh "$python" "$target" "$work/pins.txt"
