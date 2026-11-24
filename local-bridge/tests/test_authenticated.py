import asyncio
import time
import unittest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import jwt

from project_os_bridge.authenticated import Verifier, SCOPE


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.other = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.verifier = Verifier("https://issuer.example","https://resource.example/mcp","owner","client",
                                cls.key.public_key().public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo))

    def token(self, changes=None, key=None, typ="at+jwt"):
        now = int(time.time())
        claims = {"iss":"https://issuer.example","aud":"https://resource.example/mcp",
                  "sub":"owner","client_id":"client","scope":SCOPE,"iat":now,"exp":now+300}
        claims.update(changes or {})
        return jwt.encode(claims,key or self.key,algorithm="RS256",headers={"typ":typ})

    def verify(self, token):
        return asyncio.run(self.verifier.verify_token(token))

    def test_valid(self):
        self.assertEqual(self.verify(self.token()).subject,"owner")

    def test_invalid_claims(self):
        for changes in ({"iss":"https://wrong.example"},{"aud":"other"},{"sub":"other"},
                        {"client_id":"other"},{"scope":"other"},{"exp":1},
                        {"iat":int(time.time())+600},{"exp":int(time.time())+7200}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.verify(self.token(changes)))

    def test_invalid_signature_and_token_type(self):
        self.assertIsNone(self.verify(self.token(key=self.other)))
        self.assertIsNone(self.verify(self.token(typ="JWT")))
        self.assertIsNone(self.verify("not-a-token"))
        self.assertIsNone(self.verify(jwt.encode({"sub":"owner"},"bad",algorithm="HS256")))
