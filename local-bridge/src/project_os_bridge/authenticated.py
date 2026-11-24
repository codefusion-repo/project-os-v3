"""Authenticated disposable MCP tools; no real resources."""
import argparse
import os
import threading
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl

from .workos_auth import Verifier, SCOPE, load_config
from .core import Jobs, Policy
from .worker import run_pending
from .github_fixture import SyntheticGitHubReader


def build_server(verifier, jobs, fixture_reader=None):
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
        return {"status":"ready","caller_identity_verified":True,"repository_access":False,"mode":"authenticated-disposable"}

    @mcp.tool(annotations=write)
    def submit_probe_job(request_key: str) -> dict:
        """Submit the fixed read-only probe_check job; no user commands or paths."""
        return {"job_id":jobs.submit(principal(),"disposable","probe_check",request_key)}

    @mcp.tool(annotations=read)
    def get_job_status(job_id: str) -> dict:
        """Read the caller's disposable job result."""
        return jobs.get(principal(),job_id)

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",required=True,type=Path)
    parser.add_argument("--state-dir",required=True,type=Path)
    parser.add_argument("--port",type=int,default=8765)
    args = parser.parse_args()
    os.umask(0o077)
    verifier = load_config(args.config, args.state_dir)
    jobs = Jobs(args.state_dir,Policy((verifier.subject,op,"disposable") for op in ("submit","read","cancel")))
    fixture = SyntheticGitHubReader(Policy([(verifier.subject,"github_read","disposable")]),args.state_dir)
    server = build_server(verifier,jobs,fixture)
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            try:
                run_pending(jobs)
            except BlockingIOError:
                pass
            stop.wait(0.5)

    thread = threading.Thread(target=worker,daemon=True)
    thread.start()
    try:
        server.run(transport="streamable-http",host="127.0.0.1",port=args.port,
                   stateless_http=True,json_response=True,max_request_body_size=65536)
    finally:
        stop.set()
        thread.join(timeout=6)


if __name__ == "__main__":
    main()
