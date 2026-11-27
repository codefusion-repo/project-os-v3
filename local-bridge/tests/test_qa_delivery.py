import hashlib
import io
import unittest
import zipfile

from project_os_bridge.qa_delivery import DeliveryPlan, WORKFLOW


class QADeliveryTests(unittest.TestCase):
    def setUp(self):
        self.raw = b"synthetic signed APK identity"
        self.apk = {"kind": "apk", "artifact": "app-qa.apk",
                    "sha256": hashlib.sha256(self.raw).hexdigest(), "size": len(self.raw)}
        self.plan = DeliveryPlan("example/private", 123, 8, "a" * 40, 9,
                                 "b" * 40, "main", "c" * 32,
                                 self.apk["sha256"], self.apk["size"], "d" * 64)
        self.receipt = {"job_id": self.plan.job_id, "repository_id": 123,
                        "head": self.plan.head, "workspace_sha256": self.plan.snapshot_sha256,
                        "artifact": self.apk, "signature_verified": True, "published": False}
        self.repository = {"id": 123, "full_name": "example/private",
                           "private": True, "default_branch": "main"}
        self.pr = {"number": 8, "state": "open",
                   "head": {"sha": self.plan.head, "repo": {"id": 123}},
                   "base": {"repo": {"id": 123}}}
        self.run = {"id": 10, "workflow_id": 9, "path": WORKFLOW,
                    "head_branch": "main", "head_sha": self.plan.workflow_sha,
                    "repository": {"id": 123}, "head_repository": {"id": 123},
                    "event": "workflow_dispatch", "display_title": self.plan.label,
                    "run_attempt": 1, "status": "completed", "conclusion": "success"}
        self.jobs = [{"id": 11, "run_id": 10, "name": "publish-qa", "runner_id": 12,
                      "runner_name": self.plan.label, "status": "completed",
                      "conclusion": "success", "labels": [self.plan.label]}]
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("app-qa.apk", self.raw)
        self.archive = out.getvalue()
        self.artifacts = [{"id": 13, "name": self.plan.artifact_name, "expired": False,
                           "size_in_bytes": len(self.archive),
                           "digest": "sha256:" + hashlib.sha256(self.archive).hexdigest(),
                           "workflow_run": {"id": 10, "repository_id": 123,
                               "head_repository_id": 123, "head_sha": self.plan.workflow_sha,
                               "head_branch": "main"}}]

    def verify(self, **overrides):
        data = dict(repository=self.repository, pr=self.pr, run=self.run, run_id=10,
                    runner_id=12, jobs=self.jobs, artifacts=self.artifacts,
                    archive=self.archive, receipt=self.receipt)
        data.update(overrides)
        return self.plan.verify_completed(**data)

    def test_exact_delivery(self):
        result = self.verify()
        self.assertEqual(result["apk"], self.apk)
        self.assertEqual(result["artifact_url"],
                         "https://github.com/example/private/actions/runs/10/artifacts/13")
        self.assertEqual(self.plan.dispatch_request()["ref"], "main")
        self.assertEqual(self.plan.runner_request(1)["labels"], [self.plan.label])

    def test_rejects_public_repository_and_moved_or_foreign_pr(self):
        with self.assertRaises(PermissionError):
            self.verify(repository={**self.repository, "private": False})
        for head in ({"sha": "e" * 40, "repo": {"id": 123}},
                     {"sha": self.plan.head, "repo": {"id": 124}}):
            with self.assertRaises(PermissionError):
                self.verify(pr={**self.pr, "head": head})

    def test_rejects_wrong_run_attempt_workflow_or_runner(self):
        for patch in ({"run_attempt": 2}, {"workflow_id": 99}, {"head_sha": "e" * 40},
                      {"display_title": "other"}, {"conclusion": "failure"}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.verify(run={**self.run, **patch})
        with self.assertRaises(ValueError):
            self.verify(runner_id=99)
        with self.assertRaises(ValueError):
            self.verify(jobs=self.jobs * 2)

    def test_rejects_artifact_identity_and_zip_drift(self):
        for patch in ({"expired": True}, {"name": "other"}, {"digest": "sha256:" + "0" * 64},
                      {"size_in_bytes": 1}, {"workflow_run": {"id": 99}}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.verify(artifacts=[{**self.artifacts[0], **patch}])
        with self.assertRaises(ValueError):
            self.verify(artifacts=self.artifacts * 2)
        with self.assertRaises(ValueError):
            self.verify(archive=self.archive + b"tampered")

    def test_rejects_unverified_or_dirty_receipt(self):
        for patch in ({"signature_verified": False}, {"changes_sha256": "f" * 64},
                      {"workspace_sha256": "e" * 64}, {"published": True}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.verify(receipt={**self.receipt, **patch})


if __name__ == "__main__":
    unittest.main()
