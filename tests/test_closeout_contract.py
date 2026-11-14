"""Regression checks for the documented browser closeout contract."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BrowserCloseoutContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        adapter = (ROOT / 'adapters/browser-chat.md').read_text().lower()
        cls.closeout = adapter.split('## closeout de un pr', 1)[1].split('## instrucciones', 1)[0]

    def test_authorization_and_separate_issue(self):
        for phrase in ('go explícito', 'pr concreto', 'comentario de terceros',
                       'issue separado', 'autorice expresamente', 'si falta el go'):
            self.assertIn(phrase, self.closeout)

    def test_live_checks_draft_and_concurrent_head(self):
        for phrase in ('checks', 'findings', 'permisos', 'reglas aplicables',
                       'marca ready si es draft', 'sha realmente revisado',
                       'expected_head_sha', '--match-head-commit', 'no hagas bypass'):
            self.assertIn(phrase, self.closeout)

    def test_idempotency_and_ambiguous_failures(self):
        for phrase in ('ya está merged', 'sin repetir merge ni comentario',
                       'fallo ambiguo', 'identificador', 'nunca reintentes',
                       'no edites historia'):
            self.assertIn(phrase, self.closeout)

    def test_fallback_and_local_safety(self):
        for phrase in ('falta conector, permiso o capacidad', 'solo un bloque de comandos',
                       'sha completo revisado', 'git status', 'git worktree list',
                       'reset --hard', 'clean -fdx', 'branch -d', 'autorización separada'):
            self.assertIn(phrase, self.closeout)

    def test_close_and_review_route_to_adapter(self):
        for name in ('close', 'review'):
            self.assertIn('../adapters/browser-chat.md',
                          (ROOT / 'workflows' / f'{name}.md').read_text())


if __name__ == '__main__':
    unittest.main()
