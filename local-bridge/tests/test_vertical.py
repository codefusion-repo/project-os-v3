import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from project_os_bridge.core import Jobs, Policy
from project_os_bridge.vertical import local_jobs
from project_os_bridge.worker import run_pending

IMAGE="example/python@sha256:"+"a"*64


class VerticalTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.jobs=local_jobs(self.root)

    def submit(self,key="one"):
        return self.jobs.submit("local-fixture","disposable","git_fixture_check",key)

    def test_real_git_and_persisted_blocked_validation(self):
        job=self.submit()
        with patch("project_os_bridge.vertical.validate_in_container",
                   return_value={"status":"BLOCKED","reason":"ROOTLESS_UNAVAILABLE"}) as validate:
            run_pending(self.jobs,fixture_image=IMAGE)
        validate.assert_called_once()
        result=local_jobs(self.root).evidence("local-fixture",job)
        self.assertEqual(result["state"],"BLOCKED")
        self.assertEqual([e["state"] for e in result["events"]],["QUEUED","RUNNING","BLOCKED"])
        self.assertIn("+after",result["result"]["steps"][1]["diff"])
        self.assertTrue(result["result"]["steps"][1]["original_unchanged"])
        self.assertEqual(job,self.submit())
        with patch("project_os_bridge.vertical.validate_in_container") as validate:
            run_pending(self.jobs,fixture_image=IMAGE)
            validate.assert_not_called()

    def test_success_evidence_contract(self):
        job=self.submit()
        def fixture_result(repo,principal,revision,image):
            return {"status":"SUCCEEDED","revision":revision,"exit_code":0}
        with patch("project_os_bridge.vertical.validate_in_container",side_effect=fixture_result):
            run_pending(self.jobs,fixture_image=IMAGE)
        self.assertEqual(self.jobs.evidence("local-fixture",job)["state"],"SUCCEEDED")

    def test_no_image_no_git(self):
        job=self.submit()
        run_pending(self.jobs)
        self.assertEqual(self.jobs.get("local-fixture",job)["state"],"BLOCKED")
        self.assertFalse((self.root/("fixture-"+job)).exists())

    def test_default_queue_does_not_enable_workflow(self):
        queue=Jobs(self.root,self.jobs.policy)
        with self.assertRaises(ValueError):
            queue.submit("local-fixture","disposable","git_fixture_check","two")

    def test_evidence_denied(self):
        with self.assertRaises(PermissionError):
            self.jobs.evidence("other",self.submit())

    def test_pause_between_claims(self):
        job=self.submit()
        run_pending(self.jobs,fixture_image=IMAGE,enabled=lambda:False)
        self.assertEqual(self.jobs.get("local-fixture",job)["state"],"QUEUED")
