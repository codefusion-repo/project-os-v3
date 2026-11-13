import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {'continue', 'create', 'implement', 'review', 'close', 'release'}
SKILLS = {'repo-context', 'rapid-prototype', 'implement-change', 'debug', 'testing',
          'security-review', 'code-review', 'github-traceability', 'documentation'}
TEMPLATES = {'task', 'issue', 'pull-request', 'review', 'execution', 'decision',
             'prototype', 'handoff', 'release', 'dogfood', 'merge', 'close', 'comment', 'review-comment'}


class Structure(unittest.TestCase):
    def test_required_files(self):
        for path in ['AGENTS.md', 'PROJECT_OS.md', 'README.md', 'docs/V3_SPEC.md',
                     'docs/ADOPTION.md', 'docs/IMPLEMENTATION_TASK.md', 'adapters/terminal-agent.md', 'adapters/browser-chat.md',
                     'tools/select.py', 'tests/test_select.py', 'tests/test_structure.py']:
            self.assertTrue((ROOT / path).is_file(), path)
        self.assertEqual({p.stem for p in (ROOT / 'workflows').glob('*.md')}, WORKFLOWS)
        self.assertEqual({p.parent.name for p in (ROOT / 'skills').glob('*/SKILL.md')}, SKILLS)
        self.assertEqual({p.stem for p in (ROOT / 'templates').glob('*.md')}, TEMPLATES)

    def test_workflows_and_skills_have_operational_sections(self):
        for path in (ROOT / 'workflows').glob('*.md'):
            content = path.read_text()
            for heading in ('Objetivo', 'Cuándo usar', 'Ruta rápida', 'Evidencia y validación', 'Salida', 'Escalación localizada'):
                self.assertIn('## ' + heading, content, str(path))
            route = content.split('## Ruta rápida', 1)[1].split('## ', 1)[0]
            self.assertLessEqual(len(re.findall(r'^\d+\.', route, re.M)), 5, str(path))
        for path in (ROOT / 'skills').glob('*/SKILL.md'):
            content = path.read_text()
            for heading in ('Para qué sirve', 'Cuándo conviene', 'Entradas mínimas', 'Procedimiento concreto', 'Validación y salida', 'Riesgos/limitaciones'):
                self.assertIn('## ' + heading, content, str(path))

    def test_shared_response_formats_are_linked_from_both_adapters(self):
        shared = (ROOT / 'PROJECT_OS.md').read_text()
        for name in ('execution', 'review', 'decision'):
            self.assertIn(f'templates/{name}.md', shared)
        for adapter in ('terminal-agent.md', 'browser-chat.md'):
            self.assertIn('../PROJECT_OS.md', (ROOT / 'adapters' / adapter).read_text())

    def test_direct_markdown_bootstrap_links_both_base_skills(self):
        for filename in ('AGENTS.md', 'PROJECT_OS.md'):
            content = (ROOT / filename).read_text()
            for skill in ('repo-context', 'github-traceability'):
                self.assertIn(f'skills/{skill}/SKILL.md', content)

    def test_relative_markdown_links(self):
        for path in ROOT.rglob('*.md'):
            if '.git' in path.parts or '.project-os' in path.parts:
                continue
            content = re.sub(r'```.*?```', '', path.read_text(), flags=re.S)
            for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^\s)]+)(?:\s+[^)]*)?\)', content):
                parsed = urlsplit(target)
                if parsed.scheme or target.startswith('#'):
                    continue
                resolved = (path.parent / unquote(parsed.path)).resolve()
                with self.subTest(file=str(path.relative_to(ROOT)), target=target):
                    self.assertTrue(resolved.is_relative_to(ROOT), target)
                    self.assertTrue(resolved.exists(), target)


if __name__ == '__main__':
    unittest.main()
