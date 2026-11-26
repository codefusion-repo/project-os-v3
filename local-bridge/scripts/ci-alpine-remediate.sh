#!/usr/bin/env bash
# Disposable GitHub runner only. Never publish an image to a registry.
set -euo pipefail
umask 077
[ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${RUNNER_TEMP:-}" ] || exit 1
[ "$(id -u)" != 0 ] && [ "$(uname -m)" = x86_64 ] || exit 1
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
repo="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
work="$(mktemp -d "$RUNNER_TEMP/alpine-remediation.XXXXXXXX")"
context_parent=
trap 'rm -rf -- "$work"; if [ -n "$context_parent" ]; then rm -rf -- "$context_parent"; fi' EXIT
mkdir "$work/packages" "$work/context" "$work/home" "$work/cache" "$work/state"
# Only public-image scanner evidence; no container bytes, state or credentials.
evidence_dir="$RUNNER_TEMP/lb-oci-evidence"
mkdir "$evidence_dir"
base=docker.io/library/python@sha256:a61cbd76a882645de7f91423329fe43a67eed60d7da24f9e5331414bb3618b20
package=krb5-libs-1.22.3-r0.apk
url="https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/$package"
lock="$repo/local-bridge/scripts/alpine-krb5.sha256"
tag=localhost/project-os-alpine-ci:candidate
mode="${1:-baseline}"
[[ "$#" -le 1 && ( "$mode" = baseline || "$mode" = residual || "$mode" = fixture-only ) ]] || exit 1
manifest_lock="$repo/local-bridge/scripts/alpine-manifest.sha256"
if [ "$mode" != baseline ]; then
  manifest_lock="$repo/local-bridge/scripts/alpine-$mode-manifest.sha256"
fi
[ -f "$manifest_lock" ] || { echo "Required manifest lock missing" >&2; exit 1; }
podman info --format json | python3 -c 'import json,sys; h=json.load(sys.stdin)["host"]; assert h["security"]["rootless"] and h["security"]["seccompEnabled"] and h["cgroupVersion"]=="v2"'
podman --version
python3 -m unittest discover -s "$repo/local-bridge/scripts" -p test_oci_repro.py -v
python3 -m unittest discover -s "$repo/local-bridge/scripts" -p test_alpine_findings.py -v
python3 -m unittest discover -s "$repo/local-bridge/scripts" -p test_oci_control.py -v
podman pull --platform linux/amd64 "$base"
[ "$(podman image inspect --format '{{.Digest}}' "$base")" = "${base##*@}" ]
# All package acquisition is HTTPS; signature is verified using keys in the pinned base.
curl --fail --silent --show-error --proto '=https' --max-time 120 -o "$work/packages/$package" "$url"
chmod 0444 "$work/packages/$package"
podman run --rm --pull=never --network=none --http-proxy=false --volume "$work/packages:/packages:ro" --entrypoint /sbin/apk "$base" verify "/packages/$package"
(cd "$work/packages" && sha256sum "$package") > "$work/observed.sha256"
cat "$work/observed.sha256"
diff -u "$lock" "$work/observed.sha256"
echo 'APK_LOCK_VERIFIED'
if [ "$mode" != baseline ]; then
  extras=(libcrypto3-3.5.9-r1.apk libssl3-3.5.9-r1.apk zlib-1.4-r0.apk)
  for extra in "${extras[@]}"; do
    curl --fail --silent --show-error --proto '=https' --max-time 120 -o "$work/packages/$extra" "https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/$extra"
    chmod 0444 "$work/packages/$extra"
    podman run --rm --pull=never --network=none --http-proxy=false --volume "$work/packages:/packages:ro" --entrypoint /sbin/apk "$base" verify "/packages/$extra"
  done
  (cd "$work/packages" && sha256sum "${extras[@]}") > "$work/extras.sha256"
  cat "$work/extras.sha256"
  diff -u "$repo/local-bridge/scripts/alpine-residual-apks.sha256" "$work/extras.sha256"
  echo RESIDUAL_APK_LOCK_VERIFIED
fi
if [ "$mode" = residual ]; then
  cp "$repo/local-bridge/scripts/alpine-residual-pip.lock" "$work/packages/pip.lock"
  python3 -m pip --isolated download --index-url https://pypi.org/simple --only-binary=:all: --no-deps --require-hashes -r "$work/packages/pip.lock" -d "$work/packages"
  chmod 0444 "$work/packages/pip.lock" "$work/packages/pip-26.2-py3-none-any.whl"
fi
podman run --rm --pull=never --network=none --entrypoint /sbin/apk "$base" --no-network --repositories-file /dev/null info -v | LC_ALL=C sort > "$work/before"
grep -Fxq krb5-libs-1.22.2-r1 "$work/before"
sed 's/^krb5-libs-1\.22\.2-r1$/krb5-libs-1.22.3-r0/' "$work/before" | LC_ALL=C sort > "$work/expected"
if [ "$mode" != baseline ]; then
  for version in libcrypto3-3.5.9-r0 libssl3-3.5.9-r0 zlib-1.3.2-r1; do grep -Fxq "$version" "$work/before"; done
  sed -i -e 's/^libcrypto3-3\.5\.9-r0$/libcrypto3-3.5.9-r1/' -e 's/^libssl3-3\.5\.9-r0$/libssl3-3.5.9-r1/' -e 's/^zlib-1\.3\.2-r1$/zlib-1.4-r0/' "$work/expected"
  LC_ALL=C sort -o "$work/expected" "$work/expected"
fi
cat > "$work/context/Containerfile" <<'BUILD'
FROM docker.io/library/python@sha256:a61cbd76a882645de7f91423329fe43a67eed60d7da24f9e5331414bb3618b20
RUN apk verify /packages/krb5-libs-1.22.3-r0.apk && apk add --logfile=no --no-network --no-cache --repositories-file /dev/null /packages/krb5-libs-1.22.3-r0.apk
BUILD
if [ "$mode" != baseline ]; then
  cat >> "$work/context/Containerfile" <<'BUILD'
RUN apk verify /packages/libcrypto3-3.5.9-r1.apk /packages/libssl3-3.5.9-r1.apk /packages/zlib-1.4-r0.apk && apk add --logfile=no --no-network --no-cache --repositories-file /dev/null /packages/libcrypto3-3.5.9-r1.apk /packages/libssl3-3.5.9-r1.apk /packages/zlib-1.4-r0.apk
BUILD
fi
if [ "$mode" = residual ]; then
  cat >> "$work/context/Containerfile" <<'BUILD'
RUN PYTHONDONTWRITEBYTECODE=1 python -B -m pip --isolated install --no-index --find-links=/packages --no-deps --no-compile --no-cache-dir --disable-pip-version-check --require-hashes -r /packages/pip.lock
BUILD
elif [ "$mode" = fixture-only ]; then
  cat >> "$work/context/Containerfile" <<'BUILD'
# The fixed fixture only executes stdlib Python. Remove actual package-manager code and bootstrap, not just scanner metadata.
RUN python -I -B -m pip --isolated uninstall -y setuptools pip && python -I -B -c 'import ensurepip, pathlib, shutil; shutil.rmtree(pathlib.Path(ensurepip.__file__).parent)' && python -I -B -c 'import importlib.util as u; assert all(u.find_spec(n) is None for n in ("pip", "setuptools", "ensurepip"))'
BUILD
fi
# A nonzero fixed epoch reduces build-time metadata variation.
build_candidate() {
  podman build --pull=never --network=none --http-proxy=false --no-cache --timestamp 1700000000 --format oci --volume "$work/packages:/packages:ro" --tag "$1" "$work/context"
}
build_candidate "$tag"
# Force different wall-clock seconds, so a timestamp regression cannot pass by chance.
sleep 2
build_candidate localhost/project-os-alpine-ci:repeat
podman push --format oci --digestfile "$work/repeat-digest" localhost/project-os-alpine-ci:repeat "oci:$work/repeat-oci:candidate"
podman run --rm --pull=never --network=none --entrypoint /sbin/apk "$tag" --no-network --repositories-file /dev/null info -v | LC_ALL=C sort > "$work/after"
diff -u "$work/expected" "$work/after"
echo "APK_CLOSURE_PASS: $mode exact expected inventory"
# Export to an OCI layout on this runner, not a registry. Audit exactly this digest.
podman push --format oci --digestfile "$work/digest" "$tag" "oci:$work/oci:candidate"
digest="$(cat "$work/digest")"
repeat_digest="$(cat "$work/repeat-digest")"
python3 "$repo/local-bridge/scripts/oci_repro.py" "$work/oci" "$digest" "$work/repeat-oci" "$repeat_digest"
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]
python3 - "$repo/local-bridge/scripts" "$manifest_lock" "$digest" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from oci_repro import verify_expected
verify_expected(Path(sys.argv[2]).read_text().strip(), sys.argv[3])
print("OCI_MANIFEST_LOCK_VERIFIED", sys.argv[3])
PY
python3 - "$work/oci" "$digest" <<'PY'
import hashlib, json, sys
from pathlib import Path
root, digest = Path(sys.argv[1]), sys.argv[2]
index = json.loads((root / 'index.json').read_text())
assert len(index['manifests']) == 1 and index['manifests'][0]['digest'] == digest
manifest = (root / 'blobs' / 'sha256' / digest[7:]).read_bytes()
assert hashlib.sha256(manifest).hexdigest() == digest[7:]
data = json.loads(manifest)
for d in [data['config'], *data['layers']]:
    algorithm, value = d['digest'].split(':')
    assert algorithm == 'sha256'
    raw = (root / 'blobs' / algorithm / value).read_bytes()
    assert len(raw) == d['size'] and hashlib.sha256(raw).hexdigest() == value
print('OCI_LAYOUT_VERIFIED', digest)
PY
# The positive fixture imports the audited layout into its execution context after the scan.
image="${tag%:*}@$digest"
echo "CANDIDATE_MANIFEST $digest"
archive=trivy_0.76.2_Linux-64bit.tar.gz
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --max-time 180 -o "$work/$archive" "https://github.com/aquasecurity/trivy/releases/download/v0.76.2/$archive"
(cd "$work" && printf '%s  %s\n' bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf "$archive" | sha256sum -c - && tar -xzf "$archive" trivy)
scan_env=(env -i PATH=/usr/bin:/bin HOME="$work/home" LC_ALL=C)
scanner_rc=0
"${scan_env[@]}" "$work/trivy" --cache-dir "$work/cache" image --input "$work/oci@$digest" --platform linux/amd64 --scanners vuln --pkg-types os,library --ignorefile /dev/null --list-all-pkgs --no-progress --timeout 8m --format json --output "$work/report.json" || scanner_rc=$?
printf '%s\n' "$scanner_rc" > "$evidence_dir/scanner-exit.txt"
if [ -f "$work/report.json" ]; then
  cp -- "$work/report.json" "$evidence_dir/report.json"
  sha256sum "$evidence_dir/report.json"
fi
[ "$scanner_rc" = 0 ] || exit 1
[ -s "$evidence_dir/report.json" ] || exit 1
"${scan_env[@]}" "$work/trivy" --cache-dir "$work/cache" --version | tee "$evidence_dir/scanner-version.txt"
cp -- "$work/cache/db/metadata.json" "$evidence_dir/db-metadata.json"
# Review every finding against the public Alpine v3.24 secdb. Never change the scan gate.
for section in main community; do
  curl --fail --silent --show-error --proto '=https' --max-time 120 --max-filesize 10000000 -o "$work/$section.json" "https://secdb.alpinelinux.org/v3.24/$section.json"
done
python3 "$repo/local-bridge/scripts/alpine_findings.py" "$work/report.json" "$work/oci@$digest" "$work/main.json" "$work/community.json"
# Preserve audit result even if the compatibility checks fail, and vice versa.
audit=0
python3 - "$repo/local-bridge/scripts" "$work/report.json" "$work/oci@$digest" <<'PY' || audit=$?
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from oci_compare import summarize
r = summarize(json.loads(Path(sys.argv[2]).read_text()), sys.argv[3])
print('ALPINE_REMEDIATION_AUDIT', json.dumps(r, sort_keys=True))
raise SystemExit(r['candidate_gate'] == 'BLOCKED')
PY
printf '%s\n' "$audit" > "$evidence_dir/audit-exit.txt"
printf '%s\n' "$digest" > "$evidence_dir/manifest.txt"
if [ "$mode" != baseline ]; then
  python3 "$repo/local-bridge/scripts/oci_control.py" "$work/report.json" "$work/oci@$digest" "$digest" "$mode" "$work/after" "$scanner_rc" "$evidence_dir/db-metadata.json" | tee "$evidence_dir/control.txt"
fi
if [ "$mode" = residual ]; then
  # Success here is the negative test, not the vulnerable image audit.
  [ "$audit" = 1 ] || exit 1
  echo 'RESIDUAL_EXPECTED_REJECTION_PASS; candidate remains BLOCKED; no post-audit execution'
  exit 0
fi
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r "$repo/local-bridge/requirements-linux-py312.lock"
"$work/venv/bin/python" -m pip check
# Podman 4.9.3 limits runroot to 50 bytes. Keep the native execution root short.
context_parent="$(mktemp -d /tmp/lboci.XXXXXXXX)"
context="$context_parent/context"
runtime=(env "PYTHONPATH=$repo/local-bridge/src" "$work/venv/bin/python" -B)
"${runtime[@]}" -m project_os_bridge.podman_context --context "$context" prepare
[ "$("${runtime[@]}" -m project_os_bridge.podman_context --context "$context" import-layout "$work/oci" "$digest")" = "$image" ]
if [ "$mode" = fixture-only ]; then
  "${runtime[@]}" -m project_os_bridge.podman_context --context "$context" smoke "$image"
else
  "${runtime[@]}" - "$context" "$image" <<'PYSMOKE'
from pathlib import Path
import sys
from project_os_bridge.podman_context import PodmanContext
PodmanContext(Path(sys.argv[1])).smoke(sys.argv[2], fixture_only=False)
PYSMOKE
fi
fixture=0
PYTHONPATH="$repo/local-bridge/src" "$work/venv/bin/python" -m project_os_bridge.vertical --state-dir "$work/state" --request-key ci-alpine-remediation --image "$image" --podman-context "$context" > "$work/evidence.json" || fixture=$?
python3 - "$repo/local-bridge/src" "$work/evidence.json" "$image" <<'PY' || fixture=1
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
# Keep logs scoped to disposable results, not state paths or environment.
e = json.loads(Path(sys.argv[2]).read_text())
r = e['result']
v = r['steps'][-1]
print('ALPINE_FIXTURE', json.dumps({'state':e['state'], 'image':r.get('image'), 'validation':v, 'events':[x['state'] for x in e['events']]}, sort_keys=True))
assert e['state'] == 'SUCCEEDED' and r['image'] == sys.argv[3]
assert r['steps'][1]['original_unchanged'] is True and v['cleanup_verified'] is True
from project_os_bridge.isolated import CHECKS, ISOLATION_CHECKS
assert v['checks'] == CHECKS and v['isolation_checks'] == ISOLATION_CHECKS and v['exit_code'] == 0
PY
if [ "$fixture" != 0 ]; then exit 1; fi
# New CLI processes must recover exactly the original durable result without rerunning.
job_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$work/evidence.json")"
PYTHONPATH="$repo/local-bridge/src" "$work/venv/bin/python" -m project_os_bridge.vertical --state-dir "$work/state" --evidence-job-id "$job_id" > "$work/recovered.json"
PYTHONPATH="$repo/local-bridge/src" "$work/venv/bin/python" -m project_os_bridge.vertical --state-dir "$work/state" --request-key ci-alpine-remediation --image "$image" --podman-context "$context" > "$work/replay.json"
python3 - "$work/evidence.json" "$work/recovered.json" "$work/replay.json" <<'PY'
import json, sys
from pathlib import Path
a, b, c = (json.loads(Path(p).read_text()) for p in sys.argv[1:])
assert a == b == c, 'Durable fixture evidence changed on retrieval or replay'
assert [e['state'] for e in a['events']] == ['QUEUED', 'RUNNING', 'SUCCEEDED']
print('ALPINE_FIXTURE_REPLAY_PASS')
PY
if [ "$mode" = fixture-only ]; then
  "$work/venv/bin/python" -I "$repo/local-bridge/scripts/ci-reconcile-fixture.py" "$image" "$context"
fi
echo "ALPINE_EVIDENCE_COMPLETE mode=$mode audit=$audit locks=1"
# A failed command in a non-final AND-list is exempt from errexit. Explicitly fail here.
if [ "$audit" != 0 ] || [ "$fixture" != 0 ] || [ ! -f "$lock" ] || [ ! -f "$manifest_lock" ]; then
  exit 1
fi
# Release subuid-owned layers through the same context before the EXIT trap removes it.
"${runtime[@]}" - "$context" "$image" <<'PY'
from pathlib import Path
import sys
from project_os_bridge.podman_context import FIXTURE_TAG, PodmanContext

context = PodmanContext(Path(sys.argv[1]))
identity = context.identity()
context.require_import(identity, sys.argv[2])

def require_empty(*args):
    result = context.run(identity, *args, capture=True)
    if result.returncode or result.stdout.strip():
        raise SystemExit("Unexpected contents in disposable fixture store")

require_empty("ps", "--all", "--quiet")
if context.run(identity, "rmi", FIXTURE_TAG, timeout=30).returncode:
    raise SystemExit("Could not remove the pinned image from the disposable fixture store")
require_empty("image", "ls", "--all", "--quiet")
print("DISPOSABLE_CONTEXT_IMAGE_REMOVED")
PY
echo 'ALPINE_REMEDIATION_EVIDENCE_PASS'
