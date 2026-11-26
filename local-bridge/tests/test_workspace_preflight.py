import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_os_bridge.core import Policy
from project_os_bridge.workspace_preflight import FLUTTER_PROFILES, prepare_workspace, materialize_workspace
from project_os_bridge.workspace_profiles import PROFILES, artifact_identity


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
        (self.project / "package.json").write_text('{"name":"demo"}\n')
        (self.project / "package-lock.json").write_text('{"lockfileVersion":3}\n')
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
                             for op in ("workspace_prepare", "workspace_materialize", *PROFILES))

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.project), *args]).decode().strip()

    def prepare(self, profile="flutter-test", sha=None, policy=None, principal="operator", project="demo"):
        return prepare_workspace(self.runtime, self.policy if policy is None else policy,
                               principal, project, self.sha if sha is None else sha, profile)

    def test_exact_revision_and_no_checkout_mutation(self):
        (self.project / "pubspec.yaml").write_text("dirty changes\n")
        before = self.git("status", "--porcelain")
        for profile in PROFILES:
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

    def materialize(self, profile="expo-test", sha=None, job="a" * 32, policy=None):
        parent = self.root / "workspaces"
        parent.mkdir(mode=0o700, exist_ok=True)
        return materialize_workspace(self.runtime, self.policy if policy is None else policy,
                                     "operator", "demo", self.sha if sha is None else sha,
                                     profile, parent, job)

    def test_materialization_exact_bytes_both_frameworks(self):
        (self.project / "pubspec.yaml").write_text("dirty\n")
        (self.project / "untracked.txt").write_text("not committed")
        before = self.git("status", "--porcelain")
        one = self.materialize("flutter-test")
        two = self.materialize("expo-test", job="b" * 32)
        self.assertTrue(one["workspace_materialized"])
        self.assertFalse(two["execution_available"])
        self.assertEqual(one["workspace_sha256"], two["workspace_sha256"])
        for job in ("a" * 32, "b" * 32):
            dest = self.root / "workspaces" / ("workspace-" + job)
            self.assertEqual((dest / "pubspec.yaml").read_text(), "name: demo\n")
            self.assertFalse((dest / ".git").exists())
            self.assertFalse((dest / ".project-os").exists())
            self.assertFalse((dest / "untracked.txt").exists())
        self.assertEqual(self.git("status", "--porcelain"), before)
        with self.assertRaises(FileExistsError):
            self.materialize()

    def test_managed_expo_does_not_require_native_tree(self):
        self.git("rm", "android/app/src/main/AndroidManifest.xml")
        self.git("commit", "-qm", "managed expo")
        self.assertTrue(self.materialize("expo-apk-debug", sha=self.git("rev-parse", "HEAD"))
                        ["workspace_materialized"])

    def test_sensitive_path_and_symlink_rejected_before_export(self):
        for filename in (".env", "link"):
            with self.subTest(filename=filename):
                path = self.project / filename
                if filename == "link":
                    path.symlink_to("pubspec.yaml")
                else:
                    path.write_text("synthetic only")
                self.git("add", filename)
                self.git("commit", "-qm", "unsafe fixture")
                with self.assertRaises((PermissionError, ValueError)):
                    self.materialize(sha=self.git("rev-parse", "HEAD"))
                self.assertFalse((self.root / "workspaces" / ("workspace-" + "a" * 32)).exists())
                self.git("rm", filename)
                self.git("commit", "-qm", "remove fixture")

    def test_materialization_grant_separate_and_file_limit(self):
        with self.assertRaises(PermissionError):
            self.materialize(policy=Policy([("operator", "workspace_prepare", "demo"),
                                             ("operator", "expo-test", "demo")]))
        with patch("project_os_bridge.workspace_preflight.MAX_FILE", 1):
            with self.assertRaises(ValueError):
                self.materialize()
        self.assertFalse((self.root / "workspaces" / ("workspace-" + "a" * 32)).exists())

    def test_profile_contract_and_artifact_identity(self):
        self.assertEqual(PROFILES["flutter-apk-debug"].artifact_kind, "apk")
        self.assertEqual(PROFILES["expo-apk-debug"].artifact_kind, "apk")
        self.assertEqual(artifact_identity("apk", "app.apk", b"synthetic"),
                         artifact_identity("apk", "app.apk", b"synthetic"))
        self.assertNotEqual(artifact_identity("apk", "app.apk", b"one")["sha256"],
                            artifact_identity("apk", "app.apk", b"two")["sha256"])
