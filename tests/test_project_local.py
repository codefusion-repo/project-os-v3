import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('project_local_tests', ROOT / 'tools/project_local.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)
SELECT = ROOT / 'tools/select.py'


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()


def repo(root):
    root.mkdir(parents=True)
    git(root, 'init', '-q')
    return root


def execute(*args, cwd=None, input_text=None):
    return subprocess.run([sys.executable, str(SELECT), *map(str, args)], cwd=cwd or ROOT,
                          text=True, input=input_text, capture_output=True)


def save(root, name, github, folder='.project-os/prompts'):
    local.save_config(root, {'version': 1, 'name': name, 'primary_repo': github,
                             'related_repos': [], 'prompt_dir': folder})


class Privacy(unittest.TestCase):
    def test_first_use_prepares_and_verifies_local_exclude(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            save(root, 'one', 'org/one')
            self.assertFalse((root / '.gitignore').exists())
            self.assertIn('.project-os/', (root / '.git/info/exclude').read_text())
            self.assertEqual(git(root, 'check-ignore', '.project-os/config.json'), '.project-os/config.json')
            self.assertNotIn('.project-os', git(root, 'status', '--porcelain', '--untracked-files=all'))
            self.assertEqual((root / '.project-os/config.json').stat().st_mode & 0o777, 0o600)

    def test_tracked_private_files_block_without_reading_or_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            private = root / '.project-os'
            private.mkdir()
            config = private / 'config.json'
            config.write_text('not json and confidential')
            git(root, 'add', '-f', '.project-os/config.json')
            with self.assertRaises(local.ProjectError):
                save(root, 'one', 'org/one')
            self.assertEqual(config.read_text(), 'not json and confidential')
            external = Path(temp) / 'external'
            result = execute('--project', root, '--workflow', 'review', '--output-dir', external)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('bajo seguimiento', result.stderr)
            self.assertNotIn('confidential', result.stdout + result.stderr)
            self.assertEqual(len(list(external.glob('project-os-prompt-*.md'))), 1)

    def test_negation_and_inability_to_exclude_stop_private_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            (root / '.gitignore').write_text('!.project-os/\n!.project-os/**\n')
            with self.assertRaises(local.ProjectError):
                save(root, 'one', 'org/one')
            self.assertFalse((root / '.project-os/config.json').exists())

    def test_git_ignore_is_checked_for_actual_generated_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            (root / '.gitignore').write_text('output/.project-os-protection-check\n')
            target = root / 'output'
            with self.assertRaises(local.ProjectError):
                local.preflight(target)
            self.assertFalse(target.exists())

    def test_sensitive_env_file_is_not_added_to_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            token = 'ghp_' + 'Q' * 36
            (root / '.env').write_text('TOKEN=' + token)
            save(root, 'a', 'org/a')
            result = execute('--project', root, '--workflow', 'continue')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = next((root / '.project-os/prompts').glob('*.md')).read_text()
            self.assertNotIn(token, text + result.stdout + result.stderr)
            self.assertEqual((root / '.env').read_text(), 'TOKEN=' + token)

    def test_interactive_unprotected_project_can_preview_and_choose_external(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = repo(base / 'repo')
            (root / '.gitignore').write_text('!.project-os/\n!.project-os/**\n')
            external = base / 'external'
            entries = ['continue', 'org/a', '', '', '', '', '', 'g', str(external), 's']
            result = execute('--project', root, input_text='\n'.join(entries) + '\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Vista previa', result.stdout)
            self.assertEqual(len(list(external.glob('*.md'))), 1)
            self.assertFalse((root / '.project-os/config.json').exists())

    def test_unprotected_existing_config_can_use_explicit_external_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = repo(base / 'repo')
            (root / '.project-os').mkdir()
            config = root / '.project-os/config.json'
            config.write_text(json.dumps({'version': 1, 'primary_repo': 'org/a'}))
            before = config.read_bytes()
            external = base / 'external'
            result = execute('--project', root, '--workflow', 'review', '--output-dir', external)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('no está protegida', result.stderr)
            self.assertEqual(config.read_bytes(), before)
            self.assertEqual(len(list(external.glob('*.md'))), 1)

    def test_unknown_config_and_existing_private_files_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            local.preflight(root / '.project-os', prepare=True)
            folder = root / '.project-os'
            folder.mkdir()
            (folder / 'config.json').write_text('{"unknown": true}')
            (folder / 'custom').write_text('keep')
            (folder / 'old-prompt.md').write_text('keep')
            with self.assertRaises(local.ProjectError):
                save(root, 'one', 'org/one')
            self.assertEqual((folder / 'config.json').read_text(), '{"unknown": true}')
            self.assertEqual((folder / 'custom').read_text(), 'keep')
            self.assertEqual((folder / 'old-prompt.md').read_text(), 'keep')

    def test_preflight_rejects_symlink_and_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'real').mkdir()
            (root / 'link').symlink_to(root / 'real')
            for value in (root / 'link' / 'p', root / 'real' / '..' / 'p'):
                with self.subTest(value=value), self.assertRaises(local.ProjectError):
                    local.preflight(value)

    def test_bare_git_repository_is_not_a_private_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'bare.git'
            subprocess.run(['git', 'init', '--bare', '-q', str(root)], check=True)
            with self.assertRaises(local.ProjectError):
                local.preflight(root / '.project-os')
            self.assertFalse((root / '.project-os').exists())

    def test_worktree_uses_git_resolved_exclusion(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = repo(base / 'main')
            (root / 'README.md').write_text('fixture')
            git(root, 'add', 'README.md')
            git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'one')
            worktree = base / 'worktree'
            git(root, 'worktree', 'add', '--detach', str(worktree), 'HEAD')
            save(worktree, 'worktree', 'org/worktree')
            self.assertEqual(git(worktree, 'check-ignore', '.project-os/config.json'), '.project-os/config.json')
            self.assertNotIn('.project-os', git(worktree, 'status', '--porcelain', '--untracked-files=all'))


class Projects(unittest.TestCase):
    def test_two_projects_stay_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            a, b = repo(Path(temp) / 'a'), repo(Path(temp) / 'b')
            save(a, 'a', 'org/a')
            save(b, 'b', 'org/b')
            for root, context in ((a, 'context A'), (b, 'context B')):
                result = execute('--project', root, '--workflow', 'review', '--objective', context)
                self.assertEqual(result.returncode, 0, result.stderr)
            pa = next((a / '.project-os/prompts').glob('*.md'))
            pb = next((b / '.project-os/prompts').glob('*.md'))
            self.assertIn('org/a', pa.read_text())
            self.assertIn('context A', pa.read_text())
            self.assertNotIn('context B', pa.read_text())
            self.assertIn('org/b', pb.read_text())
            self.assertNotIn('context A', pb.read_text())
            self.assertEqual(execute('--project', a, '--workflow', 'continue').returncode, 0)
            self.assertTrue(pb.exists())

    def test_nested_conflicts_are_not_merged_and_explicit_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / 'workspace'
            workspace.mkdir()
            child = repo(workspace / 'frontend')
            sub = child / 'src'
            sub.mkdir()
            save(workspace, 'ws', 'org/whole')
            save(child, 'front', 'org/front')
            result = execute('--workflow', 'continue', cwd=sub)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('anidadas en conflicto', result.stderr)
            choices = ['1', 'continue', '', '', '', '', '', 'g', 's']
            interactive = execute(cwd=sub, input_text='\n'.join(choices) + '\n')
            self.assertEqual(interactive.returncode, 0, interactive.stderr)
            self.assertIn('Hay proyectos anidados con preferencias distintas', interactive.stdout)
            self.assertIn('org/front', next((child / '.project-os/prompts').glob('*.md')).read_text())
            for root, name in ((workspace, 'org/whole'), (child, 'org/front')):
                result = execute('--project', root, '--workflow', 'continue', cwd=sub)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(name, next((root / '.project-os/prompts').glob('*.md')).read_text())
            self.assertEqual(local.read_config(workspace)['primary_repo'], 'org/whole')
            self.assertEqual(local.read_config(child)['primary_repo'], 'org/front')

    def test_configure_related_checkouts_without_publishing_local_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'workspace')
            result = execute('--project', root, '--configure', '--repo', 'org/front',
                             '--related-repo', 'org/back', '--checkout', 'org/back=' + str(Path(temp) / 'back'))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = local.read_config(root)
            self.assertEqual(data['related_repos'], ['org/back'])
            self.assertIn('org/back', data['checkouts'])
            generated = execute('--project', root, '--workflow', 'continue')
            self.assertEqual(generated.returncode, 0, generated.stderr)
            text = next((root / '.project-os/prompts').glob('*.md')).read_text()
            self.assertNotIn(str(Path(temp) / 'back'), text)
            self.assertNotIn('org/back', text)

    def test_remote_without_checkout_only_previews(self):
        with tempfile.TemporaryDirectory() as temp:
            result = execute('--repo', 'org/remote', '--workflow', 'review', cwd=temp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Solo vista previa', result.stdout)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_noninteractive_generation_never_changes_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            save(root, 'a', 'org/a')
            before = (root / '.project-os/config.json').read_bytes()
            result = execute('--project', root, '--repo', 'org/other', '--workflow', 'continue')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / '.project-os/config.json').read_bytes(), before)

    def test_migrate_legacy_only_to_explicit_matching_project(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            kit = base / 'kit'
            (kit / 'tools').mkdir(parents=True)
            for name in ('select.py', 'project_local.py'):
                shutil.copy2(ROOT / 'tools' / name, kit / 'tools' / name)
            (kit / '.project-os/prompts').mkdir(parents=True)
            legacy = kit / '.project-os/config.json'
            legacy.write_text(json.dumps({'repo': 'org/old', 'output_dir': str(kit / '.project-os/prompts')}))
            old_prompt = kit / '.project-os/prompts/old.md'
            old_prompt.write_text('preserve')
            project = repo(base / 'project')
            def command(owner):
                return subprocess.run([sys.executable, str(kit / 'tools/select.py'), '--project', str(project),
                                       '--configure', '--migrate-legacy', '--repo', owner],
                                      text=True, capture_output=True)
            self.assertNotEqual(command('org/other').returncode, 0)
            self.assertFalse((project / '.project-os/config.json').exists())
            self.assertEqual(command('org/old').returncode, 0)
            self.assertEqual(local.read_config(project)['primary_repo'], 'org/old')
            self.assertEqual(local.read_config(project)['prompt_dir'], '.project-os/prompts')
            self.assertTrue(legacy.exists())
            self.assertEqual(old_prompt.read_text(), 'preserve')
            self.assertNotEqual(command('org/old').returncode, 0)

    def test_configure_rejects_secrets_without_echo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            token = 'ghp_' + 'Z' * 36
            result = execute('--project', root, '--configure', '--repo', 'org/a', '--name', token)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(token, result.stdout + result.stderr)
            self.assertFalse((root / '.project-os/config.json').exists())

    def test_discovered_config_rejects_secrets_without_echo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            save(root, 'a', 'org/a')
            token = 'ghp_' + 'Y' * 36
            (root / '.project-os/config.json').write_text(json.dumps({'version': 1, 'primary_repo': 'org/a', 'name': token}))
            result = execute('--workflow', 'continue', cwd=root)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(token, result.stdout + result.stderr)
            self.assertFalse((root / '.project-os/prompts').exists())


class Versions(unittest.TestCase):
    def test_pinned_source_uses_committed_blob_not_modified_or_untracked(self):
        with tempfile.TemporaryDirectory() as temp:
            kit = repo(Path(temp) / 'kit')
            (kit / 'PROJECT_OS.md').write_text('versión oficial\n')
            git(kit, 'add', 'PROJECT_OS.md')
            git(kit, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'one')
            sha = git(kit, 'rev-parse', 'HEAD')
            (kit / 'PROJECT_OS.md').write_text('modificación local\n')
            (kit / 'local.md').write_text('no rastreado\n')
            self.assertEqual(local.commit(kit, sha), sha)
            self.assertEqual(local.git_document(kit, sha, 'PROJECT_OS.md'), 'versión oficial\n')
            with self.assertRaises(local.ProjectError):
                local.git_document(kit, sha, 'local.md')
            with self.assertRaises(local.ProjectError):
                local.commit(kit, 'a' * 40)
            (kit / 'AGENTS.md').write_text('codefusion-repo/project-os-v3\nProject-OS-Version: ' + sha + '\n')
            self.assertEqual(local.version(kit), sha)

    def test_unavailable_pinned_version_never_generates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            save(root, 'a', 'org/a')
            (root / 'AGENTS.md').write_text('codefusion-repo/project-os-v3\nProject-OS-Version: ' + 'a' * 40 + '\n')
            result = execute('--project', root, '--workflow', 'continue')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('no está disponible', result.stderr)
            self.assertFalse((root / '.project-os/prompts').exists())

    def test_malformed_declared_version_never_falls_back_to_head(self):
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            save(root, 'a', 'org/a')
            (root / 'AGENTS.md').write_text('codefusion-repo/project-os-v3\nProject-OS-Version: main\n')
            result = execute('--project', root, '--workflow', 'continue')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('versión inválida', result.stderr)
            self.assertFalse((root / '.project-os/prompts').exists())

    def test_real_pinned_version_is_visible_in_generated_prompt(self):
        sha = git(ROOT, 'rev-parse', 'HEAD')
        with tempfile.TemporaryDirectory() as temp:
            root = repo(Path(temp) / 'repo')
            save(root, 'a', 'org/a')
            (root / 'AGENTS.md').write_text('codefusion-repo/project-os-v3\nProject-OS-Version: ' + sha + '\n')
            result = execute('--project', root, '--workflow', 'review')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = next((root / '.project-os/prompts').glob('*.md')).read_text()
            self.assertIn(sha, text)
            self.assertIn('documentos recuperados íntegramente de objetos Git', text)

    def test_full_prompt_uses_pinned_tree_after_kit_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            kit = repo(base / 'kit')
            for name in ('tools', 'workflows', 'skills', 'templates'):
                shutil.copytree(ROOT / name, kit / name, ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copy2(ROOT / 'PROJECT_OS.md', kit / 'PROJECT_OS.md')
            (kit / 'unrelated.txt').write_text('base')
            git(kit, 'add', '.')
            git(kit, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'one')
            old = git(kit, 'rev-parse', 'HEAD')
            project = repo(base / 'project')
            save(project, 'a', 'org/a')
            (project / 'AGENTS.md').write_text('codefusion-repo/project-os-v3\nProject-OS-Version: ' + old + '\n')
            cmd = [sys.executable, str(kit / 'tools/select.py'), '--project', str(project), '--workflow', 'review']
            (kit / 'unrelated.txt').write_text('cambio ajeno')
            clean_operational = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(clean_operational.returncode, 0, clean_operational.stderr)
            self.assertNotIn('Documentos locales distintos de la referencia', next((project / '.project-os/prompts').glob('*.md')).read_text())
            with (kit / 'PROJECT_OS.md').open('a') as stream:
                stream.write('\nCAMBIO_LOCAL_NO_OFICIAL\n')
            extra = kit / 'skills/untracked'
            extra.mkdir()
            (extra / 'SKILL.md').write_text('# Skill: untracked')
            result = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = next((project / '.project-os/prompts').glob('*.md')).read_text()
            self.assertIn(old, text)
            self.assertNotIn('CAMBIO_LOCAL_NO_OFICIAL', text)
            self.assertIn('Documentos locales distintos de la referencia:** PROJECT_OS.md', text)
            self.assertNotEqual(subprocess.run(cmd + ['--skill', 'untracked'], capture_output=True).returncode, 0)
            git(kit, 'add', 'PROJECT_OS.md')
            git(kit, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'two')
            newer = git(kit, 'rev-parse', 'HEAD')
            self.assertNotEqual(old, newer)
            result = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = next((project / '.project-os/prompts').glob('*.md')).read_text()
            self.assertIn(old, text)
            self.assertNotIn('CAMBIO_LOCAL_NO_OFICIAL', text)
            adoption = subprocess.run([sys.executable, str(kit / 'tools/select.py'), '--project', str(project),
                                       '--adopt', '--target-version', newer], capture_output=True, text=True)
            self.assertEqual(adoption.returncode, 0, adoption.stderr)
            text = next((project / '.project-os/prompts').glob('*.md')).read_text()
            self.assertIn('**Versión objetivo:** ' + newer, text)
            self.assertIn('**Versión declarada actualmente:** ' + old, text)
            self.assertFalse((project / 'workflows').exists())


if __name__ == '__main__':
    unittest.main()
