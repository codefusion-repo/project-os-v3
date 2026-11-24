# Independent WSL production validation (operator runbook)

Status: preparation only. Do not modify the existing pilot or enable real resources. The reference OCI gate remains blocked (53 HIGH records, 13 unique HIGH CVEs, run 45446812446). A separate image review is mandatory before any fixture execution with a replacement. Probe-only HTTPS validation can proceed independently once its own prerequisites pass.

## 1. Dedicated environment (explicit operator decision)

Use a separate WSL2 distribution, preferably under a dedicated non-administrator Windows account without personal files or credentials; for a stronger boundary use a dedicated VM. A different Linux UID or distribution alone is not a security boundary against the Windows owner, administrators, or other WSL guests. Review host ACLs, shared mounts, networking and firewall separately. No automatic provisioning, no changes to the existing distribution. In PowerShell inventory with `wsl --list --verbose`. Choose a NEW distribution name; stop if it is the pilot. Provision Ubuntu 24.04 from a verified source under the dedicated Windows account. Do not import the pilot's filesystem.

Inside ONLY that new distribution, an administrator should create an unprivileged service user (example name bridge-service) with private home and separate subuid/subgid ranges. Review before running administrative commands:

```bash
sudo adduser --disabled-password --gecos '' bridge-service
sudo chmod 0700 /home/bridge-service
sudo -l -U bridge-service
sudo apt-get update
sudo apt-get install python3.12 python3.12-venv git curl podman uidmap slirp4netns fuse-overlayfs
```

Stop if the account already exists, has sudo rules, privileged groups, overlapping subordinate IDs, or can access other users' files. Review /etc/subuid and /etc/subgid locally without sharing raw output. No Docker group or rootful Podman socket. Package installation changes only the new distribution. Do not run the bridge as the provisioning administrator.

For that new distribution only, review and merge these settings into /etc/wsl.conf (preserve unrelated settings; do not overwrite an existing file blindly):

```ini
[boot]
systemd=true
[automount]
enabled=false
mountFsTab=false
[interop]
enabled=false
appendWindowsPath=false
[user]
default=bridge-service
```

After explicitly checking the distribution name, terminate only the NEW distribution from PowerShell using `wsl --terminate <NEW-DISTRO>`, then reopen it using `wsl --distribution <NEW-DISTRO> --user bridge-service`. Do not use wsl --shutdown, unregister, or stop the pilot. WSL settings and user-systemd availability depend on the installed WSL version. See https://learn.microsoft.com/windows/wsl/wsl-config . Disabling interop may prevent Windows ADB access: do not re-enable it for this test.

## 2. Independent installation and boundary checks

Run as the new service account. Replace REVIEWED_SHA with the full explicitly reviewed Git commit (not a tag, merge preview or abbreviated SHA). Stop at any failure.

```bash
set -euo pipefail
umask 077
test "$(id -u)" -ne 0
read -rp 'Reviewed full commit SHA: ' REVIEWED_SHA
[[ "$REVIEWED_SHA" =~ ^[0-9a-f]{40}$ ]]
test ! -e "$HOME/bridge-kit" && test ! -L "$HOME/bridge-kit"
git clone --no-checkout https://github.com/codefusion-repo/project-os-v3.git "$HOME/bridge-kit"
cd "$HOME/bridge-kit"
git checkout --detach "$REVIEWED_SHA"
test "$(git rev-parse HEAD)" = "$REVIEWED_SHA"
bash local-bridge/scripts/install.sh "$REVIEWED_SHA"
# Inventory deliberately returns nonzero on WSL, requiring independent review.
python3 -I local-bridge/scripts/account_preflight.py
```

The last nonzero exit is a stop point, not a bypass. Review every boolean; require positive unprivileged UID, groups, home, other homes, sockets, Windows mounts absent and interop not observed. WSL review is always required. Independently inspect sudo policy, ACLs, mount namespace, /etc/fstab, host shares, network/firewall, systemd user session, and separate rootless Podman storage. Verify the service account cannot access a synthetic marker outside its boundary (no actual secrets). Do not copy private files, personal gh credentials, or the existing pilot state. The host administrator may still access WSL; no hostile-host isolation is claimed.

After independent review, in a NEW shell as the service user:

```bash
set -euo pipefail
cd "$HOME/bridge-kit"
test "$(id -u)" -ne 0
test "$(ps -p 1 -o comm=)" = systemd
systemctl --user show-environment >/dev/null
test "$(/usr/bin/podman info --format '{{.Host.Security.Rootless}}')" = true
test "$(/usr/bin/podman info --format '{{.Host.Security.SeccompEnabled}}')" = true
test "$(/usr/bin/podman info --format '{{.Host.CgroupVersion}}')" = v2
```

Keep all privileged sockets inaccessible. No image pull/run in this step. Install the separately verified tunnel-client binary (version and upstream hash checked independently) without personal credentials.

## 3. New HTTPS probe-only instance

Provision a separate WorkOS staging identity/application and separate tunnel with scoped runtime key (Read + Use). Follow WORKOS.md for exact issuer, resource and subject, MFA and disabled public signup. No real GitHub or device credentials. Never paste key, subject, configuration, certificates or raw logs into chat/GitHub. Ensure port 8765 is free in the dedicated environment; do not stop unknown listeners or reuse the existing tunnel. Use a new instance path outside Git.

```bash
set -euo pipefail
umask 077
cd "$HOME/bridge-kit"
ROOT="$HOME/bridge-production-probe"
test ! -e "$ROOT" && test ! -L "$ROOT"
local-bridge/.venv/bin/project-os-bridge-init --root "$ROOT"
# Enter verified tunnel executable; leave image blank; enter key privately.
local-bridge/.venv/bin/project-os-bridge-init --root "$ROOT" --prepare-service
test ! -e "$ROOT/state/allow-authenticated-probe"
systemd-analyze --user verify "$ROOT/service/project-os-bridge.service"
# Refuse an existing unit rather than replacing it.
if systemctl --user cat project-os-bridge.service >/dev/null 2>&1; then
  echo 'Existing unit; stop and review' >&2
  exit 1
fi
systemctl --user link "$ROOT/service/project-os-bridge.service"
systemctl --user daemon-reload
systemctl --user start project-os-bridge.service
systemctl --user is-active project-os-bridge.service
```

No enabling at login, no automatic restart, no plaintext exception. On startup failure, stop this unit only and inspect locally; do not repeatedly restart an uncertain operation.

## 4. TLS and authentication checks

In the same shell run this bounded probe. It prints only statuses, not metadata or configuration. If readiness is not yet available, inspect status locally; do not disable certificate verification.

```bash
python3 -I - "$ROOT" <<'PY'
import http.client, json, ssl, sys, time
from pathlib import Path
root=Path(sys.argv[1])
cfg=json.loads((root/'oauth.json').read_text())
ctx=ssl.create_default_context(cafile=str(root/'service/ca.pem'))
def request(method,path,body=None):
    c=http.client.HTTPSConnection('127.0.0.1',8765,context=ctx,timeout=3)
    try:
        c.request(method,path,body=body,headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
        r=c.getresponse()
        return r.status,r.read(16385)
    finally:
        c.close()
for attempt in range(10):
    try:
        code,data=request('GET','/.well-known/oauth-protected-resource/mcp')
        break
    except (OSError,http.client.HTTPException):
        if attempt==9: raise
        time.sleep(1)
assert code==200 and len(data)<=16384
m=json.loads(data)
assert m['resource']==cfg['resource'] and m['authorization_servers']==[cfg['issuer']]
code,_=request('POST','/mcp',b'{}')
assert code==401
print('LOCAL TLS METADATA 200; UNAUTHENTICATED 401')
PY
```

Only with explicit permission for this NEW disposable probe, create its empty local opt-in using `(umask 077; set -o noclobber; : > "$ROOT/state/allow-authenticated-probe")`. Attach the separate OAuth connector, confirm health reports no real repository access and no fixture availability, submit a unique disposable probe, replay the same request key and compare job ID/evidence. Remove only that known empty marker to revoke access; expect FORBIDDEN, not a reconnect loop. Restore with the same noclobber command, check health and job evidence again. Verify fixed-schema local audit 403 without publishing identifiers. Stop if any unexpected behavior.

```bash
systemctl --user stop project-os-bridge.service
test "$(systemctl --user show -p ActiveState --value project-os-bridge.service)" = inactive
systemctl --user start project-os-bridge.service
systemctl --user is-active project-os-bridge.service
```

Repeat TLS checks and MCP health/replay after restart. End by revoking only the new probe flag if present and stopping this unit. Preserve state, configuration and logs. No deletion, no enabling or migration of the pilot. If a forced stop occurred, reconcile jobs/containers before restarting.

## 5. Separate fixture and production gates

Do not pull or run the blocked reference image or any candidate without separate approval. Scan an exact platform manifest digest, require zero HIGH/CRITICAL and non-EOL with complete inventory; review MEDIUM/LOW/UNKNOWN and scanner/database freshness. Then with explicit permission use a fresh disposable fixture state, exact audited digest and all ten isolation checks. No changes to an existing image binding. Static scan alone is not functional validation.

Report only reviewed SHA, installer/test counts and exit statuses, preflight booleans, TLS 200/401, MCP readiness/403/replay equality, systemd stop/start status, approved image digest and aggregate audit findings. Keep secrets and private identifiers local. All gates plus an independent security review and separate explicit resource grant are required before real access. This runbook does not grant authorization.
