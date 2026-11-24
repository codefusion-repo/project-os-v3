#!/usr/bin/env bash
# CI only. Static remote image scan, never executes target image or uses daemon sockets.
set -euo pipefail
umask 077
[ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${RUNNER_TEMP:-}" ] || exit 1
[ "$(uname -m)" = x86_64 ] || exit 1
work="$(mktemp -d "$RUNNER_TEMP/bridge-oci.XXXXXXXX")"
mkdir "$work/home" "$work/cache"
cd "$work"
archive=trivy_0.76.2_Linux-64bit.tar.gz
# Published release asset SHA-256, reviewed 2026-11-24.
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --max-time 180 \
  -o "$archive" "https://github.com/aquasecurity/trivy/releases/download/v0.76.2/$archive"
printf '%s  %s\n' bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf "$archive" | sha256sum -c -
tar -xzf "$archive" trivy
image=docker.io/library/python@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
# Isolated HOME/cache and no inherited registry or GitHub credentials.
env -i PATH=/usr/bin:/bin HOME="$work/home" LC_ALL=C ./trivy --version
env -i PATH=/usr/bin:/bin HOME="$work/home" LC_ALL=C ./trivy --cache-dir "$work/cache" image \
  --image-src remote --platform linux/amd64 --scanners vuln --pkg-types os,library \
  --ignorefile /dev/null --list-all-pkgs --no-progress --timeout 8m --format json \
  --output "$work/report.json" "$image"
env -i PATH=/usr/bin:/bin HOME="$work/home" LC_ALL=C ./trivy --cache-dir "$work/cache" --version
python3 - "$work/report.json" "$image" <<'PY'
import collections, json, sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text())
if report.get('ArtifactName') != sys.argv[2]:
    raise SystemExit('OCI BLOCKED: report identity mismatch')
metadata = report.get('Metadata') or {}
os_info = metadata.get('OS') or {}
results = report.get('Results') or []
if not os_info.get('Family') or not any(r.get('Class') == 'os-pkgs' and r.get('Packages') for r in results):
    raise SystemExit('OCI BLOCKED: OS package inventory missing')
counts = collections.Counter()
for result in results:
    for vuln in result.get('Vulnerabilities') or []:
        counts[vuln.get('Severity', 'UNKNOWN')] += 1
        if vuln.get('Severity') in ('HIGH', 'CRITICAL'):
            # Public image only; no arbitrary metadata or descriptions in logs.
            print('FINDING', json.dumps({k:vuln.get(k) for k in ('VulnerabilityID','PkgName','InstalledVersion','FixedVersion','Severity')}, sort_keys=True))
print('OCI_COUNTS', json.dumps(dict(sorted(counts.items())), sort_keys=True))
if os_info.get('EOSL') or counts['HIGH'] or counts['CRITICAL']:
    raise SystemExit('OCI BLOCKED: EOL or high/critical findings require review')
print('OCI HIGH/CRITICAL GATE PASS; lower severities still require review')
PY
