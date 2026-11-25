# Project OS Local Bridge

Optional single-user, self-hosted runtime. Browser Chat executes authorized GitHub operations directly and uses the bridge for registered local jobs. No automatic terminal-agent/Codex delegation. Read [MVP](MVP.md) for the current capability contract, [SECURITY](SECURITY.md) for gates and [WORKOS](WORKOS.md) for private OAuth setup.

Historical B0 bootstrap. Stdio mode exposes only a fixed disposable SQLite marker over stdio MCP. It is NOT the completed remote development MVP. No caller identity is verified by this probe; do not expose real repositories, credentials, shell, builds or devices with it. Only use with the PM's dedicated tunnel and restricted caller access. The local opt-in authorizes this fixed probe operation, not arbitrary remote callers or other resources. A process running as the same OS user is outside this probe's trust boundary.

## Install in WSL

Use the [hash-verified installer](#hash-verified-linuxwsl-installation) in a new clean checkout of the explicitly reviewed full SHA; do not use the old unlocked pip install procedure or overwrite an existing venv. For independent readiness follow [WSL-VALIDATION.md](WSL-VALIDATION.md). Do not use sudo for the bridge.

The remaining B0 commands below are historical disposable stdio instructions, not the recommended authenticated startup path. For a new instance use the initializer and the independent HTTPS runbook.

Create a dedicated disposable state directory outside Git:

```bash
umask 077
STATE="$(mktemp -d "$HOME/.project-os-probe.XXXXXXXX")"
printf '%s\n' "$STATE"
```

Keep the path for restart. The stdio child is launched with an empty inherited environment except for PATH; this reduces accidental credential inheritance but does not isolate same-user processes. Use the existing tunnel runtime key and ID, entered interactively; stop the previous embedded demo first. Use absolute paths without whitespace for this bootstrap command (the tunnel parses the command string). Do not place credentials in command arguments or logs.

```bash
BRIDGE="$PWD/local-bridge/.venv/bin/project-os-bridge"
read -rp "Tunnel ID: " CONTROL_PLANE_TUNNEL_ID
read -rsp "Runtime key: " CONTROL_PLANE_API_KEY
printf '\n'
export CONTROL_PLANE_TUNNEL_ID CONTROL_PLANE_API_KEY
tunnel-client run --mcp.command "/usr/bin/env -i PATH=/usr/bin:/bin $BRIDGE --state-dir $STATE" --health.listen-addr 127.0.0.1:0 --health.url-file "$STATE/health.url"
unset CONTROL_PLANE_API_KEY
```

Refresh tool discovery in the ChatGPT plugin; verify that the four probe tools replace the embedded demo tools. Do not report success based solely on readiness.

## Gate procedure

1. Call health, sandbox_read and sandbox_write; initially write must return BLOCKED.
2. In a separate local terminal, set STATE to the exact private directory printed during setup. Run `(umask 077; touch "$STATE/allow-probe-write")` to enable the fixed write.
3. Call sandbox_write twice: first creates the marker, second is a replay. Read it back.
4. Stop the tunnel with Ctrl-C and restart with the same directory. Read again to verify persistence.
5. Remove only the opt-in flag with `rm -- "$STATE/allow-probe-write"`. Verify write is blocked and the existing marker remains.
6. Stop the tunnel to disable all access. Keep disposable evidence until reviewed.

No tool accepts an arbitrary path, command, marker, or authorization flag. The local directory and flag must be owned by the service user and private. This is not an isolation mechanism for untrusted repository execution. Before enabling real resources, demonstrate caller authentication, scoped policies, credential separation and execution isolation.

## Follow-on slices

B1 adds local-only `core.py`, `worker.py` and `github.py`. These are deliberately NOT registered as MCP tools. The policy accepts a principal supplied by trusted local code; it is not a remote authentication mechanism. The queue persists request keys, states, results and transition events in SQLite. The exclusive Linux worker drains the disposable `probe_check` handler; interrupted jobs are marked INTERRUPTED and never automatically replayed. Cancellation is supported only before claim. No arbitrary commands are accepted.

The GitHub reader accepts a local project-to-repository mapping and explicit grants. It uses a dedicated private gh configuration directory, explicit GET requests to github.com, a bounded response and pagination budget, and batches at most five issue references with two concurrent readers. Returned issue/comment data is untrusted and can include sensitive content; do not expose or publish it without a disclosure policy. Mocked tests do not prove live gh authentication, scope, or performance. Do not reuse personal credentials or enable this remotely before the caller-authentication gate.

Pending: real caller authentication, local policy configuration integration, worker service lifecycle, evidence retrieval and sanitization, real GitHub credentials validation, guarded repository operations, isolated validation, then Android QA. The MCP server still exposes only the four disposable probe tools.

## WorkOS Connect authenticated HTTP mode (disposable only)

The stdio bootstrap remains unchanged. HTTP mode binds only to 127.0.0.1 and requires a private configuration outside Git, with exactly issuer, resource and subject. See [WORKOS.md](WORKOS.md) for setup, negative checks and revocation. The verifier uses the hosted AuthKit JWKS and the stable ChatGPT CIMD client ID; no WorkOS API key or private signing key is needed. Access tokens must have exact issuer, resource, subject, client, consent ID, token ID, expiry, issue time and openid scope. Local opt-in is required on every authenticated request. No real resources are exposed. Live OAuth interoperability was observed in the pilot; revocation and restart require a new live test.

## B2 preliminary primitives

`repository.py` implements a fixed disposable UTF-8 file with digest-guarded atomic replacement and cooperating-process locking. `execution.py` validates that fixed fixture as data, without subprocesses. Neither is exposed by MCP. These are not a Git worktree provider or an execution sandbox. Same-user local processes are outside the trust boundary. Real repository changes and running repository-controlled tests require a separate isolated execution environment and additional acceptance tests.

## Local Git and isolation fixtures

The Git fixture creates its own repository and detached worktree in a fresh private directory. It accepts only a single text-file patch with expected HEAD and content digest; no caller path, remote, push or arbitrary checkout. Tests run actual Git operations. The rootless Podman validation profile exports only fixed fixture data, requires a locally approved digest-pinned Python image already present, disables networking and capabilities, uses a read-only root and mount, and does not fall back to host execution. The initial profile was validated on WSL; expanded security probes remain unverified locally and is not a sandbox for arbitrary project code. Rootless Podman and a trusted local image are prerequisites, not automatically installed.

Authenticated HTTP mode additionally exposes a synthetic GitHub context tool to test batching without disclosing actual issue/comment content or invoking gh. The real GitHub reader remains local-only. All synthetic data is labelled as such. The authenticated server can optionally register the fixed Git fixture when locally started with an approved image digest. No arbitrary container tools.

## Local vertical workflow and preflight

The disposable Git workflow can run via a dedicated local CLI state or the authenticated HTTP service with an explicit local fixture-image opt-in; never share those state directories. Use the preflight inventory without starting devices or inspecting credentials:

```bash
bash local-bridge/scripts/preflight.sh
```

Availability is not authorization or isolation evidence. The local fixture runner requires a trusted Python image already installed in rootless Podman, with its exact repository digest. No automatic pulls, no host execution fallback. Choose and verify the image locally before running.

```bash
umask 077
FIXTURE_STATE="$(mktemp -d "$HOME/.project-os-fixture.XXXXXXXX")"
read -rp "Approved local Python image with digest: " IMAGE
local-bridge/.venv/bin/project-os-bridge-fixture --state-dir "$FIXTURE_STATE" --request-key first --image "$IMAGE"
```

Keep the state directory private. Reusing the same request key retrieves the original job result; a new key creates a new fixture. Interrupted jobs are not replayed automatically. Evidence includes state transitions, Git HEAD, content digests, staged diff and validation outcome. A blocked isolation profile is not a successful validation. Unit tests exercise real Git and mock the container boundary; the actual container must be tested separately. The HTTP worker checks local authorization before each claim and again before dispatch; a claimed job denied at that boundary is BLOCKED and remaining queued jobs are preserved. In-flight operations are not cancelled. An exclusive per-state HTTP service lock prevents concurrent HTTP instances even on different ports. The worker waits for successful listener startup before claiming jobs. Only contention on the worker lock is recoverable; an unexpected worker infrastructure failure requests HTTP shutdown and exits unsuccessfully rather than leaving a ready server with a dead worker. The supervisor then stops the tunnel; interrupted work is not automatically retried. No adopted repos or real GitHub calls are enabled.

## Independent self-hosted installations

See [SECURITY.md](SECURITY.md) for the threat model, gates, private setup and service account guidance. Different operators have separate identities, tunnels, local credentials and databases. A same-operator exclusive staging transition may reuse the existing OAuth identity, tunnel, restricted key and connector under [WSL-VALIDATION.md](WSL-VALIDATION.md#exclusive-same-operator-staging-transition), but must retain separate private runtime state/TLS and prove exclusive cutover and fresh live checks. No shared Project OS service or collaborative RBAC. The source repository is public; a redistribution license is a separate maintainer decision.

`project-os-bridge-init --root /absolute/private/new-directory` initializes a new disposable HTTP instance interactively. It never starts a server, grants access, provisions credentials or modifies OS permissions. Keep existing installations unchanged. Install from a reviewed full commit using the hash-verified installer below. Independent clean-device validation remains required.

## Current pilot status and production follow-up

The disposable authenticated Git/Podman lifecycle passed live, including replay, restart and local deny/restore, at the SHA and evidence recorded in SECURITY.md. Earlier pending statements above describe historical milestones. Private loopback TLS is available through the paired certificate/key flags; follow WORKOS.md and validate the new transport before use. Preflight now separately reports `adb_emulator_attach` without printing serials. Android device operations, real repository access, supervised startup and reproducible installation are not yet certified or enabled.

## Supervised HTTPS preparation (explicit, local only)

Use the existing selector with `project-os-v3 --bridge-setup /absolute/private/instance` or its existing installed bridge initializer with `--root /absolute/private/instance --prepare-service`. The dedicated bridge venv must already be installed. The local wizard asks for the verified tunnel-client executable, optional previously bound image and runtime key using a hidden prompt. It creates only a new owner-private service subdirectory, never overwrites existing files or modifies the OAuth configuration, SQLite or opt-in. It generates a private local CA and a loopback leaf certificate valid for 90 days; the CA signing key is not persisted. Rotation requires a separately prepared replacement and operator approval. A partial preparation is retained for inspection; do not automatically delete it.

The generated user-systemd unit is not linked, enabled or started automatically. From the same reviewed installed virtual environment, as the dedicated unprivileged operator, inspect the unit and confirm the prior bridge and tunnel are stopped. Run only the explicitly authorized local operation:

```bash
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" link
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" start
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" status
local-bridge/.venv/bin/python -I -m project_os_bridge.lifecycle --root "$ROOT" stop
```

The controller rejects foreign units, drop-ins, changed unit definitions and ambiguous state. Controller operations are serialized per user; use one operator at a time because external same-user configuration changes are outside the trust boundary. Active is systemd process state, not verified tunnel health. Only after independently checking live MCP health, opt in to login startup using the explicit `enable` action; it does not start a unit. Stop explicitly before `disable`; disabling may remove the link, so check status and link explicitly again if needed. WSL startup and lingering are separate OS decisions. For failed startup or uncertain results, inspect status and sanitized supervisor journal locally, stop the identified unit if necessary, reconcile durable effects using the existing local reconciliation procedure, then explicitly start only after successful review. Never automate restart or replay. Retain the instance, keys and SQLite for rollback; do not delete the pilot. The supervisor uses fixed arguments and sanitized child environments, waits for verified loopback TLS metadata before launching the tunnel; the supervised worker independently verifies the same metadata before dispatch, and stops the tunnel before the bridge. It stops both if either exits; it does not automatically restart or retry uncertain effects. Local child output is suppressed to avoid accidental credential logging; only fixed supervisor status is emitted. Remote readiness requires live MCP health. A forced stop may require container reconciliation. The runtime key is owner-private at rest, not encrypted, and supplied only to the tunnel child environment; same-user processes remain outside the trust boundary. Do not share personal credentials with the service account.

## Hash-verified Linux/WSL installation

The committed runtime lock contains the 31 wheel SHA-256 hashes observed in CI job 138606270522 (Linux x86_64 CPython 3.12). That job installed the downloaded wheels in a fresh venv using hash checks and no index, passed pip check, and pip-audit 2.10.1 reported no known vulnerabilities at scan time. The build backend lock records setuptools 84.2.1, whose wheel hash, offline build and audit passed in CI job 138626336009. The installer verifies both locks and builds without index access or build isolation. CI runtime hash checks remain enforced. This is dependency reproducibility, not a guarantee of byte-identical project wheels or a pinned Python/OS toolchain. The installer creates a venv without ensurepip and verifies the exact pip 26.3 wheel from PyPI against requirements-bootstrap.lock before importing it. Package acquisition uses a private temporary wheelhouse, a clean environment and explicit index; installs of locked wheels are offline. The project builds/tests from the reviewed Git tree, not ignored checkout files. CI inventories pip's declared vendored packages and audits them separately; a successful install alone does not certify them. Host Python, OS/curl/CA trust, OCI image, tunnel binary and audit-tool dependencies remain outside this dependency-audit evidence. No automatic lock regeneration.

In a clean independent checkout of the explicitly reviewed full commit, run `bash local-bridge/scripts/install.sh REVIEWED_FULL_SHA`. Existing venvs are preserved; partial new installation is retained, not automatically removed. From Windows, the matching PowerShell wrapper accepts ReviewedSha, Distribution and the absolute Linux Checkout path and delegates to the same WSL installer. It does not install WSL or modify Windows settings. After successful install, reuse the existing selector's explicit bridge setup flow; no automatic permission or service activation.

## Independent WSL validation

Follow [WSL-VALIDATION.md](WSL-VALIDATION.md) for the grouped operator procedure. Keep the current pilot intact. The reference image remains rejected; the exact fixture-only digest is accepted only in CI. See SECURITY.md for the historical negative control and fresh evidence policy. Do not bind or run locally without separate review and authorization.


### Production installation evidence (LB-01)
The installer builds two wheels from independently extracted copies of the reviewed Git tree with the commit timestamp as SOURCE_DATE_EPOCH and identical locked dependencies, and compares filenames and SHA-256 before installing either. A mismatch stops installation. This proves reproducibility only for the observed host/toolchain, not an entire venv or a different OS. CI uses the exact observed 29-package auditor closure in requirements-audit.lock, verifies wheel bytes and installed versions, and retains raw JSON and strict exit codes; a missing or inconsistent report is a failure. The strict vendor audit remains blocking until remediated or an explicitly reviewed disposition is authorized. Host Python/OS/CA/Git/curl/tar remain prerequisites. For update/rollback keep the existing installation intact, use a separate clean checkout at a reviewed SHA, stop at any failure, and retain the old environment; do not overwrite, activate services, migrate private state or change grants automatically.

The runtime and build-backend evidence jobs use the same verified pip bootstrap and 29-package auditor lock, with separate fresh CI environments. The non-OCI selector's optional terminal test is outside Local Bridge bootstrap scope. The strict audit of every installed package version remains mandatory; bootstrap vendoring has its own report and cannot be inferred from a successful runtime/build audit.

The PM-approved LB-01 disposition is limited to three specific advisories in the exact pip 26.3 wheel. See SECURITY.md. CI preserves raw scanner findings and exit status and separately checks artifact identity, component absence and report completeness. A policy PASS is not a zero-finding scan. Any changed artifact, unknown finding or scanner failure blocks. No image or resource approval follows.

Lifecycle recovery: inspect `status` and the sanitized user-systemd journal before any recovery. A pending systemd job blocks every mutation until it settles. Start/stop do not replace conflicting jobs. A timed-out call is successful only if a fresh snapshot confirms the requested state with no pending job; otherwise do not replay. After diagnosing and reconciling the stopped instance, explicitly use `reset-failed` if systemd still reports failed, then issue a separate start only when authorized. Resetting failed state neither starts a service nor clears durable fixture effects. On supervisor shutdown, signal the tunnel first and the bridge immediately afterward, then wait for both; do not keep dispatching while waiting for tunnel exit.
