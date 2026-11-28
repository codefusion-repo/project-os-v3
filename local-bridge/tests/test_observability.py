import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from project_os_bridge.core import Jobs, Policy
from project_os_bridge.observability import list_authorized, wait_for_job, measure_wait, WAIT_LIMIT_SECONDS


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.jobs = Jobs(self.root, Policy([(a, op, "disposable")
            for a in ("alice", "bob") for op in ("submit", "read", "cancel")]))
        self.access = Mock(return_value=None)
        self.check = Mock()

    def test_filters_and_pagination_without_other_principal(self):
        ids = [self.jobs.submit("alice", "disposable", "probe_check", str(i)) for i in range(3)]
        other = self.jobs.submit("bob", "disposable", "probe_check", "other")
        self.jobs.cancel("alice", ids[0])
        first = list_authorized(self.jobs, "alice", self.access, self.check, limit=1)
        second = list_authorized(self.jobs, "alice", self.access, self.check,
                                 cursor=first["next_cursor"], limit=2)
        self.assertEqual({row["id"] for row in first["jobs"] + second["jobs"]}, set(ids))
        self.assertNotIn(other, str(first) + str(second))
        self.assertIsNone(second["next_cursor"])
        cancelled = list_authorized(self.jobs, "alice", self.access, self.check, state="CANCELLED")
        self.assertEqual([row["id"] for row in cancelled["jobs"]], [ids[0]])
        self.assertEqual(list_authorized(self.jobs, "alice", self.access, self.check,
                                        project="unrelated")["jobs"], [])
        self.assertEqual(list_authorized(self.jobs, "alice", self.access, self.check,
                                        since="2099-01-01T00:00:00+00:00")["jobs"], [])

    def test_revocation_on_return(self):
        self.jobs.submit("alice", "disposable", "probe_check", "one")
        self.access.side_effect = [None, PermissionError("DENIED")]
        with self.assertRaises(PermissionError):
            list_authorized(self.jobs, "alice", self.access, self.check)

    def test_wait_no_mutation_and_terminal(self):
        ident = self.jobs.submit("alice", "disposable", "probe_check", "wait")
        read = lambda: self.jobs.get("alice", ident)
        result = asyncio.run(wait_for_job(read, self.check, 0, max_seconds=WAIT_LIMIT_SECONDS))
        self.assertTrue(result["wait_expired"])
        with self.assertRaises(ValueError):
            asyncio.run(wait_for_job(read, self.check, 1, max_seconds=0))
        self.jobs.cancel("alice", ident)
        result = asyncio.run(wait_for_job(read, self.check, 0, max_seconds=0))
        self.assertTrue(result["terminal"])
        self.assertFalse(result["wait_expired"])

    def test_measurement_and_worker_progress(self):
        async def scenario():
            job = self.jobs.submit("alice", "disposable", "probe_check", "async")
            async def finish():
                await asyncio.sleep(0.05)
                await asyncio.to_thread(self.jobs.cancel, "alice", job)
            task = asyncio.create_task(finish())
            result = await wait_for_job(lambda: self.jobs.get("alice", job), self.check,
                                        2, max_seconds=WAIT_LIMIT_SECONDS)
            await task
            self.assertTrue(result["terminal"])
            observed = await measure_wait(1, self.check)
            self.assertGreaterEqual(observed["server_elapsed_seconds"], 1)
            self.assertFalse(observed["job_created"])
        asyncio.run(scenario())
