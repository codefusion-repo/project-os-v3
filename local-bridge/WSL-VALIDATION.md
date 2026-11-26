# Independent WSL production validation (operator runbook)

Status: preparation only. Do not modify the existing pilot or enable real resources. The reference image remains rejected (historical run 45446812446); CI accepts only the locked fixture-only digest under the policy in SECURITY.md. No local binding or execution is approved. A separate image review is mandatory before any fixture execution with a replacement. Probe-only HTTPS validation can proceed independently once its own prerequisites pass.

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

### Existing dedicated WSL: single-operator profile (conditional evaluation)

The operator may retain the existing dedicated agent distribution, Linux identity, central kit, development checkout and intentional exchange share. Do not require another account or distribution just to repeat setup. This profile treats Windows, the operator and trusted same-UID local agent processes as trusted; it does not claim isolation from them, a compromised host, or hostile code running on the host as that UID. Untrusted input and repository-controlled execution must remain within registered, bounded handlers and separately validated execution profiles. See [SECURITY.md](SECURITY.md#single-operator-trust-boundaries).

The strict independent-host path above remains available. The existing-WSL profile is a conditional alternative for LB-05 operational certification independent of the historical pilot, not proof of a separate host. No activation or acceptance follows from selecting it. The current inventory is intentionally conservative: sudo group membership and visible host mount types still produce negative indicators; there is no bypass flag, path allowlist or automatic approval. Before relying on the alternative, an independent security review must verify all of the following on the actual host and actual execution identities, record disposition of each strict negative and approve only the bounded profile:

- Identify WSL distribution/host provenance, effective Windows account/ACLs and Linux UID, groups, HOME (0700), private instance directory and file permissions. No shared personal credential stores or privileged sockets. The existing dedicated UID is acceptable only when its effective boundary passes; additional identity or VM is a mitigation if the required boundary cannot otherwise be achieved.
- Inspect effective sudo policy locally (including all included rules, NOPASSWD, authentication/timestamp scope, setuid helpers and alternative elevation routes). Group membership alone neither proves nor disproves unattended escalation. No unrestricted unattended elevation or agent access to administrator authentication; a noninteractive probe is only supporting evidence. Do not remove sudo membership or change policy automatically. Require non-root bridge and no permitted/effective/ambient capabilities. NoNewPrivs is observed in the shell; require it where the isolated execution contract requires it, not blindly on the host Podman helper path.
- Identify every host-backed mount, source/options, bind alias and namespace/propagation relation. Driver-path label is not provenance. An intentional exchange share can remain accessible to the trusted local agent only within the reviewed Windows ACL boundary; no personal files or secrets in it. Prove access outside the approved share is denied with a synthetic marker before probe-only activation. Separately prove that untrusted job profiles cannot reach the share, personal credentials, host sockets or other unauthorized paths in the live execution gate in section 5. DAC at a single mount root is not proof. Do not dismantle WSL infrastructure or alter the share to manufacture a passing result.
- Review effective Windows/Hyper-V firewall, listeners and reachable host/LAN endpoints, WSL interop, DNS/proxy inheritance and credential scope. Mirrored networking, firewall=true, DNS tunneling and autoProxy are configuration, not proof of isolation. Verify the reviewed loopback-only TLS configuration before startup and the actual listener, absence of alternate plaintext endpoints and effective reachability before authenticated opt-in in section 4; do not widen firewall rules. Inspect proxy configuration privately and report only presence/disposition, never values. See https://learn.microsoft.com/windows/wsl/networking and https://learn.microsoft.com/windows/wsl/file-permissions.
- Review rootless Podman, Seccomp, cgroup v2, distinct subordinate ID ranges and storage as host prerequisites; validate actual untrusted-job namespaces, capabilities, no-new-privileges, mounts, network and cleanup in the separate execution gate in section 5. No image pull/import/run until its separate authorization and audit gates.
- Verify a clean reviewed installation (existing verified installation evidence may be reused for the exact SHA/artifact if still applicable), fresh private instance state, either independent staging OAuth identity and tunnel or the exclusive same-operator transition in section 3, no inherited pilot job state/grants and quiescence/reconciliation of earlier effects. Keep current central kit and development checkout; no automatic reinstall, credential copying or destructive cleanup.

Run the inventory as the intended user; a negative strict result remains a stop point for strict certification. For the conditional profile it identifies review work, not permission to start the bridge. Review all observations and retain the independent security review and actual positive/negative host evidence in #14 before proceeding to the new probe-only instance, using the capability sequence below. If evidence cannot establish the applicable boundary, keep that stage BLOCKED and choose a stronger isolation mechanism; do not certify by accepting a risk silently. No new human confirmations for each authorized task: OAuth/resource grants and operation scope define the limits; job checks execute automatically. This profile never authorizes real resources, arbitrary shell, Android, Codex or OCI.

### Capability gate sequence (both profiles)

The PM-authorized correction in [#14](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7156319052) separates the live OCI execution gate from transport validation. It changes sequencing only, not the required controls or final LB-05 acceptance criteria.

1. **Before link/start (host and prepared probe-only surface):** complete the applicable host/credential boundary review above, including effective elevation, mount aliases and host namespaces, ACLs, sockets, firewall/network configuration, subordinate ranges/storage, private state and prior-effect reconciliation. Reuse valid evidence for the same host, identity and artifact; record unresolved findings and block startup on any material host or configuration uncertainty. Verify the reviewed runtime, no fixture image or binding, fresh private state without inherited jobs/grants, opt-in absent, exact OAuth configuration, verified scoped tunnel credentials and exclusive cutover where applicable. The reviewed authenticated server admits only `probe_check` jobs in this mode (fixed private SQLite read; no caller-controlled code or paths); synthetic GitHub context is not a real provider. The PM-approved [operational diagnostics](README.md#operational-diagnostics-lb-05) collector can run locally before startup, without remote opt-in or sudo; its separately authorized read-only MCP tool becomes usable only after stage 2 pre-opt-in checks and its own local marker. It is not a job, fixture, real-repository provider or host certification. No OCI, arbitrary shell, real repositories, Android or Codex. Do not require live OCI job evidence for this strictly bounded startup.
2. **After link/start, before authenticated opt-in:** verify the actual process identity/capabilities, loopback TLS listener and absence of an alternate plaintext endpoint or unauthorized reachability, readiness metadata and unauthenticated 401 in section 4. If a live host/transport control fails or remains uncertain, keep opt-in absent and stop the identified unit. After these checks and within the authorized disposable scope, test live OAuth, exact principal/resource/scope, replay, revocation/restore, audit and restart/stop; require live discovery/health to confirm no fixture or real providers. On unexpected capability exposure revoke and stop. This stage proves only the bounded transport/probe, not the sandbox or full host/production certification.
3. **Separate OCI validation, before enabling fixture or untrusted execution:** complete section 5 and OCI-LOCAL-VALIDATION.md under their separate authorizations. Require fresh image audit and exact digest before the separately authorized, bounded validation run; that run must establish actual job isolation including Exchange/personal credentials/socket/unauthorized-path denial, namespaces, capabilities, NoNewPrivs, mounts, network and verified cleanup before any subsequent fixture use or untrusted execution. Neither probe-only success nor CI substitutes for these controls. If the required evidence is missing, execution stays BLOCKED. Finish and stop the probe-only service before any separate fixture validation.
4. **Before real resources or LB-05 completion:** all applicable preceding evidence, including live OCI isolation, review and rollback, must pass. Real-resource grants remain separately authorized and gated; no grant or certification follows from startup alone.

## 2. Independent installation and boundary checks

The clean independent procedure below is initial certification, not a new checkout per update. For an existing certified instance use [single-installation maintenance](README.md#single-installation-maintenance), which retains the original checkout, verified artifact, prior state and rollback; do not repeat initial setup or create new credentials.

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

For the strict path, the last nonzero exit is a stop point, not a bypass. The additional mount booleans are diagnostic subdivisions; neither changes the required windows_mounts_absent result. Process capabilities must be absent; NoNewPrivs is an observation in this inventory, not a substitute for the in-job check. Review every boolean; require positive unprivileged UID, groups, home, other homes, sockets, Windows mounts absent and interop not observed. WSL review is always required. Independently inspect sudo policy, ACLs, mount namespace, /etc/fstab, host shares, network/firewall, systemd user session, and separate rootless Podman storage. Verify the service account cannot access a synthetic marker outside its boundary (no actual secrets). Do not copy private files, personal gh credentials, or the existing pilot state. The host administrator may still access WSL; no hostile-host isolation is claimed.

After independent review, in a NEW shell as the service user:

```bash
set -euo pipefail
cd "$HOME/bridge-kit"
test "$(id -u)" -ne 0
test "$(ps -p 1 -o comm=)" = systemd
systemctl --user show-environment >/dev/null
/usr/bin/podman info --format json | python3 -I -c '
import json, sys
host = json.load(sys.stdin)["host"]
security = host["security"]
assert security["rootless"] is True
assert security["seccompEnabled"] is True
assert host["cgroupVersion"] == "v2"
print("PODMAN_SECURITY_PASS")
'
```

Keep all privileged sockets inaccessible. No image pull/run in this step. Install the separately verified tunnel-client binary (version and upstream hash checked independently) without personal credentials.

## 3. New HTTPS probe-only instance

Choose the strict path with a separate WorkOS staging identity/application and separate tunnel, or the conditional exclusive same-operator transition below. Both require scoped runtime key (Read + Use), exact issuer, resource and subject, MFA and disabled public signup per WORKOS.md. No real GitHub or device credentials. Never paste key, subject, configuration, certificates or raw logs into chat/GitHub. Ensure port 8765 is free; do not stop unknown listeners. Use a new private instance path outside Git.

### Exclusive same-operator staging transition

PM decision [LB05-20261125-REUSE-PILOT-INFRA-01](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7155949280): the existing operator may retain the pilot's WorkOS staging application/issuer, subject, tunnel/resource, restricted runtime key and OAuth connector. This is a sequential cutover, not concurrent operation or independent credential/host certification. No mandatory duplication or routine key rotation. The strict separate-infrastructure path remains available, and distinct operators must never share credentials.

Before any link/start, record the host and prepared probe-only boundary review required by stage 1 in section 1 and verify the installed tunnel-client version and upstream artifact hash, exact existing OAuth configuration and key scope privately. Confirm no compromise, incompatible outstanding sessions or grants; if scope, credential integrity or exclusivity is uncertain, stop and resolve it before startup. Verify the previous bridge, tunnel and workers are stopped, no competing tunnel session or pending jobs/uncertain effects remain (reconcile through section 6 where applicable), and the unit identity is not foreign. A free port alone is insufficient. Do not delete, migrate or overwrite the pilot state or configuration. Preserve the prior installation for rollback, without restarting its plaintext or rejected-image configuration as a production fallback.

Use the reviewed installed runtime, new private root/state, new local TLS material, and prepared unit, with no inherited state, grants, fixture binding or opt-in. Reuse the exact already verified runtime artifact and completed preparation when still applicable; a documentation-only policy revision does not by itself require rebuilding or rerunning a wizard. Verify the integrated revision and unchanged runtime/build inputs before reusing earlier artifact evidence; record both references without claiming installation at a different SHA. If preparation already exists, validate it in place using the installed supervisor configuration checks and lifecycle status; skip the initializer commands below. A partial or foreign preparation blocks, rather than authorizing overwrite.

Complete fresh live TLS, OAuth principal/resource/scope, 401/403 and no-new-job evidence, replay and lifecycle checks in section 4 against the intended HTTPS instance. Existing connector sessions are not proof of current authentication; verify the exact destination, fresh authorization and tool discovery (no fixture or real resources), refresh/reconnect if needed without duplicating the connector by default. Reject incompatible sessions or unresolved effects. The local opt-in is not IdP token revocation. Keep only the new service active during the test, then revoke its opt-in and stop it. No real-resource or OCI authorization follows.

```bash
set -euo pipefail
umask 077
cd "$HOME/bridge-kit"
ROOT="$HOME/bridge-production-probe"
test ! -e "$ROOT" && test ! -L "$ROOT"
local-bridge/.venv/bin/project-os-bridge-init --root "$ROOT"
# Enter verified canonical tunnel executable and key privately; fixture disabled.
local-bridge/.venv/bin/project-os-bridge-init --root "$ROOT" --prepare-service --no-fixture
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

For the authorized operational diagnostic capability, follow the README section: verify sanitized live sections, deny after removing its separate marker, restore and verify, then remove it before stopping. Unknown/unavailable observations are not certification; reuse existing evidence and evaluate material gaps. Repeat TLS checks and MCP health/replay after restart. End by revoking only the new probe flag if present and stopping this unit. Preserve state, configuration and logs. No deletion, no enabling or migration of the pilot. If a forced stop occurred, reconcile jobs/containers before restarting. Inspect lifecycle status: do not mutate while pending_job=True. If failed persists after diagnosis and reconciliation, use the same reviewed venv's lifecycle reset-failed explicitly; it does not start the service or clear durable effects. Issue a separate authorized start only when quiescence and recovery have been verified.

## 5. Separate fixture and production gates

Do not pull or run the blocked reference image or any candidate without separate approval. Scan an exact platform manifest digest, require zero HIGH/CRITICAL and non-EOL with complete inventory; review MEDIUM/LOW/UNKNOWN and scanner/database freshness. Then with explicit permission use a fresh disposable fixture state, exact audited digest, the prepared private Podman context, all ten existing isolation checks and the additional fixed checks below. No changes to an existing image binding. Static scan alone is not functional validation. For the separately authorized, bounded validation run apply stage 3 in section 1; before enabling subsequent fixture use or untrusted execution require actual job-level denial of Exchange, personal credentials, host sockets and other unauthorized paths, actual namespace/mount/network/capability/NoNewPrivs evidence and verified cleanup. If the existing fixed fixture cannot establish a required control, keep that capability BLOCKED until a separately reviewed bounded test establishes it. Do not use arbitrary shell or substitute host marker evidence.

The fixed fixture compares the job's user, mount, PID, IPC, network, cgroup and UTS namespaces with the host. It checks the actual mount table against an allowlist of kernel mounts, standard character devices with exact IDs, context-generated files and the exact read-only synthetic export. Host-backed filesystem types and other mount targets fail closed. Podman runs with the numeric keep-id mapping and disables generated account-file mounts. It verifies absence of synthetic Exchange and credential markers, a synthetic Unix socket, known credential/socket locations and observed host-backed mount paths. The program does not read real credentials or mount Exchange. Review host aliases and all relevant boundary paths independently, and block certification if the fixed observations cannot establish the intended boundary. Preserve only sanitized check names and outcomes in published evidence.

Report only reviewed SHA, installer/test counts and exit statuses, preflight booleans, TLS 200/401, MCP readiness/403/replay equality, systemd stop/start status, approved image digest and aggregate audit findings. Keep secrets and private identifiers local. All gates plus an independent security review and separate explicit resource grant are required before real access. This runbook does not grant authorization.


## 6. Local reconciliation after uncertain fixture effects

The new queue records a random fixture ownership token and the verified Podman context identity in SQLite atomically with claim, before Podman can launch. The exact name and matching label identify the potential container; a timeout, unknown cleanup or interrupted fixture retains a durable barrier. No new job dispatch or new submission while pending (existing request-key replay and queued evidence are preserved); the HTTP process exits if the barrier remains after drain, and refuses restart. Normal Podman --rm is retained; the bridge never force-removes a container by name. No remote reconciliation tool.

Stop the dedicated service and verify it is inactive. Verify locally that no old worker, Podman client, helper or previous launch can still create/rename a container. If uncertain, do not acknowledge; preserve state and obtain operator assistance. Do not run this against a live legacy process or the pilot.

```bash
# Only on the explicitly reviewed independent installation, as its service user.
local-bridge/.venv/bin/python -I -m project_os_bridge.reconcile --state-dir "$ROOT/state" --list
```

The command reports only pending job IDs, exact container names and ownership labels, and whether the recorded context is known. It acquires exclusive service/worker locks, recovers interrupted rows without retrying, and does not touch containers. For an extant container, inspect the exact name and label under the recorded private Podman context; verify full immutable ID, matching ownership label and origin before any separately authorized removal by ID. Never remove arbitrary names, other jobs or all containers. This runbook does not authorize removal. If the ownership token or context identity is null (legacy uncertain job), it cannot be acknowledged by this CLI; preserve the state and resolve independently, with explicit operator review. No implicit migration or fresh-state workaround for uncertain effects.

After proving prior execution is quiescent and obtaining explicit permission, confirm only the exact job from the list:

```bash
read -rp 'Exact pending job ID: ' JOB_ID
local-bridge/.venv/bin/python -I -m project_os_bridge.reconcile --state-dir "$ROOT/state" --confirm-absent "$JOB_ID" --confirm-quiescent --podman-context "$PODMAN_CONTEXT"
```

The command queries exact name absence and absence of any container with the unique ownership label, only after verifying the supplied context against the durable effect. A missing or different context, nonconclusive response or timeout leaves the barrier intact. Preserve the original context and obtain independent review if its identity cannot be established. It records resolution without changing terminal job evidence or rerunning the job. Re-list and verify no barriers before independently authorizing service startup. The quiescence assertion is operator evidence, not proof against hostile same-user processes; keep the dedicated account boundary.

For independent candidate reproduction see [OCI-LOCAL-VALIDATION.md](OCI-LOCAL-VALIDATION.md). Preparation only; no image or fixture approval follows.
