import tempfile
import unittest
from pathlib import Path
from project_os_bridge.core import Policy
from project_os_bridge.git_fixture import GitFixture

PATCH="diff --git a/fixture.txt b/fixture.txt\n--- a/fixture.txt\n+++ b/fixture.txt\n@@ -1 +1 @@\n-before\n+after\n"


class GitFixtureTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.git=GitFixture(self.root,Policy(("local",op,"disposable") for op in ("git_prepare","git_read","git_patch")))
        self.head=self.git.initialize("local")
        self.before=self.git.prepare("local",self.head)

    def test_real_worktree_and_patch(self):
        after=self.git.apply_patch("local",self.head,self.before["revision"],PATCH)
        self.assertEqual(after["text"],"after\n")
        self.assertIn("+after",self.git.diff("local")["diff"])
        self.assertEqual((self.root/"repo"/"fixture.txt").read_text(),"before\n")
        with self.assertRaises(ValueError):
            self.git.apply_patch("local",self.head,self.before["revision"],PATCH)

    def test_denied_and_invalid_paths(self):
        with self.assertRaises(PermissionError):
            self.git.apply_patch("other",self.head,self.before["revision"],PATCH)
        with self.assertRaises(ValueError):
            self.git.apply_patch("local",self.head,self.before["revision"],PATCH.replace("fixture.txt","../other"))
        self.assertEqual(self.git.snapshot("local"),self.before)

    def test_existing_worktree_not_reused(self):
        with self.assertRaises(FileExistsError):
            self.git.prepare("local",self.head)
        with self.assertRaises(FileExistsError):
            self.git.initialize("local")

    def test_unstaged_change_denied(self):
        (self.root/"worktree"/"fixture.txt").write_text("other")
        with self.assertRaises(ValueError):
            self.git.snapshot("local")

    def test_wrong_sha_denied(self):
        with self.assertRaises(ValueError):
            self.git.prepare("local","0"*40)
