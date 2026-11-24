# Independent self-hosted security model

One local operator, one WorkOS identity per instance. Project OS distributes code, not hosted accounts, tokens, infrastructure or project data. Each operator owns the local installation, separate OAuth application/issuer configuration, tunnel, GitHub credentials, SQLite state and artifact store. Never distribute an instance configuration or use the reference operator's accounts. Collaborative RBAC and centralized SaaS are out of scope. Public source is not a license grant; maintainers must explicitly select a redistribution license.

## Threat model

- Internet caller without a valid token: deny; public metadata is intentional.
- Another authenticated subject: reject even when the issuer and signature match.
- Stolen bearer token: short expiry and local opt-in limit exposure; no proof-of-possession or immediate IdP introspection.
- Malicious payloads, issue text, repository files: untrusted data, never permission or arbitrary command input.
- Resource exhaustion: global 120 HTTP admissions per rolling minute, 8 concurrent requests, 32 active jobs per principal and 10000 retained jobs per database. Global limit can deny legitimate traffic; process restart resets it. No claim of DDoS resistance.
- Audit: private bounded JSONL (4 MiB), fixed timestamp/event/status only. Admission must be recorded before forwarding; completion is best effort if disk fails after admission. Local operator must archive/rotate offline; no automatic removal. No tamper resistance against same-user processes.
- Host compromise, hostile OCI image, kernel escape or same-user malicious process: outside disposable guarantee. No untrusted repository execution.
- WSL/Windows: a separate Linux UID alone is not a Windows boundary. Restrict Windows mounts, interop, host shares and network access using a dedicated environment before real resources. AppArmor/SELinux absence is a documented limitation, not a reason to disable protections.

## Installation

Use a dedicated unprivileged Linux service account with no sudo, no personal home access, no privileged socket membership and separate scoped credentials. Provisioning accounts, filesystem ACLs and WSL policy is an explicit operator task; the wizard does not do this. Rootless Podman must use that account's own subuid/subgid and storage. Do not share the PM's personal gh config. Keep runtime keys out of arguments, logs and Git. Use a new private canonical directory outside all checkouts, mode 0700; files 0600. The init command creates only new local configuration, no opt-in. Existing installations are not migrated.

Use a reviewed full Git SHA, a dedicated venv, pinned direct dependencies, pip check, and unit tests before startup. Transitive lockfiles, supply-chain audit and clean-device reproducibility are outstanding. Do not auto-install system packages or disable OS security protections. Use the exact issuer and resource for each operator, with signup disabled and MFA. Dedicated tunnel staging only; plaintext Harpoon exception is not acceptable for real resources. Retire unused unauthenticated connector and stop old stdio endpoint before real resources.

## Gate matrix

1. Live OAuth and local revocation/restore (401 vs 403), including persistence across restart.
2. Exact-subject denial and ownership checks; no real providers registered remotely.
3. Disposable Git change and trusted digest-pinned Python validation.
4. Negative isolation checks: rootless, Seccomp, cgroup v2 preflight; fixed in-container program checks exact bytes, fixture write denial, synthetic host sentinel and known socket absence, loopback-only interfaces, capabilities, NoNewPrivs, read-only root, CPU/memory/pids limits. Cleanup requires container absence. Failure blocks success. These checks are narrow, not an exhaustive mount/network/escape proof.
5. Dedicated service account, WSL boundary review, independent scoped credentials, dependency/image vulnerability assessment and independent clean install.
6. Only then review a separate explicit grant for any real resource. Never expose arbitrary shell, arbitrary ADB, untrusted repository execution or shared personal credentials.

Android attach is future work: detection is not device authorization or boot readiness; use an approved emulator, exact APK digest and bounded operations. No device access tools are registered.

## Pilot evidence (operator reported, sanitized)

At 8142b3f63c5cf31b244c3b87b5858a35ce3275ae, WSL update and pip check passed; 51 local tests passed. Metadata returned 200 and missing-token request 401. Podman 4.9.3 rootless, Seccomp, cgroup v2 and overlay confirmed; privileged socket disabled and both sockets inactive. AppArmor/SELinux unavailable. Official Python image pinned by digest; actual disposable Git worktree patch preserved original checkout, container returned 0 and SQLite recorded QUEUED/RUNNING/SUCCEEDED. ADB detected a connected emulator; emulator executable and Windows interop not detected by preflight. This proves the earlier narrow fixture, not the new negative gate, live revocation, cross-restart OAuth job persistence or Android QA. No personal identifiers, paths, tokens or raw logs are published.

## Integrated disposable workflow

HTTP mode remains single-subject. An explicit local `--fixture-image` digest binds the fixed fixture to the private HTTP state; no tool input can select the image, path or code. Without this option, the fixture tool is absent. Removing the binding prevents new fixture submissions and blocks queued fixtures at dispatch; already running work is not cancelled. Changing the image requires a new state directory. The queue permits at most eight retained fixture jobs, including terminal states; never delete automatically. Rejected rate-limit events are sampled at most once per minute to reduce log flooding. Access logs are disabled; fixed-schema HTTP audit remains. Real resources remain blocked. CI mocks the container; live negative checks and transport validation are required before enabling further capabilities.

## Production transport and readiness follow-up

The validated disposable pilot at d5bf579b5adf43a6b8893d3d2005b5578f8b5f97 completed WSL tests, the ten isolation checks, live authenticated fixture, replay, restart and local authorization deny/restore. See PR #9 execution records LB-MVP-20261124-04 through -09. The connector returned FORBIDDEN; raw local 403 audit and aggregate job count were not independently inspected. This is not production certification. Optional private loopback TLS now accepts a validated certificate/key pair; the TLS tunnel must be tested live without the plaintext exception before real resources. The ADB inventory reports connected emulator transports separately from executable detection; it does not authorize or operate devices. Dedicated account, credential isolation, clean installation, dependency/image review and explicit resource grants remain mandatory.

## Account boundary inventory

Run `python3 local-bridge/scripts/account_preflight.py` as the intended service user. It checks UID, known privileged groups, private home, effective traversal of other enumerated non-system homes, known privileged sockets, visible mount types and WSL interop indicators. It prints only booleans, never paths or account names. WSL always requires a separate host-boundary review; no automatic real-resource grant. This inventory cannot prove sudo policy, all ACLs, namespaces, remote endpoints or credential scopes. Do not run it as root to simulate the service account.
