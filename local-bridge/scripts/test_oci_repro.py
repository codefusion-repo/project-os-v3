"""Regression tests for OCI identity verification, including APK log variation."""
import contextlib
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from oci_repro import compare, load_manifest


def layout(root, log):
    blobs = root / "blobs" / "sha256"
    blobs.mkdir(parents=True)

    def put(raw):
        h = hashlib.sha256(raw).hexdigest()
        (blobs / h).write_bytes(raw)
        return {"digest": "sha256:" + h, "size": len(raw)}

    layer = io.BytesIO()
    with tarfile.open(fileobj=layer, mode="w") as archive:
        info = tarfile.TarInfo("var/log/apk.log")
        info.size = len(log)
        archive.addfile(info, io.BytesIO(log))
    ld = put(layer.getvalue())
    config = put(json.dumps({"rootfs": {"diff_ids": [ld["digest"]]}}).encode())
    manifest = put(json.dumps({"config": config, "layers": [ld]}).encode())
    (root / "index.json").write_text(json.dumps({"manifests": [manifest]}))
    return manifest["digest"], ld["digest"]


class ReproTests(unittest.TestCase):
    def test_equal_independent_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            ad, _ = layout(a, b"same")
            bd, _ = layout(b, b"same")
            self.assertEqual(ad, bd)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(compare(a, ad, b, bd))

    def test_timestamped_apk_log_fails_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            ad, _ = layout(a, b"2026-11-24 00:00:01")
            bd, _ = layout(b, b"2026-11-24 00:00:02")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertFalse(compare(a, ad, b, bd))
            self.assertIn("OCI_ENTRY_DIFF var/log/apk.log ['content']", out.getvalue())
            self.assertIn("OCI_CONFIG_DIFF_KEYS ['rootfs']", out.getvalue())

    def test_corrupt_blob_rejected_even_if_manifest_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "a"
            digest, layer = layout(root, b"same")
            (root / "blobs" / "sha256" / layer[7:]).write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "blob digest mismatch"):
                load_manifest(root, digest)


if __name__ == "__main__":
    unittest.main()
