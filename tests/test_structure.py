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
                     'tools/select.py', 'tests/test_select.py', 'tests/test_structure.py',
                     '.github/workflows/selector-ci.yml']:
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

    def test_adapters_can_find_all_templates_and_do_not_require_invented_fields(self):
        shared = (ROOT / 'PROJECT_OS.md').read_text()
        mapping = shared.split('## Selección de templates', 1)[1].split('## Respuesta y continuidad', 1)[0]
        for name in TEMPLATES:
            self.assertIn(f'templates/{name}.md', mapping, name)
        for adapter in ('terminal-agent.md', 'browser-chat.md'):
            content = (ROOT / 'adapters' / adapter).read_text().lower()
            self.assertIn('../project_os.md#selección-de-templates', content)
            self.assertIn('evidencia real', content)
            self.assertRegex(content, r'om(?:ite|itir)')
            self.assertRegex(content, r'(?:no|nunca) invent')

    def test_direct_markdown_bootstrap_links_both_base_skills(self):
        for filename in ('AGENTS.md', 'PROJECT_OS.md'):
            content = (ROOT / filename).read_text()
            for skill in ('repo-context', 'github-traceability'):
                self.assertIn(f'skills/{skill}/SKILL.md', content)

    def test_material_execution_history_contract_and_failed_attempts(self):
        shared = (ROOT / 'PROJECT_OS.md').read_text().lower()
        skill = (ROOT / 'skills/github-traceability/SKILL.md').read_text().lower()
        template = (ROOT / 'templates/comment.md').read_text().lower()
        for content in (shared, skill, template):
            self.assertIn('comentario nuevo', content)
            self.assertIn('ejecución material', content)
            self.assertIn('autorizad', content)
            self.assertIn('fall', content)
            self.assertRegex(content, r'(?:no|nunca) edit')
        self.assertIn('borrador', skill)
        self.assertIn('verifica', template)

    def test_browser_review_publication_contract_is_connected(self):
        adapter = (ROOT / 'adapters/browser-chat.md').read_text().lower()
        skill = (ROOT / 'skills/github-traceability/SKILL.md').read_text().lower()
        workflow = (ROOT / 'workflows/review.md').read_text().lower()
        for content in (adapter, skill):
            for term in ('review.read', 'review.publish', 'autorización', 'sha',
                         'identificador', 'reintento', 'review no publicado'):
                self.assertIn(term, content)
            self.assertIn('comentario nuevo', content)
        for link in ('../adapters/browser-chat.md', '../skills/github-traceability/SKILL.md'):
            self.assertIn(link.lower(), workflow)
        self.assertIn('../../adapters/browser-chat.md', skill)
        self.assertIn('../workflows/review.md', adapter)
        self.assertIn('<url_permanente_del_comentario>', adapter)

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
