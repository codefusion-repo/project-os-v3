# Independent WSL production validation (operator runbook)

> **Current decision (2026-11-28):** [AgentsUbuntu only](https://github.com/codefusion-repo/project-os-v3/issues/8#issuecomment-7233893145). No additional execution environment or infrastructure certification. Historical evidence remains in Git. Candidate code does not establish live acceptance.


Status: functional validation of the existing AgentsUbuntu installation.

## 1. Dedicated environment (explicit operator decision)


### Existing dedicated WSL: single-operator profile (conditional evaluation)

The operator may retain the existing dedicated agent distribution, Linux identity, central kit, development checkout and intentional exchange share. Do not require another account or distribution just to repeat setup. This profile treats Windows, the operator and trusted same-UID local agent processes as trusted; it does not claim isolation from them, a compromised host, or hostile code running on the host as that UID. Untrusted input and repository-controlled execution must remain within registered, bounded handlers and separately validated execution profiles. See [SECURITY.md](SECURITY.md#single-operator-trust-boundaries).

AgentsUbuntu is the sole local execution environment. Use the installed toolchains and registered Jobs; GitHub Connector handles remote writes, and MCP provides grouped context and typed local execution. Trusted project processes run with the local account's authority, not a sandbox. Keep private grants, scoped credentials, exact revision and lockfile, bounded process lifecycle and durable evidence.

- Identify WSL distribution/host provenance, effective Windows account/ACLs and Linux UID, groups, HOME (0700), private instance directory and file permissions. No shared personal credential stores or privileged sockets. The existing dedicated UID is acceptable only when its effective boundary passes; additional identity or VM is a mitigation if the required boundary cannot otherwise be achieved.
- Inspect effective sudo policy locally (including all included rules, NOPASSWD, authentication/timestamp scope, setuid helpers and alternative elevation routes). Group membership alone neither proves nor disproves unattended escalation. No unrestricted unattended elevation or agent access to administrator authentication; a noninteractive probe is only supporting evidence. Do not remove sudo membership or change policy automatically. Require non-root bridge and no permitted/effective/ambient capabilities. NoNewPrivs is an observation, not a new host certification requirement.
- Identify every host-backed mount, source/options, bind alias and namespace/propagation relation. Driver-path label is not provenance. An intentional exchange share can remain accessible to the trusted local agent only within the reviewed Windows ACL boundary; no personal files or secrets in it. Prove access outside the approved share is denied with a synthetic marker before probe-only activation. Separately prove that untrusted job profiles cannot reach the share, personal credentials, host sockets or other unauthorized paths in the live execution gate in section 5. DAC at a single mount root is not proof. Do not dismantle WSL infrastructure or alter the share to manufacture a passing result.
- Review effective Windows/Hyper-V firewall, listeners and reachable host/LAN endpoints, WSL interop, DNS/proxy inheritance and credential scope. Mirrored networking, firewall=true, DNS tunneling and autoProxy are configuration, not proof of isolation. Verify the reviewed loopback-only TLS configuration before startup and the actual listener, absence of alternate plaintext endpoints and the applicable network disposition below before authenticated opt-in in section 4; do not widen firewall rules. Inspect proxy configuration privately and report only presence/disposition, never values. See https://learn.microsoft.com/windows/wsl/networking and https://learn.microsoft.com/windows/wsl/file-permissions.
Use existing installed toolchains and private grants.
- Verify a clean reviewed installation (existing verified installation evidence may be reused for the exact SHA/artifact if still applicable), fresh private instance state, either independent staging OAuth identity and tunnel or the exclusive same-operator transition in section 3, no inherited pilot job state/grants and quiescence/reconciliation of earlier effects. Keep current central kit and development checkout; no automatic reinstall, credential copying or destructive cleanup.

Reuse applicable inventory; review only material changes.

### Capability gate sequence (both profiles)

Apply the current WSL-only decision and capability-specific checks.

1. Before startup: reuse applicable host/credential, reviewed installation, private state, grants and prior-effect evidence; verify material changes only. Preserve the existing unprivileged service, scoped credentials and exact TLS/OAuth setup. Probe-only startup does not enroll execution or real resources.
2. Verify current loopback HTTPS metadata, anonymous 401, authenticated health, no alternate plaintext endpoint and applicable network disposition. Reuse prior replay/revocation evidence unless relevant behavior changed. Do not activate a capability whose material controls are unresolved.
3. Verify registered local execution, exact snapshot, lockfile, evidence and physical budget.
4. Verify bounded grouped GitHub and methodology reads under their existing grants.

5. Maintain the existing installation using the reviewed main SHA, applicable CI and exact wheel digest, preserving rollback.

### Finite network acceptance and evidence reuse

For the actual reviewed host/profile, record one disposition for each control below: PASS (with source and scope), FAIL, or NOT_ASSESSED. For NET-05 only, ACCEPTED_RESIDUAL is also permitted under the specific single-operator policy below; it is not a measured PASS. Reuse prior evidence when the relevant host, policy, topology, identity and implementation are unchanged and the evidence is still valid; if applicability is uncertain, revalidate only that control. A documentation or unrelated application change alone does not invalidate Windows inventory.

| Control | Acceptance | Recheck trigger |
|---|---|---|
| NET-01 | Effective process-owned loopback listener, no other Bridge-port listener | New process/start, binding change |
| NET-02 | No alternate direct listener or unauthorized forwarding, including Windows/WSL and applicable IPv4/IPv6 | Network mode, listener/forwarding or interface change |
| NET-03 | Effective Windows/Hyper-V firewall policy matches intended exposure, including applicable profiles/rules | Firewall, network profile or host configuration change |
| NET-04 | Verified TLS metadata and anonymous 401; no alternate plaintext endpoint | Start or transport/certificate change |
| NET-05 | Full acceptance: direct unauthorized reachability denied from relevant Windows/LAN segments, demonstrated by live negative checks or reviewed equivalent effective-path evidence; same-host loopback alone is insufficient. Bounded single-operator acceptance: see below. | Relevant topology, forwarding, policy or binding change, or invalidated/missing evidence for the applicable profile |
| NET-06 | Exact authorized tunnel/authentication and revocation evidence; no unintended route | Tunnel, OAuth/credential, authorization or relevant session change |

**Bounded single-operator network disposition (NET-05).** The [ratified decision](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7190415791) accepts the residual uncertainty of untested external LAN paths and unreviewed rules only for the existing dedicated WSL, trusted same-operator host, supervised HTTPS non-fixture probe/diagnostics and typed LB-06 read-only profile. The [#48 extension](https://github.com/codefusion-repo/project-os-v3/issues/48#issuecomment-7193767732) includes only typed update/status/rollback of the same single reviewed installation. The baseline is [consolidated historical evidence](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7190026137), [live WSL evidence](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7190081967) and [Windows path observations](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7190363162): sole process-owned IPv4 loopback listener, no other Bridge-port listener, TLS metadata and anonymous 401, Linux IPv4/IPv6 forwarding disabled, no Windows TCP/8765 listener, portproxy or WinNAT mapping, same-host IPv6 TCP negative, and restrictive historical Windows/Hyper-V inbound defaults with reviewed rules not allowing TCP/8765. NET-02/03 observations are limited to these inspected mechanisms and policy, not exhaustive proof. The explicit residual disposition covers that remaining uncertainty in these controls for this profile only; do not require the same missing external-path proof under a different NET identifier.

NET-05 ACCEPTED_RESIDUAL remains scoped to the existing trusted host/operator/topology/policy/binding, current loopback/TLS/401/OAuth and no known material change or exposure. It is not LAN isolation PASS. Retain exact grants, credentials, privacy and applicable review. A new SHA or restart alone does not reopen the prior disposition. The definitive [WSL decision](https://github.com/codefusion-repo/project-os-v3/issues/8#issuecomment-7233893145) supersedes additional execution infrastructure certification.

Record only sanitized status, scope, source, observed time and material changes. Do not turn NOT_ASSESSED into PASS. A missing material activation control blocks the affected activation, not otherwise qualified maintenance.


## 2. Independent installation and boundary checks

Reuse the existing installation and [single-installation maintenance](README.md#single-installation-maintenance).

Run as the new service account. Replace REVIEWED_SHA with the full explicitly reviewed Git commit (not a tag, merge preview or abbreviated SHA). Stop at any failure. Before this step, verify the reviewed SHA and passing artifact-specific bootstrap applicability gate described in SECURITY.md; the PM-approved disposition is limited to the exact wheel and three advisories, not an override of scanner failures or other security gates. Verify host Python 3.12, distribution package provenance, OS/curl CA trust and security updates locally. The installer skips ensurepip, verifies the pinned pip wheel before execution and uses the reviewed Git tree and offline wheel installs. It requires direct HTTPS access to PyPI and files.pythonhosted.org; do not disable TLS or substitute a mirror/wheel on failure. Two independent source-tree builds must match SHA-256 before installation. Preserve the old installation and its state for rollback; a failed fresh installation is not activated or migrated. Record host Python/OS, OpenSSL, Git/curl and CA provenance locally, as well as the reviewed SHA, wheel digest and tests. No requirement to run CI-only scripts locally.

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

Reuse existing account and host evidence; review effective access only on material change. No duplicate account or host setup.

After independent review, in a NEW shell as the service user:

```bash
set -euo pipefail
cd "$HOME/bridge-kit"
test "$(id -u)" -ne 0
test "$(ps -p 1 -o comm=)" = systemd
systemctl --user show-environment >/dev/null


```

Keep privileged sockets inaccessible. Reuse the existing verified tunnel-client and dedicated credentials.

## 3. New HTTPS probe-only instance

Choose the strict path with a separate WorkOS staging identity/application and separate tunnel, or the conditional exclusive same-operator transition below. Both require scoped runtime key (Read + Use), exact issuer, resource and subject, MFA and disabled public signup per WORKOS.md. No real GitHub or device credentials. Never paste key, subject, configuration, certificates or raw logs into chat/GitHub. Ensure port 8765 is free; do not stop unknown listeners. Use a new private instance path outside Git.

### Exclusive same-operator staging transition

The existing operator retains the existing WorkOS identity, tunnel, scoped runtime key, TLS state and connector. No new host, credential or installation is required for routine maintenance.

Before any link/start, record the host and prepared probe-only boundary review required by stage 1 in section 1 and verify the installed tunnel-client version and upstream artifact hash, exact existing OAuth configuration and key scope privately. Confirm no compromise, incompatible outstanding sessions or grants; if scope, credential integrity or exclusivity is uncertain, stop and resolve it before startup. Verify the previous bridge, tunnel and workers are stopped, no competing tunnel session or pending jobs/uncertain effects remain (reconcile through section 6 where applicable), and the unit identity is not foreign. A free port alone is insufficient. Do not delete, migrate or overwrite the pilot state or configuration. Preserve the prior installation for rollback, without restarting its plaintext or rejected-image configuration as a production fallback.

Use the reviewed installed runtime, new private root/state, new local TLS material, and prepared unit, with no inherited state, grants, fixture binding or opt-in. Reuse the exact already verified runtime artifact and completed preparation when still applicable; a documentation-only policy revision does not by itself require rebuilding or rerunning a wizard. Verify the integrated revision and unchanged runtime/build inputs before reusing earlier artifact evidence; record both references without claiming installation at a different SHA. If preparation already exists, validate it in place using the installed supervisor configuration checks and lifecycle status; skip the initializer commands below. A partial or foreign preparation blocks, rather than authorizing overwrite.

Verify current TLS, OAuth and authorized health after a material cutover. Preserve prior state and evidence; no automatic enrollment or additional credentials.

```bash
set -euo pipefail
umask 077
cd "$HOME/bridge-kit"
ROOT="$HOME/bridge-production-probe"
test ! -e "$ROOT" && test ! -L "$ROOT"
local-bridge/.venv/bin/project-os-bridge-init --root "$ROOT"
# Enter verified canonical tunnel executable and key privately; fixture disabled.
local-bridge/.venv/bin/project-os-bridge-init --root "$ROOT" --prepare-service
test ! -e "$ROOT/state/allow-authenticated-probe"
systemd-analyze --user verify "$ROOT/service/project-os-bridge.service"
# Use the reviewed installed bridge venv Python, not the system Python.
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" link
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" start
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" status

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

After stage 2 live pre-opt-in checks pass, and only within the authorized NEW disposable probe scope, create its empty local opt-in using `(umask 077; set -o noclobber; : > "$ROOT/state/allow-authenticated-probe")`. Attach the separate OAuth connector for the strict path, or verify/refresh the existing connector for the exclusive transition; confirm health reports no real repository access and no fixture availability, submit a unique disposable probe, replay the same request key and compare job ID/evidence. Remove only that known empty marker to revoke access; expect FORBIDDEN, not a reconnect loop. Restore with the same noclobber command, check health and job evidence again. Verify fixed-schema local audit 403 without publishing identifiers. Stop if any unexpected behavior.

```bash
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" stop
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" status
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" start
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" status
```

For the authorized operational diagnostic capability, follow the README section: verify sanitized live sections, deny after removing its separate marker, restore and verify, then remove it before stopping. Unknown/unavailable observations are not PASS; reuse existing evidence and evaluate material gaps. Repeat TLS checks and MCP health/replay after restart. End by revoking only the new probe flag if present and stopping this unit. Preserve state, configuration and logs. No deletion, no enabling or migration of the pilot. If a forced stop occurred, reconcile jobs/processes before restarting. Inspect lifecycle status: do not mutate while pending_job=True. If failed persists after diagnosis and reconciliation, use the same reviewed venv's lifecycle reset-failed explicitly; it does not start the service or clear durable effects. Issue a separate authorized start only when quiescence and recovery have been verified.

## 5. Separate fixture and production gates


## 6. Local reconciliation after uncertain fixture effects

An unresolved effect fences later jobs. Stop the existing service, verify the exact job's processes/effects are quiescent locally, then use the existing reconciliation command. No automatic replay or removal of unrelated resources.

Stop the existing service and verify the exact job's processes are quiescent locally before acknowledging.

```bash
# Only on the explicitly reviewed independent installation, as its service user.
local-bridge/.venv/bin/python -I -m project_os_bridge.reconcile --state-dir "$ROOT/state" --list
```

The command reports pending job IDs and recorded effect identity availability. It preserves interrupted jobs and never replays them.

After proving prior execution is quiescent and obtaining explicit permission, confirm only the exact job from the list:

```bash
read -rp 'Exact pending job ID: ' JOB_ID
local-bridge/.venv/bin/python -I -m project_os_bridge.reconcile --state-dir "$ROOT/state" --confirm-absent "$JOB_ID" --confirm-quiescent
```

Confirm only the exact job after local verification of quiescence. Preserve unresolved historical effects.

Historical execution evidence remains in Git.


### LB-07 trusted local execution — current decision

AgentsUbuntu is the sole local execution environment. Use the installed toolchains and registered Jobs; GitHub Connector handles remote writes, and MCP provides grouped context and typed local execution. Trusted project processes run with the local account's authority, not a sandbox. Keep private grants, scoped credentials, exact revision and lockfile, bounded process lifecycle and durable evidence.

### LB-07 bounded single-operator functional acceptance

Before and throughout heavy work observe actual Windows backing-volume free space, preserving 20 GiB plus stop margin, not WSL virtual capacity. Use existing native observation and sequential jobs. If capacity cannot be observed, do not enroll or launch heavy profiles. If the margin is threatened revoke the execution binding or stop the service, verify process quiescence, preserve evidence and clean only job-owned regenerable outputs. No new monitor. Verify bounded functional evidence and actual QA delivery when authorized.
