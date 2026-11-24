#!/usr/bin/env bash
# Disposable GitHub runner only. Never publish an image to a registry.
set -euo pipefail
umask 077
[ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${RUNNER_TEMP:-}" ] || exit 1
[ "$(id -u)" != 0 ] && [ "$(uname -m)" = x86_64 ] || exit 1
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
repo="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
work="$(mktemp -d "$RUNNER_TEMP/alpine-remediation.XXXXXXXX")"
trap 'rm -rf -- "$work"' EXIT
mkdir "$work/packages" "$work/context" "$work/home" "$work/cache" "$work/state"
base=docker.io/library/python@sha256:a61cbd76a882645de7f91423329fe43a67eed60d7da24f9e5331414bb3618b20
package=krb5-libs-1.22.3-r0.apk
url="https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/$package"
lock="$repo/local-bridge/scripts/alpine-krb5.sha256"
tag=localhost/project-os-alpine-ci:candidate
podman info --format json | python3 -c 'import json,sys; h=json.load(sys.stdin)["host"]; assert h["security"]["rootless"] and h["security"]["seccompEnabled"] and h["cgroupVersion"]=="v2"'
podman --version
podman pull --platform linux/amd64 "$base"
[ "$(podman image inspect --format '{{.Digest}}' "$base")" = "${base##*@}" ]
# All package acquisition is HTTPS; signature is verified using keys in the pinned base.
curl --fail --silent --show-error --proto '=https' --max-time 120 -o "$work/packages/$package" "$url"
chmod 0444 "$work/packages/$package"
podman run --rm --pull=never --network=none --http-proxy=false --volume "$work/packages:/packages:ro" --entrypoint /sbin/apk "$base" verify "/packages/$package"
(cd "$work/packages" && sha256sum "$package") > "$work/observed.sha256"
cat "$work/observed.sha256"
if [ -f "$lock" ]; then
  diff -u "$lock" "$work/observed.sha256"
  echo 'APK_LOCK_VERIFIED'
else
  echo 'APK_LOCK_PENDING: discovery build only'
fi
podman run --rm --pull=never --network=none --entrypoint /sbin/apk "$base" info -v | LC_ALL=C sort > "$work/before"
grep -Fxq krb5-libs-1.22.2-r1 "$work/before"
sed 's/^krb5-libs-1\.22\.2-r1$/krb5-libs-1.22.3-r0/' "$work/before" | LC_ALL=C sort > "$work/expected"
cat > "$work/context/Containerfile" <<'BUILD'
FROM docker.io/library/python@sha256:a61cbd76a882645de7f91423329fe43a67eed60d7da24f9e5331414bb3618b20
RUN apk verify /packages/krb5-libs-1.22.3-r0.apk && apk add --no-network --no-cache --repositories-file /dev/null /packages/krb5-libs-1.22.3-r0.apk
BUILD
podman build --pull=never --network=none --http-proxy=false --no-cache --timestamp 0 --format oci --volume "$work/packages:/packages:ro" --tag "$tag" "$work/context"
podman run --rm --pull=never --network=none --entrypoint /sbin/apk "$tag" info -v | LC_ALL=C sort > "$work/after"
diff -u "$work/expected" "$work/after"
echo 'APK_CLOSURE_PASS: only krb5-libs changed'
# Export to an OCI layout on this runner, not a registry. Audit exactly this digest.
podman push --format oci --digestfile "$work/digest" "$tag" "oci:$work/oci:candidate"
digest="$(cat "$work/digest")"
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]
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
# Re-import exact audited manifest; reject any local identity mismatch.
loaded="$(podman pull --quiet "oci:$work/oci:candidate")"
podman tag "$loaded" "$tag"
image="${tag%:*}@$digest"
[ "$(podman image inspect --format '{{.Digest}}' "$image")" = "$digest" ]
echo "CANDIDATE_MANIFEST $digest"
archive=trivy_0.76.2_Linux-64bit.tar.gz
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --max-time 180 -o "$work/$archive" "https://github.com/aquasecurity/trivy/releases/download/v0.76.2/$archive"
(cd "$work" && printf '%s  %s\n' bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf "$archive" | sha256sum -c - && tar -xzf "$archive" trivy)
scan_env=(env -i PATH=/usr/bin:/bin HOME="$work/home" LC_ALL=C)
"${scan_env[@]}" "$work/trivy" --cache-dir "$work/cache" image --input "$work/oci@$digest" --platform linux/amd64 --scanners vuln --pkg-types os,library --ignorefile /dev/null --list-all-pkgs --no-progress --timeout 8m --format json --output "$work/report.json"
"${scan_env[@]}" "$work/trivy" --cache-dir "$work/cache" --version
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
podman run --rm --pull=never --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges --entrypoint python "$image" -I -B -c 'import ctypes, pathlib, platform, socket, sqlite3, ssl, sys; assert sys.version_info[:2]==(3,12); assert platform.machine()=="x86_64"; assert pathlib.Path("/lib/ld-musl-x86_64.so.1").exists(); ctypes.CDLL("libkrb5.so.3"); assert sqlite3.connect(":memory:").execute("select 1").fetchone()==(1,); assert ssl.OPENSSL_VERSION; assert {n for _,n in socket.if_nameindex()} <= {"lo"}; print("PYTHON_MUSL_PASS", sys.version.split()[0])'
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r "$repo/local-bridge/requirements-linux-py312.lock"
"$work/venv/bin/python" -m pip check
fixture=0
PYTHONPATH="$repo/local-bridge/src" "$work/venv/bin/python" -m project_os_bridge.vertical --state-dir "$work/state" --request-key ci-alpine-remediation --image "$image" > "$work/evidence.json" || fixture=$?
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
assert len(v['checks']) == 10 and v['exit_code'] == 0
PY
[ "$audit" = 0 ] && [ "$fixture" = 0 ] && [ -f "$lock" ]
echo 'ALPINE_REMEDIATION_EVIDENCE_PASS'
