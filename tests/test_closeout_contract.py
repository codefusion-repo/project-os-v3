"""Document regressions; these do not execute a browser agent.

Manual protocol (not executed): in an explicitly authorized isolated test repo,
record adapter version, inputs, calls, permissions, HEAD and remote state before
and after each scenario. Test absent/ambiguous GO and explicit GO; connector
present/absent or denied; changed HEAD and concurrent change; draft; already
merged; timeouts before/after merge or comment; existing/missing comment; and
fallback plus local cleanup. Verify no unauthorized mutation, atomic HEAD guard,
no duplicate entries, safe commands and confirmed outcomes. Use a controlled
connector double for ambiguous failures and never record secrets. Record each
result and evidence separately; without an isolated environment mark untested.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BrowserCloseoutContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Count exactly the complete UTF-8 decoded file intended for pasting.
        cls.adapter = (ROOT / 'adapters/browser-chat.md').read_text(encoding='utf-8')

    def test_complete_paste_artifact_has_headroom(self):
        self.assertLessEqual(len(self.adapter), 7500,
                             f'Complete adapter: {len(self.adapter)} Unicode code points')

    def test_closeout_retains_core_safety_in_paste_artifact(self):
        closeout = self.adapter.split('## Closeout de un PR', 1)[1].split('## Instrucciones', 1)[0]
        for phrase in ('GO explícito', 'HEAD completo', 'checks', 'permisos',
                       'expected_head_sha', '--match-head-commit', 'fallo ambiguo',
                       'issue separado', 'Sin GO, ninguna mutación'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, closeout)

    def test_branch_cleanup_safe_command_is_distinct_from_prohibition(self):
        # Do not case-fold: git branch -D is force deletion, not git branch -d.
        prohibition = self.adapter.split('No uses `git reset --hard`', 1)[1].split('por defecto.', 1)[0]
        self.assertIn('`git branch -D`', prohibition)
        instruction = self.adapter.split('Si corresponde y la rama local está integrada, usa ', 1)[1].split(' tras las comprobaciones', 1)[0]
        self.assertEqual(instruction, '`git branch -d <rama>`')
        self.assertNotRegex(instruction, r'git branch\s+-D\b')
        self.assertIn('si falla, detente y conserva la rama', self.adapter)

    def test_close_and_review_route_to_adapter(self):
        for name in ('close', 'review'):
            self.assertIn('../adapters/browser-chat.md',
                          (ROOT / 'workflows' / f'{name}.md').read_text())


if __name__ == '__main__':
    unittest.main()
