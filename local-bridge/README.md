# Project OS Local Bridge — bootstrap

Optional component. This slice exposes only a fixed disposable SQLite marker over stdio MCP. It is NOT the completed remote development MVP. No caller identity is verified by this probe; do not expose real repositories, credentials, shell, builds or devices with it. Only use with the PM's dedicated tunnel and restricted caller access. The local opt-in authorizes this fixed probe operation, not arbitrary remote callers or other resources. A process running as the same OS user is outside this probe's trust boundary.

## Install in WSL

From the repository root, using a clean checkout of the reviewed implementation commit:

```bash
python3 -m venv local-bridge/.venv
local-bridge/.venv/bin/python -m pip install ./local-bridge
PYTHONPATH=local-bridge/src local-bridge/.venv/bin/python -m unittest discover -s local-bridge/tests -v
```

The SDK version is pinned; transitive dependencies are not yet locked. Do not use sudo for the bridge.

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

The stdio bootstrap remains unchanged. HTTP mode binds only to 127.0.0.1 and requires a private configuration outside Git, with exactly issuer, resource and subject. See [WORKOS.md](WORKOS.md) for setup, negative checks and revocation. The verifier uses the hosted AuthKit JWKS and the stable ChatGPT CIMD client ID; no WorkOS API key or private signing key is needed. Access tokens must have exact issuer, resource, subject, client, consent ID, token ID, expiry, issue time and openid scope. Local opt-in is required on every authenticated request. No real resources are exposed. WorkOS/ChatGPT/tunnel interoperability still requires a live test.

## B2 preliminary primitives

`repository.py` implements a fixed disposable UTF-8 file with digest-guarded atomic replacement and cooperating-process locking. `execution.py` validates that fixed fixture as data, without subprocesses. Neither is exposed by MCP. These are not a Git worktree provider or an execution sandbox. Same-user local processes are outside the trust boundary. Real repository changes and running repository-controlled tests require a separate isolated execution environment and additional acceptance tests.

## Local Git and isolation fixtures

The Git fixture creates its own repository and detached worktree in a fresh private directory. It accepts only a single text-file patch with expected HEAD and content digest; no caller path, remote, push or arbitrary checkout. Tests run actual Git operations. The rootless Podman validation profile exports only fixed fixture data, requires a locally approved digest-pinned Python image already present, disables networking and capabilities, uses a read-only root and mount, and does not fall back to host execution. This profile is not yet validated on WSL and is not a sandbox for arbitrary project code. Rootless Podman and a trusted local image are prerequisites, not automatically installed.

Authenticated HTTP mode additionally exposes a synthetic GitHub context tool to test batching without disclosing actual issue/comment content or invoking gh. The real GitHub reader remains local-only. All synthetic data is labelled as such. No Git fixture or container tool is exposed remotely yet.

## Local vertical workflow and preflight

The disposable Git workflow is **local CLI only**, with a dedicated state directory; the authenticated MCP server still exposes only the original disposable tools. Use the preflight inventory without starting devices or inspecting credentials:

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

Keep the state directory private. Reusing the same request key retrieves the original job result; a new key creates a new fixture. Interrupted jobs are not replayed automatically. Evidence includes state transitions, Git HEAD, content digests, staged diff and validation outcome. A blocked isolation profile is not a successful validation. Unit tests exercise real Git and mock the container boundary; the actual container must be tested separately. The HTTP worker checks local authorization before each claim; in-flight operations are not cancelled. No adopted repos or real GitHub calls are enabled.

## Independent self-hosted installations

See [SECURITY.md](SECURITY.md) for the threat model, gates, private setup and service account guidance. Each installation has its own identity, tunnel, local credentials and databases. No shared Project OS service or collaborative RBAC. The source repository is public; a redistribution license is a separate maintainer decision.

`project-os-bridge-init --root /absolute/private/new-directory` initializes a new disposable HTTP instance interactively. It never starts a server, grants access, provisions credentials or modifies OS permissions. Keep existing installations unchanged. Install from a reviewed full commit using a dedicated virtual environment, run pip check and the test suite. Direct dependencies are pinned; transitive lock and independently reproduced clean installation are still pending.
