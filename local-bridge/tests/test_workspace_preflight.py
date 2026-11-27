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
        jobs = self.workspace_queue()
        image = "sha256:" + "a" * 64
        with self.assertRaises(PermissionError):
            submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "no-grant",
                             image_id=image)
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "execute",
                               image_id=image)
        run_pending(jobs)
        self.assertEqual(jobs.get("operator", job)["state"], "BLOCKED")
        self.assertFalse((jobs.probe.root / ("workspace-" + job)).exists())
        self.assertEqual(job, submit_workspace(jobs, "operator", "demo", self.sha, "expo-test",
                                               "execute", image_id=image))
        with self.assertRaises(ValueError):
            submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "execute",
                             image_id="sha256:" + "b" * 64)

    def test_execution_result_is_durable_and_no_replay(self):
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        image = "sha256:" + "a" * 64
        job = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "execute",
                               image_id=image)
        def executor(workspace, row, snapshot):
            self.assertEqual(row["workspace"]["image_id"], image)
            self.assertEqual((workspace / "pubspec.yaml").read_text(), "name: demo\n")
            return {"exit_code": 7, "image_id": image}
        with patch("builtins.print"):
            run_pending(jobs, workspace_executor=executor)
        result = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",)).evidence("operator", job)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(result["result"]["execution"]["exit_code"], 7)
        self.assertEqual(result["result"]["operation"], "execute")
        with patch("builtins.print") as unused:
            run_pending(jobs, workspace_executor=lambda *args: self.fail("must not replay"))
            unused.assert_not_called()
        from project_os_bridge.core import QueueLimitError
        with self.assertRaises(QueueLimitError):
            submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "new", image_id=image)

    def test_podman_candidate_fence_and_reconciliation(self):
        from project_os_bridge.workspace_podman import WorkspacePodman
        from project_os_bridge.podman_context import PodmanContext
        from project_os_bridge.reconcile import reconcile
        from unittest.mock import Mock
        from subprocess import CompletedProcess, TimeoutExpired
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute", "workspace_prepare"))
        context = Mock(spec=PodmanContext)
        identity = "c" * 64
        context.identity.return_value = identity
        image = "localhost/project-os-alpine-ci@sha256:" + "a" * 64
        backend = WorkspacePodman(context, {"expo-test": image})
        launched = []
        def run(expected, *args, **kwargs):
            self.assertEqual(expected, identity)
            if args[0] == "container":
                return CompletedProcess(args, 1)
            if args[0] == "ps":
                return CompletedProcess(args, 0, stdout=b"")
            self.assertEqual(args[0], "run")
            self.assertEqual(len(jobs.pending_effects()), 1)
            self.assertIn("--network=none", args)
            self.assertIn("--pull=never", args)
            self.assertIn("--cap-drop=ALL", args)
            self.assertEqual(args[args.index("--volume") + 1].split(":")[-1], "ro")
            launched.append(args)
            raise TimeoutExpired(args, 900)
        context.run.side_effect = run
        first = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "one", backend=backend)
        other = submit_workspace(jobs, "operator", "demo", self.sha, "expo-test", "two", backend=backend)
        run_pending(jobs, workspace_backend=backend)
        self.assertEqual(jobs.get("operator", first)["state"], "BLOCKED")
        self.assertEqual(jobs.get("operator", other)["state"], "QUEUED")
        self.assertEqual(len(launched), 1)
        effects = jobs.pending_effects()
        self.assertEqual(effects[0]["job_id"], first)
        self.assertEqual(effects[0]["context_id"], identity)
        self.assertIn("io.project-os.fixture=" + effects[0]["token"], launched[0])
        reopened = Jobs(jobs.probe.root, policy, workflows=("workspace_execute", "workspace_prepare"))
        run_pending(reopened, workspace_backend=backend)
        self.assertEqual(len(launched), 1)
        # Local reconciliation refuses uncertain absence, then clears only the
        # exact effect. The test double stands in for operator-proven quiescence.
        with patch("project_os_bridge.reconcile.container_absent", return_value=False):
            with self.assertRaises(PermissionError):
                reconcile(reopened, first, context)
        self.assertEqual(reopened.pending_effects(), effects)
        reconcile(reopened, first, context)
        self.assertEqual(reopened.pending_effects(), [])
        self.assertEqual(reopened.get("operator", first)["state"], "BLOCKED")
        self.assertEqual(first, submit_workspace(reopened, "operator", "demo", self.sha,
                         "expo-test", "one", backend=backend))
        def success(expected, *args, **kwargs):
            if args[0] == "run":
                self.assertEqual(len(reopened.pending_effects()), 1)
                return CompletedProcess(args, 0)
            return run(expected, *args, **kwargs)
        context.run.side_effect = success
        run_pending(reopened, workspace_backend=backend)
        self.assertEqual(reopened.get("operator", other)["state"], "SUCCEEDED")
        self.assertEqual(reopened.pending_effects(), [])

    def test_podman_apk_output_and_empty_artifact(self):
        from project_os_bridge.workspace_podman import WorkspacePodman, apk_path
        from project_os_bridge.podman_context import PodmanContext
        from unittest.mock import Mock
        from subprocess import CompletedProcess
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        context = Mock(spec=PodmanContext)
        context.identity.return_value = "c" * 64
        image = "localhost/project-os-mobile-ci@sha256:" + "a" * 64
        backend = WorkspacePodman(context, {"flutter-apk-debug": image})
        first = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-apk-debug", "apk", backend=backend)
        second = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-apk-debug", "empty", backend=backend)
        def run(expected, *args, **kwargs):
            if args[0] == "container":
                return CompletedProcess(args, 1)
            if args[0] == "ps":
                return CompletedProcess(args, 0, stdout=b"")
            self.assertEqual(args[0], "run")
            effect = jobs.pending_effects()[0]
            path = apk_path(jobs.probe.root, effect["job_id"])
            self.assertIn(str(path) + ":/output.apk:rw", args)
            self.assertIn("--network=none", args)
            self.assertIn("--ulimit=fsize=536870912:536870912", args)
            self.assertEqual(path.stat().st_size, 0)
            if effect["job_id"] == first:
                path.write_bytes(b"synthetic apk bytes")
            return CompletedProcess(args, 0)
        context.run.side_effect = run
        run_pending(jobs, workspace_backend=backend)
        result = jobs.evidence("operator", first)
        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertEqual(result["result"]["execution"]["artifact"],
                         artifact_identity("apk", "app-debug.apk", b"synthetic apk bytes"))
        failed = jobs.evidence("operator", second)
        self.assertEqual(failed["state"], "FAILED")
        self.assertEqual(failed["result"]["execution"]["artifact_error"], "APK_IDENTITY_INVALID")
        self.assertEqual(jobs.pending_effects(), [])

    def test_context_bound_execution_cannot_use_ci_executor(self):
        from project_os_bridge.workspace_podman import WorkspacePodman
        from project_os_bridge.podman_context import PodmanContext
        from unittest.mock import Mock
        jobs = self.workspace_queue()
        policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
        jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
        context = Mock(spec=PodmanContext)
        context.identity.return_value = "c" * 64
        backend = WorkspacePodman(context, {"flutter-test":
                                  "localhost/project-os-alpine-ci@sha256:" + "a" * 64})
        job = submit_workspace(jobs, "operator", "demo", self.sha, "flutter-test", "one", backend=backend)
        executor = Mock()
        run_pending(jobs, workspace_executor=executor)
        executor.assert_not_called()
        self.assertEqual(jobs.get("operator", job)["state"], "BLOCKED")
        self.assertEqual(jobs.pending_effects(), [])
