"""Opt-in OAuth resource server; only disposable jobs, never real resources."""
import argparse
import json
import os
import stat
import threading
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from .core import Jobs, Policy
from .worker import run_pending
from .github_fixture import SyntheticGitHubReader

SCOPE = "bridge:probe"


def https_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("HTTPS issuer and resource required")
    return value


class Verifier:
    """Pinned RSA public key, RFC 9068 JWT access token, exact issuer/audience/subject/client."""
    def __init__(self, issuer, resource, subject, client_id, public_key):
        self.issuer = https_url(issuer)
        self.resource = https_url(resource)
        if not all(isinstance(x,str) and 0 < len(x) <= 512 for x in (subject,client_id)):
            raise ValueError("Explicit subject and client_id required")
        self.subject, self.client_id = subject, client_id
        self.key = load_pem_public_key(public_key)
        if not isinstance(self.key, RSAPublicKey) or self.key.key_size < 2048:
            raise ValueError("RSA public key >= 2048 bits required")

    async def verify_token(self, token):
        if not isinstance(token,str) or len(token) > 16384:
            return None
        try:
            header = jwt.get_unverified_header(token)
            if header.get("typ") not in ("at+jwt","application/at+jwt"):
                return None
            claims = jwt.decode(token,self.key,algorithms=["RS256"],issuer=self.issuer,
                                audience=self.resource,options={"require":["exp","iat","iss","aud","sub","client_id","scope"]})
            if claims["sub"] != self.subject or claims["client_id"] != self.client_id:
                return None
            if not isinstance(claims["scope"],str) or SCOPE not in claims["scope"].split():
                return None
            if type(claims["exp"]) is not int or type(claims["iat"]) is not int or not 0 < claims["exp"]-claims["iat"] <= 3600:
                return None
            return AccessToken(token=token,client_id=self.client_id,subject=self.subject,
                               scopes=claims["scope"].split(),expires_at=claims["exp"],
                               resource=self.resource,claims={"iss":self.issuer})
        except (jwt.PyJWTError,ValueError,TypeError):
            return None


def load_config(path: Path):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("Canonical absolute config path required")
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_nlink != 1 or st.st_size > 32768:
        raise PermissionError("Private local config required")
    cfg = json.loads(path.read_text())
    if set(cfg) != {"issuer","resource","subject","client_id","public_key_pem"}:
        raise ValueError("Unexpected or missing configuration keys")
    return Verifier(cfg["issuer"],cfg["resource"],cfg["subject"],cfg["client_id"],cfg["public_key_pem"].encode())


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
        if token is None or token.subject != verifier.subject or token.client_id != verifier.client_id or SCOPE not in token.scopes:
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

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",required=True,type=Path)
    parser.add_argument("--state-dir",required=True,type=Path)
    parser.add_argument("--port",type=int,default=8765)
    args = parser.parse_args()
    os.umask(0o077)
    verifier = load_config(args.config)
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
