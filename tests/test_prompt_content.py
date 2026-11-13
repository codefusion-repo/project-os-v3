import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_review_fixes import fixture
from test_select import outputs, selector


class PromptContent(unittest.TestCase):
    def test_cli_keeps_request_and_version_without_copying_the_kit(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            kit, project, old, _ = fixture(base)
            folder = base / 'out'
            args = [sys.executable, str(kit / 'tools/select.py'), '--project', str(project),
                    '--workflow', 'review', '--skill', 'testing', '--skill', 'code-review',
                    '--locator', 'https://github.com/org/main/pull/42',
                    '--objective', 'Reporte uno\n\nReporte dos',
                    '--feedback', 'Comentario uno\n\nComentario dos', '--question', 'Pregunta uno\nPregunta dos',
                    '--output-dir', str(folder)]
            result = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = outputs(folder)[0].read_text()
            self.assertIn('**Versión de Project OS:** ' + old, text)
            self.assertIn('**Workflow:** review', text)
            self.assertIn('**Skills:** repo-context, github-traceability, testing, code-review', text)
            self.assertIn('**Referencia:** https://github.com/org/main/pull/42', text)
            self.assertIn('Reporte uno\n\nReporte dos', text)
            self.assertIn('## Comentario del PM — PM_FEEDBACK_HUMANO\n\nComentario uno\n\nComentario dos\n\n##', text)
            self.assertIn('## Pregunta del PM — PM_QUESTION_HUMANO\n\nPregunta uno\nPregunta dos\n\n##', text)
            self.assertNotIn('# Skill: repo-context', text)
            self.assertNotIn('## Trazabilidad GitHub obligatoria', text)
            self.assertNotIn('# Comentario de ejecución', text)
            self.assertIn('skills/repo-context/SKILL.md', text)
            self.assertIn('workflows/review.md', text)
            self.assertIn('lee su AGENTS.md', text)
            self.assertIn('verifica la referencia', text)
            self.assertIn('informa el límite sin inventar', text)
            self.assertIn('Documentos locales distintos de la referencia:** PROJECT_OS.md', text)
            self.assertNotIn('Cambio local para prueba.', text)

    def test_wizard_has_no_format_switch_and_preserves_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, project, old, _ = fixture(Path(temp))
            dest = Path(temp) / 'out'
            entries = ['review', 'testing', 'Solicitud', '#42', 'Nota', 'Pregunta', 'g', 's']
            result = subprocess.run([sys.executable, str(kit / 'tools/select.py'), '--project', str(project),
                                     '--output-dir', str(dest)], input='\n'.join(entries) + '\n',
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('/autocontenido', result.stdout)
            self.assertNotIn('/compacto', result.stdout)
            self.assertNotIn('[F]ormato', result.stdout)
            text = outputs(dest)[0].read_text()
            self.assertIn('**Versión de Project OS:** ' + old, text)
            self.assertIn('Solicitud', text)
            self.assertIn('Nota', text)
            self.assertIn('Pregunta', text)
            self.assertNotIn('# Skill: repo-context', text)
            help_result = subprocess.run([sys.executable, str(kit / 'tools/select.py'), '--help'], text=True, capture_output=True)
            self.assertNotIn('--self-contained', help_result.stdout)
            unsupported = subprocess.run([sys.executable, str(kit / 'tools/select.py'), '--self-contained'], text=True, capture_output=True)
            self.assertNotEqual(unsupported.returncode, 0)

    def test_prompt_works_offline_and_rejects_sensitive_input(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, project, _, _ = fixture(Path(temp))
            with patch.object(selector, 'ROOT', kit), patch.object(selector.project_local.urllib.request, 'build_opener', side_effect=AssertionError('unexpected network')):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(selector.main(['--project', str(project), '--workflow', 'review']), 0)
                    token = 'ghp_' + 'K' * 36
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        self.assertNotEqual(selector.main(['--project', str(project), '--workflow', 'review', '--feedback', token]), 0)
                    self.assertNotIn(token, err.getvalue())


if __name__ == '__main__':
    unittest.main()
