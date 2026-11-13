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


def install(root):
    root = Path(root)
    (root / 'tools').mkdir(parents=True)
    shutil.copy2(SCRIPT, root / 'tools/select.py')
    shutil.copy2(ROOT / 'tools/project_local.py', root / 'tools/project_local.py')
    (root / 'project').mkdir()
    shutil.copy2(ROOT / 'PROJECT_OS.md', root / 'PROJECT_OS.md')
    for name in ('workflows', 'skills', 'templates'):
        shutil.copytree(ROOT / name, root / name)
    return root


def run(folder, *args, input_text=None, kit=None):
    script = Path(kit) / 'tools/select.py' if kit else SCRIPT
    project_args = ['--project', str(Path(kit) / 'project')] if kit else []
    return subprocess.run([sys.executable, str(script), *project_args, '--output-dir', str(folder), *args],
                          input=input_text, text=True, capture_output=True, cwd=ROOT)


def outputs(folder):
    return list(Path(folder).glob('project-os-prompt-*.md'))


class CommandLine(unittest.TestCase):
    def test_list_without_writes_and_invalid_options(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'out'
            result = run(dest, '--list')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('continue', result.stdout)
            self.assertIn('rapid-prototype', result.stdout)
            self.assertFalse(dest.exists())
            for args in [('--workflow', '../review'), ('--skill', '../debug'),
                         ('--locator', '../../secret'), ('--locator', 'https://evil.test/a/b/pull/1'),
                         ('--prototype', '--workflow', 'review'), ('--template', 'review')]:
                with self.subTest(args=args):
                    self.assertNotEqual(run(dest, *args).returncode, 0)
            self.assertFalse(dest.exists())

    def test_prototype_composes_skills_and_preserves_context(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run(temp, '--prototype', '--skill', 'testing', '--skill', 'security-review',
                         '--skill', 'repo-context', '--skill', 'testing', '--repo', 'org/repo',
                         '--locator', 'https://github.com/org/repo/pull/12',
                         '--objective', 'Validar PR #12', '--feedback', 'Primera\nSegunda',
                         '--question', 'Qué falta')
            self.assertEqual(result.returncode, 0, result.stderr)
            files = outputs(temp)
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            self.assertIn('**Workflow:** implement', text)
            self.assertIn('**Skills:** repo-context, github-traceability, rapid-prototype, testing, security-review', text)
            self.assertIn('**Referencia:** https://github.com/org/repo/pull/12', text)
            self.assertIn('## Comentario del PM — PM_FEEDBACK_HUMANO\n\nPrimera\nSegunda\n\n##', text)
            self.assertIn('## Pregunta del PM — PM_QUESTION_HUMANO\n\nQué falta\n\n##', text)
            self.assertNotIn('**Advertencia:**', text)
            for name in ('repo-context', 'github-traceability', 'rapid-prototype', 'testing', 'security-review'):
                self.assertEqual(text.count('skills/' + name + '/SKILL.md'), 1)

    def test_all_operations_include_base_skills_and_contextual_heading(self):
        with tempfile.TemporaryDirectory() as temp:
            for operation in selector.ORDER:
                with self.subTest(operation=operation):
                    result = run(temp, '--workflow', operation, '--skill', 'github-traceability')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    text = outputs(temp)[0].read_text()
                    self.assertIn('## Entrada principal — ' + selector.LABELS[operation], text)
                    for name in selector.BASE:
                        self.assertEqual(text.count('skills/' + name + '/SKILL.md'), 1)

    def test_inconsistent_reference_is_warned_without_changing_pm_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run(temp, '--repo', 'org/repo', '--workflow', 'review', '--locator', '#9',
                         '--objective', 'Revisar PR #7', '--feedback', 'Nota exacta', '--question', 'Consulta exacta')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = outputs(temp)[0].read_text()
            self.assertIn('**Advertencia:** Posible inconsistencia', text)
            self.assertIn('## Comentario del PM — PM_FEEDBACK_HUMANO\n\nNota exacta\n\n##', text)
            self.assertIn('## Pregunta del PM — PM_QUESTION_HUMANO\n\nConsulta exacta\n\n##', text)
            self.assertFalse(selector.reference_warning('org/repo', 'https://github.com/org/repo/issues/7', 'PR #9'))

    def test_rejects_sensitive_values_without_echo_or_replacement(self):
        token = 'ghp_' + 'A' * 36
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(run(temp, '--workflow', 'continue').returncode, 0)
            previous = outputs(temp)[0]
            before = previous.read_bytes()
            for option in ('--objective', '--feedback', '--question', '--repo', '--locator', '--workflow', '--skill'):
                with self.subTest(option=option):
                    result = run(temp, '--workflow', 'review', option, token)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(token, result.stdout + result.stderr)
                    self.assertEqual(previous.read_bytes(), before)
            result = run(temp, '--invalid=' + token)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(token, result.stdout + result.stderr)

    def test_sensitive_source_is_not_copied_into_prompt(self):
        operations, skills, templates = selector.discover()
        token = 'ghp_' + 'C' * 36
        with patch.object(selector, 'SOURCE_VERSION', 'a' * 40), patch.object(selector, 'SOURCE_LOCAL_AVAILABLE', True), patch.object(selector, 'source', side_effect=lambda path: token if path == operations['review'] else '# Documento'):
            text = selector.render('review', [], '', '', operations, skills, templates)
        self.assertNotIn(token, text)

    def test_path_traversal_and_directory_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            link = root / 'link'
            link.symlink_to(outside, target_is_directory=True)
            for path in (root / '..' / 'escape', link, link / 'nested'):
                with self.subTest(path=path):
                    self.assertNotEqual(run(path, '--prototype').returncode, 0)
                    self.assertEqual(list(Path(outside).iterdir()), [])


class Persistence(unittest.TestCase):
    def test_replaces_only_own_files_after_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dest, other = root / 'out', root / 'other'
            dest.mkdir()
            other.mkdir()
            manual = dest / 'manual.md'
            manual.write_text('manual')
            mimic = dest / ('project-os-prompt-' + 'a' * 32 + '.md')
            mimic.write_text('sin marcador')
            external = other / ('project-os-prompt-' + 'b' * 32 + '.md')
            external.write_text(selector.MARKER + '\nexterno')
            link = dest / ('project-os-prompt-' + 'c' * 32 + '.md')
            link.symlink_to(external)
            first = run(dest, '--prototype')
            self.assertEqual(first.returncode, 0, first.stderr)
            previous = next(p for p in outputs(dest) if p not in (mimic, link))
            result = run(dest, '--workflow', 'continue')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(previous.exists())
            self.assertEqual(manual.read_text(), 'manual')
            self.assertEqual(mimic.read_text(), 'sin marcador')
            self.assertTrue(link.is_symlink())
            self.assertEqual(external.read_text(), selector.MARKER + '\nexterno')

    def test_failed_publish_preserves_previous_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old, _ = selector.save_prompt(root, selector.MARKER + '\noriginal\n')
            for fail in ('fsync', 'link'):
                with self.subTest(fail=fail), patch.object(selector.os, fail, side_effect=OSError('fallo')):
                    with self.assertRaises(OSError):
                        selector.save_prompt(root, selector.MARKER + '\nnew\n')
                    self.assertEqual(old.read_text(), selector.MARKER + '\noriginal\n')
                    self.assertEqual(list(root.iterdir()), [old])

    def test_configuration_is_atomic_and_contains_only_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(selector, 'ROOT', root):
                selector.project_local.save_config(root, {'version': 1, 'primary_repo': 'org/repo', 'prompt_dir': 'out'})
                path = root / '.project-os/config.json'
                before = path.read_bytes()
                self.assertEqual(json.loads(before), {'version': 1, 'primary_repo': 'org/repo', 'prompt_dir': 'out'})
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                with patch.object(selector.project_local.os, 'fsync', side_effect=OSError('fallo')):
                    with self.assertRaises(OSError):
                        selector.project_local.save_config(root, {'version': 1, 'primary_repo': 'other/repo'})
                self.assertEqual(path.read_bytes(), before)

    def test_source_symlinks_outside_kit_are_not_discovered(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            (root / 'workflows').mkdir()
            (root / 'skills').mkdir()
            (root / 'templates').mkdir()
            file = Path(outside) / 'x.md'
            file.write_text('# External')
            (root / 'workflows' / 'escape.md').symlink_to(file)
            with patch.object(selector, 'ROOT', root):
                operations, _, _ = selector.discover()
                self.assertNotIn('escape', operations)


class Wizard(unittest.TestCase):
    def test_freeform_intent_uses_continue_without_losing_question(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'out'
            entries = ['Qué falta para terminar el proyecto', 'org/repo', '', '', '', '', '', 'g', 's']
            result = run(dest, input_text=chr(10).join(entries) + chr(10), kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = outputs(dest)[0].read_text()
            self.assertIn('**Workflow:** continue', text)
            self.assertIn('Qué falta para terminar el proyecto', text)

    def test_search_filters_and_selects_a_matching_operation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'out'
            entries = ['revisar', '1', 'org/repo', '', '', '', '', '', 'g', 's']
            result = run(dest, input_text=chr(10).join(entries) + chr(10), kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('**Workflow:** review', outputs(dest)[0].read_text())

    def test_operation_first_relevant_skills_and_optional_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'out'
            result = run(dest, input_text='review\norg/repo\ncode-review,testing\nReporte PR #1\n#1\nNota\nPregunta\ng\ns\n', kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(result.stdout.index('1/3'), result.stdout.index('Repositorio owner/repo'))
            menu = result.stdout.split('Skills sugeridas:', 1)[1].split('Skills [Enter', 1)[0]
            self.assertIn('code-review', menu)
            self.assertNotIn('implement-change', menu)
            text = outputs(dest)[0].read_text()
            self.assertIn('**Referencia:** #1', text)
            self.assertIn('Reporte PR #1', text)
            self.assertIn('Nota', text)
            self.assertIn('Pregunta', text)

    def test_edit_preserves_fields_and_reasks_workflow_and_skills_not_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'out'
            data = ('review\norg/repo\ncode-review\nReporte\n#1\nComentario\nPregunta\n'
                    'e\nimplement\ndebug,testing\n\n\n\n\ng\ns\n')
            result = run(dest, input_text=data, kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('Repositorio owner/repo'), 1)
            self.assertEqual(result.stdout.count('1/3 — Buscar'), 2)
            text = outputs(dest)[0].read_text()
            self.assertIn('**Workflow:** implement', text)
            self.assertIn('debug, testing', text)
            self.assertIn('Reporte', text)
            self.assertIn('**Referencia:** #1', text)
            self.assertIn('Comentario', text)
            self.assertIn('Pregunta', text)

    def test_same_clears_pm_fields_and_reuses_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'out'
            data = ('review\norg/repo\n\nPrimero\n#1\nComentario anterior\nPregunta anterior\ng\n'
                    'm\n\nSegundo\n#2\n\n\ng\ns\n')
            result = run(dest, input_text=data, kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('Repositorio owner/repo'), 1)
            text = outputs(dest)[0].read_text()
            self.assertIn('Segundo', text)
            self.assertIn('**Referencia:** #2', text)
            self.assertNotIn('Comentario anterior', text)
            self.assertNotIn('Pregunta anterior', text)

    def test_cancel_does_not_write_or_remove(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'out'
            self.assertEqual(run(dest, '--prototype').returncode, 0)
            old = outputs(dest)[0]
            result = run(dest, input_text='review\norg/repo\n\nReporte\n\n\n\nc\n', kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(outputs(dest), [old])

    def test_session_can_change_repo_and_output_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'other'
            data = '/repo\norg/other\n/carpeta\n' + str(dest) + '\ncontinue\n\n\n\n\n\ng\ns\n'
            result = run(root / 'unused', input_text=data, kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('org/other', outputs(dest)[0].read_text())
            prefs = json.loads((kit / 'project/.project-os/config.json').read_text())
            self.assertEqual(prefs['primary_repo'], 'org/other')
            self.assertEqual(prefs['prompt_dir'], str(dest))

    def test_saved_preferences_are_reused_without_pm_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'out'
            first = run(dest, input_text='review\norg/repo\n\nReporte\n#1\nNota privada\nPregunta\ng\ns\n', kit=kit)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = subprocess.run([sys.executable, str(kit / 'tools/select.py')],
                                    input='continue\n\n\n\n\n\ng\ns\n', text=True,
                                    capture_output=True, cwd=kit / 'project')
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn(f'Repositorio: org/repo | Carpeta: {dest}', second.stdout)
            self.assertNotIn('Repositorio owner/repo', second.stdout)
            text = outputs(dest)[0].read_text()
            self.assertNotIn('Nota privada', text)
            self.assertNotIn('## Pregunta del PM — PM_QUESTION_HUMANO', text)
            self.assertNotIn('Nota privada', (kit / 'project/.project-os/config.json').read_text())

    def test_edit_can_explicitly_clear_one_field(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'out'
            data = ('review\norg/repo\ncode-review\nReporte\n#1\nComentario\nPregunta\n'
                    'e\n\n\n/limpiar\n\n/limpiar\n\ng\ns\n')
            result = run(dest, input_text=data, kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = outputs(dest)[0].read_text()
            self.assertNotIn('Comentario', text.split('## Reglas compartidas')[0])
            self.assertIn('**Referencia:** #1', text)
            self.assertIn('## Pregunta del PM — PM_QUESTION_HUMANO\n\nPregunta\n', text)

    def test_cli_does_not_invoke_github(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindir = root / 'bin'
            bindir.mkdir()
            marker = root / 'invoked'
            for name in ('gh',):
                path = bindir / name
                path.write_text('#!/bin/sh\n: > "$PROJECT_OS_TEST_SENTINEL"\n')
                path.chmod(0o755)
            result = subprocess.run([sys.executable, str(SCRIPT), '--workflow', 'review', '--output-dir', str(root / 'out')],
                                    text=True, capture_output=True,
                                    env=dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ.get('PATH', ''), PROJECT_OS_TEST_SENTINEL=str(marker)))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())


class PasteInTerminal(unittest.TestCase):
    @unittest.skipIf(selector.readline is None, 'readline no está disponible')
    def test_bracketed_paste_keeps_full_report_and_does_not_skip_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install(root / 'kit')
            dest = root / 'out'
            master, slave = pty.openpty()
            process = subprocess.Popen([sys.executable, str(kit / 'tools/select.py'), '--project', str(kit / 'project'), '--output-dir', str(dest)],
                                       stdin=slave, stdout=slave, stderr=slave, cwd=kit,
                                       env=dict(os.environ, TERM='xterm'))
            os.close(slave)
            pending = bytearray()
            def until(marker):
                deadline = time.monotonic() + 8
                while marker not in pending:
                    timeout = deadline - time.monotonic()
                    if timeout <= 0 or not select.select([master], [], [], timeout)[0]:
                        self.fail(f'No apareció {marker!r}')
                    pending.extend(os.read(master, 65536))
                index = pending.index(marker) + len(marker)
                data = bytes(pending[:index])
                del pending[:index]
                return data
            def send(value):
                os.write(master, value)
            report = '# Reporte de ejecución\n\nPrimera línea\ng\ne\nc\nÚltima línea'
            feedback = 'Comentario uno\n\nComentario dos'
            try:
                until(b'Operaci')
                send(b'review\n')
                until(b'Repositorio owner/repo')
                send(b'org/repo\n')
                until(b'Skills [Enter')
                send(b'code-review\n')
                until('Reporte de ejecución o solicitud de review [Enter'.encode())
                send(b'\x1b[200~' + report.encode() + b'\x1b[201~')
                time.sleep(0.2)
                while select.select([master], [], [], 0)[0]:
                    pending.extend(os.read(master, 65536))
                self.assertNotIn(b'Issue/PR opcional', pending)
                self.assertNotIn(b'Vista previa', pending)
                send(b'\n')
                until(b'Issue/PR opcional')
                send(b'#1\n')
                until(b'Comentario del PM [Enter')
                send(b'\x1b[200~' + feedback.encode() + b'\x1b[201~\n')
                until(b'Pregunta del PM [Enter')
                send(b'PreguntaX\x1b[D?\n')
                until(b'[G]uardar')
                send(b'g\n')
                until(b'[N]ueva')
                send(b'e\n')
                until(b'Operaci')
                send(b'\n')
                until(b'Skills [Enter')
                send(b'\n')
                until('Reporte de ejecución o solicitud de review [Enter'.encode())
                send(b'\n')
                until(b'Issue/PR opcional')
                send(b'\n')
                until(b'Comentario del PM [Enter')
                send(b'\n')
                until(b'Pregunta del PM [Enter')
                send(b'\n')
                until(b'[G]uardar')
                send(b'g\n')
                until(b'[N]ueva')
                send(b's\n')
                self.assertEqual(process.wait(timeout=8), 0)
                text = outputs(dest)[0].read_text()
                self.assertIn(report, text)
                self.assertIn('## Comentario del PM — PM_FEEDBACK_HUMANO\n\n' + feedback + '\n\n##', text)
                self.assertIn('## Pregunta del PM — PM_QUESTION_HUMANO\n\nPregunta?X\n\n##', text)
                self.assertIn('**Referencia:** #1', text)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=8)
                os.close(master)


@unittest.skipIf(selector.terminal_prompt is None, 'prompt_toolkit opcional no está instalado')
class EnhancedCompletion(unittest.TestCase):
    def test_live_completion_filters_and_supports_multiple_skills(self):
        from prompt_toolkit.document import Document
        selector.complete_from(['code-review', 'testing', 'security-review'])
        try:
            completer = selector.LiveCompleter()
            matches = list(completer.get_completions(Document('testing,rev'), None))
            self.assertEqual([item.text for item in matches], ['code-review', 'security-review'])
            self.assertTrue(all(item.start_position == -3 for item in matches))
        finally:
            selector.clear_completion()
        self.assertEqual(selector.COMPLETIONS, ())


if __name__ == '__main__':
    unittest.main()
