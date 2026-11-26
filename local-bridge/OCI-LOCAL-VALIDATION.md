# Local fixture-only OCI reproduction (operator proposal, not executed)

**STOP:** This procedure is for a NEW dedicated disposable Linux/amd64 VM or independently reviewed WSL service account with empty, private rootless Podman storage. It is not an approval of an image, distribution, installation or resource. Obtain explicit PM permission to acquire/build/scan in that environment, and a separate permission to run the fixture after review of the new audit. No use of the pilot or reference image; no registry upload. The PM has authorized the fixture-only digest for CI acceptance only (LB-02-PM-20261124-34); the original image is a mandatory negative control. The bootstrap uses the exact approved applicability policy in SECURITY.md. A passing CI gate does not authorize local use. Do not fake GITHUB_ACTIONS or call the CI-only script locally.

Prerequisites: reviewed full SHA and clean checkout of the public kit, host boundary reviewed per WSL-VALIDATION.md, rootless Podman 4.9.3 (the proven CI toolchain; record exact version, OS/storage/Buildah versions), cgroup v2 and Seccomp. Verify host package provenance and CA trust. No root, privileged sockets, personal credentials or existing tags/storage. If a tool/version or historical package is unavailable, stop and report; do not substitute versions or change locks. All blocks run in the same shell. Use a new dedicated VM if storage or host identity cannot be proven. These commands are prepared from the successful CI recipe, not independently tested on WSL.

## 1. Preflight and acquisition (only after explicit permission)

```bash
set -euo pipefail
umask 077
test "$(id -u)" -ne 0
test "$(uname -m)" = x86_64
read -rp 'Reviewed full SHA: ' REVIEWED_SHA
[[ "$REVIEWED_SHA" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse HEAD)" = "$REVIEWED_SHA"
checkout_status="$(git status --porcelain --untracked-files=normal)"
test -z "$checkout_status"
test "$(git config --local --get remote.origin.url)" = https://github.com/codefusion-repo/project-os-v3.git
repo="$(pwd -P)"
scripts="$repo/local-bridge/scripts"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
podman --version
# Reproducibility was demonstrated with 4.9.3 only; refuse a different version.
test "$(podman --version)" = "podman version 4.9.3"
podman info --format json | python3 -I -c 'import json,sys; h=json.load(sys.stdin)["host"]; assert h["security"]["rootless"] and h["security"]["seccompEnabled"] and h["cgroupVersion"]=="v2"'
containers="$(podman ps --all --quiet)"
images="$(podman images --all --quiet)"
test -z "$containers"
test -z "$images"
work="$(mktemp -d "$HOME/fixture-oci.XXXXXXXX")"
mkdir "$work/packages" "$work/context" "$work/home" "$work/cache"
base=docker.io/library/python@sha256:a61cbd76a882645de7f91423329fe43a67eed60d7da24f9e5331414bb3618b20
podman pull --platform linux/amd64 "$base"
test "$(podman image inspect --format '{{.Digest}}' "$base")" = "${base##*@}"
for pkg in krb5-libs-1.22.3-r0.apk libcrypto3-3.5.9-r1.apk libssl3-3.5.9-r1.apk zlib-1.4-r0.apk; do
  curl --disable --fail --silent --show-error --proto '=https' --noproxy '*' --max-time 120 -o "$work/packages/$pkg" "https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/$pkg"
done
(cd "$work/packages"; sha256sum -c "$scripts/alpine-krb5.sha256"; sha256sum -c "$scripts/alpine-residual-apks.sha256")
chmod 0444 "$work/packages/"*.apk
for pkg in krb5-libs-1.22.3-r0.apk libcrypto3-3.5.9-r1.apk libssl3-3.5.9-r1.apk zlib-1.4-r0.apk; do
  podman run --rm --pull=never --network=none --http-proxy=false --volume "$work/packages:/packages:ro" --entrypoint /sbin/apk "$base" verify "/packages/$pkg"
done
podman run --rm --pull=never --network=none --entrypoint /sbin/apk "$base" --no-network --repositories-file /dev/null info -v | LC_ALL=C sort > "$work/before"
for version in krb5-libs-1.22.2-r1 libcrypto3-3.5.9-r0 libssl3-3.5.9-r0 zlib-1.3.2-r1; do grep -Fxq "$version" "$work/before"; done
sed -e 's/^krb5-libs-1\.22\.2-r1$/krb5-libs-1.22.3-r0/' -e 's/^libcrypto3-3\.5\.9-r0$/libcrypto3-3.5.9-r1/' -e 's/^libssl3-3\.5\.9-r0$/libssl3-3.5.9-r1/' -e 's/^zlib-1\.3\.2-r1$/zlib-1.4-r0/' "$work/before" | LC_ALL=C sort > "$work/expected"
```

## 2. Build twice, export to local OCI layout and verify

```bash
cat > "$work/context/Containerfile" <<'BUILD'
FROM docker.io/library/python@sha256:a61cbd76a882645de7f91423329fe43a67eed60d7da24f9e5331414bb3618b20
RUN apk verify /packages/krb5-libs-1.22.3-r0.apk && apk add --logfile=no --no-network --no-cache --repositories-file /dev/null /packages/krb5-libs-1.22.3-r0.apk
RUN apk verify /packages/libcrypto3-3.5.9-r1.apk /packages/libssl3-3.5.9-r1.apk /packages/zlib-1.4-r0.apk && apk add --logfile=no --no-network --no-cache --repositories-file /dev/null /packages/libcrypto3-3.5.9-r1.apk /packages/libssl3-3.5.9-r1.apk /packages/zlib-1.4-r0.apk
# The fixed fixture only executes stdlib Python. Remove actual package-manager code and bootstrap, not just scanner metadata.
RUN python -I -B -m pip --isolated uninstall -y setuptools pip && python -I -B -c 'import ensurepip, pathlib, shutil; shutil.rmtree(pathlib.Path(ensurepip.__file__).parent)' && python -I -B -c 'import importlib.util as u; assert all(u.find_spec(n) is None for n in ("pip", "setuptools", "ensurepip"))'
BUILD
tag=localhost/project-os-alpine-ci:candidate
repeat=localhost/project-os-alpine-ci:repeat
build_candidate() {
  podman build --pull=never --network=none --http-proxy=false --no-cache --timestamp 1700000000 --format oci --volume "$work/packages:/packages:ro" --tag "$1" "$work/context"
}
build_candidate "$tag"
sleep 2
build_candidate "$repeat"
podman run --rm --pull=never --network=none --entrypoint /sbin/apk "$tag" --no-network --repositories-file /dev/null info -v | LC_ALL=C sort > "$work/after"
diff -u "$work/expected" "$work/after"
# OCI transport is a local directory, not a registry.
podman push --format oci --digestfile "$work/digest" "$tag" "oci:$work/oci:candidate"
podman push --format oci --digestfile "$work/repeat-digest" "$repeat" "oci:$work/repeat-oci:candidate"
digest="$(cat "$work/digest")"
repeat_digest="$(cat "$work/repeat-digest")"
python3 -I "$scripts/oci_repro.py" "$work/oci" "$digest" "$work/repeat-oci" "$repeat_digest"
test "$digest" = "$(cat "$scripts/alpine-fixture-only-manifest.sha256")"
```

The helper verifies both manifests and all referenced config/layer hashes and sizes. Mismatch is a hard stop; retain evidence, no lock updates on the host.

## 3. Fresh audit of exact bytes, before any fixture binding

```bash
archive=trivy_0.76.2_Linux-64bit.tar.gz
curl --disable --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --max-time 180 -o "$work/$archive" "https://github.com/aquasecurity/trivy/releases/download/v0.76.2/$archive"
(cd "$work"; printf '%s  %s\n' bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf "$archive" | sha256sum -c -; tar -xzf "$archive" trivy)
scan_env=(env -i PATH=/usr/bin:/bin HOME="$work/home" LC_ALL=C)
"${scan_env[@]}" "$work/trivy" --cache-dir "$work/cache" image --input "$work/oci@$digest" --platform linux/amd64 --scanners vuln --pkg-types os,library --ignorefile /dev/null --list-all-pkgs --no-progress --timeout 8m --format json --output "$work/report.json"
"${scan_env[@]}" "$work/trivy" --cache-dir "$work/cache" --version
for section in main community; do
  curl --disable --fail --silent --show-error --proto '=https' --max-time 120 --max-filesize 10000000 -o "$work/$section.json" "https://secdb.alpinelinux.org/v3.24/$section.json"
done
python3 "$scripts/alpine_findings.py" "$work/report.json" "$work/oci@$digest" "$work/main.json" "$work/community.json"
python3 -I - "$scripts" "$work/report.json" "$work/oci@$digest" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from oci_compare import summarize
r=summarize(json.loads(Path(sys.argv[2]).read_text()),sys.argv[3])
print(json.dumps(r,sort_keys=True))
raise SystemExit(r["candidate_gate"] == "BLOCKED")
PY
```

Review scanner/database freshness and every remaining finding. A scan of a different digest, missing DB, EOL, HIGH/CRITICAL or incomplete inventory blocks approval. No ignores. Even zero reported findings is not a universal security claim. Preserve local files; do not automatically delete or upload. Obtain explicit PM decision on exact candidate and fixture run before continuing.

## 4. Import audited bytes and execute only the fixed fixture (separate permission)

```bash
# Use the independently reviewed runtime and the verified local OCI bytes.
bridge_python="$repo/local-bridge/.venv/bin/python"
fixture_cli="$repo/local-bridge/.venv/bin/project-os-bridge-fixture"
context_parent="$(mktemp -d /tmp/lboci.XXXXXXXX)"  # use a native filesystem
PODMAN_CONTEXT="$context_parent/context"  # Podman 4.9.3 limits runroot to 50 bytes
"$bridge_python" -I -m project_os_bridge.podman_context --context "$PODMAN_CONTEXT" prepare
image="$("$bridge_python" -I -m project_os_bridge.podman_context \
  --context "$PODMAN_CONTEXT" import-layout "$work/oci" "$digest")"
test "$image" = "localhost/project-os-alpine-ci@$digest"
mkdir -m 0700 "$work/state"
"$fixture_cli" --state-dir "$work/state" --request-key independent-fixture \
  --image "$image" --podman-context "$PODMAN_CONTEXT" > "$work/evidence.json"
job="$(python3 -I - "$work/evidence.json" <<'PY'
import json, sys
from pathlib import Path
e = json.loads(Path(sys.argv[1]).read_text())
assert e["state"] == "SUCCEEDED"
v = e["result"]["steps"][-1]
assert v["cleanup_verified"] is True and len(v["checks"]) == 10 and len(v["isolation_checks"]) == 7
assert v["compatibility_checks"] == [
    "python_312_amd64", "musl_loader", "krb5_library", "sqlite", "tls", "loopback_only", "zlib",
    "package_modules_absent", "package_metadata_absent", "pip_entrypoints_absent", "bundled_bootstrap_absent",
]
assert e["result"]["steps"][1]["original_unchanged"] is True
print(e["id"])
PY
)"
"$repo/local-bridge/.venv/bin/project-os-bridge-fixture" --state-dir "$work/state" --evidence-job-id "$job" > "$work/recovered.json"
"$repo/local-bridge/.venv/bin/project-os-bridge-fixture" --state-dir "$work/state" --request-key independent-fixture --image "$image" --podman-context "$PODMAN_CONTEXT" > "$work/replay.json"
python3 -I - "$work/evidence.json" "$work/recovered.json" "$work/replay.json" <<'PY'
import json,sys
from pathlib import Path
a,b,c=(json.loads(Path(p).read_text()) for p in sys.argv[1:])
assert a==b==c
assert [e["state"] for e in a["events"]]==["QUEUED","RUNNING","SUCCEEDED"]
print("FIXTURE_REPLAY_PASS")
PY
```

The prepared context is separate from the build store. It imports the exact local layout, verifies the stored manifest and pins that image in its own store. The fixture checks the authorized binding and effective context before claim and again before dispatch. The same named and labeled container runs all 17 isolation checks and the compatibility checks after SQLite records its ownership token and context at claim. A timeout, interruption or unconfirmed absence keeps that same durable effect for reconciliation. A compatibility failure with verified absence is recorded as a terminal failure. Both the CI baseline and the fixture-only candidate verify the runtime libraries and loopback in this protected execution. The exact fixture-only digest also requires the package tools, metadata, entry points and bootstrap wheels to be absent.

Run all steps as the same dedicated operator. Keep the private context and fixture state intact until effects are reconciled. A reboot, lost pause namespace, replaced state DB, or moved context can invalidate identity. Preserve evidence and use the reconciliation runbook. Do not recreate the context to clear an effect.

Stop on any failure; preserve evidence and use the reconciliation runbook. No modification of an existing image binding, no automatic service startup and no real resources. Report only SHA, digest, aggregate audit, tool versions and boolean checks. No publication of images or private state.


## CI gate substitution — PM authorized, local use still blocked

The original image remains rejected. The PM-authorized CI-only replacement is the exact fixture-only manifest `sha256:0c8e915d597f997fc64b7ddfc8e25de93873d06126faccbee1f46446deb30cfb` for the fixed stdlib fixture only, not general execution, Android, Codex or a distributable release image. The original official Debian reference remains a rejected historical control; residual manifest `sha256:9e42be33d3f4b762175eb8c0f669e58d797219490c42a42017855256ce72deae` is a negative control, never approved. CI checks exact locked digest, signed APKs against pinned base keys, package closure, reproducible builds, fresh full audit without ignores, zero reported findings on candidate, runtime fixture/replay/reconciliation. Raw public scanner reports and database metadata are retained in Actions artifacts. Removal of pip, setuptools and ensurepip is proven in the effective filesystem, not erasure of their bytes from inherited OCI layers; no registry publication or claim of layer-level sanitization. The base is digest-pinned, not independently signature-attested. The workflow requires both locked candidate replicas through the matrix result and both negative controls through oci-acceptance. The legacy oci-audit check also depends on the candidate matrix. The original scanner and audit logic remain. The ratified R49 policy in SECURITY.md preserves exact deterministic historical rejection (including all historical locks) and fresh raw evidence, exit codes, metadata, identity, inventory and scanner consistency; fresh finding drift is recorded without approving the discarded image. Verify actual branch protection/rules before integration. No local binding approval follows from that CI decision: #14 requires independently rebuilt/imported exact bytes, current audit and separate PM consent. New findings, expired database, digest drift, EOL, lock or runtime failure revoke candidate evidence and require review; no automatic substitution, ignore or rollback to vulnerable original. Stop dispatch before any future authorized local binding migration, preserve durable state and reconcile uncertain effects. Rollback means stop service/disable fixture or use a separately reviewed safe digest, not silently re-enable the prior vulnerable image.
