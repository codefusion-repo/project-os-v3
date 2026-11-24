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

Keep the path for restart. Use the existing tunnel runtime key and ID, entered interactively; stop the previous embedded demo first. Use absolute paths without whitespace for this bootstrap command (the tunnel parses the command string). Do not place credentials in command arguments or logs.

```bash
BRIDGE="$PWD/local-bridge/.venv/bin/project-os-bridge"
read -rp "Tunnel ID: " CONTROL_PLANE_TUNNEL_ID
read -rsp "Runtime key: " CONTROL_PLANE_API_KEY
printf '\n'
export CONTROL_PLANE_TUNNEL_ID CONTROL_PLANE_API_KEY
tunnel-client run --mcp.command "$BRIDGE --state-dir $STATE" --health.listen-addr 127.0.0.1:0 --health.url-file "$STATE/health.url"
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

Durable jobs and handlers, read-only scoped GitHub context aggregation, guarded repository operations, isolated validation, then Android QA. These are pending, not exposed by this server.
