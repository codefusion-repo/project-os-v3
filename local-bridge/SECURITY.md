# Independent self-hosted security model

> **Current decision (2026-11-28):** [AgentsUbuntu only](https://github.com/codefusion-repo/project-os-v3/issues/8#issuecomment-7233893145). No additional execution environment or infrastructure certification. Historical evidence remains in Git. Candidate code does not establish live acceptance.


One local operator, one WorkOS identity per instance. Project OS distributes code, not hosted accounts, tokens, infrastructure or project data. Each operator owns the local installation, OAuth application/issuer configuration, tunnel, GitHub credentials, SQLite state and artifact store, separate from other operators. Never distribute an instance configuration or use the reference operator's accounts. Collaborative RBAC and centralized SaaS are out of scope. Public source is not a license grant; maintainers must explicitly select a redistribution license.

## Threat model

- Internet caller without a valid token: deny; public metadata is intentional.
- Another authenticated subject: reject even when the issuer and signature match.
- Stolen bearer token: short expiry and local opt-in limit exposure; no proof-of-possession or immediate IdP introspection.
- Malicious payloads, issue text, repository files: untrusted data, never permission or arbitrary command input.
- Resource exhaustion: global 120 HTTP admissions per rolling minute, 8 concurrent requests, 32 active jobs per principal and 10000 retained jobs per database. Global limit can deny legitimate traffic; process restart resets it. No claim of DDoS resistance.
- Audit: private bounded JSONL (4 MiB combined active budget), unchanged security-audit.jsonl timestamp/event/status schema. Separate oauth-audit.jsonl records only the matching timestamp/event/status and an allowlisted authentication outcome for MCP completions; no token, claim value, header, route, or identifier. Admission checks both files and budget before forwarding. The primary HTTP completion is written before opening/creating the supplemental file when its private metadata and the shared budget can be verified. Supplemental observations are best effort and can be missing on capacity or I/O failure, without changing HTTP behavior. If safety or the shared budget cannot be verified, neither completion is appended. Completion failures produce a fixed local warning distinguishing primary audit failure from supplemental observation failure; no exception text or request data is logged. Standard HTTPStatus enum values emitted by the SDK are normalized to plain integers; booleans, strings and floats are rejected. Local operator must archive/rotate offline; no automatic removal. Before rollback archive the supplemental file intact as described in WORKOS.md; the legacy reader and writer remain compatible with the unchanged primary stream. No tamper resistance against same-user processes.
- Host compromise and malicious same-user code are outside the trusted local execution boundary.
- WSL/Windows: a separate Linux UID alone is not a Windows boundary. Restrict Windows mounts, interop, host shares and network access using a dedicated environment before real resources. AppArmor/SELinux absence is a documented limitation, not a reason to disable protections.

## Single-operator trust boundaries

A dedicated agent OS identity can be reused for the bridge under the conditional existing-WSL profile in [WSL-VALIDATION.md](WSL-VALIDATION.md). A second Linux account is not inherently required for this product. It is required only when needed to establish the effective boundary; a separate host is required for claims of separate-host independence. The operator/Windows host and trusted same-UID local agent are inside the trust boundary: owner-only permissions, OAuth and local state do not protect against a hostile process with that UID. A local shell with access to broader GitHub credentials can bypass bridge grants; do not describe these grants as enforcement on arbitrary local shell. Untrusted callers, data and repository-controlled execution are outside the boundary; keep them in typed handlers and validated restricted execution profiles, never pass through host shell or credentials.

The PM authorizes a task by operation and resource. Read/write/build/test/commit and other inherent steps within that scope do not require interactive approval per step; authorization, resource grants, revocation, dispatch and isolation checks remain automatic and fail closed. Changes of scope, privileges or credentials are not implied by ordinary job autonomy. No unattended privilege escalation, privileged sockets, personal Windows credentials or unauthorized mounts/network in untrusted jobs. A sudo group label or an exchange directory is not by itself a decision on effective access. Review sudo policy, host ACLs, mount provenance/aliases, actual process/job namespaces, credentials and reachable endpoints; keep the strict inventory unchanged as a conservative signal. Existing-WSL acceptance is conditional on independent live evidence and review, not an automatic exception or an assertion of hostile-host isolation.

For the same operator's exclusive staging cutover, the existing OAuth application/issuer, subject, tunnel, scoped runtime key and OAuth connector may be reused under [WSL-VALIDATION.md](WSL-VALIDATION.md#exclusive-same-operator-staging-transition) and the [PM decision](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7155949280). The pilot must be quiescent and prior effects reconciled, with no concurrent use of its tunnel or unit. Require verified key scope, exact issuer/resource/subject, MFA, current authorization and fresh live transport/authentication evidence. Shared staging credentials are not independent credentials; never share across operators. Keep the new runtime instance's TLS, private state and grants separate, deny fixture and real resources, and preserve the old installation. No routine recreation or rotation; stop if compromise, incompatible sessions or uncertain effects are observed.

## Installation

Use the existing reviewed installation; historical LB-01/02 evidence remains in Git.

Use the existing unprivileged AgentsUbuntu identity, private state, scoped credentials and stopped-unit maintenance with rollback. No new environment or installation.

Verify reviewed SHA, dependency locks and wheel, applicable CI, private credentials and current HTTPS/OAuth before use.

## Operational diagnostic boundary

The [LB-05 diagnostic capability](README.md#operational-diagnostics-lb-05) is separately authorized by the PM, exact host resource grant and owner-private marker in the existing supervised HTTPS instance with no fixture. Validate caller and both local gates before and after each collection; HTTP admission/audit remains unchanged. Fixed section enum, fixed input sources, sanitized numeric/boolean/status outputs, bounded reads/SQL/network and read-only exact unit inspection; no arbitrary command, path, URL, raw logs, credentials, other caller data or remote privilege elevation. Local CLI uses the same collectors without remote opt-in. Observations do not certify effective policy, Windows host boundary, historical effects. No new privileged runtime, no exposure before applicable stage 2 gates; no resource grant by discovery alone.

## Gate matrix

Apply the [capability gate sequence](WSL-VALIDATION.md#capability-gate-sequence-both-profiles). Verify only applicable material controls; missing execution-only evidence does not block independent reads.

| Capability | Required gates before use |
|---|---|
| Remote maintenance (#48) | Reviewed single-operator non-fixture instance, authenticated principal and separate owner-private opt-in, explicit target SHA/CI digest, canonical main and successful required CI, exact non-expired run-attempt wheel evidence before quiescing and independent installer digest validation, existing stopped-unit gates and recoverable runtime. One independent transient service, durable non-replayed request/result, restore only prior opt-ins after local TLS/401 readiness; no arbitrary commands, paths, URLs or grants. Local recovery if transport fails. Apply the bounded NET-05 disposition in WSL-VALIDATION.md only within its expressly extended #48 scope. Review and applicable preconditions before explicit enrolment for bounded dogfood; successful operational validation before routine use/acceptance.  |
| Stopped-unit maintenance | Reviewed host/toolchain, exact integrated SHA and CI wheel, private paths, all-principal jobs/effects reconciled, exclusive locks, effective persistent fence, absent opt-ins and recoverable prior runtime. A completed normal rollback can be archived intact under the same guards. Live listener, Windows/LAN reachability, OAuth are not admission gates to this stopped operation; they remain required for applicable activation. No auto-start, grant changes or deletion. |
| Probe and operational diagnostics | Effective host/credential boundary and reviewed installation before startup; live process/HTTPS and authentication controls before opt-in; exact caller, fixed typed scope, revocation and audit. Diagnostics has its own grant and marker. No real data or fixture in the probe-only profile. |
| LB-06 GitHub and methodology reads | Common controls above, including effective Windows/WSL boundary and the applicable network disposition in WSL-VALIDATION.md, plus independently reviewed non-fixture supervised read-only profile, explicit per-project grants, verified dedicated least-privilege GitHub credential and pinned repo identity, bounded typed input/output, provenance and integrity of methodology, untrusted-data handling, disclosure policy, privacy, audit and revocation. Verify preconditions before enabling the existing markers for bounded authorized live validation; require positive/negative resource, revocation and isolation-of-grants evidence before routine use and LB-06 acceptance. No repository-controlled code, arbitrary paths, shell, writes. |
| LB-07 local execution | Trusted owned project, exact revision/lock, profile grant, existing WSL toolchains, bounded process lifecycle, resource reuse and durable evidence. |


Apply [resource reuse](../PROJECT_OS.md#seguridad-transversal-y-límites): existing checkout and branches, installed SDKs and caches; no extra copies, worktrees or unnecessary downloads. Reuse the scoped network disposition only under unchanged conditions; not LAN isolation PASS.

1. Live OAuth and local revocation/restore (401 vs 403), including persistence across restart.
2. Exact-subject denial and ownership checks; no real access in probe-only mode, and deny ungranted resources in an authorized read-only profile.
3. Registered direct job with exact revision, durable result and idempotency.
4. Verify relevant denial and interruption behavior, not additional infrastructure.
5. Reuse applicable host, credentials and dependency evidence.
6. Verify exact grants and functional result for the requested operation.

Android attach is future work: detection is not device authorization or boot readiness; use an approved emulator, exact APK digest and bounded operations. No device access tools are registered.

## Pilot evidence (operator reported, sanitized)

Historical pilot evidence remains in Git and issue #14.

## Integrated disposable workflow

AgentsUbuntu is the sole local execution environment. Use the installed toolchains and registered Jobs; GitHub Connector handles remote writes, and MCP provides grouped context and typed local execution. Trusted project processes run with the local account's authority, not a sandbox. Keep private grants, scoped credentials, exact revision and lockfile, bounded process lifecycle and durable evidence.

An unresolved effect fences later jobs. Stop the existing service, verify the exact job's processes/effects are quiescent locally, then use the existing reconciliation command. No automatic replay or removal of unrelated resources.

## Production transport and readiness follow-up

The validated disposable pilot at d5bf579b5adf43a6b8893d3d2005b5578f8b5f97 completed WSL tests, the ten isolation checks, live authenticated fixture, replay, restart and local authorization deny/restore. See PR #9 execution records LB-MVP-20261124-04 through -09. The connector returned FORBIDDEN; raw local 403 audit and aggregate job count were not independently inspected. This is not production certification. Optional private loopback TLS now accepts a validated certificate/key pair; the TLS tunnel must be tested live without the plaintext exception before real resources. The ADB inventory reports connected emulator transports separately from executable detection; it does not authorize or operate devices. Dedicated account, credential isolation, clean installation, dependency/image review and explicit resource grants remain mandatory.

## Account boundary inventory

Run `python3 local-bridge/scripts/account_preflight.py` as the intended service user. It checks UID, known privileged groups, current permitted/effective/ambient capabilities, NoNewPrivs observation, private home, effective traversal of other enumerated non-system homes, known privileged sockets, visible mount types and WSL interop indicators. It prints only booleans, never paths or account names. The mount inventory distinguishes an exact driver-path label and other known host mount targets; both continue to block the strict absence gate. No path allowlist or provenance claim. The existing-WSL profile in WSL-VALIDATION.md is conditional: direct access denial or current capabilities under a dedicated UID does not replace effective elevation, host/namespace/ACL review or independent operational evidence. WSL always requires a separate host-boundary review; no automatic real-resource grant. This inventory cannot prove sudo policy, all ACLs, namespaces, remote endpoints or credential scopes. Do not run it as root to simulate the service account.

## Grouped independent validation

Use [WSL-VALIDATION.md](WSL-VALIDATION.md) for the existing environment; verify only material changes.


## Disposable OCI candidate evidence (not an approval)


## Historical installer bootstrap evidence and unresolved strict audit

At 08730766a9848bdeba1c54c31d35d1b2ed256dab, [run 45456518214 / probe](https://github.com/codefusion-repo/project-os-v3/actions/runs/45456518214/job/138667322563) verified the official pip 26.3 wheel before execution, installed exact runtime/build/bootstrap locks, passed 92 tests and all installer negative controls. No host ensurepip was invoked. The separate vendor inventory audit returned exit 1: five records (three distinct advisory IDs) against setuptools 70.3.0. See [PYSEC-2025-49 / CVE-2025-47273](https://github.com/advisories/GHSA-5rjg-fvgr-3xxf), [PYSEC-2026-3447 / CVE-2026-59890](https://github.com/advisories/GHSA-h35f-9h28-mq5c), [GHSA-xmj3-9gf7-h52w](https://github.com/advisories/GHSA-xmj3-9gf7-h52w). Their affected components are package_index, macOS sdist manifest handling and Windows legacy wheel installation respectively. [Upstream vendoring policy](https://pip.pypa.io/en/stable/development/vendoring-policy/) states that only pkg_resources is retained from setuptools. The pinned wheel verifier now checks that layout before execution. Top-level build backend is separately pinned at 84.2.1. The full version-based scanner still fails, with no ignores or risk acceptance. Component absence is narrow applicability evidence, not an approved exception or a universal security claim; review the actual new CI result before independent installation. Host Python, CA store, curl/Git/tar, OS and audit-tool dependency closure remain external trust prerequisites. No local install or image approval follows.


## Uncertain fixture effects

An unresolved effect fences later jobs. Stop the existing service, verify the exact job's processes/effects are quiescent locally, then use the existing reconciliation command. No automatic replay or removal of unrelated resources.


## Historical LB-01 production bootstrap chain (before completion)
At cb6477fe3262331ba2bfe7210c6840891ee44b42, [CI probe 138684808271](https://github.com/codefusion-repo/project-os-v3/actions/runs/45461450339/job/138684808271) passed 109 tests and two byte-identical project wheel builds (SHA-256 3c7696bcf885c0b74166b5731ff5266ed9c7cedf8876fc189916e2b82123223a). The discovery run recorded the exact 29 auditor wheel hashes and deliberately failed before running unlocked auditor code. The next revision pins this observed closure and requires fresh verified download, installed closure, strict auditor dependency and vendor reports, coverage and consistent exit status. No audit ignore or applicability exception is installed. The retained pkg_resources source and vendor inventory are compared with the exact publishing commit 191854fba83d1c69534f974564af85632372d995 listed in [PyPI wheel provenance](https://pypi.org/project/pip/26.3/); source comparison is distinct from independent cryptographic attestation verification, which is not claimed. As of 2026-11-24, 26.3 is the latest official release and the upstream vendoring policy intentionally retains pkg_resources. A private fork or metadata alteration solely to satisfy the scanner is not justified. The three prior advisories remain visible and any formal not_affected disposition requires PM authorization limited to the exact artifact, not risk acceptance or a blanket exception. Host interpreter, distribution security updates and CA/tool provenance remain operator-verified trust inputs; CI records versions but does not certify WSL. See #10 and the updated README for fresh-install/rollback boundaries.

The lock-enforced run [45461791318 / probe](https://github.com/codefusion-repo/project-os-v3/actions/runs/45461791318/job/138686032274) passed 112 tests, two identical wheel builds, exact 29-package auditor closure and strict audit (29 packages, zero findings). The three retained upstream members matched byte-for-byte. The strict bootstrap vendor report covered 19 packages and returned five records / exit 1, all from the three previously identified setuptools advisories. No disposition has been accepted. Shared CI tooling now also applies the verified bootstrap and locked auditor to the existing runtime and build-backend checks; their new results must be verified separately. No OCI jobs or locks changed. The production decision must preserve the raw scanner report and reject unknown/applicable findings, missing coverage or scanner failures. Do not use an ignore flag, change vendor metadata or treat a successful runtime audit as approval of bootstrap.


## LB-01 approved applicability disposition (LB-01-PM-20261124-31)
PM authorization in the 2026-11-24 implementation request is limited to CVE-2025-47273, CVE-2026-59890 and GHSA-xmj3-9gf7-h52w for official pip 26.3 wheel SHA-256 f3b60b20ffaadd4415ed7957212a38ac63fa4c5fa375bd0f4a797777940fad13. See #10 and prior [evidence](https://github.com/codefusion-repo/project-os-v3/issues/10#issuecomment-7141029748). Status not_affected, justification component_not_present; no acceptance of exploitable findings. The strict scanner runs without ignores and prints its original JSON, diagnostics and exit code. The separate bootstrap_applicability.py evaluator verifies the exact wheel, lock, complete installed pip source tree (generated matching bytecode caches excepted), hashes of three retained upstream files, full inventory, scanner diagnostics and exact reviewed record identities/aliases/fix versions. Unknown or altered findings, missing packages, changed bytes or failed scan block. The raw finding count remains five when those records are returned; only the separate gate can pass based on approved applicability. No such disposition applies to runtime, backend, auditor dependencies, other artifacts or OCI. Re-evaluate on any change; no automatic policy refresh. The operator still must verify host trust and independent installation in #14.

Advisory descriptions are additionally hash-bound to the five reviewed raw records in CI job 138687172797. Changes to advisory content (even under the same ID) require a fresh review; the policy emits separate raw report and scanner stderr SHA-256 evidence. Conservative rejection of a database formatting update is intentional, not a reason to automatically refresh the policy.


## Historical LB-02 CI negative control (before image decision)


### Política vigente — LB-OCI-20261124-51 (ratificación PM)


### LB-07 trusted local execution — current decision

AgentsUbuntu is the sole local execution environment. Use the installed toolchains and registered Jobs; GitHub Connector handles remote writes, and MCP provides grouped context and typed local execution. Trusted project processes run with the local account's authority, not a sandbox. Keep private grants, scoped credentials, exact revision and lockfile, bounded process lifecycle and durable evidence.

### LB-07 bounded single-operator functional acceptance

Apply [resource reuse](../PROJECT_OS.md#seguridad-transversal-y-límites): existing checkout and branches, installed SDKs and caches; no extra copies, worktrees or unnecessary downloads. An unresolved effect fences later jobs. Stop the existing service, verify the exact job's processes/effects are quiescent locally, then use the existing reconciliation command. No automatic replay or removal of unrelated resources.


### Android Build v1 — QA default and explicit Production

[Ratified Android Build v1](https://github.com/codefusion-repo/project-os-v3/issues/16#issuecomment-7227042738) and [current delivery decision](https://github.com/codefusion-repo/project-os-v3/issues/16#issuecomment-7228057104). QA produces one standalone release APK for arm64-v8a and x86_64 with an automatically provisioned persistent project-specific QA signing identity. Google Drive is the primary private delivery channel within LB-07, with an authenticated link and evidence in the producing private PR. This supersedes GitHub ZIP delivery (decision 7227684635); no JIT runner or producer delivery workflow is required. GitHub CI, test artifacts and maintenance evidence remain unchanged. Resend notifications with a link, not an attachment, remain deferred until after LB-09. No Metro, emulator prerequisite, public release or binary committed to Git. Production remains explicit opt-in AAB with official private signing, not required or activated for LB-07.

Preserve persistent per-project QA identity, exact signed artifact, authorized private Drive and verified PR link.
