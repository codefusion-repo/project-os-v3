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

    def test_oauth_discovery_and_optional_refresh_scope(self):
        jobs = Jobs(self.root, Policy([(SUBJECT, "read", "disposable")]))
        app = build_http_app(self.verifier, jobs)
        prefix = "/.well-known/oauth-protected-resource"
        canonical = prefix + "/v1/mcp/tunnel_fixture"
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            documents = []
            for path in (canonical, prefix, prefix + "/mcp"):
                response = client.get(path, headers={"Origin": "https://chatgpt.com"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("access-control-allow-origin"), "*")
                documents.append(response.json())
                preflight = client.options(path, headers={
                    "Origin": "https://chatgpt.com",
                    "Access-Control-Request-Method": "GET",
                })
                self.assertEqual(preflight.status_code, 200)
                self.assertEqual(client.post(path).status_code, 405)
            self.assertEqual(documents, [documents[0]] * 3)
            self.assertEqual(documents[0], {
                "resource": RESOURCE,
                "authorization_servers": [ISSUER],
                "scopes_supported": ["openid", "offline_access"],
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
            for scope in ("openid", "openid offline_access"):
                response = client.post("/mcp", json=init, headers={
                    **accept, "Authorization": "Bearer " + self.token({"scope": scope}),
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn("result", response.json())
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

    def test_opt_in_fixture_and_evidence(self):
        from project_os_bridge.vertical import OPERATIONS, bind_image
        from project_os_bridge.worker import run_pending
        image="example/python@sha256:"+"a"*64
        jobs=Jobs(self.root,Policy((SUBJECT,op,"disposable") for op in OPERATIONS),
                  workflows=("probe_check","git_fixture_check"))
        jobs.submit(SUBJECT,"disposable","probe_check","old-probe")
        bind_image(jobs,image)
        app=build_http_app(self.verifier,jobs,fixture_image=image)
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
                run_pending(jobs,fixture_image=image,fixture_allowed=lambda:False)
                run.assert_not_called()
            evidence=json.loads(tool(client,"get_job_evidence",job_id=job)["content"][0]["text"])
            self.assertEqual(evidence["state"],"BLOCKED")
            self.assertEqual([e["state"] for e in evidence["events"]],["QUEUED","RUNNING","BLOCKED"])


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
