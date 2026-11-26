import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_os_bridge.core import Policy
from project_os_bridge.workspace_preflight import FLUTTER_PROFILES, prepare_flutter


class WorkspacePreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir(mode=0o700)
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("remote", "add", "origin", "https://github.com/example/demo.git")
        (self.project / ".gitignore").write_text(".project-os/\n")
        (self.project / "pubspec.yaml").write_text("name: demo\n")
        (self.project / "pubspec.lock").write_text("packages: {}\n")
        manifest = self.project / "android/app/src/main/AndroidManifest.xml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("<manifest/>\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.sha = self.git("rev-parse", "HEAD")
        config_dir = self.project / ".project-os"
        config_dir.mkdir(mode=0o700)
        self.config = config_dir / "config.json"
        self.config.touch(mode=0o600)
        self.config.write_text(json.dumps({
            "version": 2, "repositories": ["example/demo"],
            "github_context": {"project": "demo", "repository": "example/demo", "repository_id": 123},
        }))
        self.runtime = self.root / "runtime.json"
        self.runtime.touch(mode=0o600)
        self.data = {"tunnel": "fixture", "tunnel_id": "fixture", "image": None,
                     "github_projects": {"demo": {"config": str(self.config),
                         "repository": "example/demo", "repository_id": 123}}}
        self.runtime.write_text(json.dumps(self.data))
        self.policy = Policy(("operator", op, "demo")
                             for op in ("workspace_prepare", *FLUTTER_PROFILES))

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.project), *args]).decode().strip()

    def prepare(self, profile="flutter-test", sha=None, policy=None, principal="operator", project="demo"):
        return prepare_flutter(self.runtime, self.policy if policy is None else policy,
                               principal, project, self.sha if sha is None else sha, profile)

    def test_exact_revision_and_no_checkout_mutation(self):
        (self.project / "pubspec.yaml").write_text("dirty changes\n")
        before = self.git("status", "--porcelain")
        for profile in FLUTTER_PROFILES:
            result = self.prepare(profile)
            self.assertEqual(result["head"], self.sha)
            self.assertEqual(result["tree"], self.git("rev-parse", self.sha + "^{tree}"))
            self.assertEqual(result["repository_id"], 123)
            self.assertFalse(result["workspace_materialized"])
            self.assertFalse(result["execution_available"])
            self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.sha)

    def test_read_grant_does_not_authorize_preparation(self):
        with patch("project_os_bridge.workspace_preflight.registry_entries") as registry:
            with self.assertRaises(PermissionError):
                self.prepare(policy=Policy([("operator", "github_read", "demo")]))
            with self.assertRaises(PermissionError):
                self.prepare(principal="other")
            registry.assert_not_called()

    def test_unknown_profile_or_revision(self):
        for profile, sha in (("flutter test", self.sha), ("../other", self.sha),
                             ("flutter-test", "HEAD"), ("flutter-test", "0" * 40)):
            with self.subTest(profile=profile, sha=sha), self.assertRaises(ValueError):
                self.prepare(profile, sha)

    def test_mapping_revocation_and_identity_conflict(self):
        self.data["github_projects"]["demo"]["repository_id"] = 456
        self.runtime.write_text(json.dumps(self.data))
        with self.assertRaises(PermissionError):
            self.prepare()
        self.data["github_projects"].clear()
        self.runtime.write_text(json.dumps(self.data))
        with self.assertRaises(PermissionError):
            self.prepare()

    def test_origin_change_rejected(self):
        self.git("remote", "set-url", "origin", "https://github.com/example/other.git")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_symlink_in_required_layout_rejected(self):
        (self.project / "pubspec.lock").unlink()
        (self.project / "pubspec.lock").symlink_to("pubspec.yaml")
        self.git("add", "pubspec.lock")
        self.git("commit", "-qm", "symlink fixture")
        with self.assertRaises(ValueError):
            self.prepare(sha=self.git("rev-parse", "HEAD"))

    def test_missing_android_layout_does_not_claim_build_readiness(self):
        self.git("rm", "android/app/src/main/AndroidManifest.xml")
        self.git("commit", "-qm", "no android")
        sha = self.git("rev-parse", "HEAD")
        self.assertFalse(self.prepare(sha=sha)["execution_available"])
        with self.assertRaises(ValueError):
            self.prepare("flutter-apk-debug", sha)

    def test_revoke_during_preflight(self):
        from project_os_bridge.workspace_preflight import git
        def revoke(root, *args):
            result = git(root, *args)
            if args[0] == "ls-tree":
                self.data["github_projects"].clear()
                self.runtime.write_text(json.dumps(self.data))
            return result
        with patch("project_os_bridge.workspace_preflight.git", side_effect=revoke):
            with self.assertRaises(PermissionError):
                self.prepare()
