import unittest
import subprocess
import tempfile
from unittest.mock import patch
from pathlib import Path

from project_os_bridge.codex_provider import (
    capacity_from_response, select_executor, validate_task, run_codex, require_checkout, _summary, provider_catalog, selection_valid,
)


class CodexProviderTests(unittest.TestCase):
    def setUp(self):
        self.task = {"mode": "auto", "issue": 18, "pr": None,
                     "branch": "work/18-codex-provider", "prompt": "Review the documented contract."}
        self.request = {"codex_task": self.task, "expected_sha": "a" * 40, "execution_id": "b" * 64}
        self.before = {"head": "a" * 40, "branch": self.task["branch"], "dirty": False,
                       "status_sha256": "c" * 64, "tracked_diff_sha256": "d" * 64}

    def test_route_and_structured_capacity(self):
        self.assertEqual(capacity_from_response({"ordinaryUsageAllowed": True}), "available")
        self.assertEqual(capacity_from_response({"ordinaryUsageAllowed": False,
            "rateLimits": {"rateLimitReachedType": "rate_limit_reached"}}), "exhausted")
        self.assertEqual(capacity_from_response({"message": "quota exhausted"}), "unknown")
        self.assertEqual(capacity_from_response({"rateLimits": {"primary": {"usedPercent": 1}}}), "unknown")
        for state in ("unknown", "denied", "exhausted", "unavailable"):
            self.assertEqual(select_executor("auto", state), "browser")
            self.assertEqual(select_executor("codex", state), "blocked")
        self.assertEqual(select_executor("auto", "available"), "codex")
        self.assertEqual(select_executor("browser", "available"), "browser")

    def test_task_is_bounded_and_no_sensitive_prompt(self):
        self.assertEqual(validate_task(self.task), self.task)
        for change in ({"branch": "main"}, {"branch": "work/../main"}, {"target_branch": "main"}, {"issue": True},
                       {"mode": "browser"}, {"prompt": "x" * 16385},
                       {"prompt": "password: synthetic-private-value"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_task({**self.task, **change})

    def test_fallback_pre_dispatch_and_uncertain_probe(self):
        with patch("project_os_bridge.codex_provider.require_checkout", return_value=self.before), \
             patch("project_os_bridge.codex_provider.shutil.which", return_value="/fixture/codex"), \
             patch("project_os_bridge.codex_provider.probe_capacity", return_value=("exhausted", True)), \
             patch("project_os_bridge.codex_provider.execute_turn") as turn:
            result = run_codex(Path("/fixture"), {"PATH": "/fixture"}, self.request, enabled=lambda: True)
            self.assertEqual(result["executor"], "browser")
            self.assertTrue(result["cleanup_verified"])
            self.assertFalse(result["started"])
            turn.assert_not_called()
        with patch("project_os_bridge.codex_provider.require_checkout", return_value=self.before), \
             patch("project_os_bridge.codex_provider.shutil.which", return_value="/fixture/codex"), \
             patch("project_os_bridge.codex_provider.probe_capacity", return_value=("unknown", False)):
            result = run_codex(Path("/fixture"), {"PATH": "/fixture"}, self.request, enabled=lambda: True)
            self.assertEqual(result["executor"], "blocked")
            self.assertFalse(result["cleanup_verified"])

    def test_recheck_before_dispatch_and_no_fallback_after_uncertain_turn(self):
        with patch("project_os_bridge.codex_provider.require_checkout",
                   side_effect=[self.before, ValueError("changed")]), \
             patch("project_os_bridge.codex_provider.shutil.which", return_value="/fixture/codex"), \
             patch("project_os_bridge.codex_provider.probe_capacity", return_value=("available", True)), \
             patch("project_os_bridge.codex_provider.execute_turn") as turn:
            result = run_codex(Path("/fixture"), {"PATH": "/fixture"}, self.request, enabled=lambda: True)
            self.assertEqual(result["executor"], "blocked")
            turn.assert_not_called()
        with patch("project_os_bridge.codex_provider.require_checkout", return_value=self.before), \
             patch("project_os_bridge.codex_provider.shutil.which", return_value="/fixture/codex"), \
             patch("project_os_bridge.codex_provider.probe_capacity", return_value=("available", True)), \
             patch("project_os_bridge.codex_provider.execute_turn", return_value={
                 "started": True, "exit_code": 125, "cleanup_verified": False}), \
             patch("project_os_bridge.codex_provider.checkout_state", return_value=self.before), \
             patch("project_os_bridge.codex_provider.git"):
            result = run_codex(Path("/fixture"), {"PATH": "/fixture"}, self.request, enabled=lambda: True)
            self.assertEqual(result["executor"], "codex")
            self.assertFalse(result["cleanup_verified"])

    def test_fallback_revalidates_checkout_and_revocation(self):
        for changed, live, reason in ((True, True, "CODEX_CHECKOUT_CHANGED"),
                                      (False, False, "CODEX_AUTHORIZATION_REVOKED")):
            with self.subTest(changed=changed, live=live), \
                 patch("project_os_bridge.codex_provider.require_checkout",
                       side_effect=[self.before, ValueError("changed") if changed else self.before]), \
                 patch("project_os_bridge.codex_provider.shutil.which", return_value="/fixture/codex"), \
                 patch("project_os_bridge.codex_provider.probe_capacity", return_value=("exhausted", True)), \
                 patch("project_os_bridge.codex_provider.execute_turn") as turn:
                result = run_codex(Path("/fixture"), {"PATH": "/fixture"}, self.request, enabled=lambda: live)
                self.assertEqual(result["executor"], "blocked")
                self.assertEqual(result["reason"], reason)
                turn.assert_not_called()

    def test_dirty_checkout_and_explicit_branch_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", "-C", directory, *args], stderr=subprocess.DEVNULL).decode().strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("checkout", "-qb", "work/entry")
            (root / "tracked").write_text("base\n")
            git("add", "tracked")
            git("commit", "-qm", "base")
            sha = git("rev-parse", "HEAD")
            (root / "tracked").write_text("staged\n")
            git("add", "tracked")
            (root / "tracked").write_text("unstaged\n")
            (root / "untracked").write_text("preserve\n")
            before = require_checkout(root, sha, "work/entry")
            self.assertTrue(before["dirty"])
            with self.assertRaises(ValueError):
                require_checkout(root, sha, "work/other")
            task = {**self.task, "branch": "work/entry", "target_branch": "work/authorized"}
            request = {**self.request, "expected_sha": sha, "codex_task": task}
            def execute(*args):
                git("switch", "-c", "work/authorized")
                return {"started": True, "exit_code": 0, "cleanup_verified": True}
            with patch("project_os_bridge.codex_provider.shutil.which", return_value="codex"), \
                 patch("project_os_bridge.codex_provider.probe_capacity", return_value=("available", True)), \
                 patch("project_os_bridge.codex_provider.execute_turn", side_effect=execute):
                result = run_codex(root, {"PATH": "/bin"}, request, enabled=lambda: True)
            self.assertTrue(result["cleanup_verified"])
            self.assertEqual(result["before"], before)
            self.assertEqual(result["after"]["branch"], "work/authorized")
            self.assertEqual(result["after"]["staged_diff_sha256"], before["staged_diff_sha256"])
            self.assertEqual((root / "untracked").read_text(), "preserve\n")
            with patch("project_os_bridge.codex_provider.shutil.which", return_value="codex"), \
                 patch("project_os_bridge.codex_provider.probe_capacity", return_value=("available", True)), \
                 patch("project_os_bridge.codex_provider.execute_turn", return_value={"started": True, "exit_code": 0, "cleanup_verified": True}):
                wrong = run_codex(root, {"PATH": "/bin"}, {**request, "codex_task": {**task, "branch": "work/authorized", "target_branch": "work/other"}}, enabled=lambda: True)
            self.assertFalse(wrong["cleanup_verified"])
            self.assertEqual(wrong["reason"], "CODEX_CHECKOUT_UNCERTAIN")

    def test_catalog_allowlist_and_selection(self):
        responses = [{}, {"ordinaryUsageAllowed": True, "accountId": "private",
            "rateLimits": {"primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": 123}, "planType": "private"}},
            {"data": [{"model": "model-a", "hidden": False, "isDefault": True,
                       "supportedReasoningEfforts": [{"reasoningEffort": "high", "description": "private"}]}], "nextCursor": None}]
        class Child:
            def __init__(self, *args): pass
            def send(self, value): pass
            def response(self, *args): return responses.pop(0)
            def stop(self): return True
        with patch("project_os_bridge.codex_provider._Child", Child):
            result, clean = provider_catalog("codex", "/fixture", {}, lambda: True)
        self.assertTrue(clean)
        self.assertEqual(result, {"capacity": "available", "windows": {"primary": {
            "used_percent": 25, "window_minutes": 300, "resets_at": 123}},
            "models": [{"model": "model-a", "reasoning_efforts": ["high"], "default": True}], "model_windows": None})
        self.assertTrue(selection_valid({"model": "model-a", "reasoning_effort": "high"}, result["models"]))
        self.assertFalse(selection_valid({"reasoning_effort": "high"}, result["models"]))
        self.assertFalse(selection_valid({"model": "other"}, result["models"]))
        self.assertFalse(selection_valid({"model": "model-a", "reasoning_effort": "low"}, result["models"]))
        self.assertFalse(selection_valid({"model": "model-a"}, None))
        with self.assertRaises(ValueError):
            validate_task({**self.task, "model": "--bad"})

    def test_invalid_selection_never_dispatches(self):
        task = {**self.task, "model": "not-authorized"}
        with patch("project_os_bridge.codex_provider.require_checkout", return_value=self.before), \
             patch("project_os_bridge.codex_provider.shutil.which", return_value="codex"), \
             patch("project_os_bridge.codex_provider.probe_capacity", return_value=("available", True)), \
             patch("project_os_bridge.codex_provider.provider_catalog", return_value=({"models": [], "capacity": "available"}, True)), \
             patch("project_os_bridge.codex_provider.execute_turn") as turn:
            result = run_codex(Path("/fixture"), {"PATH": "/fixture"}, {**self.request, "codex_task": task}, enabled=lambda: True)
            self.assertEqual(result["reason"], "CODEX_SELECTION_UNAVAILABLE")
            turn.assert_not_called()

    def test_message_sanitization(self):
        self.assertEqual(_summary("Updated the contract; tests passed."), "Updated the contract; tests passed.")
        for value in ("Bearer synthetic-value", "/home/operator/private", "x" * 4097):
            self.assertEqual(_summary(value), "[OMITTED: PRIVATE_OR_UNBOUNDED]")
