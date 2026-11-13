import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_project_local import execute, repo, save
from test_select import install, outputs, run, selector


class Migration(unittest.TestCase):
    def legacy(self, root, data):
        selector.project_local.preflight(root / '.project-os', prepare=True)
        folder = root / '.project-os'
        folder.mkdir(exist_ok=True)
        config = folder / 'config.json'
        config.write_text(json.dumps(data, ensure_ascii=False))
        return config

    def test_v1_projects_migrate_atomically_preserving_preferences_and_files(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            kit = install(base / 'kit')
            project = kit / 'project'
            path_a, path_b = base / 'a', base / 'b'
            legacy = {'version': 1, 'name': 'proyecto', 'primary_repo': 'org/front',
                      'related_repos': ['ORG/FRONT', 'org/api', 'org/mobile', 'org/api'],
                      'checkouts': {'org/front': str(path_a), 'org/api': str(path_b)},
                      'prompt_dir': '.project-os/prompts'}
            config = self.legacy(project, legacy)
            folder = project / '.project-os'
            (folder / 'custom.txt').write_text('conservar')
            (folder / 'prompts').mkdir()
            (folder / 'prompts/manual.md').write_text('manual')
            before = config.read_bytes()
            # CLI generation can interpret v1 without changing the stored configuration.
            output = base / 'cli'
            cli = run(output, '--workflow', 'implement', '--objective', 'Cambiar API y frontend', kit=kit)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertEqual(config.read_bytes(), before)
            text = outputs(output)[0].read_text()
            for name in ('org/front', 'org/api', 'org/mobile'):
                self.assertIn(name, text)
            self.assertNotIn(str(path_a), text)
            self.assertNotIn(str(path_b), text)
            # Wizard use commits the lossless migration after the Git preflight.
            entries = ['continue', '', '', '', '', '', 'g', 's']
            result = run(base / 'interactive', input_text='\n'.join(entries) + '\n', kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('migrada a la versión 2', result.stdout)
            migrated = json.loads(config.read_text())
            self.assertEqual(migrated, {'version': 2, 'name': 'proyecto',
                                        'repositories': ['org/front', 'org/api', 'org/mobile'],
                                        'checkouts': legacy['checkouts'], 'prompt_dir': legacy['prompt_dir']})
            self.assertEqual((folder / 'custom.txt').read_text(), 'conservar')
            self.assertEqual((folder / 'prompts/manual.md').read_text(), 'manual')

    def test_migration_failure_and_concurrent_change_preserve_original(self):
        with tempfile.TemporaryDirectory() as temp:
            project = repo(Path(temp) / 'project')
            legacy = {'version': 1, 'primary_repo': 'org/front', 'related_repos': ['org/api'],
                      'prompt_dir': '.project-os/prompts'}
            config = self.legacy(project, legacy)
            before = config.read_bytes()
            converted = selector.project_local.migrate_v1(legacy)
            with patch.object(selector.project_local.os, 'fsync', side_effect=OSError('fallo')):
                with self.assertRaises(OSError):
                    selector.project_local.save_config(project, converted, expected=legacy)
            self.assertEqual(config.read_bytes(), before)
            updated = dict(legacy, name='cambio externo')
            config.write_text(json.dumps(updated))
            with self.assertRaises(selector.project_local.ProjectError):
                selector.project_local.save_config(project, converted, expected=legacy)
            self.assertEqual(json.loads(config.read_text()), updated)

    def test_explicit_configure_migrates_and_adds_without_losing_old_repos(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'project')
            legacy = {'version': 1, 'name': 'producto', 'primary_repo': 'org/front',
                      'related_repos': ['org/api'], 'checkouts': {'org/front': str(Path(temp) / 'front')},
                      'prompt_dir': '.project-os/prompts'}
            config = self.legacy(root, legacy)
            result = execute('--project', root, '--configure', '--repo', 'org/mobile')
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(config.read_text())
            self.assertEqual(data['repositories'], ['org/front', 'org/api', 'org/mobile'])
            self.assertEqual(data['checkouts'], legacy['checkouts'])
            self.assertNotIn('primary_repo', data)
            self.assertNotIn('related_repos', data)

    def test_unknown_ambiguous_and_unprotected_configs_are_preserved(self):
        cases = [
            {'version': 1, 'primary_repo': 'org/front', 'related_repos': ['org/api'], 'extra': 'no tocar'},
            {'version': 1, 'primary_repo': '', 'related_repos': []},
            {'version': 1, 'primary_repo': 'org/front', 'related_repos': [], 'checkouts': {'org/otro': '/tmp/otro'}},
            {'version': 3, 'repositories': ['org/front']},
        ]
        for data in cases:
            with self.subTest(data=data), tempfile.TemporaryDirectory() as temp:
                project = repo(Path(temp) / 'project')
                config = self.legacy(project, data)
                before = config.read_bytes()
                result = execute('--project', project, '--workflow', 'continue')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(config.read_bytes(), before)
                self.assertFalse((project / '.project-os/prompts').exists())
        with tempfile.TemporaryDirectory() as temp:
            project = repo(Path(temp) / 'project')
            config = self.legacy(project, {'version': 1, 'primary_repo': 'org/front', 'related_repos': ['org/api']})
            before = config.read_bytes()
            # A tracked config is detected without reading or overwriting its content.
            result = __import__('subprocess').run(['git', '-C', str(project), 'add', '-f', '.project-os/config.json'], capture_output=True)
            self.assertEqual(result.returncode, 0)
            result = execute('--project', project, '--workflow', 'continue')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('bajo seguimiento', result.stderr)
            self.assertEqual(config.read_bytes(), before)


class MultiRepository(unittest.TestCase):
    def configured(self, root):
        selector.project_local.save_config(root, {'version': 2, 'name': 'producto',
            'repositories': ['org/front', 'org/api', 'org/mobile'],
            'checkouts': {'org/front': str(root / 'local-front'), 'org/api': str(root / 'local-api')},
            'prompt_dir': '.project-os/prompts'})
        return root / '.project-os/config.json'

    def test_shared_output_isolated_by_project_and_remote_only_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            first, second = repo(base / 'first'), repo(base / 'second')
            save(first, 'primero', 'org/first')
            save(second, 'segundo', 'org/second')
            folder = base / 'shared'
            def generate(project):
                result = execute('--project', project, '--workflow', 'continue', '--output-dir', folder)
                self.assertEqual(result.returncode, 0, result.stderr)
            generate(first)
            first_old = outputs(folder)[0]
            generate(second)
            second_file = next(path for path in outputs(folder) if path != first_old)
            generate(first)
            self.assertFalse(first_old.exists())
            self.assertTrue(second_file.exists())
            self.assertEqual(len(outputs(folder)), 2)
            remote = base / 'remote'
            for name in ('org/first', 'org/second'):
                result = run(remote, '--workflow', 'continue', '--repo', name)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(outputs(remote)), 2)

    def test_issue_reference_outside_scope_warns(self):
        self.assertIn('fuera del alcance', selector.reference_warning(
            ['org/front'], 'https://github.com/org/api/issues/17'))
        self.assertEqual('', selector.reference_warning(
            ['org/front'], 'https://github.com/org/front/issues/17', 'PR #4'))

    def test_transversal_and_explicit_scopes_do_not_change_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'project')
            config = self.configured(root)
            before = config.read_bytes()
            for args, expected in (([], 'No restringido'),
                                   (['--repo', 'org/front', '--repo', 'org/api'], 'org/front, org/api')):
                with self.subTest(args=args):
                    result = execute('--project', root, '--workflow', 'implement', '--objective',
                                     'Actualizar frontend, API y mobile', *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    text = next((root / '.project-os/prompts').glob('*.md')).read_text()
                    self.assertIn('**Proyecto:** producto', text)
                    known = 'org/front, org/api, org/mobile' if not args else 'org/front, org/api'
                    self.assertIn('**Repositorios conocidos (sin verificar):** ' + known, text)
                    self.assertIn('**Alcance explícito:** ' + expected, text)
                    self.assertIn('Identifica los repositorios necesarios', text)
                    self.assertIn('Verifica por separado permisos, visibilidad, rama, cambios y autorización', text)
                    self.assertIn('no concede escritura', text)
                    self.assertIn('No expongas secretos, rutas locales ni asociaciones privadas', text)
                    self.assertNotIn(str(root / 'local-front'), text)
                    self.assertNotIn(str(root / 'local-api'), text)
                    if args:
                        self.assertNotIn('org/mobile', text)
                    self.assertEqual(config.read_bytes(), before)

    def test_wizard_requires_no_repo_choice_and_scope_is_temporary(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            kit = install(base / 'kit')
            project = kit / 'project'
            config = self.configured(project)
            before = config.read_bytes()
            # Restrict the first operation, then reuse the workflow for a new unrestricted one.
            entries = ['/alcance', '1,2', 'review', '', 'Primero', '#1', 'Nota anterior', '', 'g',
                       'm', '', 'Segundo', '#2', '', '', 'g', 's']
            result = run(base / 'out', input_text='\n'.join(entries) + '\n', kit=kit)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('Repositorios owner/repo separados', result.stdout)
            self.assertIn('**Alcance explícito:** org/front, org/api', result.stdout)
            text = outputs(base / 'out')[0].read_text()
            self.assertIn('**Alcance explícito:** No restringido', text)
            self.assertIn('Segundo', text)
            self.assertNotIn('Nota anterior', text)
            self.assertEqual(config.read_bytes(), before)

    def test_single_repo_and_duplicate_configuration_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'project')
            save(root, 'uno', 'org/uno')
            result = execute('--project', root, '--workflow', 'continue')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = next((root / '.project-os/prompts').glob('*.md')).read_text()
            self.assertIn('**Repositorios conocidos (sin verificar):** org/uno', text)
            self.assertIn('**Alcance explícito:** No restringido', text)
            with self.assertRaises(selector.project_local.ProjectError):
                selector.project_local.save_config(root, {'version': 2, 'repositories': ['org/uno', 'ORG/UNO']})
            configured = execute('--project', root, '--configure', '--repo', 'org/dos')
            self.assertEqual(configured.returncode, 0, configured.stderr)
            config = selector.project_local.read_config(root)
            self.assertEqual(config['repositories'], ['org/uno', 'org/dos'])

    def test_local_only_does_not_include_project_repositories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'project')
            config = self.configured(root)
            before = config.read_bytes()
            result = execute('--project', root, '--prototype', '--repo', '-', '--objective', 'Experimento local')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = next((root / '.project-os/prompts').glob('*.md')).read_text()
            for name in ('org/front', 'org/api', 'org/mobile'):
                self.assertNotIn(name, text)
            self.assertIn('experimento local y descartable', text)
            self.assertEqual(config.read_bytes(), before)

    def test_each_repository_may_have_different_pinned_instructions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'workspace')
            self.configured(root)
            for directory, sha in (('local-front', 'a' * 40), ('local-api', 'b' * 40)):
                checkout = root / directory
                checkout.mkdir()
                (checkout / 'AGENTS.md').write_text('Project-OS-Version: ' + sha)
            result = execute('--project', root, '--workflow', 'implement', '--objective', 'Coordinar front y API')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = next((root / '.project-os/prompts').glob('*.md')).read_text()
            self.assertIn('cada repositorio puede fijar otra versión', text)
            self.assertIn('no mezcles sus instrucciones', text)
            self.assertNotIn(str(root / 'local-front'), text)
            self.assertNotIn(str(root / 'local-api'), text)


if __name__ == '__main__':
    unittest.main()
