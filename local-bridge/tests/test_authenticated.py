import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from starlette.testclient import TestClient
from project_os_bridge.authenticated import build_http_app
from project_os_bridge.workos_auth import Verifier, JWKS, SCOPE, CLIENT_ID, load_config
from project_os_bridge.core import Jobs, Policy
from project_os_bridge.github_fixture import SyntheticGitHubReader

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

    def token(self,changes=None,key=None,kid="one",headers=None):
        now=int(time.time())
        claims={"iss":ISSUER,"aud":RESOURCE,"sub":SUBJECT,"client_id":CLIENT_ID,
                "scope":"openid offline_access","sid":"consent_fixture","jti":"token_fixture","iat":now,"exp":now+300}
        claims.update(changes or {})
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
                             {"health","submit_probe_job","get_job_status","cancel_job","github_fixture_context"})
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
