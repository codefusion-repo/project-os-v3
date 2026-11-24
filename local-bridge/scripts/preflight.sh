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
# Inventory only. A failed group lookup must not produce PASS.
if groups="$(id -Gn 2>/dev/null)" && [ -n "$groups" ] && [ "$(id -u)" -ne 0 ]; then
  if printf '%s\n' "$groups" | tr ' ' '\n' | grep -Eq '^(sudo|wheel|docker|lxd|libvirt|disk|root|adm|podman)$'; then
    printf 'service_account_groups: BLOCKED\n'
  else
    printf 'service_account_groups: PASS\n'
  fi
else
  printf 'service_account_groups: BLOCKED\n'
fi
check systemd_user systemctl --user show-environment
check adb adb version
check emulator emulator -version
# Inventory only; do not print device serials, start an emulator, install
# packages or issue shell commands to a device. ADB may start its local server.
if devices="$(timeout 10s adb devices 2>/dev/null)"; then
  if printf '%s\n' "$devices" | awk '$1 ~ /^emulator-[0-9]+$/ && $2 == "device" { found=1 } END { exit !found }'; then
    printf 'adb_emulator_attach: CONNECTED\n'
  else
    printf 'adb_emulator_attach: NOT_DETECTED\n'
  fi
else
  printf 'adb_emulator_attach: UNAVAILABLE_OR_FAILED\n'
fi
check windows_interop cmd.exe /d /c exit 0
check adb_windows adb.exe version
check emulator_windows emulator.exe -version
printf 'Preflight only: no gh authentication, device authorization, boot readiness or isolation proof.\n'
