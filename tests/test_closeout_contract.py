"""Document regressions; these do not execute a browser agent.

Text assertions are narrow documentation tripwires, not semantic or behavioral
proof. Keep stable command tokens and links exact; avoid depending on prose
punctuation or paragraph boundaries. Review semantic changes against the manual
protocol, including review-only code mutation, checkpoint autonomy and resume
controls that do not grant authorization.

Manual protocol (not executed): in an explicitly authorized isolated test repo,
record adapter version, inputs, calls, permissions, HEAD and remote state before
and after each scenario. Test absent/ambiguous GO and explicit GO; connector
present/absent or denied; changed HEAD and concurrent change; draft; already
merged; timeouts before/after merge or comment; existing/missing comment; and
fallback plus local cleanup. Verify no unauthorized mutation, atomic HEAD guard,
no duplicate entries, safe commands and confirmed outcomes. Use a controlled
connector double for ambiguous failures and never record secrets. Record each
result and evidence separately; without an isolated environment mark untested.
Also exercise an identified issue with explicit close GO, already-closed issue,
open issue without GO, missing identification and unavailable close capability.
For one scoped authorization verify review, ready, guarded merge and completed
issue happen in one operation, without a second prompt. Verify PASS alone has no
closeout mutation; review intent permits its technical comment unless read-only; failed CI, findings or changed HEAD yield BLOCKED. For missing connector
inspect guarded fallback; for already merged/closed and ambiguous timeouts verify
no duplicated action. Check cleanup ancestry and preservation of unrelated data.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BrowserCloseoutContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = (ROOT / 'PROJECT_OS.md').read_text(encoding='utf-8')
        # Count exactly the complete UTF-8 decoded file intended for pasting.
        cls.adapter = (ROOT / 'adapters/browser-chat.md').read_text(encoding='utf-8')

    def test_complete_paste_artifact_has_headroom(self):
        self.assertLessEqual(len(self.adapter), 7500,
                             f'Complete adapter: {len(self.adapter)} Unicode code points')

    def test_pasted_adapter_requires_verified_methodology(self):
        for phrase in ('lee AGENTS.md', 'recupera y verifica PROJECT_OS.md',
                       'antes de cualquier mutación', 'detén toda mutación'):
            self.assertIn(phrase, self.adapter)
        self.assertIn('../PROJECT_OS.md#implementación-testing-y-review', self.adapter)
        self.assertIn('../PROJECT_OS.md#seguridad-transversal-y-límites', self.adapter)

    def test_closeout_retains_core_safety_in_central_policy(self):
        for phrase in ('autorización explícita', 'HEAD completo', 'checks', 'permisos',
                       'fallo ambiguo', 'issue vinculado y estado',
                       'ninguna mutación no concedida', 'closed/completed',
                       'Si ya está cerrado no repitas', 'sin otra confirmación',
                       'PASS / CLOSEOUT PENDIENTE DE AUTORIZACIÓN', 'BLOCKED',
                       'previa verificable o dada en esta solicitud', 'ancestry'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.shared)
        for phrase in ('expected_head_sha', '--match-head-commit', 'ancestry'):
            self.assertIn(phrase, self.adapter)

    def test_intent_authorization(self):
        for phrase in ('autorización por intención', 'acciones inherentes',
                       'restricciones explícitas prevalecen', 'sin confirmaciones redundantes',
                       'incluso NO GO', 'salvo solo lectura', 'Continuar hereda',
                       'Un PASS no concede autorización de closeout'):
            self.assertIn(phrase, self.shared)

    def test_review_does_not_authorize_code_changes(self):
        self.assertIn('La intención de review por sí sola no autoriza modificar código', self.shared)
        self.assertIn('solo si la intención autorizada comprende implementación o corrección', self.shared)
        self.assertIn('BLOCKED: informa la corrección requerida', self.shared)

    def test_checkpoint_is_not_an_approval_gate(self):
        for phrase in ('La unidad de ejecución es el outcome autorizado',
                       'Los checkpoints internos no son gates de aprobación',
                       'bloqueo material no resoluble', 'límite técnico efectivo',
                       'una interrupción no equivale a finalización'):
            self.assertIn(phrase, self.shared)

    def test_resume_control_is_not_authorization(self):
        for phrase in ('La reanudación no constituye nueva autorización',
                       'No detengas checkpoints internos',
                       'Sin controles interactivos'):
            self.assertIn(phrase, self.shared)
        for phrase in ('botón de continuación', 'botón de siguiente operación recomendada',
                       'Si no hay botones', 'No esperes clics en checkpoints internos'):
            self.assertIn(phrase, self.adapter)

    def test_branch_cleanup_safe_command_is_distinct_from_prohibition(self):
        # Do not case-fold: git branch -D is force deletion, not git branch -d.
        self.assertRegex(self.shared, r'No uses[^\n]*`git branch -D`')
        self.assertIn('`git branch -d <rama>`', self.adapter)
        self.assertNotRegex(self.adapter, r'git branch\s+-D\b')
        self.assertIn('si falla, detente y conserva la rama', self.adapter)

    def test_close_and_review_route_to_adapter(self):
        for name in ('review_for_close',):
            self.assertIn('../adapters/browser-chat.md',
                          (ROOT / 'workflows' / f'{name}.md').read_text())


if __name__ == '__main__':
    unittest.main()
