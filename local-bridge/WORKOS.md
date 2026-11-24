# WorkOS Connect bootstrap (Staging)

Only disposable jobs and synthetic GitHub fixtures. No adopted repos, real gh calls or execution tools. Keep identifiers local. No tokens, API keys, private signing keys or config in Git.

## Configure

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

Configure the ChatGPT plugin for OAuth/CIMD, not no authentication. Verify the discovered resource matches exactly, authenticate in AuthKit and consent, and refresh discovery. The bridge requests openid; only the standard CIMD scopes are accepted. Refresh behavior is client-dependent. Never pass bearer tokens as tool arguments.

## Evidence and stop

Local HTTP tests use generated JWTs and a mocked JWKS fetch; they do not prove live WorkOS or tunnel discovery. Check health, submit a unique disposable probe job, replay the same request key, inspect status and synthetic batch. Remove only the local opt-in file to deny subsequent requests. Missing or invalid tokens still receive HTTP 401 with an OAuth challenge; authenticated requests with the local opt-in revoked receive HTTP 403 without a WWW-Authenticate challenge. OAuth metadata remains public. Recreating the empty private flag restores access without intentionally requiring a new OAuth session. The worker does not begin a new drain cycle while disabled; an already started drain or running work is not cancelled. Stop the process for immediate termination of local work. A prior live revocation attempt triggered repeated reconnect prompts; the corrected behavior must be verified through ChatGPT after installation. Stop both processes with Ctrl-C to terminate access. Removing the opt-in is not revocation of WorkOS refresh tokens; revoke the WorkOS application authorization separately if required. JWKS cache TTL 300 seconds, unknown-key refresh cooldown 15 seconds; expiry and failed refresh fail closed for the requested key. No introspection. Same-user local processes are outside the trust boundary.

References: https://workos.com/docs/authkit/mcp ; https://workos.com/docs/authkit/connect/token-claims ; https://github.com/openai/tunnel-client/blob/v0.0.21/docs/architecture.md
