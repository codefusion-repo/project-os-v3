import base64
import csv
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def wheel(directory):
    # Controlled test wheel: validates installer isolation and launcher wiring without network.
    files = {
        'prompt_toolkit/__init__.py': b'def prompt(*a, **k): return input(a[0])\n',
        'prompt_toolkit/completion.py': b'class Completer: pass\nclass Completion: pass\n',
        'prompt_toolkit-3.0.53.dist-info/METADATA': b'Metadata-Version: 2.1\nName: prompt_toolkit\nVersion: 3.0.53\n',
        'prompt_toolkit-3.0.53.dist-info/WHEEL': b'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
    }
    record = io.StringIO(newline='')
    writer = csv.writer(record)
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow((name, 'sha256=' + digest, len(data)))
    writer.writerow(('prompt_toolkit-3.0.53.dist-info/RECORD', '', ''))
    files['prompt_toolkit-3.0.53.dist-info/RECORD'] = record.getvalue().encode()
    name = directory / 'prompt_toolkit-3.0.53-py3-none-any.whl'
    with zipfile.ZipFile(name, 'w') as archive:
        for path, data in files.items():
            archive.writestr(path, data)


def install_fixture(root):
    kit = root / 'kit'
    kit.mkdir()
    shutil.copy2(ROOT / 'install.sh', kit / 'install.sh')
    shutil.copytree(ROOT / 'tools', kit / 'tools', ignore=shutil.ignore_patterns('__pycache__'))
    (kit / '.gitignore').write_text('.venv/\n.venv-install.*/\n__pycache__/\n')
    git = lambda *args: subprocess.run(['git', '-C', str(kit), *args], check=True, capture_output=True)
    git('init', '-q', '-b', 'main')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'initial')
    subprocess.run(['git', 'clone', '--bare', '-q', str(kit), str(root / 'remote.git')], check=True)
    git('remote', 'add', 'origin', 'https://github.com/codefusion-repo/project-os-v3.git')
    return kit


def transport(root):
    return {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': f'url.{(root / "remote.git").as_uri()}.insteadOf',
            'GIT_CONFIG_VALUE_0': 'https://github.com/codefusion-repo/project-os-v3.git'}


class Installer(unittest.TestCase):
    def test_unexpected_origin_and_unsafe_bin_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install_fixture(root)
            env = dict(os.environ, HOME=str(root), **transport(root))
            subprocess.run(['git', '-C', str(kit), 'remote', 'set-url', 'origin',
                            'https://example.invalid/foreign.git'], check=True)
            result = subprocess.run([str(kit / 'install.sh')], env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Origen no esperado', result.stderr)
            self.assertFalse((root / '.local/bin/project-os-v3').exists())
            subprocess.run(['git', '-C', str(kit), 'remote', 'set-url', 'origin',
                            'https://github.com/codefusion-repo/project-os-v3.git'], check=True)
            unsafe = root / 'unsafe'
            unsafe.mkdir(mode=0o777)
            unsafe.chmod(0o777)
            env['PROJECT_OS_BIN_DIR'] = str(unsafe)
            result = subprocess.run([str(kit / 'install.sh')], env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('inseguro', result.stderr)
            self.assertFalse((unsafe / 'project-os-v3').exists())
            link = root / 'bin-link'
            link.symlink_to(unsafe, target_is_directory=True)
            env['PROJECT_OS_BIN_DIR'] = str(link)
            result = subprocess.run([str(kit / 'install.sh')], env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('enlace simbólico', result.stderr)

    def test_update_fast_forward_and_preserves_conflicts_and_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install_fixture(root)
            (kit / '.venv').mkdir()  # Unknown environment must remain untouched.
            (kit / '.venv' / 'keep').write_text('keep')
            project = root / 'project'
            project.mkdir()
            (project / 'AGENTS.md').write_text('pinned version\n')
            (project / '.project-os').mkdir()
            (project / '.project-os' / 'prompt').write_text('private fixture\n')
            env = dict(os.environ, HOME=str(root), **transport(root))
            run = lambda: subprocess.run([str(kit / 'install.sh')], cwd=root, env=env, text=True, capture_output=True)
            first = run()
            self.assertEqual(first.returncode, 0, first.stderr)
            launcher = root / '.local/bin/project-os-v3'
            previous = launcher.read_bytes()
            timestamp = launcher.stat().st_mtime_ns
            again = run()
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(timestamp, launcher.stat().st_mtime_ns)
            writer = root / 'writer'
            subprocess.run(['git', 'clone', '-q', str(root / 'remote.git'), str(writer)], check=True)
            (writer / 'version.txt').write_text('new main\n')
            def git(*args):
                return subprocess.run(['git', '-C', str(writer), *args], check=True, capture_output=True, text=True).stdout.strip()
            git('add', 'version.txt')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'update')
            expected = git('rev-parse', 'HEAD')
            git('push', '-q', 'origin', 'main')
            updated = run()
            self.assertEqual(updated.returncode, 0, updated.stderr)
            self.assertEqual(subprocess.check_output(['git', '-C', str(kit), 'rev-parse', 'HEAD'], text=True).strip(), expected)
            self.assertEqual(launcher.read_bytes(), previous)
            self.assertEqual((kit / '.venv/keep').read_text(), 'keep')
            self.assertEqual((project / 'AGENTS.md').read_text(), 'pinned version\n')
            self.assertEqual((project / '.project-os/prompt').read_text(), 'private fixture\n')
            (kit / 'version.txt').write_text('local changes\n')
            conflict = run()
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn('cambios locales', conflict.stderr)
            self.assertEqual((kit / 'version.txt').read_text(), 'local changes\n')
            self.assertEqual(launcher.read_bytes(), previous)
            (kit / 'version.txt').write_text('new main\n')
            env.update(transport(root / 'offline'))
            offline = run()
            self.assertNotEqual(offline.returncode, 0)
            self.assertIn('se conserva la instalación anterior', offline.stderr)
            self.assertEqual(launcher.read_bytes(), previous)
            self.assertEqual(subprocess.check_output(['git', '-C', str(kit), 'rev-parse', 'HEAD'], text=True).strip(), expected)
            env.update(transport(root))
            (kit / 'local.txt').write_text('local commit\n')
            subprocess.run(['git', '-C', str(kit), 'add', 'local.txt'], check=True)
            subprocess.run(['git', '-C', str(kit), '-c', 'user.name=Test', '-c',
                            'user.email=test@example.invalid', 'commit', '-qm', 'local'], check=True)
            local_sha = subprocess.check_output(['git', '-C', str(kit), 'rev-parse', 'HEAD'], text=True).strip()
            diverged = run()
            self.assertNotEqual(diverged.returncode, 0)
            self.assertIn('no avanza limpiamente', diverged.stderr)
            self.assertEqual(subprocess.check_output(['git', '-C', str(kit), 'rev-parse', 'HEAD'], text=True).strip(), local_sha)
            self.assertEqual(launcher.read_bytes(), previous)

    def test_install_reinstall_and_launcher_from_elsewhere(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install_fixture(root)
            wheels = root / 'wheels'
            wheels.mkdir()
            wheel(wheels)
            bindir = root / 'bin'
            rc = root / '.bashrc'
            rc.write_text('sentinel\n')
            env = dict(os.environ, HOME=str(root), PROJECT_OS_BIN_DIR=str(bindir), PIP_NO_INDEX='1', PIP_FIND_LINKS=str(wheels), **transport(root))
            for _ in range(2):
                result = subprocess.run([str(kit / 'install.sh')], env=env, cwd=root, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            launch = bindir / 'project-os-v3'
            self.assertTrue(launch.is_file())
            self.assertEqual(launch.stat().st_mode & 0o777, 0o700)
            self.assertEqual(rc.read_text(), 'sentinel\n')
            self.assertEqual(len(list(bindir.iterdir())), 1)
            previous_launcher = launch.read_bytes()
            other = root / 'other'
            other.mkdir()
            other_kit = install_fixture(other)
            second = subprocess.run([str(other_kit / 'install.sh')], env=env, cwd=root, text=True, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(launch.read_bytes(), previous_launcher)
            result = subprocess.run([str(launch), '--help'], env=env, cwd='/', text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--project', result.stdout)
            result = subprocess.run([str(kit / '.venv/bin/python'), '-c', 'import sys,prompt_toolkit; assert sys.prefix != sys.base_prefix'],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_dependency_falls_back_and_preserves_foreign_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install_fixture(root)
            bindir = root / 'bin'
            env = dict(os.environ, HOME=str(root), PROJECT_OS_BIN_DIR=str(bindir), PIP_NO_INDEX='1', PIP_FIND_LINKS=str(root / 'missing'), **transport(root))
            result = subprocess.run([str(kit / 'install.sh')], env=env, cwd=root, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Python estándar', result.stderr)
            launch = bindir / 'project-os-v3'
            result = subprocess.run([str(launch), '--help'], env=env, cwd='/', text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            launch.write_text('foreign')
            result = subprocess.run([str(kit / 'install.sh')], env=env, cwd=root, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(launch.read_text(), 'foreign')

    def test_launcher_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install_fixture(root)
            bindir = root / 'bin'
            bindir.mkdir()
            foreign = root / 'foreign'
            foreign.write_text('keep')
            (bindir / 'project-os-v3').symlink_to(foreign)
            env = dict(os.environ, HOME=str(root), PROJECT_OS_BIN_DIR=str(bindir))
            result = subprocess.run([str(kit / 'install.sh')], env=env, cwd=root, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(foreign.read_text(), 'keep')

    def test_unknown_existing_venv_is_preserved_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kit = install_fixture(root)
            binary = kit / '.venv/bin/python'
            binary.parent.mkdir(parents=True)
            marker = root / 'ran-unknown-python'
            binary.write_text('#!/bin/sh\n: > "' + str(marker) + '"\n')
            binary.chmod(0o755)
            env = dict(os.environ, HOME=str(root), PROJECT_OS_BIN_DIR=str(root / 'bin'), **transport(root))
            result = subprocess.run([str(kit / 'install.sh')], env=env, cwd=root, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
            self.assertTrue(binary.exists())


if __name__ == '__main__':
    unittest.main()
