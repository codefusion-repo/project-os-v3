import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from project_os_bridge.core import Jobs, Policy, QueueLimitError
from project_os_bridge.worker import run_pending, exclusive_worker
from project_os_bridge.reconcile import reconcile
from project_os_bridge.isolated import container_absent


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.policy = Policy(("p", op, "disposable") for op in ("submit","read","git_workflow"))
        self.jobs = self.open()
        self.first = self.jobs.submit("p","disposable","git_fixture_check","first")
        self.second = self.jobs.submit("p","disposable","probe_check","second")

    def open(self):
        return Jobs(self.root,self.policy,workflows=("probe_check","git_fixture_check"))

    def test_cleanup_failure_blocks_queue_and_new_work_across_restart(self):
        with patch("project_os_bridge.vertical.run_git_fixture", return_value=("BLOCKED", {"container_absent":False})):
            run_pending(self.jobs, fixture_image="fixture")
        reopened = self.open()
        self.assertEqual(reopened.get("p",self.first)["state"],"BLOCKED")
        self.assertEqual(reopened.get("p",self.second)["state"],"QUEUED")
        self.assertIsNone(reopened.claim())
        with self.assertRaises(QueueLimitError):
            reopened.submit("p","disposable","probe_check","third")
        self.assertEqual(reopened.submit("p","disposable","git_fixture_check","first"),self.first)
        run_pending(reopened)
        self.assertEqual(reopened.get("p",self.second)["state"],"QUEUED")

    def test_interrupted_claim_and_explicit_resolution(self):
        with exclusive_worker(self.jobs):
            row = self.jobs.claim()
            self.assertIsNone(self.open().claim())
            with self.assertRaises(BlockingIOError):
                reconcile(self.jobs,self.first)
        reopened = self.open()
        run_pending(reopened)
        self.assertEqual(reopened.get("p",self.first)["state"],"INTERRUPTED")
        with patch("project_os_bridge.reconcile.rootless_host"), patch("project_os_bridge.reconcile.container_absent",return_value=False):
            with self.assertRaises(PermissionError):
                reconcile(reopened,self.first)
        self.assertEqual(reopened.pending_effects()[0]["token"],row["effect_token"])
        with patch("project_os_bridge.reconcile.rootless_host"), patch("project_os_bridge.reconcile.container_absent",return_value=True) as absent:
            reconcile(reopened,self.first)
            absent.assert_called_once_with(row["effect_token"])
        run_pending(reopened)
        self.assertEqual(reopened.get("p",self.first)["state"],"INTERRUPTED")
        self.assertEqual(reopened.get("p",self.second)["state"],"SUCCEEDED")

    def test_absence_requires_both_name_and_label_queries(self):
        token = "a"*32
        for code, output, expected in ((1,b"",True),(0,b"",False),(1,b"other-id",False),(125,b"",False)):
            with patch("project_os_bridge.isolated.podman_run",side_effect=[Mock(returncode=code),Mock(returncode=0,stdout=output)]) as run:
                self.assertEqual(container_absent(token),expected)
                self.assertEqual(run.call_args_list[0].args,("container","exists","project-os-fixture-"+token))
                self.assertIn("label=io.project-os.fixture="+token,run.call_args_list[1].args)
        with patch("project_os_bridge.isolated.podman_run",side_effect=subprocess.TimeoutExpired("podman",10)):
            with self.assertRaises(subprocess.TimeoutExpired):
                container_absent(token)

    def test_success_clears_barrier_atomically(self):
        with patch("project_os_bridge.vertical.run_git_fixture",return_value=("SUCCEEDED",{"container_absent":True})):
            run_pending(self.jobs,fixture_image="fixture")
        self.assertFalse(self.open().pending_effects())
        self.assertEqual(self.jobs.get("p",self.second)["state"],"SUCCEEDED")
