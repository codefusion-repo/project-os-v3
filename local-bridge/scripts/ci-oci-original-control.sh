#!/usr/bin/env bash
# CI-only wrapper. The original scanner and HIGH/CRITICAL rejection remain intact.
set -euo pipefail
umask 077
[ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${RUNNER_TEMP:-}" ] || exit 1
repo="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
evidence="$RUNNER_TEMP/lb-original-oci-evidence"
mkdir "$evidence"
work="$(mktemp -d "$RUNNER_TEMP/original-control.XXXXXXXX")"
trap 'rm -rf -- "$work"' EXIT
audit=0
RUNNER_TEMP="$work" bash "$repo/local-bridge/scripts/ci-oci-audit.sh" >"$evidence/audit.log" 2>&1 || audit=$?
printf '%s\n' "$audit" > "$evidence/audit-exit.txt"
cat "$evidence/audit.log"
dirs=("$work"/bridge-oci.*)
[ "${#dirs[@]}" = 1 ] && [ -d "${dirs[0]}" ] || exit 1
source_dir="${dirs[0]}"
for file in report.json scanner-exit.txt; do
  if [ -f "$source_dir/$file" ]; then cp -- "$source_dir/$file" "$evidence/$file"; fi
done
if [ -f "$source_dir/cache/db/metadata.json" ]; then
  cp -- "$source_dir/cache/db/metadata.json" "$evidence/db-metadata.json"
fi
python3 -I "$repo/local-bridge/scripts/oci_original_control.py" "$evidence/report.json" "$repo/local-bridge/scripts/oci-original-rejection-r37.json" "$evidence/scanner-exit.txt" "$evidence/audit-exit.txt" "$evidence/audit.log" "$evidence/db-metadata.json" | tee "$evidence/control.txt"
