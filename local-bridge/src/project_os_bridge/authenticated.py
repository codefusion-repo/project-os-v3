"""Authenticated disposable MCP tools; no real resources."""
import argparse
import os
import ssl
import threading
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse
from pydantic import AnyHttpUrl

from .workos_auth import Verifier, SCOPE, load_config
from .core import Jobs, Policy
from .worker import run_pending
from .security import RequestGate, Audit
from .github_fixture import SyntheticGitHubReader
from .vertical import OPERATIONS, bind_image
from .isolated import IMAGE
from .workos_auth import private_file


def fixture_enabled(verifier, image):
    if not image or not verifier.enabled():
        return False
    try:
        path = verifier.state_dir / "fixture-image"
        return private_file(path).st_size <= 1024 and path.read_text(encoding="utf-8") == image + "\n"
    except (OSError, ValueError):
        return False


def build_server(verifier, jobs, fixture_reader=None, *, fixture_image=None):
    mcp = MCPServer("Project OS authenticated disposable jobs",
                    token_verifier=verifier,
                    auth=AuthSettings(issuer_url=AnyHttpUrl(verifier.issuer),
                                      resource_server_url=AnyHttpUrl(verifier.resource),
                                      required_scopes=[SCOPE],validate_token_resource=True))
    read = ToolAnnotations(read_only_hint=True,open_world_hint=False)
    write = ToolAnnotations(read_only_hint=False,destructive_hint=False,idempotent_hint=True,open_world_hint=False)

    def principal():
        token = get_access_token()
        if not verifier.enabled() or token is None or token.subject != verifier.subject or token.client_id != verifier.client_id or SCOPE not in token.scopes:
            raise PermissionError("DENIED")
        return token.subject

    @mcp.tool(annotations=read)
    def health() -> dict:
        """Report authenticated disposable service status."""
        principal()
        return {"status":"ready","caller_identity_verified":True,"repository_access":False,"mode":"authenticated-disposable",
                "git_fixture_available":fixture_enabled(verifier, fixture_image)}

    @mcp.tool(annotations=write)
    def submit_probe_job(request_key: str) -> dict:
        """Submit the fixed read-only probe_check job; no user commands or paths."""
        return {"job_id":jobs.submit(principal(),"disposable","probe_check",request_key)}

    if fixture_image is not None:
        @mcp.tool(annotations=write)
        def submit_git_fixture(request_key: str) -> dict:
            """Run only the registered disposable Git/Podman fixture; no paths, code or image arguments."""
            actor = principal()
            if not fixture_enabled(verifier, fixture_image):
                raise PermissionError("DENIED")
            return {"job_id":jobs.submit(actor,"disposable","git_fixture_check",request_key)}

    @mcp.tool(annotations=read)
    def get_job_status(job_id: str) -> dict:
        """Read the caller's disposable job result."""
        return jobs.get(principal(),job_id)

    @mcp.tool(annotations=read)
    def get_job_evidence(job_id: str) -> dict:
        """Read the caller's persisted result and transitions; never execute a job."""
        return jobs.evidence(principal(),job_id)

    @mcp.tool(annotations=write)
    def cancel_job(job_id: str) -> dict:
        """Cancel the caller's queued disposable job; running jobs are not cancellable."""
        return {"cancelled":jobs.cancel(principal(),job_id)}

    if fixture_reader is not None:
        @mcp.tool(annotations=read)
        def github_fixture_context(numbers: list[int]) -> dict:
            """Aggregate synthetic issue fixtures only; never contacts GitHub."""
            return fixture_reader.batch_issues(principal(), "disposable", numbers)

    # Tunnel discovery may request the local endpoint path rather than the public path.
    from starlette.responses import JSONResponse
    from urllib.parse import urlsplit
    public_path = "/.well-known/oauth-protected-resource" + urlsplit(verifier.resource).path
    for route in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        if route != public_path:
            async def metadata(request):
                return JSONResponse({"resource": verifier.resource, "authorization_servers": [verifier.issuer],
                                     "scopes_supported": [SCOPE, "offline_access"], "bearer_methods_supported": ["header"]})
            mcp.custom_route(route, methods=["GET"])(metadata)
    return mcp


class LocalAuthorizationMiddleware:
    """Deny authenticated requests without issuing an OAuth challenge."""
    def __init__(self, app, verifier):
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope["path"] == "/mcp"
                and isinstance(scope.get("user"), AuthenticatedUser)
                and not self.verifier.enabled()):
            response = JSONResponse({"error": "local_access_revoked"}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_http_app(verifier, jobs, fixture_reader=None, *, audit=None, limit=120, fixture_image=None):
    """Use the same authenticated ASGI stack in production and HTTP tests."""
    server = build_server(verifier, jobs, fixture_reader, fixture_image=fixture_image)
    app = server.streamable_http_app(
        stateless_http=True, json_response=True, max_request_body_size=65536,
        host="127.0.0.1",
    )
    # SDK v2.3.0 authenticates before routing. Insert the local policy gate
    # immediately after that middleware; fail closed if the stack changes.
    positions = [i for i, m in enumerate(app.user_middleware)
                 if m.cls is AuthenticationMiddleware]
    if len(positions) != 1:
        raise RuntimeError("Expected exactly one authentication middleware")
    app.user_middleware.insert(positions[0] + 1,
                               Middleware(LocalAuthorizationMiddleware, verifier=verifier))
    # Outer gate limits all HTTP requests, including malformed tokens before JWKS.
    # No reliance on client-controlled IP headers.
    app.add_middleware(RequestGate, audit=audit or Audit(jobs.probe.root), limit=limit)
    return app


def tls_options(cert, key):
    """Validate the optional local TLS pair before starting any worker."""
    if cert is None and key is None:
        return {}
    if cert is None or key is None:
        raise ValueError("TLS certificate and key must be supplied together")
    for path in (cert, key):
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError("Canonical TLS paths required")
        private_file(path)
    # Validate the pair before Uvicorn starts. Do not read key material into logs.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key), password=lambda: "")
    return {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}


def serve_with_worker(server, jobs, verifier, fixture_image):
    """Stop HTTP on infrastructure failure; preserve in-flight cleanup on shutdown."""
    stop = threading.Event()
    failed = threading.Event()

    def worker():
        try:
            while not stop.is_set():
                try:
                    if verifier.enabled():
                        run_pending(jobs, fixture_image=fixture_image,
                                    enabled=lambda: verifier.enabled() and not stop.is_set(),
                                    fixture_allowed=lambda: fixture_enabled(verifier, fixture_image))
                except BlockingIOError:
                    # Another exclusive worker owns the disposable queue.
                    pass
                stop.wait(0.5)
        except Exception:
            # Never log exceptions containing local paths or credentials.
            failed.set()
            stop.set()
            server.should_exit = True

    thread = threading.Thread(target=worker, daemon=False)
    thread.start()
    try:
        server.run()
    finally:
        stop.set()
        # Let a registered fixture finish cleanup before exiting.
        thread.join()
    if failed.is_set():
        raise RuntimeError("DISPOSABLE_WORKER_FAILED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",required=True,type=Path)
    parser.add_argument("--state-dir",required=True,type=Path)
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--fixture-image",help="Explicit local opt-in for fixed disposable fixture, approved digest only")
    parser.add_argument("--tls-cert", type=Path, help="Private local PEM certificate")
    parser.add_argument("--tls-key", type=Path, help="Private local PEM key")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        tls = tls_options(args.tls_cert, args.tls_key)
    except (OSError, ValueError):
        parser.error("Invalid private TLS certificate/key configuration")
    verifier = load_config(args.config, args.state_dir)
    if os.getuid()==0 or os.path.lexists(args.state_dir/"local-fixture-mode"):
        parser.error("Unprivileged dedicated HTTP state required")
    if args.fixture_image is not None and not IMAGE.fullmatch(args.fixture_image):
        parser.error("Digest-pinned image required")
    operations = OPERATIONS if args.fixture_image else ("submit","read","cancel")
    workflows = ("probe_check","git_fixture_check") if args.fixture_image else ("probe_check",)
    jobs = Jobs(args.state_dir,Policy((verifier.subject,op,"disposable") for op in operations),workflows=workflows)
    if args.fixture_image:
        bind_image(jobs,args.fixture_image)
    fixture = SyntheticGitHubReader(Policy([(verifier.subject,"github_read","disposable")]),args.state_dir)
    app = build_http_app(verifier,jobs,fixture,fixture_image=args.fixture_image)
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port,
                                          access_log=False, **tls))
    serve_with_worker(server, jobs, verifier, args.fixture_image)


if __name__ == "__main__":
    main()
