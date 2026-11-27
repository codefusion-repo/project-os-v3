"""Regression coverage for Docker-to-OCI conversion identity."""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ci_mobile_smoke", Path(__file__).resolve().parents[1] / "scripts/ci-mobile-smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class MobileConversionTests(unittest.TestCase):
    def setUp(self):
        self.image = "sha256:" + "a" * 64
        self.layer = "sha256:" + "b" * 64
        self.source = {"Id": self.image, "RootFS": {"Type": "layers", "Layers": [self.layer]},
                       "Architecture": "amd64", "Os": "linux",
                       "Config": {"User": "1001:1001", "WorkingDir": "/fixture",
                                  "Env": ["HOME=/home/smoke"], "Cmd": ["node"],
                                  "Entrypoint": None, "Volumes": None, "Labels": None}}
        self.target = {"architecture": "amd64", "os": "linux",
                       "rootfs": {"type": "layers", "diff_ids": [self.layer]},
                       "config": {"User": "1001:1001", "WorkingDir": "/fixture",
                                  "Env": ["HOME=/home/smoke"], "Cmd": ["node"]}}

    def evidence(self, corrupt=False):
        config = json.dumps(self.target).encode()
        digest = "sha256:" + hashlib.sha256(config).hexdigest()
        manifest = json.dumps({"config": {"digest": digest, "size": len(config)},
                               "layers": [{}]}).encode()
        return smoke.verify_oci_conversion(self.source, self.image, manifest,
                                           config + b" " if corrupt else config)

    def test_distinct_config_digest_preserves_identity(self):
        result = self.evidence()
        self.assertNotEqual(result["oci_config"], result["docker_config"])
        self.assertTrue(result["filesystem_identity_verified"])
        self.assertTrue(result["execution_config_verified"])

    def test_reject_changed_layers(self):
        self.target["rootfs"]["diff_ids"] = ["sha256:" + "c" * 64]
        with self.assertRaisesRegex(RuntimeError, "FILESYSTEM_IDENTITY"):
            self.evidence()

    def test_reject_changed_command_or_user(self):
        for field, value in (("User", "0"), ("Cmd", ["sh"])):
            with self.subTest(field=field):
                original = self.target["config"][field]
                self.target["config"][field] = value
                with self.assertRaisesRegex(RuntimeError, "EXECUTION_CONFIG_IDENTITY"):
                    self.evidence()
                self.target["config"][field] = original

    def test_reject_config_bytes_mismatch(self):
        with self.assertRaisesRegex(RuntimeError, "CONFIG_INTEGRITY"):
            self.evidence(corrupt=True)
