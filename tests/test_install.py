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
    return kit


class Installer(unittest.TestCase):
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
            env = dict(os.environ, HOME=str(root), PROJECT_OS_BIN_DIR=str(bindir), PIP_NO_INDEX='1', PIP_FIND_LINKS=str(wheels))
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
            env = dict(os.environ, HOME=str(root), PROJECT_OS_BIN_DIR=str(bindir), PIP_NO_INDEX='1', PIP_FIND_LINKS=str(root / 'missing'))
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
            env = dict(os.environ, HOME=str(root), PROJECT_OS_BIN_DIR=str(root / 'bin'))
            result = subprocess.run([str(kit / 'install.sh')], env=env, cwd=root, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
            self.assertTrue(binary.exists())


if __name__ == '__main__':
    unittest.main()
