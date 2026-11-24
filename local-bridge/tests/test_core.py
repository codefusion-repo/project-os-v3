import tempfile
import unittest
from pathlib import Path
from project_os_bridge.core import Jobs, Policy
from project_os_bridge.worker import run_pending, exclusive_worker


class CoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.policy = Policy(("local-test", op, "disposable") for op in ("submit","read","cancel"))
        self.jobs = Jobs(self.root, self.policy)

    def submit(self, key="one"):
        return self.jobs.submit("local-test","disposable","probe_check",key)

    def test_denied(self):
        with self.assertRaises(PermissionError):
            self.jobs.submit(None,"disposable","probe_check","one")
        with self.assertRaises(PermissionError):
            self.jobs.submit("local-test","real","probe_check","one")

    def test_persist_replay_worker(self):
        job = self.submit()
        self.assertEqual(job,self.submit())
        run_pending(self.jobs)
        reopened = Jobs(self.root,self.policy)
        self.assertEqual(reopened.get("local-test",job)["state"],"SUCCEEDED")
        self.assertEqual(reopened.get("local-test",job)["result"],{"present":False,"marker":None})
        self.assertEqual(job,self.submit())
        with self.assertRaises(PermissionError):
            reopened.get("other",job)

    def test_cancel(self):
        job = self.submit()
        self.assertTrue(self.jobs.cancel("local-test",job))
        run_pending(self.jobs)
        self.assertEqual(self.jobs.get("local-test",job)["state"],"CANCELLED")

    def test_recovery(self):
        job = self.submit()
        with exclusive_worker(self.jobs):
            self.jobs.claim()
        run_pending(self.jobs)
        self.assertEqual(self.jobs.get("local-test",job)["state"],"INTERRUPTED")
        self.assertEqual(job,self.submit())

    def test_exclusive_worker(self):
        with exclusive_worker(self.jobs):
            with self.assertRaises(BlockingIOError):
                with exclusive_worker(self.jobs):
                    pass

    def test_revoked_before_claim(self):
        job = self.submit()
        revoked = Jobs(self.root,Policy([("local-test","read","disposable")]))
        run_pending(revoked)
        self.assertEqual(revoked.get("local-test",job)["state"],"BLOCKED")
