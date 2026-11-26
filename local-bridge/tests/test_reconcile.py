import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from project_os_bridge.core import Jobs, Policy, QueueLimitError
from project_os_bridge.worker import run_pending, exclusive_worker
from project_os_bridge.reconcile import reconcile
from project_os_bridge.isolated import ALPINE_FIXTURE_ONLY, container_absent
from project_os_bridge.vertical import OPERATIONS, bind_image


IDENTITY = "a" * 64
IMAGE = "localhost/project-os-alpine-ci@" + ALPINE_FIXTURE_ONLY


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.policy = Policy(("p", op, "disposable") for op in OPERATIONS)
        self.jobs = self.open()
        self.context = Mock(root=Path("/unused-test-context"), identity=Mock(return_value=IDENTITY))
        self.context.host.return_value = {"security": {}}
        bind_image(self.jobs, IMAGE, IDENTITY)
        self.first = self.jobs.submit("p","disposable","git_fixture_check","first")
        self.second = self.jobs.submit("p","disposable","probe_check","second")

    def open(self):
        return Jobs(self.root,self.policy,workflows=("probe_check","git_fixture_check"))

    def drain_fixture(self):
        run_pending(self.jobs, fixture_image=IMAGE, podman_context=self.context, context_id=IDENTITY)

    def test_cleanup_failure_blocks_queue_and_new_work_across_restart(self):
        with patch("project_os_bridge.vertical.run_git_fixture", return_value=("BLOCKED", {"container_absent":False})):
            self.drain_fixture()
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
            row = self.jobs.claim(fixture_context=IDENTITY)
            self.assertIsNone(self.open().claim())
            with self.assertRaises(BlockingIOError):
                reconcile(self.jobs,self.first,self.context)
        reopened = self.open()
        run_pending(reopened)
        self.assertEqual(reopened.get("p",self.first)["state"],"INTERRUPTED")
        with patch("project_os_bridge.reconcile.container_absent",return_value=False):
            with self.assertRaises(PermissionError):
                reconcile(reopened,self.first,self.context)
        self.assertEqual(reopened.pending_effects()[0]["token"],row["effect_token"])
        with patch("project_os_bridge.reconcile.container_absent",return_value=True) as absent:
            reconcile(reopened,self.first,self.context)
            absent.assert_called_once_with(self.context, IDENTITY, row["effect_token"])
        run_pending(reopened)
        self.assertEqual(reopened.get("p",self.first)["state"],"INTERRUPTED")
        self.assertEqual(reopened.get("p",self.second)["state"],"SUCCEEDED")

    def test_absence_requires_both_name_and_label_queries(self):
        token = "a"*32
        for code, output, expected in ((1,b"",True),(0,b"",False),(1,b"other-id",False),(125,b"",False)):
            with patch.object(self.context,"run",side_effect=[Mock(returncode=code),Mock(returncode=0,stdout=output)]) as run:
                self.assertEqual(container_absent(self.context, IDENTITY, token),expected)
                self.assertEqual(run.call_args_list[0].args,(IDENTITY,"container","exists","project-os-fixture-"+token))
                self.assertIn("label=io.project-os.fixture="+token,run.call_args_list[1].args)
        with patch.object(self.context,"run",side_effect=subprocess.TimeoutExpired("podman",10)):
            with self.assertRaises(subprocess.TimeoutExpired):
                container_absent(self.context, IDENTITY, token)

    def test_success_clears_barrier_atomically(self):
        with patch("project_os_bridge.vertical.run_git_fixture",return_value=("SUCCEEDED",{"container_absent":True})):
            self.drain_fixture()
        self.assertFalse(self.open().pending_effects())
        self.assertEqual(self.jobs.get("p",self.second)["state"],"SUCCEEDED")

    def assert_compatibility_barrier(self, failure, expected_state):
        effects = []
        responses = iter([Mock(returncode=1), Mock(returncode=0, stdout=b"owned-container\n")]
                         if failure is None else [])

        def launch(identity, action, *args, **kwargs):
            self.assertEqual(identity, IDENTITY)
            if action != "run":
                return next(responses)
            effect = self.open().pending_effects()[0]
            effects.append(effect)
            self.assertEqual(effect["job_id"], self.first)
            self.assertEqual(effect["context_id"], IDENTITY)
            self.assertIn("project-os-fixture-" + effect["token"], args)
            self.assertIn("io.project-os.fixture=" + effect["token"], args)
            self.assertIn("check_compatibility(True)", args[args.index("-c") + 1])
            if failure is not None:
                raise failure
            return Mock(returncode=20)  # Fixed program reported a compatibility failure.

        self.context.run.side_effect = launch
        with patch("project_os_bridge.isolated.challenge", return_value='{"forbidden": []}'):
            if isinstance(failure, KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    self.drain_fixture()
            else:
                self.drain_fixture()
        self.assertEqual(len(effects), 1)
        run_count = self.context.run.call_count
        reopened = self.open()
        run_pending(reopened, fixture_image=IMAGE, podman_context=self.context, context_id=IDENTITY)
        self.assertEqual(self.context.run.call_count, run_count)
        self.assertEqual(reopened.get("p", self.first)["state"], expected_state)
        self.assertEqual(reopened.get("p", self.second)["state"], "QUEUED")
        self.assertEqual(reopened.pending_effects(), effects)
        evidence = reopened.evidence("p", self.first)
        with patch("project_os_bridge.reconcile.container_absent", return_value=True) as absent:
            reconcile(reopened, self.first, self.context)
        absent.assert_called_once_with(self.context, IDENTITY, effects[0]["token"])
        self.assertFalse(reopened.pending_effects())
        self.assertEqual(reopened.submit("p", "disposable", "git_fixture_check", "first"), self.first)
        run_pending(reopened, fixture_image=IMAGE, podman_context=self.context, context_id=IDENTITY)
        self.assertEqual(reopened.evidence("p", self.first), evidence)
        self.assertEqual(reopened.get("p", self.second)["state"], "SUCCEEDED")
        self.assertEqual(self.context.run.call_count, run_count)

    def test_interrupted_compatibility_is_recorded_before_launch_and_recovered(self):
        self.assert_compatibility_barrier(KeyboardInterrupt(), "INTERRUPTED")

    def test_compatibility_timeout_keeps_barrier_across_restart(self):
        self.assert_compatibility_barrier(subprocess.TimeoutExpired("podman", 30), "BLOCKED")

    def test_unconfirmed_compatibility_cleanup_keeps_barrier(self):
        self.assert_compatibility_barrier(None, "BLOCKED")

    def test_legacy_unknown_container_cannot_be_reconciled(self):
        with self.jobs.transaction() as c:
            c.execute("DROP TABLE fixture_effects")
            c.execute("UPDATE jobs SET state='RUNNING' WHERE id=?", (self.first,))
        reopened = self.open()
        self.assertEqual(reopened.pending_effects(), [{"job_id": self.first, "token": None, "context_id": None}])
        with self.assertRaises(PermissionError):
            reconcile(reopened,self.first,self.context)
        self.context.host.assert_not_called()
        self.assertIsNone(reopened.claim())
        self.assertEqual(reopened.get("p",self.second)["state"],"QUEUED")

    def test_reconcile_timeout_keeps_barrier(self):
        with exclusive_worker(self.jobs):
            self.jobs.claim(fixture_context=IDENTITY)
        with patch("project_os_bridge.reconcile.container_absent",
                   side_effect=subprocess.TimeoutExpired("podman",10)):
            with self.assertRaises(subprocess.TimeoutExpired):
                reconcile(self.jobs,self.first,self.context)
        self.assertEqual(len(self.open().pending_effects()),1)
        self.assertIsNone(self.open().claim())

    def test_pre_context_token_stays_unresolved_after_migration(self):
        with self.jobs.transaction() as conn:
            conn.execute("DROP TABLE fixture_effects")
            conn.execute("CREATE TABLE fixture_effects(job_id TEXT PRIMARY KEY, token TEXT, resolved_at TEXT)")
            conn.execute("INSERT INTO fixture_effects VALUES(?,?,NULL)", (self.first,"b"*32))
        jobs = self.open()
        self.assertEqual(jobs.pending_effects(),[{"job_id":self.first,"token":"b"*32,"context_id":None}])
        with self.assertRaises(PermissionError):
            reconcile(jobs,self.first,self.context)
        self.context.host.assert_not_called()
        self.assertIsNone(jobs.claim())

    def test_wrong_context_does_not_query_absence_or_release(self):
        row = self.jobs.claim(fixture_context=IDENTITY)
        mismatch = Mock(host=Mock(side_effect=PermissionError("different context")))
        with self.assertRaises(PermissionError):
            reconcile(self.open(),self.first,mismatch)
        mismatch.host.assert_called_once_with(IDENTITY)
        mismatch.run.assert_not_called()
        with self.assertRaises(RuntimeError):
            self.jobs.resolve_effect(self.first,row["effect_token"],"b"*64)
        self.assertEqual(self.open().pending_effects()[0]["context_id"],IDENTITY)
