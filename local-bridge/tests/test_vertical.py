import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from project_os_bridge.core import Jobs, Policy
from project_os_bridge.vertical import local_jobs, bind_image, main
from project_os_bridge.worker import run_pending
from project_os_bridge.isolated import CHECKS

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
            return {"status":"SUCCEEDED","revision":revision,"exit_code":0,
                    "profile":"fixture-python","cleanup_verified":True,"checks":CHECKS}
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

    def test_bound_image_conflict(self):
        bind_image(self.jobs,IMAGE)
        bind_image(self.jobs,IMAGE)
        with self.assertRaises(PermissionError):
            bind_image(self.jobs,"example/python@sha256:"+"b"*64)

    def test_legacy_state_cannot_bind_image(self):
        self.submit()
        with self.assertRaises(PermissionError):
            bind_image(self.jobs,IMAGE)

    def test_evidence_cli_does_not_run_worker(self):
        job=self.submit()
        with patch("sys.argv",["fixture","--state-dir",str(self.root),"--evidence-job-id",job]), patch("project_os_bridge.vertical.run_pending") as run, patch("builtins.print"):
            main()
        run.assert_not_called()
        self.assertEqual(self.jobs.get("local-fixture",job)["state"],"QUEUED")

    def test_evidence_refuses_new_state(self):
        other=self.root/"new"
        other.mkdir(mode=0o700)
        with self.assertRaises(PermissionError):
            local_jobs(other,existing=True)
        self.assertEqual(list(other.iterdir()),[])

    def test_fixture_quota(self):
        from project_os_bridge.core import QueueLimitError
        first=self.submit("first")
        for n in range(7):
            self.submit(str(n))
        self.assertEqual(first,self.submit("first"))
        with self.assertRaises(QueueLimitError):
            self.submit("ninth")

    def test_incomplete_isolation_evidence_blocks_success(self):
        job=self.submit()
        def incomplete(repo,principal,revision,image):
            return {"status":"SUCCEEDED","revision":revision,"exit_code":0}
        with patch("project_os_bridge.vertical.validate_in_container",side_effect=incomplete):
            run_pending(self.jobs,fixture_image=IMAGE)
        evidence=self.jobs.evidence("local-fixture",job)
        self.assertEqual(evidence["state"],"BLOCKED")
        self.assertEqual(evidence["result"]["error"],"INCOMPLETE_ISOLATION_EVIDENCE")
