#!/usr/bin/env bash
# Local-only inventory. No credentials, device serials, paths or raw tool output.
set -u
export LC_ALL=C
check() {
  local label="$1"
  shift
  if timeout 10s "$@" >/dev/null 2>&1; then
    printf '%s: AVAILABLE\n' "$label"
  else
    printf '%s: UNAVAILABLE_OR_FAILED\n' "$label"
  fi
}
check git git --version
check gh gh --version
check podman /usr/bin/podman --version
if [ "$(id -u)" -ne 0 ] && [ "$(timeout 10s /usr/bin/podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null)" = true ]; then
  printf 'podman_rootless: AVAILABLE\n'
else
  printf 'podman_rootless: UNAVAILABLE_OR_FAILED\n'
fi
check adb adb version
check emulator emulator -version
check windows_interop cmd.exe /d /c exit 0
check adb_windows adb.exe version
check emulator_windows emulator.exe -version
printf 'Preflight only: no gh authentication, device access or isolation proof.\n'
