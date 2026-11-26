import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch
from project_os_bridge.core import Jobs, Policy
from project_os_bridge.vertical import local_jobs, bind_image, main
from project_os_bridge.worker import run_pending
from project_os_bridge.isolated import CHECKS, ISOLATION_CHECKS

IMAGE="example/python@sha256:"+"a"*64
CONTEXT_ID="1"*64


class VerticalTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.jobs=local_jobs(self.root)
        self.context=Mock(identity=Mock(return_value=CONTEXT_ID))

    def submit(self,key="one"):
        return self.jobs.submit("local-fixture","disposable","git_fixture_check",key)

    def drain_fixture(self):
        run_pending(self.jobs, fixture_image=IMAGE, podman_context=self.context, context_id=CONTEXT_ID)

    def test_real_git_and_persisted_blocked_validation(self):
        bind_image(self.jobs, IMAGE, CONTEXT_ID)
        job=self.submit()
        with patch("project_os_bridge.vertical.validate_in_container",
                   return_value={"status":"BLOCKED","reason":"ROOTLESS_UNAVAILABLE","container_absent":True}) as validate:
            self.drain_fixture()
        validate.assert_called_once()
        result=local_jobs(self.root).evidence("local-fixture",job)
        self.assertEqual(result["state"],"BLOCKED")
        self.assertEqual([e["state"] for e in result["events"]],["QUEUED","RUNNING","BLOCKED"])
        self.assertIn("+after",result["result"]["steps"][1]["diff"])
        self.assertTrue(result["result"]["steps"][1]["original_unchanged"])
        self.assertEqual(job,self.submit())
        with patch("project_os_bridge.vertical.validate_in_container") as validate:
            self.drain_fixture()
            validate.assert_not_called()

    def test_success_evidence_contract(self):
        bind_image(self.jobs, IMAGE, CONTEXT_ID)
        job=self.submit()
        def fixture_result(repo,principal,revision,image,*,token,context,identity):
            return {"status":"SUCCEEDED","revision":revision,"exit_code":0,
                    "profile":"fixture-python","cleanup_verified":True,"checks":CHECKS,
                    "isolation_checks":ISOLATION_CHECKS,"compatibility_checks":[]}
        with patch("project_os_bridge.vertical.validate_in_container",side_effect=fixture_result):
            self.drain_fixture()
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
        run_pending(self.jobs,fixture_image=IMAGE,podman_context=self.context,enabled=lambda:False)
        self.assertEqual(self.jobs.get("local-fixture",job)["state"],"QUEUED")

    def test_bound_image_conflict(self):
        bind_image(self.jobs,IMAGE,CONTEXT_ID)
        bind_image(self.jobs,IMAGE,CONTEXT_ID)
        with self.assertRaises(PermissionError):
            bind_image(self.jobs,"example/python@sha256:"+"b"*64,CONTEXT_ID)

    def test_same_image_cannot_switch_context(self):
        bind_image(self.jobs, IMAGE, CONTEXT_ID)
        with self.assertRaises(PermissionError):
            bind_image(self.jobs, IMAGE, "2"*64)

    def test_cli_never_adopts_replacement_before_claim_or_dispatch(self):
        for changed_before_claim in (True, False):
            with self.subTest(changed_before_claim=changed_before_claim), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                context = Mock()
                identities = iter([CONTEXT_ID] if changed_before_claim else [CONTEXT_ID, CONTEXT_ID])
                context.identity.side_effect = lambda expected=None: next(identities, "2" * 64)
                argv = ["fixture", "--state-dir", str(root), "--request-key", "drift",
                        "--image", IMAGE, "--podman-context", "/unused-test-context"]
                with patch("sys.argv", argv), patch("project_os_bridge.vertical.PodmanContext", return_value=context), \
                        patch("project_os_bridge.vertical.run_git_fixture") as handler, patch("builtins.print"):
                    with self.assertRaises(SystemExit) as exit_status:
                        main()
                    self.assertEqual(exit_status.exception.code, 1)
                    handler.assert_not_called()
                self.assertEqual(context.identity.call_args_list[0], call())
                self.assertTrue(all(c == call(CONTEXT_ID) for c in context.identity.call_args_list[1:]))
                jobs = local_jobs(root, existing=True)
                with jobs.transaction() as conn:
                    job = conn.execute("SELECT id FROM jobs").fetchone()[0]
                    effects = list(conn.execute("SELECT context_id, resolved_at FROM fixture_effects"))
                evidence = jobs.evidence("local-fixture", job)
                self.assertEqual(evidence["state"], "BLOCKED")
                if changed_before_claim:
                    self.assertEqual(effects, [])
                    self.assertEqual([e["state"] for e in evidence["events"]], ["QUEUED", "BLOCKED"])
                else:
                    self.assertEqual(len(effects), 1)
                    self.assertEqual(effects[0]["context_id"], CONTEXT_ID)
                    self.assertIsNotNone(effects[0]["resolved_at"])
                self.assertFalse(jobs.pending_effects())
                self.assertEqual((root / "fixture-context").read_text(), CONTEXT_ID + "\n")

    def test_legacy_state_cannot_bind_image(self):
        self.submit()
        with self.assertRaises(PermissionError):
            bind_image(self.jobs,IMAGE,CONTEXT_ID)

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
        bind_image(self.jobs, IMAGE, CONTEXT_ID)
        job=self.submit()
        def incomplete(repo,principal,revision,image,*,token,context,identity):
            return {"status":"SUCCEEDED","revision":revision,"exit_code":0}
        with patch("project_os_bridge.vertical.validate_in_container",side_effect=incomplete):
            self.drain_fixture()
        evidence=self.jobs.evidence("local-fixture",job)
        self.assertEqual(evidence["state"],"BLOCKED")
        self.assertEqual(evidence["result"]["error"],"INCOMPLETE_ISOLATION_EVIDENCE")
