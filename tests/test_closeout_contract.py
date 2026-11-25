"""Document regressions; these do not execute a browser agent.

Text assertions are narrow documentation tripwires, not semantic or behavioral
proof. Keep stable command tokens and links exact; avoid depending on prose
punctuation or paragraph boundaries. Review semantic changes against the manual
protocol, including review-only code mutation, checkpoint autonomy and resume
controls that preserve the requested operation and authorize a newly selected operation.

Manual protocol (not executed): in an explicitly authorized isolated test repo,
record adapter version, inputs, calls, permissions, HEAD and remote state before
and after each scenario. Test a direct review_for_close request and a clicked operation button; connector
present/absent or denied; changed HEAD and concurrent change; draft; already
merged; timeouts before/after merge or comment; existing/missing comment; and
fallback plus local cleanup. Verify no unauthorized mutation, atomic HEAD guard,
no duplicate entries, safe commands and confirmed outcomes. Use a controlled
connector double for ambiguous failures and never record secrets. Record each
result and evidence separately; without an isolated environment mark untested.
Also exercise a requested close on an identified issue, an already-closed issue,
a read-only request, missing identification and unavailable close capability.
For a requested review_for_close operation, verify both
branches: PASS -> ready, guarded merge, integration checks and completed issue
in one operation; BLOCKED -> publish findings with SHA and evidence, no merge.
Neither branch may request a second authorization or require a human GO.
With CI pending, continue safe validation without approval prompts. Interrupt and
resume in a fresh chat from the repository, issue/PR and authorization source;
verify the generated prompt preserves scope and exclusions, adds no restrictions
and does not request renewal. Contrast explicit no-closeout, read-only, absent,
revoked or out-of-scope requests; PASS in those cases cannot imply merge.
Review intent permits its technical comment unless read-only; failed CI,
findings or changed HEAD yield BLOCKED. For missing connector
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
        for phrase in ('HEAD completo', 'checks', 'permisos', 'fallo ambiguo',
                       'issue vinculado y estado', 'closed/completed',
                       'Si ya está cerrado no repitas', 'BLOCKED',
                       'exclusión explícita', 'ancestry'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.shared)
        for phrase in ('expected_head_sha', '--match-head-commit', 'ancestry'):
            self.assertIn(phrase, self.adapter)

    def test_requested_operation_authorizes_full_outcome(self):
        for phrase in ('La solicitud del PM autoriza la operación que solicita',
                       'al pulsar un botón', 'sin pedir autorización, confirmación ni GO adicional',
                       'restricciones explícitas prevalecen', 'No amplíes la operación',
                       'incluso NO GO', 'salvo solo lectura'):
            self.assertIn(phrase, self.shared)
        self.assertNotIn('autorización por intención', self.shared)
        self.assertNotIn('PASS / CLOSEOUT PENDIENTE DE AUTORIZACIÓN', self.shared)

    def test_review_for_close_resolves_both_branches(self):
        for phrase in ('GO / PASS → closeout automático',
                       'NO GO / BLOCKED → publicación automática de review',
                       'No requiere otro GO', 'PASS / REVIEW SIN CIERRE',
                       'una consulta de solo lectura no publica'):
            self.assertIn(phrase, self.shared)
        workflow = (ROOT / 'workflows/review_for_close.md').read_text(encoding='utf-8')
        self.assertIn('../PROJECT_OS.md#implementación-testing-y-review', workflow)
        self.assertIn('la solicitud del workflow autoriza sus dos ramas', workflow)
        self.assertIn('Con PASS ejecuta en la misma operación el closeout', workflow)
        self.assertNotIn('CLOSEOUT PENDIENTE DE AUTORIZACIÓN', workflow)

    def test_same_agent_and_review_only_scope(self):
        self.assertIn('El mismo agente que implementó puede ejecutar', self.shared)
        self.assertIn('No exijas otro agente, modelo, sesión, review adicional', self.shared)
        self.assertIn('Corrige código solo cuando la operación comprende implementación o corrección', self.shared)
        self.assertIn('BLOCKED: informa la corrección requerida', self.shared)

    def test_checkpoint_is_not_an_approval_gate(self):
        for phrase in ('La unidad de ejecución es el outcome autorizado',
                       'Los checkpoints internos no son gates de aprobación',
                       'bloqueo material no resoluble', 'límite técnico efectivo',
                       'una interrupción no equivale a finalización'):
            self.assertIn(phrase, self.shared)

    def test_resume_and_next_operation_controls(self):
        for phrase in ('La reanudación continúa la operación vigente',
                       'No detengas checkpoints internos',
                       'Sin controles interactivos',
                       'pulsar un botón de siguiente operación solicita y autoriza esa operación completa',
                       'sin introducir nuevas barreras ni restricciones inventadas',
                       'no pidas renovar permisos vigentes'):
            self.assertIn(phrase, self.shared)
        for phrase in ('botón de continuación', 'botón de siguiente operación recomendada',
                       'Si no hay botones', 'No esperes clics en checkpoints internos',
                       'sin inventar exclusiones ni solicitar renovación',
                       'al pulsarlo, el PM solicita y autoriza la operación indicada'):
            self.assertIn(phrase, self.adapter)

    def test_handoff_and_continue_preserve_authorization_source(self):
        handoff = (ROOT / 'templates/handoff.md').read_text(encoding='utf-8')
        continuation = (ROOT / 'workflows/continue.md').read_text(encoding='utf-8')
        self.assertIn('fuente_verificable_alcance_exclusiones_estado', handoff)
        self.assertIn('../PROJECT_OS.md#respuesta-y-continuidad', handoff)
        self.assertIn('fuente de autorización vigente verificable', continuation)
        self.assertIn('política de automatización aplicable', continuation)
        self.assertIn('ni transformar la reanudación en una renovación de permisos', continuation)

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
