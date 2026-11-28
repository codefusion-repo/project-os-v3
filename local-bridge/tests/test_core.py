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

    def test_revoked_job_does_not_starve_queue(self):
        first = self.submit("first")
        policy = Policy([("other","submit","disposable"),("other","read","disposable"),
                         ("local-test","read","disposable")])
        queue = Jobs(self.root,policy)
        second = queue.submit("other","disposable","probe_check","second")
        run_pending(queue)
        self.assertEqual(queue.get("local-test",first)["state"],"BLOCKED")
        self.assertEqual(queue.get("other",second)["state"],"SUCCEEDED")

    def test_disabled_after_claim_blocks_without_dispatch(self):
        from unittest.mock import patch
        first = self.submit("first")
        second = self.submit("second")
        with patch.object(self.jobs.probe, "read", side_effect=AssertionError("must not execute")) as read:
            checks = iter((True, False))
            run_pending(self.jobs, enabled=lambda: next(checks))
            read.assert_not_called()
        self.assertEqual(self.jobs.get("local-test", first)["state"], "BLOCKED")
        self.assertEqual(self.jobs.get("local-test", second)["state"], "QUEUED")
        self.assertEqual(self.jobs.get("local-test", first)["result"], {"reason": "DISPATCH_DISABLED"})

    def test_active_quota_and_replay(self):
        from project_os_bridge.core import QueueLimitError
        first=self.submit("first")
        for n in range(31):
            self.submit(str(n))
        self.assertEqual(first,self.submit("first"))
        with self.assertRaises(QueueLimitError):
            self.submit("overflow")
        self.assertTrue(self.jobs.cancel("local-test",first))
        self.submit("new")

    def test_workspace_history_does_not_exhaust_active_admission(self):
        from project_os_bridge.core import QueueLimitError
        policy = Policy([*self.policy.grants,
                         *(("local-test", op, "demo") for op in
                           ("workspace_prepare", "workspace_materialize", "flutter-test"))])
        jobs = Jobs(self.root, policy, workflows=("workspace_prepare",))
        request = {"project": "demo", "profile": "flutter-test",
                   "expected_sha": "a" * 40, "binding": "b" * 64}
        def submit(key):
            return jobs.submit("local-test", "disposable", "workspace_prepare", key,
                               workspace=request)
        historical = []
        for n in range(9):
            job = submit(f"history-{n}")
            self.assertTrue(jobs.cancel("local-test", job))
            historical.append(job)
        active = [submit(f"active-{n}") for n in range(8)]
        with self.assertRaisesRegex(QueueLimitError, "WORKSPACE_ACTIVE_LIMIT"):
            submit("overflow")
        self.assertEqual(submit("active-0"), active[0])
        self.assertEqual(submit("history-0"), historical[0])
        self.assertEqual(jobs.evidence("local-test", historical[0])["state"], "CANCELLED")
        self.assertTrue(jobs.cancel("local-test", active[0]))
        self.assertEqual(jobs.get("local-test", submit("overflow"))["state"], "QUEUED")
        with jobs.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM jobs").fetchone()[0], 18)
            conn.execute("INSERT INTO fixture_effects(job_id) VALUES(?)", (historical[0],))
        with self.assertRaisesRegex(QueueLimitError, "RECONCILIATION_REQUIRED"):
            submit("uncertain")
