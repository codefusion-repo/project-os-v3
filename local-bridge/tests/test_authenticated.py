import asyncio
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import time
import unittest
import httpx
from pathlib import Path
from datetime import datetime, timezone
from http import HTTPStatus
from unittest.mock import Mock, patch
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from starlette.testclient import TestClient
from project_os_bridge.authenticated import build_http_app
from project_os_bridge.workos_auth import Verifier, JWKS, SCOPE, CLIENT_ID, load_config
from project_os_bridge.core import Jobs, Policy
from project_os_bridge.security import Audit, AuditObservationError, MAX_AUDIT_BYTES, AUTH_AUDIT_NAME
from project_os_bridge.workos_auth import AuthOutcome, auth_outcome
from project_os_bridge.github_fixture import SyntheticGitHubReader
from project_os_bridge.github import GitHubReader
from project_os_bridge.github_context import GitHubContext

ISSUER="https://fixture.authkit.app"
RESOURCE="https://api.openai.com/v1/mcp/tunnel_fixture"
SUBJECT="user_fixture"


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.other=rsa.generate_private_key(public_exponent=65537,key_size=2048)

    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.flag=self.root/"allow-authenticated-probe"
        self.flag.touch(mode=0o600)
        self.jwks=JWKS(ISSUER)
        self.document={"keys":[self.jwk(self.key,"one")]}
        self.fetch=patch.object(self.jwks,"fetch",side_effect=lambda: self.document).start()
        self.addCleanup(patch.stopall)
        self.verifier=Verifier(ISSUER,RESOURCE,SUBJECT,self.root,jwks=self.jwks)

    def jwk(self,key,kid):
        return {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())),
                "kid":kid,"use":"sig","alg":"RS256"}

    def token(self,changes=None,key=None,kid="one",headers=None,*,omit=()):
        now=int(time.time())
        claims={"iss":ISSUER,"aud":RESOURCE,"sub":SUBJECT,"client_id":CLIENT_ID,
                "scope":"openid offline_access","sid":"consent_fixture","jti":"token_fixture","iat":now,"exp":now+300}
        claims.update(changes or {})
        for name in omit:
            del claims[name]
        return jwt.encode(claims,key or self.key,algorithm="RS256",headers={"kid":kid,**(headers or {})})

    def verify(self,token):
        return asyncio.run(self.verifier.verify_token(token))

    def test_valid_and_cache(self):
        self.assertEqual(self.verify(self.token()).subject,SUBJECT)
        self.assertIsNotNone(self.verify(self.token()))
        self.assertEqual(self.fetch.call_count,1)

    def test_invalid_claims(self):
        for changes in ({"iss":"https://wrong.authkit.app"},{"aud":"other"},{"aud":[RESOURCE]},
                        {"sub":"user_other"},{"client_id":"other"},{"scope":"profile"},{"scope":"openid admin"},
                        {"exp":1},{"iat":int(time.time())+600},{"exp":int(time.time())+7200},
                        {"sid":None},{"jti":None},{"act":{}},{"sub_profile":"ai_agent"},{"org_id":"org_fixture"}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.verify(self.token(changes)))

    def test_clock_skew_does_not_extend_expiry(self):
        # Freeze both the pinned library's UTC clock and the verifier clock.
        # The same signed token is rejected under the original zero leeway.
        now = int(time.time())
        fixed = datetime.fromtimestamp(now, timezone.utc)
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)

        with patch("jwt.api_jwt.datetime", FrozenDatetime), \
                patch("project_os_bridge.workos_auth.time.time", return_value=now):
            token = self.token({"iat": now + 3, "nbf": now + 3, "exp": now + 300})
            with self.assertRaises(jwt.exceptions.ImmatureSignatureError):
                jwt.decode(token, self.key.public_key(), algorithms=["RS256"],
                           issuer=ISSUER, audience=RESOURCE, leeway=0)
            self.assertIsNotNone(self.verify(token))
            for field in ("iat", "nbf"):
                for seconds in (0, 3, 5, 6):
                    with self.subTest(field=field, seconds=seconds):
                        result = self.verify(self.token({field: now + seconds}))
                        self.assertEqual(result is not None, seconds <= 5)
            for seconds in (-6, -5, -1, 0, 1):
                with self.subTest(expiry=seconds):
                    result = self.verify(self.token({"iat": now - 300, "exp": now + seconds}))
                    self.assertEqual(result is not None, seconds > 0)
                    if result is not None:
                        self.assertEqual(result.expires_at, now + seconds)
            for changes in ({"iat": now + 2, "exp": now + 2},
                            {"nbf": now + 4, "exp": now + 4},
                            {"nbf": now + 5, "exp": now + 4},
                            {"iat": now, "exp": now + 3601},
                            {"iat": str(now + 1)}, {"nbf": str(now + 1)},
                            {"exp": str(now + 300)},
                            {"iat": now + 3, "sub": "user_other"},
                            {"iat": now + 3, "aud": "other"},
                            {"iat": now + 3, "scope": "openid admin"}):
                with self.subTest(changes=changes):
                    self.assertIsNone(self.verify(self.token(changes)))
            self.assertIsNone(self.verify(self.token({"iat": now + 3}, key=self.other)))

    def test_clock_skew_http_contract(self):
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        app = build_http_app(self.verifier, jobs)
        now = int(time.time())
        # Long-lived boundaries in this HTTP test; exact edges tested above.
        accepted = self.token({"iat": now + 3, "nbf": now + 3, "exp": now + 300})
        future = self.token({"iat": now + 60})
        expired = self.token({"iat": now - 300, "exp": now - 1})
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            def call(token):
                return client.post("/mcp", json=init, headers={
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer " + token})
            for token in (future, expired):
                response = call(token)
                self.assertEqual(response.status_code, 401)
                self.assertIn("www-authenticate", response.headers)
                self.assertNotIn("TOKEN_NOT_YET_VALID", response.text + str(response.headers))
                self.assertNotIn("TOKEN_EXPIRED", response.text + str(response.headers))
            self.assertEqual(call(accepted).status_code, 200)
            self.flag.unlink()
            response = call(accepted)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("www-authenticate", response.headers)
        raw = (self.root / AUTH_AUDIT_NAME).read_text()
        self.assertEqual([json.loads(line)["auth_outcome"] for line in raw.splitlines()],
                         ["TOKEN_NOT_YET_VALID", "TOKEN_EXPIRED", "TOKEN_ACCEPTED", "TOKEN_ACCEPTED"])
        for token in (future, expired, accepted):
            self.assertNotIn(token, raw)

    def test_malformed_numeric_dates_fail_closed(self):
        for field in ("exp", "iat", "nbf"):
            for value in (float("inf"), float("-inf"), float("nan"), [], {}, True):
                with self.subTest(field=field, value=value):
                    self.assertIsNone(self.verify(self.token({field: value})))
        self.assertIsNone(self.verify(self.token({"nbf": str(int(time.time()) - 1)})))

    def test_parser_recursion_fails_closed(self):
        with patch("project_os_bridge.workos_auth.jwt.get_unverified_header", side_effect=RecursionError):
            self.assertIsNone(self.verify(self.token()))

    def test_malformed_numeric_date_http_401(self):
        jobs = Jobs(self.root, Policy([(SUBJECT, "submit", "disposable")]))
        app = build_http_app(self.verifier, jobs)
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            result = client.post("/mcp", headers={"Authorization": "Bearer " + self.token({"exp": float("inf")})})
            self.assertEqual(result.status_code, 401)
        with jobs.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_jwks_wire_size_and_encoding(self):
        import httpx
        client_class = httpx.Client
        for headers, content, expected in (
            ({"Content-Encoding": "gzip"}, b"not decompressed", "Compressed JWKS"),
            ({}, b"x" * 65537, "JWKS too large"),
        ):
            with self.subTest(expected=expected):
                def handle(request):
                    self.assertEqual(request.headers["accept-encoding"], "identity")
                    return httpx.Response(200, headers=headers, stream=httpx.ByteStream(content))
                with patch("project_os_bridge.workos_auth.httpx.Client",
                           side_effect=lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)):
                    with self.assertRaisesRegex(ValueError, expected):
                        JWKS.fetch(self.jwks)

    def test_invalid_signature_header(self):
        self.assertIsNone(self.verify(self.token(key=self.other)))
        self.assertIsNone(self.verify(self.token(headers={"jku":"https://wrong.example"})))
        self.assertIsNone(self.verify("not-a-token"))
        self.assertIsNone(self.verify(jwt.encode({"sub":SUBJECT},"bad",algorithm="HS256")))

    def test_rotation_and_expired_cache_fail_closed(self):
        self.assertIsNotNone(self.verify(self.token()))
        self.document={"keys":[self.jwk(self.other,"two")]}
        self.assertIsNone(self.verify(self.token(key=self.other,kid="two")))
        self.jwks.last_attempt -= 16
        self.assertIsNotNone(self.verify(self.token(key=self.other,kid="two")))
        self.assertIsNone(self.verify(self.token()))
        self.jwks.expires=0
        self.jwks.last_attempt -= 16
        self.fetch.side_effect=OSError("offline")
        self.assertIsNone(self.verify(self.token(key=self.other,kid="two")))

    def test_local_revocation_and_config(self):
        cfg=self.root/"oauth.json"
        cfg.touch(mode=0o600)
        cfg.write_text(json.dumps({"issuer":ISSUER,"resource":RESOURCE,"subject":SUBJECT}))
        self.assertEqual(load_config(cfg,self.root).subject,SUBJECT)
        cfg.chmod(0o644)
        with self.assertRaises(PermissionError):
            load_config(cfg,self.root)
        self.assertIsNotNone(self.verify(self.token()))
        self.flag.unlink()
        self.assertFalse(self.verifier.enabled())
        self.assertIsNotNone(self.verify(self.token()))
        self.assertIsNone(self.verify(self.token({"exp":1})))

    def test_local_auth_outcomes_and_unchanged_http_contract(self):
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        app = build_http_app(self.verifier, jobs)
        now = int(time.time())
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        base = {"Accept": "application/json, text/event-stream"}
        cases = [
            (None, "TOKEN_MISSING"),
            ("Bearer not-a-token", "TOKEN_MALFORMED"),
            ("Basic fixture", "TOKEN_MALFORMED"),
            ("Bearer " + self.token({"iat": now - 600, "exp": now - 300}), "TOKEN_EXPIRED"),
            ("Bearer " + self.token(key=self.other), "TOKEN_SIGNATURE_INVALID"),
            ("Bearer " + self.token({"aud": "private-fixture-audience"}), "TOKEN_AUDIENCE_INVALID"),
            ("Bearer " + self.token({"sub": "user_privatefixture"}), "TOKEN_SUBJECT_INVALID"),
            ("Bearer " + self.token({"scope": "offline_access"}), "TOKEN_SCOPE_INVALID"),
        ]
        tokens = [value for value, _ in cases if value is not None]
        valid = "Bearer " + self.token()
        tokens.append(valid)
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            for value, outcome in cases:
                headers = dict(base)
                if value is not None:
                    headers["Authorization"] = value
                response = client.post("/mcp", headers=headers, json=init)
                self.assertEqual(response.status_code, 401)
                self.assertIn("www-authenticate", response.headers)
                self.assertNotIn(outcome, response.text)
                self.assertNotIn(outcome, str(response.headers))
            with patch.object(self.jwks, "key", side_effect=OSError("private-fixture-network")):
                response = client.post("/mcp", headers={**base, "Authorization": valid}, json=init)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn("JWKS_UNAVAILABLE", response.text)
            response = client.post("/mcp", headers={**base, "Authorization": valid}, json=init)
            self.assertEqual(response.status_code, 200)
            self.flag.unlink()
            response = client.post("/mcp", headers={**base, "Authorization": valid}, json=init)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("www-authenticate", response.headers)
            response = client.get("/.well-known/oauth-protected-resource")
            self.assertEqual(response.status_code, 200)
        raw = (self.root / "security-audit.jsonl").read_text()
        auth_raw = (self.root / AUTH_AUDIT_NAME).read_text()
        events = [json.loads(line) for line in raw.splitlines()]
        observed = [json.loads(line) for line in auth_raw.splitlines()]
        completion = [event for event in events if event["status"] != 100]
        # Independently assert the legacy stream and its exact format, then
        # join the supplemental observations to the same completion timestamps.
        self.assertEqual([event["status"] for event in events],
                         [code for status in [401] * 9 + [200, 403, 200]
                          for code in (100, status)])
        self.assertTrue(all(set(e) == {"at", "event", "status"} for e in events))
        self.assertEqual([event["auth_outcome"] for event in observed],
                         [outcome for _, outcome in cases] +
                         ["JWKS_UNAVAILABLE", "TOKEN_ACCEPTED", "TOKEN_ACCEPTED"])
        self.assertTrue(all(set(e) == {"at", "event", "status", "auth_outcome"}
                            for e in observed))
        self.assertEqual([{k: v for k, v in e.items() if k != "auth_outcome"}
                          for e in observed], completion[:-1])
        for secret in tokens + ["private-fixture-audience", "user_privatefixture",
                                "private-fixture-network", SUBJECT, RESOURCE, ISSUER]:
            self.assertNotIn(secret, raw + auth_raw)
        self.assertIsNone(auth_outcome.get())
        with jobs.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_claim_rejection_categories_and_legacy_audit(self):
        # All rejection details remain local, with the original four-field
        # sidecar schema, unchanged primary stream and identical HTTP 401.
        audit = Audit(self.root)
        audit.record(401, outcome=AuthOutcome.TOKEN_CLAIMS_INVALID)
        old_primary = audit.path.read_bytes()
        old_sidecar = audit.auth_path.read_bytes()
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        app = build_http_app(self.verifier, jobs)
        now = int(time.time())
        cases = [
            (self.token({"sub": "user_privatefixture"}), "TOKEN_SUBJECT_INVALID"),
            (self.token({"sub": 123}), "TOKEN_SUBJECT_INVALID"),
            (self.token({"client_id": "private-fixture-client"}), "TOKEN_CLIENT_MISMATCH"),
            (self.token(omit=("sid",)), "TOKEN_REQUIRED_CLAIM_MISSING"),
            (self.token({"org_id": "private-fixture-org"}), "TOKEN_FORBIDDEN_CLAIM_PRESENT"),
            (self.token({"sid": ""}), "TOKEN_SESSION_CLAIM_INVALID"),
            (self.token({"jti": 123}), "TOKEN_SESSION_CLAIM_INVALID"),
            (self.token({"scope": ["openid"]}), "TOKEN_SCOPE_INVALID"),
            (self.token({"scope": "openid private-fixture-scope"}), "TOKEN_SCOPE_INVALID"),
            (self.token({"exp": now + 7200}), "TOKEN_TEMPORAL_CLAIM_INVALID"),
            (self.token({"nbf": now + 600}), "TOKEN_NOT_YET_VALID"),
            (self.token({"iat": "private-fixture-date"}), "TOKEN_TEMPORAL_CLAIM_INVALID"),
            (self.token({"iss": "https://private-fixture.authkit.app"}), "TOKEN_ISSUER_INVALID"),
        ]
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        base = {"Accept": "application/json, text/event-stream"}
        def check(client, token):
            response = client.post("/mcp", headers={**base, "Authorization": "Bearer " + token}, json=init)
            self.assertEqual(response.status_code, 401)
            self.assertIn("www-authenticate", response.headers)
            for outcome in AuthOutcome:
                self.assertNotIn(outcome.value, response.text)
                self.assertNotIn(outcome.value, str(response.headers))
            return response.content, response.headers["www-authenticate"]

        valid = self.token()
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            baseline = check(client, cases[0][0])
            for token, outcome in cases[1:]:
                with self.subTest(outcome=outcome):
                    self.assertEqual(check(client, token), baseline)
            with patch("project_os_bridge.workos_auth.jwt.decode",
                       side_effect=ValueError("private-fixture-exception")):
                self.assertEqual(check(client, valid), baseline)
            self.assertEqual(client.post("/mcp", headers={**base, "Authorization": "Bearer " + valid}, json=init).status_code, 200)
        primary = audit.path.read_bytes()
        supplemental = audit.auth_path.read_bytes()
        self.assertTrue(primary.startswith(old_primary))
        self.assertTrue(supplemental.startswith(old_sidecar))
        events = [json.loads(line) for line in primary.splitlines()]
        observed = [json.loads(line) for line in supplemental.splitlines()]
        self.assertEqual([e["auth_outcome"] for e in observed],
                         ["TOKEN_CLAIMS_INVALID"] + [outcome for _, outcome in cases] +
                         ["TOKEN_CLAIMS_INVALID", "TOKEN_ACCEPTED"])
        self.assertTrue(all(set(e) == {"at", "event", "status", "auth_outcome"} for e in observed))
        self.assertEqual([{k: v for k, v in e.items() if k != "auth_outcome"} for e in observed],
                         [e for e in events if e["status"] != 100])
        self.assertTrue(all(AuthOutcome(e["auth_outcome"]) for e in observed))
        for value in [token for token, _ in cases] + [valid, "private-fixture", SUBJECT, RESOURCE, ISSUER]:
            self.assertNotIn(value.encode(), primary + supplemental)
        self.assertIsNone(auth_outcome.get())
        with jobs.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_sdk_http_status_enum_and_health_audit(self):
        # Trace the actual pinned SDK -> ASGI -> RequestGate -> Audit path.
        # Capture status and the fixed category only, not headers or JWTs.
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        audit = Audit(self.root)
        app = build_http_app(self.verifier, jobs, audit=audit)
        headers = {"Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + self.token()}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        health = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": "health", "arguments": {}}}
        trace = []
        record = audit.record

        def traced(status, *, outcome=None):
            kind = type(status).__name__
            try:
                record(status, outcome=outcome)
            except (OSError, ValueError) as exc:
                trace.append((kind, int(status), outcome, type(exc).__name__))
                raise
            trace.append((kind, int(status), outcome, "recorded"))

        with patch.object(audit, "record", side_effect=traced):
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                response = client.post("/mcp", headers=headers, json=init)
                self.assertEqual(response.status_code, 200)
                headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
                response = client.post("/mcp", headers=headers, json=health)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["result"].get("isError", False))
                result = response.json()["result"]
                self.assertEqual(len(result["content"]), 1)
                self.assertEqual(result["content"][0]["type"], "text")
                payload = json.loads(result["content"][0]["text"])
                self.assertEqual(payload, {"status": "ready",
                    "caller_identity_verified": True, "repository_access": False,
                    "mode": "authenticated-disposable", "git_fixture_available": False,
                    "installation": {"status": "unavailable"}})
        self.assertEqual(trace, [
            ("int", 100, None, "recorded"),
            ("HTTPStatus", 200, AuthOutcome.TOKEN_ACCEPTED, "recorded"),
            ("int", 100, None, "recorded"),
            ("HTTPStatus", 200, AuthOutcome.TOKEN_ACCEPTED, "recorded"),
        ])
        # The previous strict predicate rejected exactly this input.
        self.assertIsNot(type(HTTPStatus.OK), int)
        events = [json.loads(line) for line in audit.path.read_text().splitlines()]
        observations = [json.loads(line) for line in audit.auth_path.read_text().splitlines()]
        self.assertEqual([e["status"] for e in events], [100, 200, 100, 200])
        self.assertTrue(all(type(e["status"]) is int for e in events))
        self.assertEqual(observations, [{**e, "auth_outcome": "TOKEN_ACCEPTED"}
                                        for e in events if e["status"] == 200])

    def test_auth_observation_open_failure_preserves_http_completion(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                audit = Audit(root)
                if existing:
                    audit.record(401, outcome=AuthOutcome.TOKEN_EXPIRED)
                audit.record(100)
                original_open = audit._open

                def fail_sidecar(path, **kwargs):
                    if path == audit.auth_path:
                        raise OSError("fixture private path")
                    return original_open(path, **kwargs)

                with patch.object(audit, "_open", side_effect=fail_sidecar):
                    with self.assertRaises(AuditObservationError):
                        audit.record(HTTPStatus.OK, outcome=AuthOutcome.TOKEN_ACCEPTED)
                    if existing:
                        # A subsequent admission still fails closed.
                        with self.assertRaises(OSError):
                            audit.record(100)
                events = [json.loads(line) for line in audit.path.read_text().splitlines()]
                self.assertEqual([e["status"] for e in events],
                                 ([401] if existing else []) + [100, 200])
                if existing:
                    self.assertEqual(len(audit.auth_path.read_text().splitlines()), 1)
                else:
                    self.assertFalse(audit.auth_path.exists())

    def test_http_completion_warning_is_sanitized(self):
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        audit = Audit(self.root)
        app = build_http_app(self.verifier, jobs, audit=audit)
        headers = {"Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + self.token()}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        original_open = audit._open

        def fail_sidecar(path, **kwargs):
            if path == audit.auth_path:
                raise OSError("private-fixture-error")
            return original_open(path, **kwargs)

        with patch.object(audit, "_open", side_effect=fail_sidecar):
            with self.assertLogs("project_os_bridge.security", level="WARNING") as logs:
                with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                    self.assertEqual(client.post("/mcp", headers=headers, json=init).status_code, 200)
        self.assertEqual(logs.output, [
            "WARNING:project_os_bridge.security:OAuth audit observation unavailable"])
        self.assertEqual([json.loads(line)["status"] for line in
                          audit.path.read_text().splitlines()], [100, 200])

    def test_auth_outcome_audit_validation_and_capacity(self):
        audit = Audit(self.root)
        for invalid in (True, 200.0, "200", 99, 600):
            with self.assertRaises(ValueError):
                audit.record(invalid)
        with self.assertRaises(ValueError):
            audit.record(401, outcome="arbitrary-private-value")
        with self.assertRaises(ValueError):
            audit.record(100, outcome=AuthOutcome.TOKEN_ACCEPTED)
        audit.record(401, outcome=AuthOutcome.TOKEN_EXPIRED)
        legacy = json.loads(audit.path.read_text())
        observed = json.loads(audit.auth_path.read_text())
        self.assertEqual(observed, {**legacy, "auth_outcome": "TOKEN_EXPIRED"})
        self.assertEqual(set(legacy), {"at", "event", "status"})
        with audit.path.open("wb") as stream:
            stream.truncate(MAX_AUDIT_BYTES - audit.auth_path.stat().st_size)
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        app = build_http_app(self.verifier, jobs)
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            self.assertEqual(client.post("/mcp", headers={"Authorization": "Bearer " + self.token()}).status_code, 503)
        self.assertEqual(audit.path.stat().st_size + audit.auth_path.stat().st_size,
                         MAX_AUDIT_BYTES)
        self.assertEqual(self.fetch.call_count, 0)

    def test_auth_observation_failure_preserves_http_completion(self):
        audit = Audit(self.root)
        audit.record(100)
        append = audit._append
        def fail_sidecar(fd, data):
            if b'"auth_outcome"' in data:
                raise OSError("fixture write failure")
            append(fd, data)
        with patch.object(audit, "_append", side_effect=fail_sidecar):
            with self.assertRaises(OSError):
                audit.record(403, outcome=AuthOutcome.TOKEN_ACCEPTED)
        self.assertEqual([json.loads(line)["status"] for line in
                          audit.path.read_text().splitlines()], [100, 403])
        self.assertEqual(audit.auth_path.read_bytes(), b"")

    def test_auth_audit_shared_budget_and_unsafe_sidecar(self):
        audit = Audit(self.root)
        audit.auth_path.touch(mode=0o600)
        with audit.auth_path.open("wb") as stream:
            stream.truncate(MAX_AUDIT_BYTES - 110)
        # Legacy completion fits, but the supplemental record cannot.
        with self.assertRaises(OSError):
            audit.record(403, outcome=AuthOutcome.TOKEN_ACCEPTED)
        self.assertEqual(json.loads(audit.path.read_text())["status"], 403)
        self.assertLessEqual(audit.path.stat().st_size + audit.auth_path.stat().st_size,
                             MAX_AUDIT_BYTES)
        with self.assertRaises(OSError):
            audit.record(100)
        audit.auth_path.unlink()
        target = self.root / "private-target"
        target.write_bytes(b"unchanged")
        audit.auth_path.symlink_to(target)
        with self.assertRaises(OSError):
            audit.record(100)
        self.assertEqual(target.read_bytes(), b"unchanged")

    def test_auth_outcomes_concurrent_requests_and_child_tasks(self):
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        app = build_http_app(self.verifier, jobs)
        valid = self.token()
        now = int(time.time())
        expired = self.token({"iat": now - 600, "exp": now - 300})
        verify = self.verifier.verify_token
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}

        async def scenario():
            accepted = asyncio.Event()
            rejected = asyncio.Event()

            async def interleaved(token):
                # Force verification in an inherited child-task context.
                result = await asyncio.create_task(verify(token))
                if token == valid:
                    accepted.set()
                    await asyncio.wait_for(rejected.wait(), timeout=5)
                elif token == expired:
                    await asyncio.wait_for(accepted.wait(), timeout=5)
                    rejected.set()
                return result

            async with app.router.lifespan_context(app):
                with patch.object(self.verifier, "verify_token", side_effect=interleaved):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app),
                        base_url="http://127.0.0.1:8765",
                        headers={"Accept": "application/json, text/event-stream"},
                    ) as client:
                        async def call(token):
                            return await client.post("/mcp", json=init,
                                headers={"Authorization": "Bearer " + token})
                        good, bad = await asyncio.wait_for(
                            asyncio.gather(call(valid), call(expired)), timeout=15)
                        self.assertEqual((good.status_code, bad.status_code), (200, 401))
                        self.assertIn("www-authenticate", bad.headers)
                        self.assertEqual((await client.get(
                            "/.well-known/oauth-protected-resource")).status_code, 200)
                        self.assertEqual((await client.post("/mcp", json=init)).status_code, 401)
                        self.assertIsNone(auth_outcome.get())

        asyncio.run(scenario())
        events = [json.loads(line) for line in
                  (self.root / "security-audit.jsonl").read_text().splitlines()]
        observed = [json.loads(line) for line in
                    (self.root / AUTH_AUDIT_NAME).read_text().splitlines()]
        self.assertCountEqual([(e["status"], e["auth_outcome"]) for e in observed],
                              [(200, "TOKEN_ACCEPTED"), (401, "TOKEN_EXPIRED"),
                               (401, "TOKEN_MISSING")])
        self.assertCountEqual([e["status"] for e in events],
                              [100, 100, 200, 401, 100, 200, 100, 401])
        for e in observed:
            self.assertIn({k: v for k, v in e.items() if k != "auth_outcome"}, events)
        self.assertIsNone(auth_outcome.get())

    def test_resource_discovery_excludes_refresh_scope(self):
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        app = build_http_app(self.verifier, jobs)
        prefix = "/.well-known/oauth-protected-resource"
        canonical = prefix + "/v1/mcp/tunnel_fixture"
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            # Metadata must remain public when the local opt-in is revoked.
            self.flag.unlink()
            documents = []
            cache_headers = []
            for path in (canonical, prefix, prefix + "/mcp"):
                response = client.get(path, headers={"Origin": "https://chatgpt.com"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("access-control-allow-origin"), "*")
                documents.append(response.json())
                cache_headers.append(response.headers.get("cache-control"))
                preflight = client.options(path, headers={
                    "Origin": "https://chatgpt.com",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "MCP-Protocol-Version",
                })
                self.assertEqual(preflight.status_code, 200)
                self.assertEqual(client.post(path).status_code, 405)
            self.assertEqual(documents, [documents[0]] * 3)
            self.assertTrue(cache_headers[0])
            self.assertEqual(cache_headers, [cache_headers[0]] * 3)
            self.assertEqual(documents[0], {
                "resource": RESOURCE,
                "authorization_servers": [ISSUER],
                "scopes_supported": ["openid"],
                "bearer_methods_supported": ["header"],
            })
            accept = {"Accept": "application/json, text/event-stream"}
            init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "test", "version": "1"}}}
            denied = client.post("/mcp", headers=accept, json=init)
            self.assertEqual(denied.status_code, 401)
            self.assertIn("https://api.openai.com" + canonical,
                          denied.headers["www-authenticate"])
            self.assertNotIn("offline_access", denied.headers["www-authenticate"])
            valid = {**accept, "Authorization": "Bearer " + self.token({"scope": "openid"})}
            revoked = client.post("/mcp", headers=valid, json=init)
            self.assertEqual(revoked.status_code, 403)
            self.assertNotIn("www-authenticate", revoked.headers)
            self.flag.touch(mode=0o600)
            for scope in ("openid", "openid offline_access"):
                response = client.post("/mcp", json=init, headers={
                    **accept, "Authorization": "Bearer " + self.token({"scope": scope}),
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn("result", response.json())
            no_access = client.post("/mcp", json=init, headers={
                **accept, "Authorization": "Bearer " + self.token({"scope": "offline_access"}),
            })
            self.assertEqual(no_access.status_code, 401)
            self.assertNotIn("offline_access", no_access.headers["www-authenticate"])
        with jobs.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_expired_and_replacement_tokens_across_app_restart(self):
        policy = Policy((SUBJECT, op, "disposable") for op in ("read", "submit"))
        now = int(time.time())
        expired = self.token({"iat": now - 600, "exp": now - 300, "jti": "expired_fixture"})
        tokens = [self.token({"jti": "replacement_fixture_" + str(i)}) for i in range(2)]
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": "submit_probe_job", "arguments": {"request_key": "refresh-replay"}}}
        first_result = None
        for token in tokens:
            jobs = Jobs(self.root, policy)
            app = build_http_app(self.verifier, jobs)
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                headers = {"Accept": "application/json, text/event-stream",
                           "Authorization": "Bearer " + expired}
                response = client.post("/mcp", headers=headers, json=init)
                self.assertEqual(response.status_code, 401)
                self.assertIn("www-authenticate", response.headers)
                headers["Authorization"] = "Bearer " + token
                response = client.post("/mcp", headers=headers, json=init)
                self.assertEqual(response.status_code, 200)
                headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
                response = client.post("/mcp", headers=headers, json=request)
                self.assertEqual(response.status_code, 200)
                result = response.json()["result"]
                self.assertFalse(result.get("isError", False))
                if first_result is None:
                    first_result = result
                else:
                    self.assertEqual(result, first_result)
            with jobs.transaction() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_candidate_github_context_authenticated_and_revocable(self):
        jobs = Jobs(self.root, Policy([]))
        reader = GitHubReader(Policy([(SUBJECT, "github_read", "demo")]),
                              {"demo": "example/demo"}, self.root)
        grants = {(SUBJECT, "demo", "example/demo")}
        provider = GitHubContext(reader, lambda *grant: grant in grants)
        app = build_http_app(self.verifier, jobs, github_provider=provider)
        headers = {"Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + self.token()}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "github_context", "arguments": {"project": "demo", "numbers": [1]}}}

        def fake(endpoint):
            if "/comments?" in endpoint:
                return {"complete": True, "data": []}
            return {"complete": True, "data": {"number": 1, "title": "candidate-context", "comments": 0,
                                                    "body": None, "state": "open",
                                                    "repository_url": "https://api.github.com/repos/example/demo",
                                                    "url": "https://api.github.com/repos/example/demo/issues/1"}}

        with patch.object(reader, "_request", side_effect=fake) as request:
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                response = client.post("/mcp", headers=headers, json=init)
                self.assertEqual(response.status_code, 200)
                headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
                listing = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
                self.assertIn("github_context", {tool["name"] for tool in listing.json()["result"]["tools"]})
                result = client.post("/mcp", headers=headers, json=call)
                self.assertEqual(result.status_code, 200)
                self.assertFalse(result.json()["result"].get("isError", False))
                self.assertIn("candidate-context", result.text)
                self.assertEqual(request.call_count, 2)
                denied = client.post("/mcp", headers={**headers, "Authorization": "Bearer " + self.token({"sub": "user_other"})}, json=call)
                self.assertEqual(denied.status_code, 401)
                self.assertEqual(request.call_count, 2)

                def revoke(endpoint):
                    grants.clear()
                    return fake(endpoint)
                request.side_effect = revoke
                denied = client.post("/mcp", headers=headers, json=call)
                self.assertTrue(denied.json()["result"].get("isError", False))
                self.assertNotIn("candidate-context", denied.text)
                count = request.call_count
                self.assertEqual(count, 3)
                denied = client.post("/mcp", headers=headers, json=call)
                self.assertTrue(denied.json()["result"].get("isError", False))
                self.assertEqual(request.call_count, count)
                grants.add((SUBJECT, "demo", "example/demo"))

                def revoke_global(endpoint):
                    self.flag.unlink()
                    return fake(endpoint)

                request.side_effect = revoke_global
                denied = client.post("/mcp", headers=headers, json=call)
                self.assertTrue(denied.json()["result"].get("isError", False))
                self.assertNotIn("candidate-context", denied.text)
                self.assertEqual(request.call_count, count + 1)


    def test_multirepo_http_overlap_and_revocation(self):
        from project_os_bridge.github_operational import (
            CONFIG_DIR, FLAG, load_operational_provider, read_project_binding,
        )
        state = self.root / "state"
        state.mkdir(mode=0o700)
        (state / "allow-authenticated-probe").touch(mode=0o600)
        (self.root / CONFIG_DIR).mkdir(mode=0o700)
        service = self.root / "service"
        service.mkdir(mode=0o700)
        runtime = service / "runtime.json"
        runtime.touch(mode=0o600)
        grants = {}
        for project, repo_id in (("alpha", 101), ("beta", 202)):
            checkout = self.root / project
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            (checkout / ".gitignore").write_text(".project-os/\n")
            (checkout / ".project-os").mkdir(mode=0o700)
            config = checkout / ".project-os/config.json"
            config.touch(mode=0o600)
            repo = "example/" + project
            config.write_text(json.dumps({"version": 2, "repositories": [repo],
                                          "github_context": {"project": project, "repository": repo,
                                                             "repository_id": repo_id}}))
            grants[project] = {"config": str(config), "repository": repo, "repository_id": repo_id}
        def publish(entries):
            tmp = service / "fixture-runtime.tmp"
            tmp.touch(mode=0o600)
            tmp.write_text(json.dumps({"tunnel": "fixture", "tunnel_id": "fixture", "image": None,
                                       "github_projects": entries}))
            os.replace(tmp, runtime)
        publish(grants)
        verifier = Verifier(ISSUER, RESOURCE, SUBJECT, state, jwks=self.jwks)
        (state / FLAG).touch(mode=0o600)
        # Reconstruct the provider with the previous opt-in already present,
        # as on a routine supervised restart. Existing HTTP overlap/revocation
        # checks exercise both restored grants without creating new access.
        provider = load_operational_provider(verifier, supervised=True, multi=True)
        app = build_http_app(verifier, Jobs(state, Policy([])), github_provider=provider)
        headers = {"Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + self.token()}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "concurrent-test", "version": "1"}}}

        def upstream(reader, endpoint):
            repo = endpoint.split("/")[1:3]
            self.assertEqual("/".join(repo), next(iter(reader.repositories.values())))
            project = repo[1]
            base = "https://api.github.com/repos/example/" + project
            if endpoint == "repos/example/" + project:
                return {"complete": True, "data": {"id": grants[project]["repository_id"],
                                                   "full_name": "example/" + project}}
            if "/comments?" in endpoint:
                return {"complete": True, "data": []}
            return {"complete": True, "data": {"number": 1, "title": project + "-fixture-issue",
                                                "body": None, "state": "open", "comments": 0,
                                                "repository_url": base, "url": base + "/issues/1"}}

        def methodology(path, repository, workflow, skills, templates, expected_revision):
            self.assertEqual(str(path), grants[repository.split("/")[1]]["config"])
            return {"complete": True, "documents": [{"content": repository + "-fixture-methodology"}]}

        def call(client, tool, project, number):
            args = {"project": project}
            if tool == "github_context":
                args["numbers"] = [1]
            else:
                args.update(workflow="implement", skills=[], templates=[])
            return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": number,
                               "method": "tools/call", "params": {"name": tool, "arguments": args}})

        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            initialized = client.post("/mcp", headers=headers, json=init)
            self.assertEqual(initialized.status_code, 200)
            headers["MCP-Protocol-Version"] = initialized.json()["result"]["protocolVersion"]
            listing = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2,
                                  "method": "tools/list", "params": {}})
            self.assertTrue({"github_context", "methodology_context"} <=
                            {tool["name"] for tool in listing.json()["result"]["tools"]})
            with patch.object(GitHubReader, "_request", autospec=True, side_effect=upstream), \
                    patch("project_os_bridge.authenticated.installed_context", side_effect=methodology):
                for index, (slow_tool, revoke) in enumerate(
                        (("github_context", False), ("methodology_context", True))):
                    with self.subTest(tool=slow_tool):
                        publish(grants)
                        entered, release = threading.Event(), threading.Event()
                        def slow_binding(path):
                            if str(path) == grants["alpha"]["config"] and not entered.is_set():
                                entered.set()
                                if not release.wait(15):
                                    raise RuntimeError("Fixture synchronization timeout")
                            return read_project_binding(path)
                        with patch("project_os_bridge.github_operational.read_project_binding",
                                   side_effect=slow_binding), ThreadPoolExecutor(max_workers=2) as executor:
                            alpha = executor.submit(call, client, slow_tool, "alpha", 10 + index * 3)
                            try:
                                self.assertTrue(entered.wait(5))
                                beta = executor.submit(call, client, "github_context", "beta", 11 + index * 3)
                                answer = beta.result(timeout=8)
                                self.assertEqual(answer.status_code, 200)
                                self.assertFalse(answer.json()["result"].get("isError", False))
                                self.assertIn("beta-fixture-issue", answer.text)
                                self.assertNotIn("alpha-fixture-issue", answer.text)
                                self.assertFalse(alpha.done())
                                if revoke:
                                    publish({"beta": grants["beta"]})
                            finally:
                                release.set()
                            answer = alpha.result(timeout=8)
                            self.assertEqual(answer.status_code, 200)
                            self.assertEqual(bool(answer.json()["result"].get("isError", False)), revoke)
                            if revoke:
                                self.assertNotIn("alpha-fixture-methodology", answer.text)
                                still = call(client, "methodology_context", "beta", 12 + index * 3)
                                self.assertFalse(still.json()["result"].get("isError", False))
                                self.assertIn("beta-fixture-methodology", still.text)
                            else:
                                self.assertIn("alpha-fixture-issue", answer.text)
                                self.assertNotIn("beta-fixture-issue", answer.text)

    def test_candidate_github_context_expires_during_http_read(self):
        jobs = Jobs(self.root, Policy([]))
        reader = GitHubReader(Policy([(SUBJECT, "github_read", "demo")]),
                              {"demo": "example/demo"}, self.root)
        provider = GitHubContext(reader, lambda *grant:
                                 grant == (SUBJECT, "demo", "example/demo"))
        app = build_http_app(self.verifier, jobs, github_provider=provider)
        now = int(time.time())
        expires_at = now + 300
        headers = {"Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + self.token({"exp": expires_at})}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "github_context", "arguments": {"project": "demo", "numbers": [1]}}}

        # Move only the handler's clock; JWT verification and the HTTP stack
        # retain their real clocks. No sleeps or real upstream traffic.
        with patch("project_os_bridge.authenticated.time", wraps=time) as clock:
            clock.time.return_value = now

            def fake(endpoint):
                if "/comments?" in endpoint:
                    return {"complete": True, "data": []}
                return {"complete": True, "data": {"number": 1, "title": "expiry-fixture-context", "comments": 0,
                                                    "body": None, "state": "open",
                                                    "repository_url": "https://api.github.com/repos/example/demo",
                                                    "url": "https://api.github.com/repos/example/demo/issues/1"}}

            with patch.object(reader, "_request", side_effect=fake) as request:
                with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                    response = client.post("/mcp", headers=headers, json=init)
                    self.assertEqual(response.status_code, 200)
                    headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
                    response = client.post("/mcp", headers=headers, json=call)
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(response.json()["result"].get("isError", False))
                    self.assertIn("expiry-fixture-context", response.text)
                    self.assertEqual(request.call_count, 2)

                    def expire(endpoint):
                        result = fake(endpoint)
                        # Equality with exp must already be denied.
                        clock.time.return_value = expires_at
                        return result

                    request.reset_mock()
                    request.side_effect = expire
                    response = client.post("/mcp", headers=headers, json=call)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.json()["result"].get("isError", False))
                    self.assertNotIn("expiry-fixture-context", response.text)
                    request.assert_called_once_with("repos/example/demo/issues/1")
                    self.assertTrue(self.verifier.enabled())
                    self.assertEqual(provider.require(SUBJECT, "demo"), "example/demo")

                    # The same logically expired session cannot start more reads.
                    response = client.post("/mcp", headers=headers, json=call)
                    self.assertTrue(response.json()["result"].get("isError", False))
                    request.assert_called_once_with("repos/example/demo/issues/1")

    def test_operational_context_audit_denies_disclosure_on_failure(self):
        from project_os_bridge.github_operational import GitHubContextAudit, AUDIT_NAME
        jobs = Jobs(self.root, Policy([]))
        reader = GitHubReader(Policy([(SUBJECT, "github_read", "demo")]),
                              {"demo": "example/demo"}, self.root)
        audit = GitHubContextAudit(self.root)
        provider = GitHubContext(reader, lambda *grant: grant == (SUBJECT, "demo", "example/demo"),
                                 audit=audit)
        app = build_http_app(self.verifier, jobs, github_provider=provider)
        headers = {"Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + self.token()}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "github_context", "arguments": {"project": "demo", "numbers": [1]}}}
        def fake(endpoint):
            if "/comments?" in endpoint:
                return {"complete": True, "data": []}
            return {"complete": True, "data": {"number": 1, "title": "audit-fixture-content", "comments": 0,
                                               "body": None, "state": "open",
                                               "repository_url": "https://api.github.com/repos/example/demo",
                                               "url": "https://api.github.com/repos/example/demo/issues/1"}}
        with patch.object(reader, "_request", side_effect=fake) as request:
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                response = client.post("/mcp", headers=headers, json=init)
                self.assertEqual(response.status_code, 200)
                headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
                response = client.post("/mcp", headers=headers, json=call)
                self.assertIn("audit-fixture-content", response.text)
                self.assertEqual(request.call_count, 2)
                records = [json.loads(line) for line in (self.root / AUDIT_NAME).read_text().splitlines()]
                self.assertEqual([r["outcome"] for r in records], ["admitted", "complete"])
                with patch.object(audit, "record", side_effect=OSError("private fixture")):
                    denied = client.post("/mcp", headers=headers, json=call)
                    self.assertTrue(denied.json()["result"].get("isError", False))
                    self.assertNotIn("private fixture", denied.text)
                    self.assertEqual(request.call_count, 2)
                with patch.object(audit, "record", side_effect=[None, OSError("private fixture")]):
                    denied = client.post("/mcp", headers=headers, json=call)
                    self.assertTrue(denied.json()["result"].get("isError", False))
                    self.assertNotIn("audit-fixture-content", denied.text)
                    self.assertNotIn("private fixture", denied.text)
                    self.assertEqual(request.call_count, 4)

    def test_health_reports_install_receipt_without_private_details(self):
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        app = build_http_app(self.verifier, jobs)
        headers = {"Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + self.token()}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "health", "arguments": {}}}
        receipt = {"sha": "a" * 40, "wheel_sha256": "b" * 64}
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            response = client.post("/mcp", headers=headers, json=init)
            self.assertEqual(response.status_code, 200)
            headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
            with patch("project_os_bridge.authenticated.installed_receipt", return_value=receipt):
                result = client.post("/mcp", headers=headers, json=call)
                self.assertEqual(result.status_code, 200)
                self.assertFalse(result.json()["result"].get("isError", False))
                self.assertIn("receipt_observed", result.text)
                self.assertIn(receipt["sha"], result.text)
                self.assertIn(receipt["wheel_sha256"], result.text)
            with patch("project_os_bridge.authenticated.installed_receipt",
                       side_effect=PermissionError("/private/fixture")):
                result = client.post("/mcp", headers=headers, json=call)
                self.assertEqual(result.status_code, 200)
                self.assertIn("unavailable", result.text)
                self.assertNotIn("/private/fixture", result.text)
                self.assertNotIn(receipt["wheel_sha256"], result.text)

    def test_maintenance_http_grant_and_local_revocation(self):
        from project_os_bridge.maintenance import Maintenance, FLAG
        root = self.root / "instance"
        root.mkdir(mode=0o700)
        (root / "service").mkdir(mode=0o700)
        (root / "state").mkdir(mode=0o700)
        maintenance = Maintenance(root, root / "kit")
        for name in (FLAG, "allow-authenticated-probe"):
            (maintenance.state / name).touch(mode=0o600)
        params = {"expected_sha": "a" * 40, "target_sha": "b" * 40,
                  "wheel_sha256": "c" * 64, "ci_run_id": 123, "request_key": "test"}
        headers = {"Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + self.token()}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "1"}}}
        def call(client, name, arguments):
            return client.post("/mcp", headers=headers,
                               json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                     "params": {"name": name, "arguments": arguments}})
        for allowed in (False, True):
            grants = [(SUBJECT, "read", "disposable")]
            if allowed:
                grants.append((SUBJECT, "maintenance", "installation"))
            jobs = Jobs(self.root, Policy(grants))
            app = build_http_app(self.verifier, jobs, maintenance=maintenance)
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                response = client.post("/mcp", headers=headers, json=init)
                self.assertEqual(response.status_code, 200)
                headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
                with patch.object(maintenance, "submit", return_value={"state": "ACCEPTED"}) as submit, \
                        patch.object(maintenance, "status", return_value={"state": "ACCEPTED"}) as status:
                    for name, arguments in (("maintenance_update", params),
                                            ("maintenance_status", {"request_key": "test"})):
                        response = call(client, name, arguments)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["result"].get("isError", False), not allowed)
                    self.assertEqual(submit.call_count, int(allowed))
                    self.assertEqual(status.call_count, int(allowed))
                    if allowed:
                        (maintenance.state / FLAG).unlink()
                        denied = call(client, "maintenance_update", params)
                        self.assertTrue(denied.json()["result"].get("isError", False))
                        self.assertEqual(submit.call_count, 1)
                        denied = call(client, "maintenance_rollback",
                                      {k: v for k, v in params.items() if k != "ci_run_id"})
                        self.assertTrue(denied.json()["result"].get("isError", False))
                        self.assertEqual(submit.call_count, 1)

    def test_workspace_candidate_http_materializes_exact_revision(self):
        from project_os_bridge.workspace_jobs import MARKER, RUNTIME
        from project_os_bridge.worker import run_pending
        source = self.root / "synthetic"
        source.mkdir(mode=0o700)
        def git(*args):
            return subprocess.check_output(["git", "-C", str(source), *args]).decode().strip()
        git("init", "-q")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        git("remote", "add", "origin", "https://github.com/example/demo.git")
        for name, value in ((".gitignore", ".project-os/\n"),
                            ("pubspec.yaml", "name: demo\n"), ("pubspec.lock", "packages: {}\n"),
                            ("package.json", '{"name":"demo"}\n'), ("package-lock.json", "{}\n")):
            (source / name).write_text(value)
        git("add", ".")
        git("commit", "-qm", "fixture")
        sha = git("rev-parse", "HEAD")
        (source / "pubspec.yaml").write_text("dirty\n")
        config_dir = source / ".project-os"
        config_dir.mkdir(mode=0o700)
        config = config_dir / "config.json"
        config.touch(mode=0o600)
        config.write_text(json.dumps({"version": 2, "repositories": ["example/demo"],
            "github_context": {"project": "demo", "repository": "example/demo", "repository_id": 1}}))
        state = self.root / "workspace"
        state.mkdir(mode=0o700)
        (state / MARKER).touch(mode=0o600)
        runtime = state / RUNTIME
        runtime.touch(mode=0o600)
        runtime.write_text(json.dumps({"tunnel": "fixture", "tunnel_id": "fixture", "image": None,
            "github_projects": {"demo": {"config": str(config), "repository": "example/demo", "repository_id": 1}}}))
        policy = Policy([(SUBJECT, op, "disposable") for op in ("submit", "read", "cancel")]
                        + [(SUBJECT, op, "demo") for op in
                           ("workspace_prepare", "workspace_materialize", "flutter-test", "expo-test")])
        jobs = Jobs(state, policy, workflows=("workspace_prepare",))
        app = build_http_app(self.verifier, jobs, workspace_candidate=True)
        headers = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer " + self.token()}
        def call(client, method, params):
            response = client.post("/mcp", headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            self.assertEqual(response.status_code, 200)
            return response.json()["result"]
        def tool(client, name, **arguments):
            return call(client, "tools/call", {"name": name, "arguments": arguments})
        def payload(result):
            self.assertFalse(result.get("isError", False), result)
            return json.loads(result["content"][0]["text"])
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            init = call(client, "initialize", {"protocolVersion": "2025-11-25",
                "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
            headers["MCP-Protocol-Version"] = init["protocolVersion"]
            tools = {item["name"] for item in call(client, "tools/list", {})["tools"]}
            self.assertIn("submit_workspace_job", tools)
            self.assertNotIn("submit_workspace_execute", tools)
            ids = []
            for profile in ("flutter-test", "expo-test"):
                args = {"project": "demo", "expected_sha": sha, "profile": profile, "request_key": profile}
                first = payload(tool(client, "submit_workspace_job", **args))
                self.assertEqual(first, payload(tool(client, "submit_workspace_job", **args)))
                ids.append(first["job_id"])
            for change in ({"project": "other"}, {"expected_sha": "HEAD"}, {"profile": "flutter-apk-debug"},
                           {"profile": "shell"}, {"profile": "flutter-test", "request_key": "expo-test"}):
                args = {"project": "demo", "expected_sha": sha, "profile": "expo-test", "request_key": "invalid"}
                args.update(change)
                self.assertTrue(tool(client, "submit_workspace_job", **args).get("isError", False))
            with jobs.transaction() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 2)
            run_pending(jobs)
            for job in ids:
                evidence = payload(tool(client, "get_job_evidence", job_id=job))
                self.assertEqual(evidence["state"], "SUCCEEDED")
                self.assertEqual(evidence["result"]["head"], sha)
                self.assertTrue(evidence["result"]["workspace_materialized"])
                self.assertFalse(evidence["result"]["execution_available"])
                self.assertNotIn(str(self.root), json.dumps(evidence))
                self.assertEqual((state / ("workspace-" + job) / "pubspec.yaml").read_text(), "name: demo\n")
            self.assertEqual((source / "pubspec.yaml").read_text(), "dirty\n")
            # Removing the exact mapping denies further submission and disclosure.
            data = json.loads(runtime.read_text())
            data["github_projects"] = {}
            runtime.write_text(json.dumps(data))
            self.assertTrue(tool(client, "get_job_evidence", job_id=ids[0]).get("isError", False))
            self.assertTrue(tool(client, "get_job_status", job_id=ids[0]).get("isError", False))
            self.assertTrue(tool(client, "submit_workspace_job", project="demo", expected_sha=sha,
                                 profile="expo-test", request_key="revoked").get("isError", False))
            with jobs.transaction() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 2)
            (state / MARKER).unlink()
            self.assertTrue(tool(client, "cancel_job", job_id=ids[0]).get("isError", False))

    def test_workspace_candidate_cannot_register_on_active_state_or_execution_queue(self):
        jobs = Jobs(self.root, Policy([]), workflows=("workspace_prepare",))
        with self.assertRaises(ValueError):
            build_http_app(self.verifier, jobs, workspace_candidate=True)
        candidate = self.root / "candidate"
        candidate.mkdir(mode=0o700)
        jobs = Jobs(candidate, Policy([]), workflows=("workspace_prepare", "workspace_execute"))
        with self.assertRaises(ValueError):
            build_http_app(self.verifier, jobs, workspace_candidate=True)

    def test_http_transport(self):
        policy=Policy((SUBJECT,op,"disposable") for op in ("submit","read","cancel","github_read"))
        jobs=Jobs(self.root,policy)
        app=build_http_app(self.verifier,jobs,SyntheticGitHubReader(policy,self.root))
        headers={"Accept":"application/json, text/event-stream","Authorization":"Bearer "+self.token()}
        def call(client,method,params,auth=headers):
            return client.post("/mcp",headers=auth,json={"jsonrpc":"2.0","id":1,"method":method,"params":params})
        with TestClient(app,base_url="http://127.0.0.1:8765") as client:
            meta=client.get("/.well-known/oauth-protected-resource/mcp")
            self.assertEqual(meta.status_code,200)
            self.assertEqual(meta.json()["resource"],RESOURCE)
            self.assertEqual(meta.json()["authorization_servers"],[ISSUER])
            args={"name":"health","arguments":{}}
            for invalid in ({},{"Authorization":"Bearer broken"},{"Authorization":"Bearer "+self.token({"sub":"user_other"})}):
                self.assertEqual(call(client,"tools/call",args,{"Accept":headers["Accept"],**invalid}).status_code,401)
            result=call(client,"initialize",{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1"} })
            self.assertEqual(result.status_code,200)
            headers["MCP-Protocol-Version"]=result.json()["result"]["protocolVersion"]
            listing=call(client,"tools/list",{})
            self.assertEqual(listing.status_code,200)
            self.assertEqual({x["name"] for x in listing.json()["result"]["tools"]},
                             {"health","submit_probe_job","get_job_status","get_job_evidence","cancel_job","github_fixture_context"})
            health=call(client,"tools/call",args)
            self.assertEqual(health.status_code,200)
            self.assertFalse(health.json()["result"].get("isError",False))
            self.assertIn("caller_identity_verified",json.dumps(health.json()))
            write={"name":"submit_probe_job","arguments":{"request_key":"http-test"}}
            first=call(client,"tools/call",write)
            self.assertEqual(first.status_code,200)
            self.assertFalse(first.json()["result"].get("isError",False))
            self.assertIn("job_id",json.dumps(first.json()))
            self.assertEqual(call(client,"tools/call",write).json()["result"],first.json()["result"])
            self.flag.unlink()
            denied_write={"name":"submit_probe_job","arguments":{"request_key":"revoked-new"}}
            for method, params in (
                ("tools/list", {}),
                ("tools/call", args),
                ("tools/call", denied_write),
                ("tools/call", {"name":"github_fixture_context","arguments":{"numbers":[1]}}),
                ("tools/call", {"name":"get_job_status","arguments":{"job_id":"unknown"}}),
                ("tools/call", {"name":"cancel_job","arguments":{"job_id":"unknown"}}),
            ):
                with self.subTest(method=method, params=params):
                    denied=call(client,method,params)
                    self.assertEqual(denied.status_code,403)
                    self.assertEqual(denied.json(),{"error":"local_access_revoked"})
                    self.assertNotIn("www-authenticate",denied.headers)
            for invalid in ({},{"Authorization":"Bearer broken"},
                            {"Authorization":"Bearer "+self.token({"exp":1})}):
                denied=call(client,"tools/call",args,{"Accept":headers["Accept"],**invalid})
                self.assertEqual(denied.status_code,401)
                self.assertIn("www-authenticate",denied.headers)
            self.assertEqual(client.get("/.well-known/oauth-protected-resource/mcp").status_code,200)
            with jobs.transaction() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0],1)
            self.flag.touch(mode=0o600)
            self.assertEqual(call(client,"tools/call",write).json()["result"],first.json()["result"])
            self.assertEqual(call(client,"tools/call",args).status_code,200)

    def test_rate_limit_and_sanitized_audit(self):
        policy=Policy([(SUBJECT,"read","disposable")])
        jobs=Jobs(self.root,policy)
        app=build_http_app(self.verifier,jobs,limit=2)
        with TestClient(app,base_url="http://127.0.0.1:8765") as client:
            for _ in range(2):
                self.assertEqual(client.post("/mcp",headers={"Authorization":"Bearer synthetic-secret"}).status_code,401)
            response=client.post("/mcp")
            self.assertEqual(response.status_code,429)
            self.assertIn("retry-after",response.headers)
        raw=(self.root/"security-audit.jsonl").read_text()
        self.assertNotIn("synthetic-secret",raw)
        events=[json.loads(line) for line in raw.splitlines()]
        self.assertEqual([e["status"] for e in events],[100,401,100,401,429])
        self.assertTrue(all(set(e)=={"at","event","status"} for e in events))
        observations = [json.loads(line) for line in
                        (self.root / AUTH_AUDIT_NAME).read_text().splitlines()]
        self.assertEqual(observations, [{**e, "auth_outcome": "TOKEN_MALFORMED"}
                                        for e in events if e["status"] == 401])

    def test_opt_in_fixture_and_evidence(self):
        from project_os_bridge.vertical import OPERATIONS, bind_image
        from project_os_bridge.worker import run_pending
        image="example/python@sha256:"+"a"*64
        jobs=Jobs(self.root,Policy((SUBJECT,op,"disposable") for op in OPERATIONS),
                  workflows=("probe_check","git_fixture_check"))
        jobs.submit(SUBJECT,"disposable","probe_check","old-probe")
        context=Mock(identity=Mock(return_value="1"*64))
        bind_image(jobs,image,context.identity())
        app=build_http_app(self.verifier,jobs,fixture_image=image,context_id="1"*64)
        headers={"Accept":"application/json, text/event-stream","Authorization":"Bearer "+self.token()}
        def call(client,method,params):
            return client.post("/mcp",headers=headers,json={"jsonrpc":"2.0","id":1,"method":method,"params":params}).json()["result"]
        def tool(client,name,**args):
            return call(client,"tools/call",{"name":name,"arguments":args})
        with TestClient(app,base_url="http://127.0.0.1:8765") as client:
            init=call(client,"initialize",{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1"}})
            headers["MCP-Protocol-Version"]=init["protocolVersion"]
            first=tool(client,"submit_git_fixture",request_key="new-fixture")
            self.assertFalse(first.get("isError",False))
            job=json.loads(first["content"][0]["text"])["job_id"]
            self.assertEqual(first,tool(client,"submit_git_fixture",request_key="new-fixture"))
            (self.root/"fixture-image").unlink()
            self.assertTrue(tool(client,"submit_git_fixture",request_key="denied").get("isError"))
            with patch("project_os_bridge.vertical.run_git_fixture") as run:
                run_pending(jobs,fixture_image=image,podman_context=context,context_id="1"*64,
                            fixture_allowed=lambda:False)
                run.assert_not_called()
            evidence=json.loads(tool(client,"get_job_evidence",job_id=job)["content"][0]["text"])
            self.assertEqual(evidence["state"],"BLOCKED")
            self.assertEqual([e["state"] for e in evidence["events"]],["QUEUED","BLOCKED"])
            self.assertFalse(jobs.pending_effects())


    def test_operational_diagnostics_auth_and_revocation(self):
        from unittest.mock import Mock
        from project_os_bridge.diagnostics import Diagnostics, FLAG
        state = self.root / "state"
        state.mkdir(mode=0o700)
        probe = state / "allow-authenticated-probe"
        probe.touch(mode=0o600)
        verifier = Verifier(ISSUER, RESOURCE, SUBJECT, state, jwks=self.jwks)
        policy = Policy([(SUBJECT, "diagnostics_read", "host")])
        jobs = Jobs(state, policy)
        diagnostics = Diagnostics(verifier, self.root)
        def observe(_):
            # Collectors must not block the ASGI event loop (network calls loop back).
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()
            return {"section": "host", "status": "observed", "data": {"wsl": True}}
        collect = Mock(side_effect=observe)
        diagnostics.collect = collect
        flag = state / FLAG
        app = build_http_app(verifier, jobs, diagnostics=diagnostics)
        headers = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer " + self.token()}
        def call(client, method, params, auth=None):
            return client.post("/mcp", headers=headers if auth is None else auth,
                               json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        args = {"name": "operational_diagnostics", "arguments": {"section": "host"}}
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            init = call(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                             "clientInfo": {"name": "test", "version": "1"}})
            headers["MCP-Protocol-Version"] = init.json()["result"]["protocolVersion"]
            listing = call(client, "tools/list", {}).json()["result"]["tools"]
            self.assertIn("operational_diagnostics", {t["name"] for t in listing})
            denied = call(client, "tools/call", args).json()["result"]
            self.assertTrue(denied["isError"])
            collect.assert_not_called()
            flag.touch(mode=0o600)
            for invalid in ({"sub": "user_other"}, {"aud": "wrong"}, {"scope": "profile"}):
                self.assertEqual(call(client, "tools/call", args,
                    dict(headers, Authorization="Bearer " + self.token(invalid))).status_code, 401)
            collect.assert_not_called()
            good = call(client, "tools/call", args).json()["result"]
            self.assertFalse(good.get("isError", False))
            collect.assert_called_once_with("host")
            collect.reset_mock()
            invalid = call(client, "tools/call", {"name": args["name"], "arguments": {"section": "../../etc/shadow"}}).json()
            self.assertTrue("error" in invalid or invalid["result"].get("isError"))
            collect.assert_not_called()
            flag.unlink()
            self.assertTrue(call(client, "tools/call", args).json()["result"]["isError"])
            collect.assert_not_called()
            flag.touch(mode=0o600)
            def revoke(_):
                flag.unlink()
                return {"private": "should-not-return"}
            collect.side_effect = revoke
            revoked = call(client, "tools/call", args).json()
            self.assertTrue(revoked["result"]["isError"])
            self.assertNotIn("should-not-return", json.dumps(revoked))
            probe.unlink()
            self.assertEqual(call(client, "tools/call", args).status_code, 403)
        with jobs.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_diagnostics_no_grant_or_fixture_exposure(self):
        from unittest.mock import Mock
        diagnostics = Mock()
        jobs = Jobs(self.root, Policy([]))
        for fixture in (None, "example/python@sha256:" + "a" * 64):
            app = build_http_app(self.verifier, jobs, diagnostics=diagnostics, fixture_image=fixture)
            headers = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer " + self.token()}
            def call(client, method, params):
                return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1,
                                                                 "method": method, "params": params}).json()
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                init = call(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                 "clientInfo": {"name": "test", "version": "1"}})
                headers["MCP-Protocol-Version"] = init["result"]["protocolVersion"]
                names = {t["name"] for t in call(client, "tools/list", {})["result"]["tools"]}
                if fixture:
                    self.assertNotIn("operational_diagnostics", names)
                else:
                    self.assertIn("operational_diagnostics", names)
                    result = call(client, "tools/call", {"name": "operational_diagnostics",
                                                          "arguments": {"section": "host"}})
                    self.assertTrue(result["result"]["isError"])
        diagnostics.collect.assert_not_called()

def execute_workspace_http_fixture(jobs, backend, project, revision, profiles):
    """Reuse the signed synthetic auth fixture for real disposable Podman CI."""
    from project_os_bridge.worker import run_pending
    AuthTests.setUpClass()
    fixture = AuthTests()
    try:
        fixture.setUp()
        app = build_http_app(fixture.verifier, jobs, workspace_candidate=True,
                             workspace_backend=backend)
        headers = {"Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + fixture.token(changes={"exp": int(time.time()) + 300})}
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            def call(method, params):
                response = client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                fixture.assertEqual(response.status_code, 200)
                return response.json()["result"]
            def raw(name, **arguments):
                return call("tools/call", {"name": name, "arguments": arguments})
            def payload(name, **arguments):
                result = raw(name, **arguments)
                fixture.assertFalse(result.get("isError", False), result)
                return json.loads(result["content"][0]["text"])
            init = call("initialize", {"protocolVersion": "2025-11-25",
                "capabilities": {}, "clientInfo": {"name": "workspace-ci", "version": "1"}})
            headers["MCP-Protocol-Version"] = init["protocolVersion"]
            fixture.assertIn("submit_workspace_execute", {x["name"] for x in call("tools/list", {})["tools"]})
            ids = {}
            for profile in profiles:
                args = {"project": project, "expected_sha": revision, "profile": profile, "request_key": profile}
                first = payload("submit_workspace_execute", **args)
                fixture.assertEqual(first, payload("submit_workspace_execute", **args))
                ids[profile] = first["job_id"]
                fixture.assertEqual(payload("get_job_status", job_id=first["job_id"])["state"], "QUEUED")
            for profile in ("shell", "flutter-analyze", "flutter-test", "expo-typecheck",
                            "expo-test", "flutter-apk-debug", "expo-apk-debug"):
                if profile in profiles:
                    continue
                result = raw("submit_workspace_execute", project=project, expected_sha=revision,
                             profile=profile, request_key="invalid-" + profile)
                fixture.assertTrue(result.get("isError", False))
            run_pending(jobs, workspace_backend=backend, enabled=fixture.verifier.enabled)
            # New token, same authorized identity; no execution replay.
            headers["Authorization"] = "Bearer " + fixture.token()
            evidence = {profile: payload("get_job_evidence", job_id=job) for profile, job in ids.items()}
            # Local opt-in revocation denies disclosure without deleting evidence.
            fixture.flag.unlink()
            response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2,
                "method": "tools/call", "params": {"name": "get_job_evidence",
                                                  "arguments": {"job_id": next(iter(ids.values()))}}})
            fixture.assertEqual(response.status_code, 403)
            return ids, evidence
    finally:
        fixture.doCleanups()
