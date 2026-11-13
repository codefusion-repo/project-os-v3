import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from test_select import ROOT, install, outputs, run, selector


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout.strip()


def fixture(base):
    kit = install(base / 'kit')
    git(kit, 'init', '-q')
    git(kit, 'add', '.')
    git(kit, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'one')
    old = git(kit, 'rev-parse', 'HEAD')
    with (kit / 'PROJECT_OS.md').open('a') as stream:
        stream.write('\nCambio local para prueba.\n')
    git(kit, 'add', 'PROJECT_OS.md')
    git(kit, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'two')
    new = git(kit, 'rev-parse', 'HEAD')
    project = kit / 'project'
    (project / 'AGENTS.md').write_text('codefusion-repo/project-os-v3\nProject-OS-Version: ' + old + '\n')
    selector.project_local.save_config(project, {'version': 2, 'name': 'fixture', 'repositories': ['org/main', 'org/api', 'org/mobile'],
                                                  'prompt_dir': '.project-os/prompts'})
    return kit, project, old, new


def fake_response(url, data):
    response = MagicMock()
    response.status = 200
    response.geturl.return_value = url
    response.read.return_value = json.dumps(data).encode()
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    return opener


class CanonicalSource(unittest.TestCase):
    def test_exact_remote_commit_is_confirmed_and_no_credentials_sent(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, _, _, new = fixture(Path(temp))
            url = 'https://api.github.com/repos/codefusion-repo/project-os-v3/commits/' + new
            opener = fake_response(url, {'sha': new})
            with patch.object(selector.project_local.urllib.request, 'build_opener', return_value=opener):
                self.assertEqual(selector.project_local.verify_canonical(kit, new), new)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, url)
            self.assertNotIn('Authorization', request.headers)
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)

    def test_local_only_commit_cannot_be_presented_as_canonical(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, project, _, new = fixture(Path(temp))
            folder = project / '.project-os/prompts'
            folder.mkdir()
            previous = folder / ('project-os-prompt-' + 'a' * 32 + '.md')
            previous.write_text(selector.MARKER + '\nanterior\n')
            error = urllib.error.HTTPError('https://api.github.com', 404, 'not found', {}, None)
            opener = MagicMock()
            opener.open.side_effect = error
            out, err = io.StringIO(), io.StringIO()
            with patch.object(selector, 'ROOT', kit), patch.object(selector.project_local.urllib.request, 'build_opener', return_value=opener):
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    status = selector.main(['--project', str(project), '--adopt', '--target-version', new])
            self.assertEqual(status, 0, err.getvalue())
            self.assertIn('Versión propuesta local (no verificada en GitHub)', out.getvalue())
            self.assertIn('Borrador no verificado', out.getvalue())
            generated = outputs(folder)
            self.assertEqual(len(generated), 2)
            self.assertEqual(previous.read_text(), selector.MARKER + '\n' + 'anterior\n')
            content = next(path for path in generated if path != previous).read_text()
            self.assertNotIn('Project-OS-Version: ' + new, content)
            self.assertIn('Project-OS-Version: <SHA_CANONICO_VERIFICADO>', content)
            opener.open.assert_called_once()

    def test_mismatched_response_timeout_and_redirect_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, _, _, new = fixture(Path(temp))
            url = 'https://api.github.com/repos/codefusion-repo/project-os-v3/commits/' + new
            for opener in (fake_response(url, {'sha': 'a' * 40}), fake_response('https://other.invalid/', {'sha': new})):
                with self.subTest(case=opener), patch.object(selector.project_local.urllib.request, 'build_opener', return_value=opener):
                    with self.assertRaises(selector.project_local.ProjectError):
                        selector.project_local.verify_canonical(kit, new)
            opener = MagicMock()
            opener.open.side_effect = TimeoutError('no network')
            with patch.object(selector.project_local.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaises(selector.project_local.ProjectError):
                    selector.project_local.verify_canonical(kit, new)

    def test_ordinary_workflow_does_not_attempt_network(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, project, _, _ = fixture(Path(temp))
            output = io.StringIO()
            with patch.object(selector, 'ROOT', kit), patch.object(selector.project_local.urllib.request, 'build_opener', side_effect=AssertionError('unexpected network')):
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                    status = selector.main(['--project', str(project), '--workflow', 'review'])
            self.assertEqual(status, 0)
            self.assertIn('Vista previa', output.getvalue())


class WizardReviewFixes(unittest.TestCase):
    def test_adoption_selects_new_target_without_changing_project(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, project, old, new = fixture(Path(temp))
            out, err = io.StringIO(), io.StringIO()
            before = (project / 'AGENTS.md').read_bytes()
            with patch.object(selector, 'ROOT', kit), patch('sys.stdin', io.StringIO('/adoptar\n' + new + '\ng\ns\n')):
                with patch.object(selector.project_local, 'verify_canonical', return_value=new) as verify:
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        status = selector.main(['--project', str(project)])
            self.assertEqual(status, 0, err.getvalue())
            self.assertIn('Versión actual del proyecto: ' + old, out.getvalue())
            self.assertIn('Versión objetivo seleccionada: ' + new, out.getvalue())
            content = outputs(project / '.project-os/prompts')[0].read_text()
            self.assertIn('**Versión objetivo:** ' + new, content)
            self.assertIn('**Versión declarada actualmente:** ' + old, content)
            self.assertIn('haz inventario de los componentes obsoletos', content)
            self.assertEqual((project / 'AGENTS.md').read_bytes(), before)
            verify.assert_called_once_with(kit, new)

    def test_unavailable_old_version_allows_explicit_adoption_only(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, project, _, new = fixture(Path(temp))
            (project / 'AGENTS.md').write_text('codefusion-repo/project-os-v3\nProject-OS-Version: ' + 'a' * 40 + '\n')
            out, err = io.StringIO(), io.StringIO()
            entries = '/adoptar\n' + new + '\ng\ns\n'
            with patch.object(selector, 'ROOT', kit), patch('sys.stdin', io.StringIO(entries)):
                with patch.object(selector.project_local, 'verify_canonical', return_value=new):
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        status = selector.main(['--project', str(project)])
            self.assertEqual(status, 0, err.getvalue())
            self.assertIn('La versión fijada no está disponible', out.getvalue())
            self.assertEqual(len(outputs(project / '.project-os/prompts')), 1)
            self.assertIn('**Versión objetivo:** ' + new, outputs(project / '.project-os/prompts')[0].read_text())

    def test_offline_adoption_is_labeled_draft_and_cancel_preserves_previous(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, project, _, new = fixture(Path(temp))
            folder = project / '.project-os/prompts'
            folder.mkdir()
            previous = folder / ('project-os-prompt-' + 'b' * 32 + '.md')
            previous.write_text(selector.MARKER + '\nanterior\n')
            out, err = io.StringIO(), io.StringIO()
            with patch.object(selector, 'ROOT', kit), patch('sys.stdin', io.StringIO('/adoptar\n' + new + '\nc\n')):
                with patch.object(selector.project_local, 'verify_canonical', side_effect=selector.project_local.ProjectError('sin red')):
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        status = selector.main(['--project', str(project)])
            self.assertEqual(status, 0, err.getvalue())
            self.assertIn('Borrador no verificado', out.getvalue())
            self.assertIn('no actualices la referencia', out.getvalue())
            self.assertEqual(previous.read_text(), selector.MARKER + '\nanterior\n')

    def test_temporary_scope_menu_and_manual_entry(self):
        for selection, expected in (('2', 'org/api'), ('org/custom', 'org/custom')):
            with self.subTest(selection=selection), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                kit = install(root / 'kit')
                project = kit / 'project'
                selector.project_local.save_config(project, {'version': 2, 'name': 'fixture', 'repositories': ['org/main', 'org/api', 'org/mobile'],
                                                              'prompt_dir': '.project-os/prompts'})
                entries = ['/repo', selection, 'review', '', '', '', '', '', 'g', 's']
                result = run(root / 'out', input_text='\n'.join(entries) + '\n', kit=kit)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Repositorios del proyecto:', result.stdout)
                self.assertIn('2. org/api', result.stdout)
                self.assertIn('3. org/mobile', result.stdout)
                content = outputs(root / 'out')[0].read_text()
                self.assertIn('**Alcance explícito:** ' + expected, content)
                self.assertNotIn('org/mobile', content)
                self.assertEqual(json.loads((project / '.project-os/config.json').read_text())['repositories'], ['org/main', 'org/api', 'org/mobile'])


if __name__ == '__main__':
    unittest.main()
