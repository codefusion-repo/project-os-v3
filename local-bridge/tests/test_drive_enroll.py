import base64
import hashlib
import unittest
from urllib.parse import parse_qs, urlsplit

from project_os_bridge.drive_enroll import authorization_url, callback_code
from project_os_bridge.drive_delivery import SCOPE


class DriveEnrollmentTests(unittest.TestCase):
    def test_pkce_offline_minimal_scope(self):
        verifier = "a" * 64
        url = authorization_url("client", "http://127.0.0.1:1234/callback", "state", verifier)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["scope"], [SCOPE])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["code_challenge"], [base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()])

    def test_callback_rejects_wrong_state_and_duplicates(self):
        self.assertEqual(callback_code("/callback?state=good&code=abc", "good"), "abc")
        for url in ("/callback?state=bad&code=abc",
                    "/callback?state=good&code=abc&code=def",
                    "/callback?state=good&code=abc&error=denied",
                    "/other?state=good&code=abc",
                    "http://other/callback?state=good&code=abc"):
            self.assertIsNone(callback_code(url, "good"))
