import importlib.util
import json
import os
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'select.py'
spec = importlib.util.spec_from_file_location('selector', SCRIPT)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def copy_install(target):
    target = Path(target)
    (target / 'tools').mkdir(parents=True)
    shutil.copy2(SCRIPT, target / 'tools' / 'select.py')
    shutil.copy2(ROOT / 'PROJECT_OS.md', target / 'PROJECT_OS.md')
    for directory in ('workflows', 'skills', 'templates'):
        shutil.copytree(ROOT / directory, target / directory)
    return target


def run(output_dir, *args, input_text=None, install=None):
    def execute(script):
        return subprocess.run([sys.executable, str(script), '--output-dir', str(output_dir), *args],
                              input=input_text, text=True, capture_output=True, cwd=ROOT)
    if install:
        return execute(Path(install) / 'tools' / 'select.py')
    if input_text is not None:
        with tempfile.TemporaryDirectory() as tmp:
            return execute(copy_install(tmp) / 'tools' / 'select.py')
    return execute(SCRIPT)


def generated(folder):
    return sorted(Path(folder).glob('project-os-prompt-*.md'))


class SelectorCLI(unittest.TestCase):
    def test_noninteractive_prompt_persists_context_and_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'prompts'
            result = run(dest, '--workflow', 'review', '--skill', 'code-review', '--skill', 'testing',
                         '--locator', 'https://github.com/a/b/pull/12',
                         '--objective', 'Revisar el filtro del repo ejemplo; no hacer merge.')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Vista previa', result.stdout)
            self.assertIn('Prompt guardado:', result.stdout)
            files = generated(dest)
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            for value in (selector.MARKER, '**Workflow:** review', 'code-review, testing',
                          'Revisar el filtro', 'https://github.com/a/b/pull/12',
                          'Reglas compartidas', 'Workflow seleccionado', 'Skill seleccionada',
                          '# Comentario de review', 'no conceden permisos'):
                self.assertIn(value, text)
            self.assertIn(str(files[0]), result.stdout)
            self.assertLess(result.stdout.index('Vista previa'), result.stdout.index('Prompt guardado:'))

    def test_base_skill_is_automatic_for_every_workflow_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            for workflow in selector.WORKFLOW_ORDER:
                with self.subTest(workflow=workflow):
                    result = run(dest, '--workflow', workflow, '--skill', 'testing',
                                 '--skill', 'github-traceability', '--skill', 'github-traceability', '--skill', 'repo-context')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    text = generated(dest)[0].read_text()
                    self.assertIn('**Skills:** repo-context, github-traceability, testing', text)
                    self.assertEqual(text.count('# Skill: github-traceability'), 1)
                    self.assertEqual(text.count('# Skill: repo-context'), 1)
                    self.assertIn('# Skill: testing', text)
                    self.assertIn('trazabilidad pendiente', text)
            result = run(dest, '--workflow', 'implement')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('**Skills:** repo-context, github-traceability', generated(dest)[0].read_text())

    def test_interactive_base_skill_is_not_a_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, input_text='owner/repo\nimplement\n-\nContexto\n\n\n\ng\n\ns\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            menu = result.stdout.split('--- Vista previa del prompt ---')[0]
            self.assertIn('Skills base automáticas: repo-context', menu)
            self.assertNotRegex(menu, r'\d+\. (github-traceability|repo-context)')
            text = generated(tmp)[0].read_text()
            self.assertIn('**Skills:** repo-context, github-traceability', text)
            self.assertEqual(text.count('# Skill: github-traceability'), 1)

    def test_prototype_and_multiple_additional_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, '--prototype', '--skill', 'testing', '--skill', 'security-review',
                         '--skill', 'rapid-prototype', '--skill', 'repo-context')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = generated(tmp)[0].read_text()
            self.assertIn('**Workflow:** implement', text)
            self.assertIn('**Skills:** repo-context, github-traceability, rapid-prototype, testing, security-review', text)
            for name in ('repo-context', 'github-traceability', 'rapid-prototype', 'testing', 'security-review'):
                self.assertEqual(text.count('# Skill: ' + name + '\n'), 1)

    def test_review_displays_only_relevant_skills_with_optional_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, input_text='org/repo\nreview\n\n\n\n\n\nc\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            menu = result.stdout.split('Skills sugeridas (opcionales):', 1)[1].split('Skills [Enter:', 1)[0]
            for skill in ('code-review', 'security-review', 'testing'):
                self.assertIn(skill, menu)
            self.assertNotIn('implement-change', menu)
            result = run(tmp, input_text='org/repo\nreview\n/todas\nimplement-change\n\n\n\n\nc\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('**Skills:** repo-context, github-traceability, implement-change', result.stdout)

    def test_interactive_multiple_specialized_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, input_text='owner/repo\nimplement\ndebug,testing,security-review\nCorregir repo\n\n\n\ng\n\ns\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = generated(tmp)[0].read_text()
            self.assertIn('**Skills:** repo-context, github-traceability, debug, testing, security-review', text)
            for name in ('repo-context', 'github-traceability', 'debug', 'testing', 'security-review'):
                self.assertEqual(text.count('# Skill: ' + name + '\n'), 1)

    def test_local_prototype_does_not_call_git_or_github(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            sentinel = root / 'invoked'
            for name in ('gh', 'git'):
                executable = bin_dir / name
                executable.write_text('#!/bin/sh\nprintf invoked > "$PROJECT_OS_TEST_SENTINEL"\n')
                executable.chmod(0o755)
            env = dict(os.environ, PATH=str(bin_dir), PROJECT_OS_TEST_SENTINEL=str(sentinel))
            result = subprocess.run([sys.executable, str(SCRIPT), '--output-dir', str(root / 'prompts'),
                                     '--prototype', '--skill', 'testing', '--objective',
                                     'Experimento local y descartable sin repositorio'],
                                    env=env, text=True, capture_output=True, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(sentinel.exists())
            text = generated(root / 'prompts')[0].read_text()
            self.assertIn('Experimento local y descartable sin repositorio', text)
            self.assertIn('no exijas consultas GitHub ni publicación remota', text)

    def test_sensitive_cli_values_do_not_leak_or_replace_existing_prompt(self):
        secret = 'ghp_' + 'A' * 36
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / 'out'
            self.assertEqual(run(dest, '--workflow', 'continue').returncode, 0)
            previous = generated(dest)[0]
            before = previous.read_bytes()
            for option in ('--objective', '--feedback', '--question', '--repo', '--locator', '--workflow', '--skill'):
                with self.subTest(option=option):
                    result = run(dest, '--workflow', 'review', option, secret)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(secret, result.stdout + result.stderr)
                    self.assertEqual(previous.read_bytes(), before)
            result = run(root / ('secret=' + secret), '--workflow', 'review')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertEqual(previous.read_bytes(), before)
            result = run(dest, '--unrecognized=' + secret)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_sensitive_assignment_and_private_key_are_rejected(self):
        for value in ('password=not-a-real-password', 'token=synthetic-example',
                      'https://sample:synthetic@example.test/path', '-----BEGIN PRIVATE KEY-----'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                result = run(tmp, '--workflow', 'review', '--feedback', value)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(value, result.stdout + result.stderr)
                self.assertEqual(generated(tmp), [])

    def test_replacement_preserves_foreign_files_symlinks_and_other_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest, other = Path(tmp) / 'selected', Path(tmp) / 'other'
            dest.mkdir()
            other.mkdir()
            manual = dest / 'manual.md'
            manual.write_text('contenido manual')
            lookalike = dest / ('project-os-prompt-' + 'a' * 32 + '.md')
            lookalike.write_text('sin marcador')
            external = other / ('project-os-prompt-' + 'b' * 32 + '.md')
            external.write_text(selector.MARKER + '\nexterno')
            link = dest / ('project-os-prompt-' + 'c' * 32 + '.md')
            link.symlink_to(external)
            first = run(dest, '--prototype', '--objective', 'Primero')
            self.assertEqual(first.returncode, 0, first.stderr)
            old = next(p for p in generated(dest) if p not in (lookalike, link))
            second = run(dest, '--workflow', 'continue', '--objective', 'Segundo')
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn('se eliminarán los prompts anteriores', second.stdout)
            self.assertFalse(old.exists())
            self.assertEqual(manual.read_text(), 'contenido manual')
            self.assertEqual(lookalike.read_text(), 'sin marcador')
            self.assertTrue(link.is_symlink())
            self.assertEqual(external.read_text(), selector.MARKER + '\nexterno')
            current = [p for p in generated(dest) if p not in (lookalike, link)]
            self.assertEqual(len(current), 1)
            self.assertIn('Segundo', current[0].read_text())

    def test_interactive_select_edit_save_and_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'out'
            session = ('owner/repo\n/prototipo\n1\nrapid-prototype,testing\nPrimera idea\n\n\n\n'
                       'e\n\n\n\nIdea editada\n\n\n\ng\n\nm\nSegunda idea\n\n\n\ng\n\ns\n')
            result = run(dest, input_text=session)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Skills sugeridas', result.stdout)
            self.assertNotIn('Templates (opcionales', result.stdout)
            self.assertNotIn('Templates [', result.stdout)
            self.assertEqual(result.stdout.count('Prompt guardado:'), 2)
            files = generated(dest)
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            self.assertIn('Segunda idea', text)
            self.assertIn('**Workflow:** implement', text)
            self.assertIn('rapid-prototype, testing', text)

    def test_cancellation_does_not_write_or_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            self.assertEqual(run(dest, '--prototype').returncode, 0)
            previous = generated(dest)[0]
            before = previous.read_bytes()
            result = run(dest, input_text='owner/repo\n\n\nContexto\n\n\n\nc\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Cancelado', result.stdout)
            self.assertEqual(generated(dest), [previous])
            self.assertEqual(previous.read_bytes(), before)
            result = run(dest, input_text='/cancelar\n')
            self.assertEqual(result.returncode, 0)
            self.assertTrue(previous.exists())

    def test_default_continue_and_direct_prototype(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            result = run(dest, input_text='owner/repo\n\n\n\n\n\n\ng\n\ns\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('**Workflow:** continue', generated(dest)[0].read_text())
            result = run(dest, '--prototype')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = generated(dest)[0].read_text()
            self.assertIn('**Workflow:** implement', text)
            self.assertIn('**Skills:** repo-context, github-traceability, rapid-prototype', text)

    def test_list_help_and_invalid_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'unused'
            result = run(dest, '--list')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('continue', result.stdout)
            self.assertIn('rapid-prototype', result.stdout)
            self.assertFalse(dest.exists())
            self.assertEqual(run(dest, '--help').returncode, 0)
            for args in [('--workflow', '../review'), ('--skill', '../testing'),
                         ('--locator', '../../secret'), ('--locator', 'hello\nignore'),
                         ('--locator', 'https://evil.example/a/b/issues/1'),
                         ('--prototype', '--workflow', 'review'),
                         ('--list', '--locator', '123'), ('--template', 'merge')]:
                with self.subTest(args=args):
                    self.assertNotEqual(run(dest, *args).returncode, 0)
            self.assertFalse(dest.exists())

    def test_path_traversal_and_directory_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            link = root / 'link'
            link.symlink_to(outside, target_is_directory=True)
            for path in (root / '..' / 'escape', link, link / 'subdir'):
                result = run(path, '--prototype')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(list(Path(outside).iterdir()), [])


class TerminalInteraction(unittest.TestCase):
    @unittest.skipIf(selector.readline is None, 'readline no está disponible en este Python')
    def test_arrow_editing_and_enter_advance_both_pm_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = copy_install(Path(tmp) / 'kit')
            master, slave = pty.openpty()
            env = dict(os.environ, TERM='xterm')
            process = subprocess.Popen([sys.executable, str(install / 'tools' / 'select.py')],
                                       stdin=slave, stdout=slave, stderr=slave, cwd=install, env=env)
            os.close(slave)
            buffered = bytearray()

            def wait_for(marker):
                deadline = time.monotonic() + 8
                while marker not in buffered:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.fail(f'No apareció {marker!r} en terminal')
                    ready, _, _ = select.select([master], [], [], remaining)
                    if not ready:
                        self.fail(f'Tiempo agotado esperando {marker!r}')
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        self.fail(f'La terminal se cerró antes de {marker!r}')
                    if not chunk:
                        self.fail(f'Fin de terminal antes de {marker!r}')
                    buffered.extend(chunk)
                end = buffered.index(marker) + len(marker)
                result = bytes(buffered[:end])
                del buffered[:end]
                return result

            try:
                wait_for(b'Repositorio owner/repo')
                os.write(master, b'org/repo\n')
                wait_for(b'Workflow [')
                os.write(master, b'review\n')
                wait_for(b'Skills [Enter:')
                os.write(master, b'\n')
                wait_for('Reporte de ejecución o solicitud de review actual'.encode())
                os.write(master, b'\n')
                wait_for(b'Issue/PR (')
                os.write(master, b'\n')
                wait_for(b'PM_FEEDBACK_HUMANO')
                os.write(master, b'holaXY\x1b[D\x1b[D\x1b[C!\n')
                wait_for(b'PM_QUESTION_HUMANO')
                os.write(master, b'mundoX\x1b[D?\n')
                preview = wait_for(b'[G]uardar')
                self.assertIn(b'holaX!Y', preview)
                self.assertIn(b'mundo?X', preview)
                os.write(master, b'c\n')
                self.assertEqual(process.wait(timeout=8), 0)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=8)
                os.close(master)


class WizardConfiguration(unittest.TestCase):
    @staticmethod
    def invoke(install, input_text):
        return subprocess.run([sys.executable, str(Path(install) / 'tools' / 'select.py')],
                              input=input_text, text=True, capture_output=True, cwd=install)

    def test_fresh_and_existing_configuration_multiline_and_changed_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            destination = root / 'selected'
            first_input = ('repo-invalido\norg/uno\n\n/todas\ndebug,testing\n\n\n'
                           '/m\nfeedback privado línea uno\nfeedback línea dos\n.\n'
                           '/m\npregunta privada uno\npregunta dos\n.\n'
                           'g\n' + str(destination) + '\ns\n')
            first = self.invoke(install, first_input)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn('repositorio inválido', first.stdout)
            self.assertIn('Repositorio indicado; el agente deberá verificarlo', first.stdout)
            prompt = generated(destination)[0].read_text()
            self.assertIn('**Repositorio indicado (sin verificar):** org/uno', prompt)
            self.assertIn('debug, testing', prompt)
            self.assertIn('feedback privado línea uno\nfeedback línea dos', prompt)
            self.assertIn('pregunta privada uno\npregunta dos', prompt)
            config_path = install / '.project-os' / 'config.json'
            config = json.loads(config_path.read_text())
            self.assertEqual(config, {'repo': 'org/uno', 'output_dir': str(destination)})
            self.assertNotIn('privado', config_path.read_text())
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
            second = self.invoke(install, '\n\n\n\n#77\n\n\ng\n\ns\n')
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn('Repositorio owner/repo [org/uno;', second.stdout)
            self.assertIn(f'Carpeta de salida [{destination}]', second.stdout)
            prompt = generated(destination)[0].read_text()
            self.assertIn('#77', prompt)
            self.assertNotIn('feedback privado', prompt)
            self.assertNotIn('pregunta privada', prompt)
            third = self.invoke(install, 'org/dos\n\n\n\n\n\n\ng\n\ns\n')
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertEqual(json.loads(config_path.read_text())['repo'], 'org/dos')
            self.assertIn('org/dos', generated(destination)[0].read_text())

    def test_reuse_clears_pm_fields_and_back_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            destination = root / 'out'
            inputs = ('org/repo\nimplement\n/volver\nreview\ncode-review,testing\n'
                      'Contexto primero\n\ncomentario privado\npregunta privada\n'
                      'g\n' + str(destination) + '\nm\nContexto segundo\n\n\n\ng\n\ns\n')
            result = self.invoke(install, inputs)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('Prompt guardado:'), 2)
            text = generated(destination)[0].read_text()
            self.assertIn('**Workflow:** review', text)
            self.assertIn('Contexto segundo', text)
            self.assertNotIn('comentario privado', text)
            self.assertNotIn('pregunta privada', text)
            self.assertNotIn('PM_FEEDBACK_HUMANO', text)
            self.assertNotIn('PM_QUESTION_HUMANO', text)

    def test_sequential_edit_shows_values_and_preserves_exact_pm_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            dest = root / 'out'
            feedback = '  Primera línea  \nsegunda línea  '
            question = ' ¿Qué falta?  '
            inputs = ('org/repo\nreview\ncode-review\nRevisar PR #55\n#55\n/m\n' + feedback +
                      '\n.\n' + question + '\ne\n\n\n\n\n\n\n\ng\n' + str(dest) + '\ns\n')
            result = self.invoke(install, inputs)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('Editar [R]epositorio', result.stdout)
            for value in ('Workflow [review;', 'Skills adicionales actuales: code-review',
                          'Reporte de ejecución o solicitud de review actual: Revisar PR #55',
                          'Issue/PR actual: #55', 'Comentario del PM — PM_FEEDBACK_HUMANO actual:\n' + feedback,
                          'Pregunta del PM — PM_QUESTION_HUMANO actual:\n' + question):
                self.assertIn(value, result.stdout)
            text = generated(dest)[0].read_text()
            feedback_body = text.split('## Comentario del PM — PM_FEEDBACK_HUMANO\n\n', 1)[1].split('\n\n## ', 1)[0]
            question_body = text.split('## Pregunta del PM — PM_QUESTION_HUMANO\n\n', 1)[1].split('\n\n## ', 1)[0]
            self.assertEqual(feedback_body, feedback)
            self.assertEqual(question_body, question)
            self.assertIn('## Notas del sistema\n', text)

    def test_edit_can_return_to_preview_without_clearing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            dest = root / 'out'
            inputs = ('org/repo\nreview\n\nReporte\n#5\nFeedback\nPregunta\n'
                      'e\n/preview\ng\n' + str(dest) + '\ns\n')
            result = self.invoke(install, inputs)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('--- Vista previa del prompt ---'), 2)
            text = generated(dest)[0].read_text()
            for value in ('Reporte', '**Referencia:** #5', 'Feedback', 'Pregunta'):
                self.assertIn(value, text)

    def test_inconsistent_locator_warns_without_altering_pm_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            dest = root / 'out'
            inputs = ('org/repo\nreview\n\nRevisar PR #7\n#9\nNota exacta\nConsulta exacta\ng\n' + str(dest) + '\ns\n')
            result = self.invoke(install, inputs)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('Issue/PR (número'), 1)
            text = generated(dest)[0].read_text()
            self.assertIn('**Advertencia:** Posible inconsistencia', text)
            self.assertIn('## Comentario del PM — PM_FEEDBACK_HUMANO\n\nNota exacta\n\n##', text)
            self.assertIn('## Pregunta del PM — PM_QUESTION_HUMANO\n\nConsulta exacta\n\n##', text)
            self.assertFalse(selector.reference_warning('org/repo', 'https://github.com/org/repo/issues/7', 'PR #9'))
            self.assertFalse(selector.reference_warning('org/repo', '#7', 'Revisar PR #7'))
            self.assertTrue(selector.reference_warning('org/repo', '#7', 'Revisar PR #9'))

    def test_review_locator_and_partial_edit_preserve_pm_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            dest = root / 'out'
            locator = 'https://github.com/codefusion-repo/project-os-v3/pull/1'
            inputs = ('codefusion-repo/project-os-v3\nreview\ncode-review\nObjetivo inicial\n' + locator +
                      '\nComentario original\nPregunta original\ne\n\n\n\nObjetivo actualizado\n\n\nPregunta editada\ng\n' + str(dest) + '\ns\n')
            result = self.invoke(install, inputs)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = generated(dest)[0].read_text()
            self.assertIn('Objetivo actualizado', text)
            self.assertIn('**Referencia:** ' + locator, text)
            self.assertIn('Comentario original', text)
            self.assertIn('Pregunta editada', text)
            self.assertNotIn('Pregunta original', text)
            self.assertIn('**Repositorio indicado (sin verificar):** codefusion-repo/project-os-v3', text)

    def test_explicit_clear_does_not_clear_other_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            dest = root / 'out'
            inputs = ('org/repo\nreview\n\nObjetivo\n#123\nComentario\nPregunta\n'
                      'e\n\n\n\n\n\n/limpiar\n\ng\n' + str(dest) + '\ns\n')
            result = self.invoke(install, inputs)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = generated(dest)[0].read_text()
            self.assertIn('**Referencia:** #123', text)
            self.assertIn('Objetivo', text)
            self.assertIn('Pregunta', text)
            self.assertNotIn('## Comentario del PM — PM_FEEDBACK_HUMANO', text)

    def test_continue_has_one_optional_structured_locator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            dest = root / 'out'
            result = self.invoke(install, 'org/repo\ncontinue\n\n\n#77\n\n\ng\n' + str(dest) + '\ns\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('Issue/PR (número'), 1)
            self.assertIn('**Referencia:** #77', generated(dest)[0].read_text())
            result = self.invoke(install, '\ncontinue\n\n\n\n\n\nc\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('Issue/PR (número'), 1)
            self.assertIn('No proporcionada por separado', result.stdout)

    def test_sensitive_interactive_fields_are_rejected_without_leaking(self):
        secret = 'ghp_' + 'B' * 36
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            dest = root / 'out'
            inputs = ('org/repo\nreview\n\n' + secret + '\nObjetivo seguro\n\n' + secret +
                      '\nComentario seguro\n' + secret + '\nPregunta segura\ng\n' + str(dest) + '\ns\n')
            result = self.invoke(install, inputs)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreaterEqual(result.stdout.count('posible información sensible'), 3)
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertNotIn(secret, generated(dest)[0].read_text())
            self.assertNotIn(secret, (install / '.project-os' / 'config.json').read_text())

    def test_sensitive_value_spanning_multiline_can_be_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            dest = root / 'out'
            secret_part = 'z' * 24
            inputs = ('org/repo\nreview\n\nObjetivo\n\n/m\nBearer\n' + secret_part +
                      '\n.\n/limpiar\n\ng\n' + str(dest) + '\ns\n')
            result = self.invoke(install, inputs)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('posible información sensible', result.stdout)
            self.assertNotIn(secret_part, result.stdout + result.stderr)
            self.assertNotIn(secret_part, generated(dest)[0].read_text())

    def test_cancel_and_unsafe_config_do_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            result = self.invoke(install, 'org/repo\n\n\n\n\n\n\nc\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((install / '.project-os').exists())
            outside = root / 'external.json'
            outside.write_text('{"repo":"outside/repo"}')
            (install / '.project-os').mkdir()
            (install / '.project-os' / 'config.json').symlink_to(outside)
            result = self.invoke(install, '')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outside.read_text(), '{"repo":"outside/repo"}')
            self.assertTrue((install / '.project-os' / 'config.json').is_symlink())

    def test_optional_pm_fields_available_for_every_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = copy_install(Path(tmp) / 'kit')
            for workflow in selector.WORKFLOW_ORDER:
                with self.subTest(workflow=workflow):
                    locator_line = '\n' if workflow in selector.UNIT_WORKFLOWS else ''
                    result = self.invoke(install, 'org/repo\n' + workflow + '\n\n\n' + locator_line + '\n\nc\n')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('Comentario del PM — PM_FEEDBACK_HUMANO', result.stdout)
                    self.assertIn('Pregunta del PM — PM_QUESTION_HUMANO', result.stdout)
                    self.assertIn(selector.INPUT_LABELS[workflow], result.stdout)
                    self.assertFalse((install / '.project-os').exists())

    def test_cli_flags_do_not_read_or_write_wizard_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            destination = root / 'out'
            result = run(destination, '--repo', 'org/repo', '--workflow', 'review',
                         '--feedback', 'Nota uno\nNota dos', '--question', 'Consulta uno\nConsulta dos',
                         install=install)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((install / '.project-os').exists())
            text = generated(destination)[0].read_text()
            self.assertIn('org/repo', text)
            self.assertIn('Nota uno\nNota dos', text)
            self.assertIn('Consulta uno\nConsulta dos', text)

    def test_local_disposable_without_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = copy_install(root / 'kit')
            destination = root / 'out'
            result = self.invoke(install, '-\nimplement\n-\nPrototipo local y descartable\n\n\ng\n' + str(destination) + '\ns\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('**Repositorio indicado (sin verificar):** No indicado', generated(destination)[0].read_text())
            self.assertIn('experimento expresamente local y descartable, sin repositorio', generated(destination)[0].read_text())
            self.assertEqual(json.loads((install / '.project-os' / 'config.json').read_text()), {'output_dir': str(destination)})


class SafePersistence(unittest.TestCase):
    def test_failed_write_keeps_previous_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous, _ = selector.save_prompt(root, selector.MARKER + '\noriginal\n')
            for failing in ('fsync', 'link'):
                with self.subTest(failing=failing), patch.object(selector.os, failing, side_effect=OSError('fallo simulado')):
                    with self.assertRaises(OSError):
                        selector.save_prompt(root, selector.MARKER + '\nnuevo\n')
                    self.assertEqual(previous.read_text(), selector.MARKER + '\noriginal\n')
                    self.assertEqual(list(root.iterdir()), [previous])

    def test_sensitive_source_is_not_rendered_or_persisted(self):
        workflows, skills, templates = selector.discover()
        real_read = selector.read_source
        secret = 'ghp_' + 'C' * 36
        def source(path):
            return secret if path == workflows['review'] else real_read(path)
        with patch.object(selector, 'read_source', side_effect=source):
            with self.assertRaises(selector.SensitiveInput) as result:
                selector.render('review', [], '', '', workflows, skills, templates)
            self.assertNotIn(secret, str(result.exception))

    def test_config_write_failure_preserves_previous_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(selector, 'ROOT', root):
                selector.save_config('old/repo', root / 'output')
                config_path = root / '.project-os' / 'config.json'
                before = config_path.read_bytes()
                with patch.object(selector.os, 'fsync', side_effect=OSError('fallo simulado')):
                    with self.assertRaises(OSError):
                        selector.save_config('new/repo', root / 'new-output')
                self.assertEqual(config_path.read_bytes(), before)
                self.assertEqual(list((root / '.project-os').iterdir()), [config_path])

    def test_unowned_name_collision_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manual = root / ('project-os-prompt-' + 'b' * 32 + '.md')
            manual.write_text('archivo manual')
            class ID:
                def __init__(self, value): self.hex = value
            with patch.object(selector.uuid, 'uuid4', side_effect=[ID('a' * 32), ID('b' * 32)]):
                with self.assertRaises(FileExistsError):
                    selector.save_prompt(root, selector.MARKER + '\nnuevo')
            self.assertEqual(manual.read_text(), 'archivo manual')
            self.assertEqual(list(root.iterdir()), [manual])

    def test_missing_base_skill_cannot_generate_a_prompt(self):
        for missing in selector.BASE_SKILLS:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'workflows').mkdir()
                (root / 'workflows' / 'implement.md').write_text('# implement\n')
                (root / 'PROJECT_OS.md').write_text('# Reglas\n')
                available = next(name for name in selector.BASE_SKILLS if name != missing)
                (root / 'skills' / available).mkdir(parents=True)
                (root / 'skills' / available / 'SKILL.md').write_text('# Skill\n')
                with patch.object(selector, 'ROOT', root), patch('sys.stderr'):
                    with self.assertRaises(SystemExit) as result:
                        selector.main(['--workflow', 'implement', '--output-dir', str(root / 'out')])
                    self.assertNotEqual(result.exception.code, 0)
                self.assertFalse((root / 'out').exists())

    def test_discovery_rejects_external_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / 'workflows').mkdir()
            (root / 'templates').mkdir()
            (root / 'skills' / 'new-skill').mkdir(parents=True)
            (root / 'workflows' / 'new-flow.md').write_text('# New\n\nDescripción desde Markdown.\n')
            (root / 'templates' / 'new-template.md').write_text('# Template\n')
            (root / 'skills' / 'new-skill' / 'SKILL.md').write_text('# Skill\n')
            external = Path(outside) / 'external.md'
            external.write_text('# External\n')
            (root / 'workflows' / 'escape.md').symlink_to(external)
            (root / 'templates' / 'escape.md').symlink_to(external)
            (root / 'skills' / 'escape').symlink_to(Path(outside), target_is_directory=True)
            (Path(outside) / 'SKILL.md').write_text('# External skill\n')
            with patch.object(selector, 'ROOT', root):
                workflows, skills, templates = selector.discover()
                self.assertEqual(set(workflows), {'new-flow'})
                self.assertEqual(set(skills), {'new-skill'})
                self.assertEqual(set(templates), {'new-template'})
                self.assertEqual(selector.description(workflows['new-flow']), 'Descripción desde Markdown.')


if __name__ == '__main__':
    unittest.main()
