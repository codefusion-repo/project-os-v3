import subprocess
import tempfile
import unittest
from pathlib import Path

from project_os_bridge.methodology import CANONICAL, build_context


class MethodologyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.kit = self.root / "kit"
        self.project = self.root / "project"
        self.init(self.kit, CANONICAL)
        self.init(self.project, "example/demo")
        documents = {"AGENTS.md": "kit agents\n", "PROJECT_OS.md": "base methodology\n",
                     "workflows/implement.md": "implementation\n",
                     "skills/repo-context/SKILL.md": "context\n",
                     "skills/github-traceability/SKILL.md": "traceability\n",
                     "skills/testing/SKILL.md": "tests\n",
                     "templates/comment.md": "comment\n",
                     "adapters/browser-chat.md": "browser\n",
                     "docs/PRODUCT.md": "product\n", "local-bridge/MVP.md": "contract\n"}
        for path, content in documents.items():
            target = self.kit / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.base = self.commit(self.kit)
        (self.kit / "PROJECT_OS.md").write_text("new methodology\n")
        self.installed = self.commit(self.kit)
        (self.project / "AGENTS.md").write_text(
            "Canonical codefusion-repo/project-os-v3\nProject-OS-Version: " + self.base + "\n")
        self.commit(self.project)

    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()

    def init(self, path, repo):
        path.mkdir()
        self.git(path, "init", "-q")
        self.git(path, "config", "user.name", "Fixture")
        self.git(path, "config", "user.email", "fixture@example.invalid")
        self.git(path, "remote", "add", "origin", "https://github.com/" + repo + ".git")

    def commit(self, root):
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "fixture")
        return self.git(root, "rev-parse", "HEAD")

    def test_pinned_selection_exact_git_documents_and_dedup(self):
        (self.kit / "PROJECT_OS.md").write_text("uncommitted content\n")
        result = build_context(self.kit, self.installed, self.project, "example/demo",
                               "implement", ["testing", "repo-context", "testing"], ["comment", "comment"])
        self.assertEqual(result["methodology_revision"], self.base)
        docs = {doc["path"]: doc for doc in result["documents"]}
        self.assertEqual(len(docs), len(result["documents"]))
        self.assertEqual(docs["PROJECT_OS.md"]["content"], "base methodology\n")
        self.assertEqual(docs["PROJECT_OS.md"]["blob_sha"],
                         self.git(self.kit, "rev-parse", self.base + ":PROJECT_OS.md"))
        self.assertIn("skills/github-traceability/SKILL.md", docs)
        self.assertIn("skills/testing/SKILL.md", docs)
        self.assertIn("templates/comment.md", docs)
        self.assertIn("adapters/browser-chat.md", docs)
        self.assertEqual(docs["AGENTS.md"]["repository"], "example/demo")

    def test_kit_uses_installed_base_and_rejects_unknown_or_unsafe_selection(self):
        result = build_context(self.kit, self.installed, self.project, CANONICAL, "implement", [], [])
        self.assertEqual(result["methodology_revision"], self.installed)
        self.assertIn("docs/PRODUCT.md", {doc["path"] for doc in result["documents"]})
        with self.assertRaises(ValueError):
            build_context(self.kit, self.installed, self.project, CANONICAL, "implement", [], [],
                          expected_revision=self.base)
        for workflow, skills in [("../AGENTS", []), ("implement", ["../secret"]), ("missing", [])]:
            with self.assertRaises(ValueError):
                build_context(self.kit, self.installed, self.project, CANONICAL, workflow, skills, [])

    def test_uninstalled_pin_fails_without_fallback(self):
        (self.kit / "PROJECT_OS.md").write_text("candidate\n")
        candidate = self.commit(self.kit)
        (self.project / "AGENTS.md").write_text(
            "Canonical codefusion-repo/project-os-v3\nProject-OS-Version: " + candidate + "\n")
        self.commit(self.project)
        with self.assertRaises(ValueError):
            build_context(self.kit, self.installed, self.project, "example/demo", "implement", [], [])
