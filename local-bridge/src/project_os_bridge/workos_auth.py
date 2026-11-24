"""WorkOS Connect user access-token verifier. No token or private key storage."""
import asyncio
import json
import os
import re
import stat
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from mcp.server.auth.provider import AccessToken

SCOPE = "openid"
CLIENT_ID = "https://chatgpt.com/oauth/client.json"
SCOPES = {"openid", "profile", "email", "offline_access"}
MAX_JWKS = 65536


def private_file(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_nlink != 1:
        raise PermissionError("Private regular file required")
    return st


def private_directory(path):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("Canonical absolute directory required")
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise PermissionError("Private directory required")


def validate_issuer(issuer):
    # Staging/hosted AuthKit only; no userinfo, port, query, path or custom hosts.
    if not isinstance(issuer, str) or not re.fullmatch(r"https://[a-z0-9-]+\.authkit\.app", issuer):
        raise ValueError("Expected exact HTTPS hosted AuthKit issuer")
    return issuer


def validate_resource(resource):
    if not isinstance(resource, str) or not re.fullmatch(r"https://api\.openai\.com/v1/mcp/[A-Za-z0-9_-]+", resource):
        raise ValueError("Expected exact public OpenAI MCP tunnel URL")
    return resource


class JWKS:
    """Bounded HTTPS retrieval, no redirects/proxy or token-provided key URLs.
    Cache expires after five minutes; unknown kid refresh throttled globally.
    No stale-key fallback on expiry or failed refresh.
    """
    def __init__(self, issuer):
        self.url = validate_issuer(issuer) + "/oauth2/jwks"
        self.keys = {}
        self.expires = 0.0
        self.last_attempt = float("-inf")
        self.lock = threading.Lock()

    def fetch(self):
        with httpx.Client(timeout=5.0, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", self.url, headers={"Accept":"application/json","Accept-Encoding":"identity"}) as response:
                response.raise_for_status()
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise ValueError("Compressed JWKS rejected")
                raw = bytearray()
                for chunk in response.iter_raw():
                    if len(raw) + len(chunk) > MAX_JWKS:
                        raise ValueError("JWKS too large")
                    raw.extend(chunk)
                return json.loads(raw)

    def key(self, kid):
        with self.lock:
            now = time.monotonic()
            if now < self.expires and kid in self.keys:
                return self.keys[kid]
            if now - self.last_attempt < 15:
                raise ValueError("Unknown key or refresh cooldown")
            self.last_attempt = now
            document = self.fetch()
            entries = document.get("keys") if isinstance(document, dict) else None
            if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
                raise ValueError("Invalid JWKS")
            keys = {}
            seen = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Invalid JWK")
                name = entry.get("kid")
                if not isinstance(name,str) or not 1 <= len(name) <= 256 or name in seen:
                    raise ValueError("Invalid or duplicate kid")
                seen.add(name)
                if entry.get("kty") != "RSA" or entry.get("alg","RS256") != "RS256" or entry.get("use","sig") != "sig":
                    continue
                if "key_ops" in entry and (not isinstance(entry["key_ops"],list) or "verify" not in entry["key_ops"]):
                    continue
                if any(k in entry for k in ("d","p","q","dp","dq","qi","oth")):
                    raise ValueError("Private JWK rejected")
                key = jwt.PyJWK.from_dict(entry, algorithm="RS256").key
                if not isinstance(key,RSAPublicKey) or key.key_size < 2048:
                    raise ValueError("Invalid RSA key")
                keys[name] = key
            self.keys = keys
            self.expires = time.monotonic() + 300
            if kid not in keys:
                raise ValueError("Unknown signing key")
            return keys[kid]


class Verifier:
    def __init__(self, issuer, resource, subject, state_dir: Path, *, jwks=None):
        self.issuer = validate_issuer(issuer)
        self.resource = validate_resource(resource)
        if not isinstance(subject,str) or not re.fullmatch(r"user_[A-Za-z0-9]{1,128}",subject):
            raise ValueError("Explicit WorkOS user ID required")
        self.subject = subject
        self.client_id = CLIENT_ID
        private_directory(state_dir)
        self.state_dir = state_dir
        self.jwks = jwks if jwks is not None else JWKS(issuer)

    def enabled(self):
        try:
            private_directory(self.state_dir)
            return private_file(self.state_dir / "allow-authenticated-probe").st_size == 0
        except (OSError,ValueError):
            return False

    async def verify_token(self, token):
        if not isinstance(token,str) or not 1 <= len(token) <= 16384:
            return None
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            # WorkOS does not promise RFC 9068 typ. Distinguish access tokens
            # from ID/session tokens using exact audience, client, consent and scopes.
            if header.get("alg") != "RS256" or not isinstance(kid,str) or not 1 <= len(kid) <= 256:
                return None
            if header.get("typ") not in (None,"JWT","at+jwt","application/at+jwt"):
                return None
            if any(k in header for k in ("jku","jwk","x5u","crit")):
                return None
            key = await asyncio.to_thread(self.jwks.key,kid)
            claims = jwt.decode(token,key,algorithms=["RS256"],issuer=self.issuer,audience=self.resource,
                options={"require":["iss","aud","sub","client_id","sid","jti","scope","iat","exp"],"strict_aud":True})
            if claims["sub"] != self.subject or claims["client_id"] != CLIENT_ID:
                return None
            if any(k in claims for k in ("act","sub_profile","org_id")):
                return None
            if not all(isinstance(claims[k],str) and 0 < len(claims[k]) <= 512 for k in ("sid","jti")):
                return None
            if not isinstance(claims["scope"],str):
                return None
            scopes = set(claims["scope"].split())
            if SCOPE not in scopes or not scopes <= SCOPES:
                return None
            if ("nbf" in claims and type(claims["nbf"]) is not int) or type(claims["exp"]) is not int or type(claims["iat"]) is not int or not 0 < claims["exp"]-claims["iat"] <= 3600:
                return None
            return AccessToken(token=token,client_id=CLIENT_ID,subject=self.subject,
                scopes=sorted(scopes),expires_at=claims["exp"],resource=self.resource,claims={"iss":self.issuer})
        except (jwt.PyJWTError,ValueError,TypeError,KeyError,OSError,httpx.HTTPError,OverflowError,RecursionError):
            return None


def load_config(path: Path, state_dir: Path):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("Canonical absolute config path required")
    private_directory(path.parent)
    if private_file(path).st_size > 16384:
        raise ValueError("Config too large")
    cfg = json.loads(path.read_text())
    if not isinstance(cfg,dict) or set(cfg) != {"issuer","resource","subject"}:
        raise ValueError("Expected issuer, resource and subject only")
    return Verifier(cfg["issuer"],cfg["resource"],cfg["subject"],state_dir)
