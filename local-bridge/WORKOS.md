# WorkOS Connect bootstrap (Staging)

Only disposable jobs and synthetic GitHub fixtures. No adopted repos, real gh calls or execution tools. Keep identifiers local. No tokens, API keys, private signing keys or config in Git.

## Configure

For new independent validation use [WSL-VALIDATION.md](WSL-VALIDATION.md) and its private initializer/supervised HTTPS path. The plaintext commands below document the earlier staging pilot only; do not use them for a new production-readiness run. For the same operator, the existing staging identity, tunnel, restricted runtime key and OAuth connector may be retained only through the [exclusive transition](WSL-VALIDATION.md#exclusive-same-operator-staging-transition), with fresh private state, TLS, quiescence, verified scope and fresh live evidence. Do not duplicate resources or rotate uncompromised scoped keys just to repeat setup; do not inherit pilot grants or allow concurrent tunnel use.

In AuthKit Staging keep email/password and MFA enabled, public signup and unused social login disabled. Enable CIMD under Connect, leave DCR disabled. The issuer is the exact hosted AuthKit HTTPS domain from public OAuth metadata (no trailing slash). Register the exact public MCP tunnel URL as the sole Resource Indicator, not localhost or the WorkOS client ID. For the default OpenAI tunnel base the documented candidate is https://api.openai.com/v1/mcp/<tunnel_id>. Verify the actual connector URL and protected-resource metadata before granting access; this document does not attest any live tunnel. Do not configure wildcards or fallback audiences.

From the installed bridge checkout, after running its tests, create private configuration using the local shell:

```bash
umask 077
AUTH_ROOT="$(mktemp -d "$HOME/.project-os-auth.XXXXXXXX")"
mkdir -m 700 "$AUTH_ROOT/state"
export AUTH_ROOT
python3 - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ["AUTH_ROOT"])
cfg = {k: input(p).strip() for k,p in [
    ("issuer","Exact AuthKit issuer: "),
    ("resource","Exact public MCP tunnel URL: "),
    ("subject","WorkOS user ID: ")]}
with (root/"oauth.json").open("x") as f:
    json.dump(cfg,f)
PY
printf 'Private auth root: %s\n' "$AUTH_ROOT"
local-bridge/.venv/bin/project-os-bridge-http --config "$AUTH_ROOT/oauth.json" --state-dir "$AUTH_ROOT/state"
```

Keep the server terminal running. With a second terminal, check the local public metadata at http://127.0.0.1:8765/.well-known/oauth-protected-resource/mcp and confirm resource and issuer exactly match the local config. An unauthenticated MCP POST must return 401. Only after checking the metadata, enable the disposable mode with an empty owner-private file: `(umask 077; touch "$AUTH_ROOT/state/allow-authenticated-probe")` (set AUTH_ROOT to the same directory in the second terminal). Do not reuse the stdio state directory.

Stop the old tunnel process; reuse the same runtime credentials entered privately, not in arguments or chat. In a separate shell:

```bash
(
  set -euo pipefail
  read -rp "Tunnel ID: " CONTROL_PLANE_TUNNEL_ID
  read -rsp "Runtime key: " CONTROL_PLANE_API_KEY
  printf '\n'
  export CONTROL_PLANE_TUNNEL_ID CONTROL_PLANE_API_KEY
  read -rp "Private auth root: " AUTH_ROOT
  ISSUER="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["issuer"])' "$AUTH_ROOT/oauth.json")"
  tunnel-client run \
    --mcp.server-url http://127.0.0.1:8765/mcp \
    --mcp.oauth-trusted-origin "$ISSUER" \
    --harpoon.allow-plaintext-http
)
```

For tunnel-client v0.0.21, the exact AuthKit origin must be trusted for OAuth discovery. The plaintext Harpoon exception is process-wide and is suitable only for the dedicated trusted loopback staging fixture; do not add other HTTP targets or use this exception for real resources. Prefer HTTPS for production. The PM observed automatic OAuth discovery after these flags were added. A new OAuth connector was needed because the previous connector was configured without authentication. Keep the old connector unused; retire it only with explicit authorization.

Configure the ChatGPT plugin for OAuth/CIMD, not no authentication. Verify the discovered resource matches exactly, authenticate in AuthKit and consent, and refresh discovery. The protected-resource metadata advertises openid and offline_access on the canonical SDK path and both tunnel aliases. Only openid is required for tool authorization; offline_access requests renewal capability from the issuer, not local permissions. ChatGPT owns the refresh token and its rotation; the bridge validates access tokens only. Refresh behavior is client-dependent. Never pass bearer tokens as tool arguments.

## OAuth lifecycle acceptance and recovery (#28)

Use the existing authorized supervised HTTPS instance and connector, with the reviewed runtime and unchanged private state, issuer, resource, subject, tunnel and grants. Do not create another connector or rotate credentials merely to troubleshoot. Keep fixture and real-resource access disabled.

1. Before enabling the local markers, compare the JSON documents at the canonical protected-resource path (the well-known prefix followed by the exact public resource URL path), the well-known root and its /mcp alias. All must advertise openid and offline_access, the same resource and issuer, and header bearer authentication. Check that the unauthenticated MCP response is 401 and its resource_metadata challenge resolves to the correct public metadata through the existing tunnel. Do not publish private URLs or identifiers.
2. Verify the existing ChatGPT OAuth/CIMD grant privately. In WorkOS, inspect whether offline_access was requested and whether refresh grants succeed, if the available provider events expose those facts. Do not extract access tokens, refresh tokens, authorization codes, cookies or private configuration. If the previous grant lacks renewal capability, reconnect the existing connector once after correcting discovery and record that intervention.
3. Record a successful read-only health call and its UTC time. After the configured access-token lifetime has elapsed, repeat the read-only call without manual reconnect; do this over two renewal intervals. Establish actual refresh success with provider evidence when available, not simply repeated HTTP 200 or an assumed five-minute lifetime. If refresh cannot be observed, report the limit and keep live acceptance pending.
4. Reuse prior revocation and job-count evidence from #14. If a focused post-change revocation test is needed, remove only the known empty global marker, check one authenticated read returns 403 without an OAuth challenge, restore using the existing noclobber procedure and check health without new consent. Never retry a submission of uncertain outcome. A client reconnect prompt after 403 is a client/provider interoperability finding, not permission to return 200 or weaken local authorization.
5. Follow [WSL-VALIDATION.md](WSL-VALIDATION.md) for quiescent stop/start with the same private state; compare the existing job evidence and replay the same request key only. Stop and revoke markers when done. Preserve state and logs.

Correlate UTC call times with the fixed-schema local HTTP audit and available WorkOS grant events. Report only status counts, timestamps, scope-presence booleans and sanitized error categories. A 401 can mean absent/expired/invalid access token or verifier/JWKS failure; aggregate counts cannot distinguish these. A 403 from the local gate is authorization denial, not token expiry. If WorkOS reports invalid_grant or rotation failure, or ChatGPT prompts again despite successful refresh, stop repeated reconnections and isolate the client/provider failure before changing server policy. Do not lengthen token lifetime, relax JWT checks or store refresh tokens in the bridge as a workaround.

The regression suite uses synthetic access tokens and reconstructs the HTTP app over the same SQLite state; this is not proof of live OAuth refresh, systemd restart or tunnel behavior. Issue #28 remains open until live criteria pass.

## Evidence and stop

Local HTTP tests use generated JWTs and a mocked JWKS fetch; they do not prove live WorkOS or tunnel discovery. Check health, submit a unique disposable probe job, replay the same request key, inspect status and synthetic batch. Remove only the local opt-in file to deny subsequent requests. Missing or invalid tokens still receive HTTP 401 with an OAuth challenge; authenticated requests with the local opt-in revoked receive HTTP 403 without a WWW-Authenticate challenge. OAuth metadata remains public. Recreating the empty private flag restores access without intentionally requiring a new OAuth session. The worker checks authorization before claim and dispatch; a claimed but denied job becomes BLOCKED, while already dispatched work is not cancelled. One HTTP service per private state is allowed, and workers wait for successful listener startup. Unexpected worker infrastructure failure stops HTTP with a nonzero exit rather than silently abandoning the queue. Stop accepting requests by shutting down the server. Normal shutdown waits for an in-flight registered job and its cleanup; it does not immediately cancel work. Forced termination may leave a container or interrupted job; inspect locally before restart. The prior pilot later observed FORBIDDEN and restoration (SECURITY.md); the raw local 403 audit and aggregate job count were not independently inspected. Reverify on the independent HTTPS instance. Stop both processes with Ctrl-C to terminate access. Removing the opt-in is not revocation of WorkOS refresh tokens; revoke the WorkOS application authorization separately if required. JWKS cache TTL 300 seconds, unknown-key refresh cooldown 15 seconds; expiry and failed refresh fail closed for the requested key. No introspection. Same-user local processes are outside the trust boundary.

References: https://workos.com/docs/authkit/mcp ; https://workos.com/docs/authkit/connect/token-claims ; https://github.com/openai/tunnel-client/blob/v0.0.21/docs/architecture.md

## Optional integrated disposable Git job

After the expanded isolation gate passes locally, stop the HTTP server and restart with the same private config/state plus `--fixture-image IMAGE_AT_DIGEST` (replace with the locally approved, already installed exact image digest). Do not use an arbitrary or remote-provided image. This enables only `submit_git_fixture(request_key)`; all code and paths are fixed. Refresh tool discovery. Use one unique request key, read status and `get_job_evidence(job_id)`, replay the same key, and compare evidence after restart. Missing image binding denies new submissions and blocks queued fixture dispatch. Stop the process before changing local configuration; no in-flight cancellation guarantee. No real repository access.

## Private loopback TLS (production transport prerequisite)

Use a dedicated local CA and a server certificate with IP SAN 127.0.0.1, serverAuth usage and a protected private key. Provision them outside Git under the service user's private instance directory; do not reuse the WorkOS issuer keys or install the CA globally. Keep the CA signing key offline. The server certificate and key must be canonical absolute owner-private regular files. Start the HTTP entrypoint with the existing config/state and `--tls-cert /private/server.pem --tls-key /private/server-key.pem`. Preserve the approved fixture image option if applicable. Verify locally with curl using the dedicated CA and exact loopback IP, then start tunnel-client v0.0.21 with `--mcp.server-url https://127.0.0.1:8765/mcp --ca-bundle /private/ca.pem --mcp.oauth-trusted-origin "$ISSUER"`. Do not pass the plaintext exception; ensure HARPOON_ALLOW_PLAINTEXT_HTTP is unset and no loaded config enables it. The CA bundle is additive and applies to all tunnel-client outbound TLS, not only MCP; use a dedicated narrowly controlled CA and process. Do not disable TLS validation. Recheck metadata, unauthenticated 401, live health, fixture evidence, revocation and restoration. Restart on certificate rotation. This mode is implemented but live tunnel interoperability is not yet demonstrated. No real resource grant follows from TLS alone.
