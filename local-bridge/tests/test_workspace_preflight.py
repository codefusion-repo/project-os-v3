import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_os_bridge.core import Jobs, Policy
from project_os_bridge.workspace_jobs import submit_workspace, MARKER, RUNTIME
from project_os_bridge.worker import run_pending, exclusive_worker
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

    def test_selected_dirty_context_is_bounded_and_preserves_checkout(self):
        from project_os_bridge.workspace_preflight import read_workspace_context
        policy = Policy([*self.policy.grants, ("operator", "workspace_context", "demo"),
                         ("operator", "workspace_dirty_context", "demo")])
        def read(*paths, **kwargs):
            return read_workspace_context(self.runtime, policy, "operator", "demo", self.sha,
                                          "flutter-test", list(paths), **kwargs)
        file = self.project / "pubspec.yaml"
        file.write_text("name: local change\n")
        status = self.git("status", "--porcelain")
        self.assertNotIn("diff", read("pubspec.yaml"))
        result = read("pubspec.yaml", include_dirty=True)
        self.assertIn("+name: local change", result["diff"])
        self.assertEqual(self.git("status", "--porcelain"), status)
        self.assertEqual(file.read_text(), "name: local change\n")
        file.unlink()
        self.assertIsNone(read("pubspec.yaml", include_dirty=True)["files"][0]["working_sha256"])
        outside = self.root / "outside.txt"
        outside.write_text("synthetic outside")
        file.symlink_to(outside)
        with self.assertRaises(OSError):
            read("pubspec.yaml", include_dirty=True)
        file.unlink()
        file.write_bytes(b"x" * 65536)
        with self.assertRaises(ValueError):
            read("pubspec.yaml", include_dirty=True)
        (self.project / "untracked.txt").write_text("synthetic")
        with self.assertRaises(ValueError):
            read("untracked.txt", include_dirty=True)
        self.git("commit", "--allow-empty", "-qm", "new head")
        with self.assertRaises(ValueError):
            read("pubspec.yaml", include_dirty=True)

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

    def test_root_environment_template_omitted_without_reading_blob(self):
        from project_os_bridge.workspace_preflight import git, read_workspace_context
        (self.project / ".env.example").write_text("SYNTHETIC_VALUE=not-for-export\n")
        self.git("add", ".env.example")
        self.git("commit", "-qm", "environment template")
        sha = self.git("rev-parse", "HEAD")
        blob = self.git("rev-parse", sha + ":.env.example")
        before = self.git("status", "--porcelain")
        with patch("project_os_bridge.workspace_preflight.git", wraps=git) as observed:
            result = self.materialize(sha=sha)
        self.assertEqual(result["excluded_paths"], [".env.example"])
        self.assertEqual(result["head"], sha)
        self.assertFalse(any(blob in call.args[1:] for call in observed.call_args_list))
        dest = self.root / "workspaces" / ("workspace-" + "a" * 32)
        self.assertFalse((dest / ".env.example").exists())
        self.assertTrue((dest / "package-lock.json").is_file())
        self.assertEqual(self.git("status", "--porcelain"), before)
        policy = Policy([*self.policy.grants, ("operator", "workspace_context", "demo")])
        with self.assertRaises(PermissionError):
            read_workspace_context(self.runtime, policy, "operator", "demo", sha,
                                   "expo-test", [".env.example"])
        # A real env file remains a blocker even when the template is omitted.
        (self.project / ".env.local").write_text("SYNTHETIC=blocked\n")
        self.git("add", ".env.local")
        self.git("commit", "-qm", "private file")
        with self.assertRaises(PermissionError):
            self.materialize(sha=self.git("rev-parse", "HEAD"), job="b" * 32)
        self.assertFalse((self.root / "workspaces" / ("workspace-" + "b" * 32)).exists())

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

    def workspace_queue(self):
        state = self.root / "queue"
        state.mkdir(mode=0o700)
        (state / MARKER).touch(mode=0o600)
        runtime = state / RUNTIME
        runtime.touch(mode=0o600)
        runtime.write_bytes(self.runtime.read_bytes())
        policy = Policy([*self.policy.grants, *(( "operator", op, "disposable")
                                                for op in ("submit", "read", "cancel"))])
        return Jobs(state, policy, workflows=("workspace_prepare",))

    def test_durable_job_materializes_both_profiles(self):
        jobs = self.workspace_queue()
        ids = []
        for profile in ("flutter-test", "expo-test"):
            job = submit_workspace(jobs, "operator", "demo", self.sha, profile, profile)
            ids.append(job)
            self.assertEqual(job, submit_workspace(jobs, "operator", "demo", self.sha, profile, profile))
        with self.assertRaises(ValueError):
            submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "flutter-test")
        run_pending(jobs)
        reopened = Jobs(jobs.probe.root, jobs.policy, workflows=("workspace_prepare",))
        for job in ids:
            evidence = reopened.evidence("operator", job)
            self.assertEqual(evidence["state"], "SUCCEEDED")
            self.assertTrue(evidence["result"]["workspace_materialized"])
            self.assertFalse(evidence["result"]["execution_available"])
            self.assertEqual(evidence["result"]["head"], self.sha)
            self.assertEqual((jobs.probe.root / ("workspace-" + job) / "pubspec.yaml").read_text(),
                             "name: demo\n")
        self.assertEqual(reopened.evidence("operator", ids[0])["result"]["workspace_sha256"],
                         reopened.evidence("operator", ids[1])["result"]["workspace_sha256"])

    def test_saved_changes_are_atomic_and_idempotent(self):
        import hashlib
        from project_os_bridge.workspace_preflight import changes_digest
        jobs = self.workspace_queue()
        edits = [{"path": "pubspec.yaml", "before": hashlib.sha256(b"name: demo\n").hexdigest(),
                  "text": "name: updated\n"},
                 {"path": "lib/example.txt", "before": None, "text": "synthetic\n"}]
        with self.assertRaises(PermissionError):
            submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test", "edit", changes=edits)
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_change", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_prepare",))
        original = self.git("status", "--porcelain")
        job = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test", "edit", changes=edits)
        self.assertEqual(job, submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test",
                                               "edit", changes=list(reversed(edits))))
        with self.assertRaises(ValueError):
            submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test", "edit",
                             changes=[{**edits[0], "text": "name: different\n"}])
        bad = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test", "conflict",
                               changes=[{**edits[0], "before": "0" * 64}])
        collision = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test", "collision",
                    changes=[{"path": "pubspec.yaml/child", "before": None, "text": "data"}])
        for path in ("../escape", ".env"):
            with self.assertRaises((PermissionError, ValueError)):
                submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test", "invalid",
                                 changes=[{"path": path, "before": None, "text": "data"}])
        run_pending(jobs)
        reopened = Jobs(jobs.probe.root, policy, workflows=("workspace_prepare",))
        evidence = reopened.evidence("operator", job)
        self.assertEqual(evidence["state"], "SUCCEEDED")
        self.assertEqual(evidence["result"]["changes_sha256"], changes_digest(edits))
        target = jobs.probe.root / ("workspace-" + job)
        self.assertEqual((target / "pubspec.yaml").read_text(), "name: updated\n")
        self.assertEqual((target / "lib/example.txt").read_text(), "synthetic\n")
        self.assertNotIn("name: updated", json.dumps(evidence))
        self.assertEqual(self.git("status", "--porcelain"), original)
        for blocked in (bad, collision):
            self.assertEqual(reopened.evidence("operator", blocked)["state"], "BLOCKED")
            self.assertFalse((jobs.probe.root / ("workspace-" + blocked)).exists())

    def test_saved_delete_diff_and_failed_staging(self):
        import hashlib
        from project_os_bridge.workspace_jobs import workspace_changes
        (self.project / "remove.txt").write_text("old text\n")
        self.git("add", "remove.txt")
        self.git("commit", "-qm", "synthetic deletion")
        sha = self.git("rev-parse", "HEAD")
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_change", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_prepare",))
        edits = [{"path": "remove.txt", "before": hashlib.sha256(b"old text\n").hexdigest(),
                  "text": None}]
        job = submit_workspace(jobs, "operator", "demo", sha, "expo-test", "delete", changes=edits)
        run_pending(jobs)
        self.assertEqual(jobs.get("operator", job)["state"], "SUCCEEDED")
        self.assertFalse((jobs.probe.root / ("workspace-" + job) / "remove.txt").exists())
        self.assertEqual((self.project / "remove.txt").read_text(), "old text\n")
        self.assertIn("-old text", workspace_changes(jobs, "operator", job)["diff"])
        (self.project / "remove.txt").write_text("dirty text\n")
        self.assertNotIn("dirty text", workspace_changes(jobs, "operator", job)["diff"])
        denied = Jobs(jobs.probe.root, Policy([g for g in policy.grants if g[1] != "workspace_change"]),
                      workflows=("workspace_prepare",))
        with self.assertRaises(PermissionError):
            workspace_changes(denied, "operator", job)
        failed = submit_workspace(jobs, "operator", "demo", sha, "expo-test", "sync", changes=edits)
        with patch("project_os_bridge.workspace_preflight._sync_directory", side_effect=OSError("fixture")):
            run_pending(jobs)
        self.assertEqual(jobs.get("operator", failed)["state"], "FAILED")
        self.assertFalse((jobs.probe.root / ("workspace-" + failed)).exists())

    def test_saved_changes_reject_binary_base(self):
        import hashlib
        raw = b"binary\0fixture"
        (self.project / "binary.txt").write_bytes(raw)
        self.git("add", "binary.txt")
        self.git("commit", "-qm", "binary fixture")
        jobs = self.workspace_queue()
        jobs = Jobs(jobs.probe.root, Policy([*jobs.policy.grants, ("operator", "workspace_change", "demo")]),
                    workflows=("workspace_prepare",))
        job = submit_workspace(jobs, "operator", "demo", self.git("rev-parse", "HEAD"), "expo-test",
                               "binary", changes=[{"path": "binary.txt",
                               "before": hashlib.sha256(raw).hexdigest(), "text": "new"}])
        run_pending(jobs)
        self.assertEqual(jobs.get("operator", job)["state"], "BLOCKED")
        self.assertFalse((jobs.probe.root / ("workspace-" + job)).exists())

    def test_saved_changes_revoked_before_dispatch(self):
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_change", "demo")])
        granted = Jobs(jobs.probe.root, policy, workflows=("workspace_prepare",))
        job = submit_workspace(granted, "operator", "demo", self.sha, "expo-test", "revoked-edit",
                               changes=[{"path": "note.txt", "before": None, "text": "synthetic"}])
        run_pending(jobs)
        self.assertEqual(jobs.get("operator", job)["state"], "BLOCKED")
        self.assertFalse((jobs.probe.root / ("workspace-" + job)).exists())

    def test_workspace_mapping_revoked_before_worker(self):
        jobs = self.workspace_queue()
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "revoke")
        self.data["github_projects"].clear()
        (jobs.probe.root / RUNTIME).write_text(json.dumps(self.data))
        run_pending(jobs)
        self.assertEqual(jobs.get("operator", job)["state"], "BLOCKED")
        self.assertFalse((jobs.probe.root / ("workspace-" + job)).exists())

    def test_workspace_cancel_and_interrupted_no_replay(self):
        jobs = self.workspace_queue()
        first = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "cancel")
        second = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "interrupt")
        self.assertTrue(jobs.cancel("operator", first))
        with exclusive_worker(jobs):
            self.assertEqual(jobs.claim()["id"], second)
        run_pending(jobs)
        self.assertEqual(jobs.get("operator", first)["state"], "CANCELLED")
        self.assertEqual(jobs.get("operator", second)["state"], "INTERRUPTED")
        self.assertEqual(second, submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "interrupt"))
        self.assertFalse((jobs.probe.root / ("workspace-" + second)).exists())

    def test_workspace_profile_not_enabled_by_default(self):
        jobs = self.workspace_queue()
        default = Jobs(jobs.probe.root, jobs.policy)
        with self.assertRaises(ValueError):
            submit_workspace(default, "operator", "demo", self.sha, "expo-test", "default")
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "marker")
        (jobs.probe.root / MARKER).unlink()
        run_pending(jobs)
        self.assertEqual(jobs.get("operator", job)["state"], "BLOCKED")
        self.assertFalse((jobs.probe.root / ("workspace-" + job)).exists())

    def test_execution_requires_explicit_grant_and_backend(self):
        from project_os_bridge.execution import WorkspaceWSL
        jobs = self.workspace_queue()
        backend = WorkspaceWSL({"demo:expo-test": {"PATH": "/usr/bin:/bin"}})
        with self.assertRaises(PermissionError):
            submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "no-grant", backend=backend)
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "execute", backend=backend)
        run_pending(jobs)
        self.assertEqual(jobs.get("operator", job)["state"], "BLOCKED")
        self.assertFalse((jobs.probe.root / ("workspace-" + job)).exists())
        self.assertEqual(job, submit_workspace(jobs, "operator", "demo", self.sha,
                                               "expo-test", "execute", backend=backend))
        different = WorkspaceWSL({"demo:expo-test": {"PATH": "/bin"}})
        with self.assertRaises(ValueError):
            submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "execute", backend=different)

    def test_execution_result_is_durable_and_no_replay(self):
        from project_os_bridge.execution import WorkspaceWSL
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        backend = WorkspaceWSL({"demo:expo-test": {"PATH": "/usr/bin:/bin"}})
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "execute", backend=backend)
        with patch("project_os_bridge.execution._command", return_value=(7, True)) as command:
            run_pending(jobs, workspace_backend=backend)
            command.assert_called_once()
        reopened = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        result = reopened.evidence("operator", job)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(result["result"]["execution"]["exit_code"], 7)
        self.assertEqual(reopened.pending_effects(), [])
        with patch("project_os_bridge.execution._command") as command:
            run_pending(reopened, workspace_backend=backend)
            command.assert_not_called()

    def test_direct_uncertain_effect_fences_other_profiles_and_no_replay(self):
        from project_os_bridge.execution import WorkspaceWSL
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        backend = WorkspaceWSL({key: {"PATH": "/usr/bin:/bin"}
                                for key in ("demo:expo-test", "demo:flutter-test")})
        first = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "first", backend=backend)
        other = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test", "other", backend=backend)
        with patch("project_os_bridge.execution._command", return_value=(124, False)) as command:
            run_pending(jobs, workspace_backend=backend)
            command.assert_called_once()
            reopened = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
            run_pending(reopened, workspace_backend=backend)
            command.assert_called_once()
        self.assertEqual(reopened.get("operator", first)["state"], "BLOCKED")
        self.assertEqual(reopened.get("operator", other)["state"], "QUEUED")
        effect, = reopened.pending_effects()
        self.assertEqual(effect["job_id"], first)
        self.assertEqual(effect["context_id"], backend.identities()["demo:expo-test"])
        # The persistence primitive is called only after local quiescence is verified.
        from project_os_bridge.reconcile import reconcile
        with self.assertRaises(PermissionError):
            reconcile(reopened, first)
        reconcile(reopened, first, quiescent=True)
        with patch("project_os_bridge.execution._command", return_value=(0, True)):
            run_pending(reopened, workspace_backend=backend)
        self.assertEqual(reopened.get("operator", other)["state"], "SUCCEEDED")
        self.assertEqual(reopened.get("operator", first)["state"], "BLOCKED")
        self.assertEqual(reopened.pending_effects(), [])

    def test_project_scoped_bindings_no_cross_project_fallback(self):
        from project_os_bridge.execution import WorkspaceWSL
        backend = WorkspaceWSL({key: {"PATH": "/usr/bin:/bin"}
                                for key in ("demo:expo-test", "other:expo-test")})
        self.assertNotEqual(backend.binding("expo-test", "demo"), backend.binding("expo-test", "other"))
        with self.assertRaises(PermissionError):
            backend.binding("expo-test", "unregistered")
        with self.assertRaises(PermissionError):
            backend.binding("expo-test")

    def test_direct_apk_output_and_empty_artifact(self):
        from project_os_bridge.execution import WorkspaceWSL
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        backend = WorkspaceWSL({"demo:flutter-apk-debug": {"PATH": "/usr/bin:/bin"}})
        first = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-apk-debug", "apk", backend=backend)
        second = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-apk-debug", "empty", backend=backend)
        def command(argv, cwd, env, deadline, *, enabled):
            if argv[1] == "build":
                path = cwd / "build/app/outputs/flutter-apk/app-debug.apk"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"synthetic apk bytes" if jobs.pending_effects()[0]["job_id"] == first else b"")
            return 0, True
        with patch("project_os_bridge.execution._command", side_effect=command):
            run_pending(jobs, workspace_backend=backend)
        result = jobs.evidence("operator", first)
        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertEqual(result["result"]["execution"]["artifact"],
                         artifact_identity("apk", "app-debug.apk", b"synthetic apk bytes"))
        result = jobs.evidence("operator", second)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(result["result"]["execution"]["artifact_error"], "APK_IDENTITY_INVALID")
        self.assertEqual(jobs.pending_effects(), [])

    def test_qa_release_plan_and_unfinalized_build_identity(self):
        from project_os_bridge.workspace_profiles import qa_plan
        from project_os_bridge.workspace_jobs import verified_qa_build_input
        from project_os_bridge.execution import WorkspaceWSL
        from project_os_bridge.workspace_profiles import apk_path
        flutter = qa_plan("flutter-apk-qa", {"dart_defines": {"QA": "true"}, "build_number": 42})
        self.assertIn("--release", flutter.argv)
        self.assertIn("--build-number=42", flutter.argv)
        self.assertIn("--dart-define=QA=true", flutter.argv)
        expo = {"native": "managed-script", "public_env": {"EXPO_PUBLIC_QA": "true"}}
        self.assertNotEqual(qa_plan("expo-apk-qa", expo).digest(),
                            qa_plan("expo-apk-qa", {"native": "native"}).digest())
        for profile, bad in (("flutter-apk-qa", {"variant": "debug"}),
                             ("flutter-apk-qa", {"build_number": True}),
                             ("expo-apk-qa", {"public_env": {"TOKEN": "private"}}),
                             ("expo-apk-qa", {"native": "shell"})):
            with self.assertRaises(ValueError):
                qa_plan(profile, bad)
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        route = "demo:expo-apk-qa"
        toolchain = {route: {"PATH": "/usr/bin:/bin"}}
        # The fixture has native Android source; use the native plan here.
        with self.assertRaises(ValueError):
            WorkspaceWSL(toolchain)
        backend = WorkspaceWSL(toolchain, qa_plans={route: {"public_env": {"EXPO_PUBLIC_QA": "true"}}})
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-apk-qa", "qa", backend=backend)
        def command(argv, cwd, env, deadline, *, enabled):
            self.assertEqual(env["EXPO_PUBLIC_QA"], "true")
            if ":app:assembleRelease" in argv:
                path = cwd / "app/build/outputs/apk/release/app-release.apk"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"unfinalized synthetic bytes")
            return 0, True
        with patch("project_os_bridge.execution._command", side_effect=command):
            run_pending(jobs, workspace_backend=backend)
        result = jobs.evidence("operator", job)["result"]["execution"]
        self.assertFalse(result["qa_delivery_ready"])
        raw, identity = verified_qa_build_input(jobs, "operator", job,
                                                expected_project="demo", expected_sha=self.sha)
        self.assertEqual(raw, b"unfinalized synthetic bytes")
        self.assertEqual(identity, result["artifact"])
        with self.assertRaises(PermissionError):
            verified_qa_build_input(jobs, "operator", job, expected_project="other", expected_sha=self.sha)
        apk_path(jobs.probe.root, job).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            verified_qa_build_input(jobs, "operator", job, expected_project="demo", expected_sha=self.sha)

    def test_qa_finalizer_persists_identity_and_rejects_tampering(self):
        import os
        from unittest.mock import Mock
        from project_os_bridge.android_qa import AndroidQATools, finalize_qa_build
        from project_os_bridge.execution import WorkspaceWSL
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        route = "demo:expo-apk-qa"
        backend = WorkspaceWSL({route: {"PATH": "/usr/bin:/bin"}}, qa_plans={route: {}})
        def build(key):
            job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-apk-qa", key, backend=backend)
            def command(argv, cwd, env, deadline, *, enabled):
                if ":app:assembleRelease" in argv:
                    path = cwd / "app/build/outputs/apk/release/app-release.apk"
                    path.parent.mkdir(parents=True)
                    path.write_bytes(b"unfinalized synthetic bytes")
                return 0, True
            with patch("project_os_bridge.execution._command", side_effect=command):
                run_pending(jobs, workspace_backend=backend)
            return job
        tools = Mock(spec=AndroidQATools)
        metadata = {"package": "example.demo.qa", "version_code": 42,
                    "abis": ["arm64-v8a", "x86_64"], "debuggable": False}
        tools.inspect.side_effect = lambda *args: dict(metadata)
        tools.certificate.return_value = "d" * 64
        tools.verify.return_value = "d" * 64
        def generate(directory, password):
            fd = os.open(directory / "qa.p12", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        def sign(source, dest, directory, password, work):
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(b"signed synthetic bytes")
        tools.generate.side_effect = generate
        tools.sign.side_effect = sign
        def finalize(job, package="example.demo.qa"):
            return finalize_qa_build(jobs, "operator", job, expected_project="demo",
                expected_sha=self.sha, expected_package=package, tools=tools)
        first = build("first-finalize")
        with self.assertRaises(ValueError):
            finalize(first, "example.other.qa")
        tools.generate.assert_not_called()
        result = finalize(first)
        self.assertTrue(result["signature_verified"])
        self.assertFalse(result["published"])
        self.assertEqual(finalize(first), result)
        tools.generate.assert_called_once()
        tools.sign.assert_called_once()
        second = build("second-finalize")
        metadata["version_code"] = 41
        with self.assertRaises(ValueError):
            finalize(second)
        metadata["version_code"] = 43
        second_result = finalize(second)
        self.assertEqual(second_result["certificate_sha256"], result["certificate_sha256"])
        tools.generate.assert_called_once()
        target = jobs.probe.root / "qa-signing" / "123" / "artifacts" / second / "app-qa.apk"
        target.write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            finalize(second)
        self.assertEqual(jobs.pending_effects(), [])
        import shutil
        shutil.rmtree(jobs.probe.root / "qa-signing" / "123" / "identity")
        third = build("third-finalize")
        with self.assertRaises(ValueError):
            finalize(third)
        tools.generate.assert_called_once()

    def test_qa_zip_preserves_exact_signed_apk_identity(self):
        import io
        import zipfile
        from project_os_bridge.android_qa import verify_qa_artifact_zip
        from project_os_bridge.workspace_profiles import artifact_identity
        raw = b"synthetic signed apk"
        receipt = {"signature_verified": True,
                   "artifact": artifact_identity("apk", "app-qa.apk", raw)}
        def archive(entries):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as out:
                for name, data in entries:
                    out.writestr(name, data)
            return buffer.getvalue()
        good = archive([("app-qa.apk", raw)])
        identity = artifact_identity("zip", "app-qa.zip", good)
        self.assertEqual(verify_qa_artifact_zip(good, receipt,
            expected_zip_sha256=identity["sha256"]), identity)
        for bad in (archive([("app-qa.apk", b"x" * len(raw))]),
                    archive([("../app-qa.apk", raw)]),
                    archive([("app-qa.apk", raw), ("extra.txt", b"extra")]),
                    archive([("app-qa.apk", raw[:-1])]), b"invalid archive"):
            with self.assertRaises(ValueError):
                verify_qa_artifact_zip(bad, receipt)
        with self.assertRaises(ValueError):
            verify_qa_artifact_zip(good, receipt, expected_zip_sha256="0" * 64)
        with self.assertRaises(ValueError):
            verify_qa_artifact_zip(good, {**receipt, "signature_verified": False})

    def test_worker_automatically_finalizes_bound_qa_build(self):
        from unittest.mock import Mock
        from project_os_bridge.android_qa import QASignerBinding
        from project_os_bridge.execution import WorkspaceWSL
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        signer = Mock(spec=QASignerBinding)
        signer.digest = "d" * 64
        route = "demo:expo-apk-qa"
        backend = WorkspaceWSL({route: {"PATH": "/usr/bin:/bin"}}, qa_plans={route: {}},
                               qa_signers={route: signer})
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-apk-qa", "auto-qa", backend=backend)
        def command(argv, cwd, env, deadline, *, enabled):
            if ":app:assembleRelease" in argv:
                path = cwd / "app/build/outputs/apk/release/app-release.apk"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"synthetic")
            return 0, True
        def finalize(jobs_arg, principal, job_id, request):
            self.assertEqual(jobs_arg.pending_effects(), [])
            self.assertEqual(jobs_arg.evidence(principal, job_id)["state"], "SUCCEEDED")
            self.assertEqual(request["qa_signer_sha256"], signer.digest)
            return {"signature_verified": True, "published": False}
        signer.finalize_locked.side_effect = finalize
        with patch("project_os_bridge.execution._command", side_effect=command):
            run_pending(jobs, workspace_backend=backend)
        self.assertEqual(jobs.evidence("operator", job)["result"]["qa_finalization"],
                         {"state": "SUCCEEDED", "receipt": {"signature_verified": True, "published": False}})
        reopened = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        run_pending(reopened, workspace_backend=backend)
        signer.finalize_locked.assert_called_once()

    def test_context_bound_execution_cannot_use_unregistered_executor(self):
        from project_os_bridge.execution import WorkspaceWSL
        from unittest.mock import Mock
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        backend = WorkspaceWSL({"demo:flutter-test": {"PATH": "/usr/bin:/bin"}})
        job = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test", "one", backend=backend)
        run_pending(jobs)
        self.assertEqual(jobs.get("operator", job)["state"], "BLOCKED")
        self.assertEqual(jobs.pending_effects(), [])

    def test_direct_wsl_profile_uses_durable_jobs_and_real_subprocess(self):
        from project_os_bridge.execution import WorkspaceWSL
        tools = self.root / "tools"
        tools.mkdir(mode=0o700)
        npm = tools / "npm"
        npm.write_text("#!/bin/sh\ncase \"$1\" in\nci) exit 0;;\nrun) test \"$2\" = test && printf success > result.txt;;\n*) exit 9;;\nesac\n")
        npm.chmod(0o700)
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        backend = WorkspaceWSL({"demo:expo-test": {"PATH": str(tools) + ":/usr/bin:/bin"}})
        before = self.git("status", "--porcelain")
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "direct", backend=backend)
        run_pending(jobs, workspace_backend=backend)
        evidence = jobs.evidence("operator", job)
        self.assertEqual(evidence["state"], "SUCCEEDED", evidence)
        result = evidence["result"]["execution"]
        self.assertEqual(result["execution_environment"], "wsl-direct")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["cleanup_verified"])
        self.assertNotIn("image_id", result)
        self.assertEqual((jobs.probe.root / ("workspace-" + job) / "result.txt").read_text(), "success")
        self.assertEqual(jobs.pending_effects(), [])
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual(submit_workspace(jobs, "operator", "demo", self.sha,
                                          "expo-test", "direct", backend=backend), job)
        npm.write_text("#!/bin/sh\nif test \"$1\" = ci; then printf changed > package-lock.json; fi\n")
        npm.chmod(0o700)
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "changed", backend=backend)
        run_pending(jobs, workspace_backend=backend)
        evidence = jobs.evidence("operator", job)
        self.assertEqual(evidence["state"], "FAILED", evidence)
        self.assertEqual(evidence["result"]["execution"]["reason"], "LOCKFILE_CHANGED")
        self.assertEqual(jobs.pending_effects(), [])
