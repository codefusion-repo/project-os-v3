import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'select.py'
spec = importlib.util.spec_from_file_location('selector', SCRIPT)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def run(output_dir, *args, input_text=None):
    return subprocess.run([sys.executable, str(SCRIPT), '--output-dir', str(output_dir), *args],
                          input=input_text, text=True, capture_output=True, cwd=ROOT)


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
            result = run(tmp, input_text='implement\n-\nContexto\ng\ns\n')
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

    def test_interactive_multiple_specialized_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(tmp, input_text='implement\ndebug,testing,security-review\nCorregir repo\ng\ns\n')
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
            session = ('/prototipo\n1\nrapid-prototype,testing\nPrimera idea\n'
                       'e\n\n\nIdea editada\ng\nm\nSegunda idea\ng\ns\n')
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
            result = run(dest, input_text='\n\nContexto\nc\n')
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
            result = run(dest, input_text='\n\n\ng\ns\n')
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
