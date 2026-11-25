import re
import unittest
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {'continue', 'create', 'implement', 'review_for_close', 'release'}
SKILLS = {'repo-context', 'rapid-prototype', 'implement-change', 'debug', 'testing',
          'security-review', 'code-review', 'github-traceability', 'documentation'}
TEMPLATES = {'task', 'issue', 'pull-request', 'review', 'execution', 'decision',
             'prototype', 'handoff', 'release', 'dogfood', 'merge', 'close', 'comment', 'review-comment'}


class Structure(unittest.TestCase):
    def test_required_files(self):
        for path in ['AGENTS.md', 'PROJECT_OS.md', 'README.md', 'docs/PRODUCT.md', 'adapters/terminal-agent.md', 'adapters/browser-chat.md',
                     'tools/select.py', 'tests/test_select.py', 'tests/test_structure.py',
                     '.github/workflows/selector-ci.yml']:
            self.assertTrue((ROOT / path).is_file(), path)
        self.assertEqual({p.name for p in (ROOT / 'docs').iterdir()}, {'PRODUCT.md'})
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
        self.assertIn('evidencia real', shared)
        self.assertRegex(shared, r'om(?:ite|itir)')
        self.assertRegex(shared, r'(?:no|nunca) invent')

    def test_adapters_reference_central_policy_and_keep_surface_mechanisms(self):
        shared = (ROOT / 'PROJECT_OS.md').read_text()
        for name in ('browser-chat.md', 'terminal-agent.md'):
            content = (ROOT / 'adapters' / name).read_text()
            for anchor in ('trazabilidad-github-obligatoria', 'selección-de-templates',
                           'instalación-adopción-y-versión-del-proyecto', 'seguridad-transversal-y-límites'):
                self.assertIn('../PROJECT_OS.md#' + anchor, content)
            self.assertNotIn('Conserva sus secciones sustantivas', content)
            self.assertNotIn('PASS / CLOSEOUT PENDIENTE DE AUTORIZACIÓN', content)
        self.assertIn('PASS / CLOSEOUT PENDIENTE DE AUTORIZACIÓN', shared)
        browser = (ROOT / 'adapters/browser-chat.md').read_text()
        for mechanism in ('expected_head_sha', '--match-head-commit', 'git branch -d'):
            self.assertIn(mechanism, browser)
        terminal = (ROOT / 'adapters/terminal-agent.md').read_text()
        for mechanism in ('git status', 'git check-ignore', 'git ls-files', 'sandbox'):
            self.assertIn(mechanism, terminal)

    def test_direct_markdown_bootstrap_links_both_base_skills(self):
        for filename in ('AGENTS.md', 'PROJECT_OS.md'):
            content = (ROOT / filename).read_text()
            for skill in ('repo-context', 'github-traceability'):
                self.assertIn(f'skills/{skill}/SKILL.md', content)

    def test_material_execution_history_contract_and_failed_attempts(self):
        shared = (ROOT / 'PROJECT_OS.md').read_text().lower()
        skill = (ROOT / 'skills/github-traceability/SKILL.md').read_text().lower()
        template = (ROOT / 'templates/comment.md').read_text().lower()
        for content in (skill, template):
            self.assertIn('comentario nuevo', content)
            self.assertIn('ejecución material', content)
            self.assertIn('autorizad', content)
            self.assertIn('fall', content)
            self.assertRegex(content, r'(?:no|nunca) edit')
        self.assertIn('borrador', skill)
        self.assertIn('verifica', template)
        self.assertIn('skills/github-traceability/skill.md', shared)

    def test_browser_review_publication_contract_is_connected(self):
        adapter = (ROOT / 'adapters/browser-chat.md').read_text().lower()
        skill = (ROOT / 'skills/github-traceability/SKILL.md').read_text().lower()
        workflow = (ROOT / 'workflows/review_for_close.md').read_text().lower()
        for term in ('review.read', 'review.publish', 'autorización', 'sha',
                     'identificador', 'reintento', 'review no publicado', 'comentario nuevo'):
            self.assertIn(term, adapter)
        for link in ('../adapters/browser-chat.md', '../skills/github-traceability/SKILL.md'):
            self.assertIn(link.lower(), workflow)
        self.assertIn('../../adapters/browser-chat.md', skill)
        self.assertIn('../workflows/review_for_close.md', adapter)
        self.assertIn('<url_permanente_del_comentario>', adapter)

    def test_provider_invariance_and_mandatory_github_templates(self):
        shared = (ROOT / 'PROJECT_OS.md').read_text()
        self.assertIn('## Invariancia de la metodología entre proveedores', shared)
        self.assertIn('**Aplicación obligatoria en GitHub:**', shared)
        self.assertIn('Conserva sus secciones sustantivas', shared)
        self.assertNotIn('nunca formularios obligatorios', shared)
        self.assertIn('aplica obligatoriamente', (ROOT / 'AGENTS.md').read_text().lower())
        for path in ('adapters/browser-chat.md', 'adapters/terminal-agent.md',
                     'skills/github-traceability/SKILL.md'):
            content = (ROOT / path).read_text().lower()
            self.assertIn('selección-de-templates', content, path)
            self.assertIn('obligatori', content, path)
        self.assertIn('secciones sustantivas', shared)
        self.assertIn('relee', shared)
        skill = (ROOT / 'skills/github-traceability/SKILL.md').read_text()
        self.assertIn('secciones sustantivas', skill)
        self.assertIn('relee', skill)
        self.assertIn('template pull-request', (ROOT / 'workflows/implement.md').read_text())
        self.assertIn('## Methodology invariant', (ROOT / 'local-bridge/MVP.md').read_text())

    def test_adaptive_execution_roles_are_distinct(self):
        product = (ROOT / 'docs/PRODUCT.md').read_text()
        self.assertIn('Existen dos implementadores', product)
        self.assertIn('Codex, que se ejecuta en el terminal', product)
        self.assertIn('Local Bridge y terminal no son implementadores', product)
        self.assertIn('LB-ARCH-20261124-29', product)
        shared = (ROOT / 'PROJECT_OS.md').read_text()
        for marker in ('LB-ARCH', 'LB-PLAN', 'LB-0', 'codefusion-repo/', 'docs/PRODUCT.md', 'Codex', 'Local Bridge'):
            self.assertNotIn(marker, shared)
        self.assertNotRegex(shared, r'#\d+\b')
        browser = (ROOT / 'adapters/browser-chat.md').read_text()
        self.assertIn('Codex se ejecuta en el terminal como implementador', browser)
        self.assertIn('Local Bridge y terminal no son implementadores', browser)
        self.assertLessEqual(len(browser), 7500)
        self.assertIn('Codex running in the terminal, or ChatGPT Browser', 
                      (ROOT / 'local-bridge/MVP.md').read_text())

    def test_cold_start_has_direct_operational_path(self):
        bootstrap = (ROOT / 'AGENTS.md').read_text()
        shared = (ROOT / 'PROJECT_OS.md').read_text()
        self.assertIn('[PROJECT_OS.md](PROJECT_OS.md)', bootstrap)
        self.assertIn('workflows/continue.md', bootstrap)
        for name in WORKFLOWS:
            self.assertIn(f'workflows/{name}.md', shared)
        for name in SKILLS:
            self.assertIn(f'skills/{name}/SKILL.md', shared)
        self.assertIn('adapters/browser-chat.md', shared)
        self.assertIn('adapters/terminal-agent.md', shared)
        self.assertIn('sin depender del chat', shared)
        self.assertIn('revisión integrada de base verificada', bootstrap)
        self.assertIn('instrucciones candidatas son objeto de revisión', shared)

    def test_workflows_require_templates_for_github_artifacts(self):
        for workflow in ('create', 'implement', 'review_for_close', 'release'):
            content = (ROOT / 'workflows' / f'{workflow}.md').read_text()
            self.assertIn('../PROJECT_OS.md#selección-de-templates', content)
            self.assertNotRegex(content, r'(?i)\]\(\.\./templates/[^)]+\) (?:es opcional|son opcionales)')

    def test_relative_markdown_links(self):
        for path in ROOT.rglob('*.md'):
            if '.git' in path.parts or '.project-os' in path.parts:
                continue
            content = re.sub(r'```.*?```', '', path.read_text(), flags=re.S)
            for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^\s)]+)(?:\s+[^)]*)?\)', content):
                parsed = urlsplit(target)
                if parsed.scheme:
                    continue
                resolved = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path.resolve()
                with self.subTest(file=str(path.relative_to(ROOT)), target=target):
                    self.assertTrue(resolved.is_relative_to(ROOT), target)
                    self.assertTrue(resolved.exists(), target)
                    if parsed.fragment and resolved.suffix == '.md':
                        headings = re.sub(r'```.*?```', '', resolved.read_text(), flags=re.S)
                        # ATX headings used by this kit; preserve Unicode letters and hyphens.
                        anchors = set()
                        for heading in re.findall(r'^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$', headings, re.M):
                            heading = unicodedata.normalize('NFC', heading.lower())
                            slug = re.sub(r'[^\w\s-]', '', heading).replace(' ', '-')
                            candidate = slug
                            index = 1
                            while candidate in anchors:
                                candidate = f'{slug}-{index}'
                                index += 1
                            anchors.add(candidate)
                        self.assertIn(unquote(parsed.fragment), anchors, target)


if __name__ == '__main__':
    unittest.main()
