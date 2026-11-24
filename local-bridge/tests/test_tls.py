import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_os_bridge.authenticated import tls_options


class TLSOptionsTests(unittest.TestCase):
    def test_plaintext_pilot_is_explicitly_unchanged(self):
        self.assertEqual(tls_options(None, None), {})

    def test_requires_pair(self):
        with self.assertRaises(ValueError):
            tls_options(Path("/cert.pem"), None)

    def test_rejects_insecure_or_symlink_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            cert, key = root / "cert.pem", root / "key.pem"
            for p in (cert, key):
                p.touch(mode=0o600)
                p.chmod(0o600)
            key.chmod(0o644)
            with self.assertRaises(PermissionError):
                tls_options(cert, key)
            key.chmod(0o600)
            link = root / "link.pem"
            link.symlink_to(key)
            with self.assertRaises(ValueError):
                tls_options(cert, link)

    def test_rejects_invalid_pem(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in ("cert.pem", "key.pem"):
                p = root / name
                p.write_text("not a PEM", encoding="utf-8")
                p.chmod(0o600)
            with self.assertRaises(OSError):
                tls_options(root / "cert.pem", root / "key.pem")

    def test_real_certificate_pair(self):
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import ipaddress
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fixture")])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(minutes=1))
                    .not_valid_after(now + timedelta(days=1))
                    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                    .sign(key, hashes.SHA256()))
            cp, kp = root / "cert.pem", root / "key.pem"
            cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
            cp.chmod(0o600)
            kp.chmod(0o600)
            self.assertEqual(tls_options(cp, kp), {"ssl_certfile":str(cp), "ssl_keyfile":str(kp)})
