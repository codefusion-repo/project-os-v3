import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from project_os_bridge.core import Jobs, Policy
from project_os_bridge.workspace_fixture import package_jobs, PRINCIPAL, MARKER, OPERATIONS
from project_os_bridge.worker import run_pending


class PackageFixtureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.jobs, self.sha = package_jobs(self.root, initialize=True)

    def submit(self, key="one", sha=None):
        return self.jobs.submit(PRINCIPAL, "disposable", "fixture_package", key,
                                expected_sha=self.sha if sha is None else sha)

    def test_real_revision_package_and_durable_replay(self):
        job = self.submit()
        run_pending(self.jobs)
        reopened, _ = package_jobs(self.root)
        evidence = reopened.evidence(PRINCIPAL, job)
        self.assertEqual(evidence["state"], "SUCCEEDED")
        self.assertEqual(evidence["result"]["head"], self.sha)
        self.assertEqual(evidence["result"]["revision"], hashlib.sha256(b"before\n").hexdigest())
        artifact = self.root / ("package-" + job) / "fixture.zip"
        build = evidence["result"]["steps"][-1]
        self.assertEqual(build["exit_code"], 0)
        self.assertEqual(build["sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
        with zipfile.ZipFile(artifact) as archive:
            self.assertEqual(archive.namelist(), ["fixture.txt"])
            self.assertEqual(archive.read("fixture.txt"), b"before\n")
        self.assertEqual(self.submit(), job)
        run_pending(reopened)
        self.assertEqual(evidence, reopened.evidence(PRINCIPAL, job))
        self.assertEqual((self.root / "source" / "repo" / "fixture.txt").read_bytes(), b"before\n")
        second = self.submit("two")
        run_pending(self.jobs)
        self.assertEqual(reopened.evidence(PRINCIPAL, second)["result"]["steps"][-1], build)

    def test_wrong_sha_and_idempotency_conflict(self):
        job = self.submit(sha="0" * 40)
        with self.assertRaises(ValueError):
            self.submit()
        run_pending(self.jobs)
        self.assertEqual(self.jobs.get(PRINCIPAL, job)["state"], "BLOCKED")
        self.assertFalse((self.root / ("package-" + job)).exists())
        self.assertFalse((self.root / "source" / ("worktree-" + job)).exists())

    def test_default_queue_and_missing_grant(self):
        default = Jobs(self.root, self.jobs.policy)
        with self.assertRaises(ValueError):
            default.submit(PRINCIPAL, "disposable", "fixture_package", "other", expected_sha=self.sha)
        grants = Policy((PRINCIPAL, op, "disposable") for op in OPERATIONS if op != "fixture_package")
        revoked = Jobs(self.root, grants, workflows=("fixture_package",))
        with self.assertRaises(PermissionError):
            revoked.submit(PRINCIPAL, "disposable", "fixture_package", "other", expected_sha=self.sha)
        job = self.submit()
        run_pending(revoked)
        self.assertEqual(self.jobs.get(PRINCIPAL, job)["state"], "BLOCKED")
        self.assertFalse((self.root / ("package-" + job)).exists())

    def test_marker_revoked_before_dispatch(self):
        job = self.submit()
        (self.root / MARKER).unlink()
        run_pending(self.jobs)
        self.assertEqual(self.jobs.get(PRINCIPAL, job)["state"], "BLOCKED")
        self.assertFalse((self.root / ("package-" + job)).exists())

    def test_cancel_and_interruption_do_not_replay(self):
        from project_os_bridge.worker import exclusive_worker
        cancelled = self.submit("cancel")
        self.assertTrue(self.jobs.cancel(PRINCIPAL, cancelled))
        interrupted = self.submit("interrupt")
        with exclusive_worker(self.jobs):
            self.assertEqual(self.jobs.claim()["id"], interrupted)
        run_pending(self.jobs)
        self.assertEqual(self.jobs.get(PRINCIPAL, cancelled)["state"], "CANCELLED")
        self.assertEqual(self.jobs.get(PRINCIPAL, interrupted)["state"], "INTERRUPTED")
        self.assertEqual(self.submit("interrupt"), interrupted)
        self.assertFalse((self.root / ("package-" + interrupted)).exists())

    def test_existing_worktree_is_preserved(self):
        job = self.submit()
        path = self.root / "source" / ("worktree-" + job)
        path.mkdir()
        (path / "unrelated").write_text("preserve")
        run_pending(self.jobs)
        self.assertEqual(self.jobs.get(PRINCIPAL, job)["state"], "BLOCKED")
        self.assertEqual((path / "unrelated").read_text(), "preserve")

    def test_evidence_does_not_dispatch(self):
        from project_os_bridge.vertical import main
        job = self.submit()
        with patch("sys.argv", ["fixture", "--state-dir", str(self.root), "--profile",
                                "fixture-package", "--evidence-job-id", job]), \
                patch("project_os_bridge.workspace_fixture.run_pending") as run, patch("builtins.print"):
            main()
        run.assert_not_called()
        self.assertEqual(self.jobs.get(PRINCIPAL, job)["state"], "QUEUED")

    def test_reject_existing_state_and_foreign_principal(self):
        with self.assertRaises(PermissionError):
            package_jobs(self.root, initialize=True)
        with self.assertRaises(PermissionError):
            self.jobs.submit("other", "disposable", "fixture_package", "foreign", expected_sha=self.sha)
