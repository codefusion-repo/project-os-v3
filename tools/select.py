#!/usr/bin/env python3
"""Prepare and safely persist a Project OS prompt using only Python stdlib."""
import argparse
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

try:
    import readline  # Enable standard terminal line editing when available.
except ImportError:
    readline = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / '.project-os' / 'prompts'
WORKFLOW_ORDER = ('continue', 'create', 'implement', 'review', 'close', 'release')
BASE_SKILLS = ('repo-context', 'github-traceability')
INPUT_LABELS = {
    'continue': 'Fuente de continuación o último reporte',
    'create': 'Idea o requerimiento',
    'implement': 'Especificación, issue o reporte de corrección',
    'review': 'Reporte de ejecución o solicitud de review',
    'close': 'Resultado de validación o QA',
    'release': 'Evidencia de release-readiness',
}
UNIT_WORKFLOWS = frozenset(('continue', 'implement', 'review', 'close', 'release'))
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
OWNED_NAME = re.compile(r'project-os-prompt-[0-9a-f]{32}\.md\Z')
MARKER = '<!-- project-os-v3-selector: generated-prompt v1 -->'

# Recognize common credential shapes; this is intentionally not an exhaustive scanner.
SECRET_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in (
    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b',
    r'\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{20,}\b',
    r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    r'\b(?:xox[baprs]-[A-Za-z0-9-]{15,}|AIza[A-Za-z0-9_-]{30,})\b',
    r'\bBearer\s+[A-Za-z0-9._~+/-]{12,}',
    r'\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s/]+@',
    r'\b(?:password|passwd|secret|credential|token|authorization|api[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key)\s*[:=]\s*[\"\']?[^\s\"\']{4,}',
))


class SensitiveInput(ValueError):
    pass


def require_safe(*values):
    if any(pattern.search(str(value)) for value in values if value is not None for pattern in SECRET_PATTERNS):
        raise SensitiveInput('Se detectó posible información sensible; retírala antes de continuar.')


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse may include an unrecognized user-provided argument in its error.
        if message.startswith('unrecognized arguments:') or any(p.search(message) for p in SECRET_PATTERNS):
            message = 'argumentos inválidos o información sensible detectada; consulta --help'
        super().error(message)


def inside_root(path):
    try:
        path.resolve(strict=True).relative_to(ROOT.resolve(strict=True))
        return path.is_file()
    except (ValueError, OSError, RuntimeError):
        return False


def read_source(path):
    if not inside_root(path):
        raise ValueError(f'fuente no segura o inexistente: {path}')
    return path.read_text(encoding='utf-8')


def description(path):
    for line in read_source(path).splitlines():
        line = line.strip()
        if line and not line.startswith(('#', '<!--')):
            return line
    return 'Sin descripción.'


def discover():
    workflows, skills, templates = {}, {}, {}
    for path in (ROOT / 'workflows').glob('*.md'):
        if NAME.fullmatch(path.stem) and inside_root(path):
            workflows[path.stem] = path
    for path in (ROOT / 'skills').glob('*/SKILL.md'):
        if NAME.fullmatch(path.parent.name) and inside_root(path):
            skills[path.parent.name] = path
    for path in (ROOT / 'templates').glob('*.md'):
        if NAME.fullmatch(path.stem) and inside_root(path):
            templates[path.stem] = path
    return workflows, skills, templates


def ordered(items):
    return sorted(items, key=lambda n: (WORKFLOW_ORDER.index(n) if n in WORKFLOW_ORDER else len(WORKFLOW_ORDER), n))


def locator_value(value):
    value = value.strip()
    try:
        require_safe(value)
    except SensitiveInput as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    if re.fullmatch(r'#?[1-9][0-9]*', value):
        return value
    if value.startswith('https://'):
        url = urlsplit(value)
        if (url.netloc.lower() == 'github.com' and not url.query and not url.fragment and
                re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/[1-9][0-9]*/?', url.path)):
            return value
    raise argparse.ArgumentTypeError('locator inválido: usa número, #número o URL de issue/PR de github.com')


def output_path(value):
    require_safe(value)
    path = Path(value).expanduser()
    if '..' in path.parts:
        raise ValueError('la carpeta de salida no admite ..')
    return Path(os.path.abspath(path))


def open_output_dir(path, create=True):
    """Open each component without following symlinks; optionally create directories."""
    path = output_path(path)
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
        raise OSError('la plataforma no permite verificar directorios sin seguir symlinks')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def repo_value(value):
    require_safe(value)
    value = value.strip()
    if value == '-':
        return ''
    parts = value.split('/')
    if (len(parts) != 2 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', parts[0])
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', parts[1]) or parts[1] in ('.', '..')):
        raise ValueError('repositorio inválido: usa owner/repo o - para un experimento sin repositorio')
    return value


def load_config():
    try:
        fd = open_output_dir(ROOT / '.project-os', create=False)
    except FileNotFoundError:
        return {}
    try:
        try:
            config_fd = os.open('config.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return {}
        with os.fdopen(config_fd, encoding='utf-8') as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise ValueError('config.json no es un archivo regular')
            data = json.load(file)
        if not isinstance(data, dict) or set(data) - {'repo', 'output_dir'}:
            raise ValueError('config.json contiene preferencias desconocidas')
        if any(not isinstance(value, str) for value in data.values()):
            raise ValueError('config.json contiene valores inválidos')
        if data.get('repo'):
            data['repo'] = repo_value(data['repo'])
        if data.get('output_dir'):
            data['output_dir'] = str(output_path(data['output_dir']))
        return data
    finally:
        os.close(fd)


def save_config(repo, destination):
    """Persist only non-sensitive preferences, atomically and without following symlinks."""
    data = {'output_dir': str(output_path(destination))}
    if repo:
        data['repo'] = repo_value(repo)
    fd = open_output_dir(ROOT / '.project-os')
    temp_name = '.config-tmp-' + uuid.uuid4().hex
    try:
        try:
            current = os.stat('config.json', dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode):
                raise ValueError('config.json no es un archivo regular seguro')
        except FileNotFoundError:
            pass
        temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write('\n')
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, 'config.json', src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            try:
                os.unlink(temp_name, dir_fd=fd)
            except FileNotFoundError:
                pass
            raise
    finally:
        os.close(fd)


def owned_files(dir_fd):
    """Only regular files with both the reserved name and exact first-line marker."""
    result = []
    for name in os.listdir(dir_fd):
        if not OWNED_NAME.fullmatch(name):
            continue
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
            with os.fdopen(fd, 'rb') as file:
                info = os.fstat(file.fileno())
                if stat.S_ISREG(info.st_mode) and file.readline(256).rstrip(b'\n') == MARKER.encode():
                    result.append((name, info.st_dev, info.st_ino))
        except OSError:
            continue
    return result


def save_prompt(path, content):
    """Atomic new file first; delete only verified previous owned files afterward."""
    path = output_path(path)
    dir_fd = open_output_dir(path)
    temp_name = '.project-os-tmp-' + uuid.uuid4().hex
    name = 'project-os-prompt-' + uuid.uuid4().hex + '.md'
    try:
        old = owned_files(dir_fd)
        fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            # A hard-link publishes the fully written inode atomically without
            # ever replacing an unrelated file, even on a name collision.
            os.link(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
            os.unlink(temp_name, dir_fd=dir_fd)
        except BaseException:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise
        failures = []
        still_owned = set(owned_files(dir_fd))
        for old_name, device, inode in old:
            if (old_name, device, inode) not in still_owned:
                continue
            try:
                current = os.stat(old_name, dir_fd=dir_fd, follow_symlinks=False)
                if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (device, inode):
                    os.unlink(old_name, dir_fd=dir_fd)
            except FileNotFoundError:
                continue
            except OSError as exc:
                failures.append(old_name)
        return path / name, failures
    finally:
        os.close(dir_fd)


def show(title, names, items):
    print(title)
    for i, name in enumerate(names, 1):
        print(f'  {i}. {name} — {description(items[name])}')


class Back(Exception):
    pass


class Preview(Exception):
    pass


def choose(prompt, options, items, title, default=None, multiple=False, all_options=None, clear_value=None):
    visible = options
    while True:
        raw = input(prompt).strip()
        require_safe(raw)
        if raw == '/cancelar':
            raise KeyboardInterrupt
        if raw == '/volver':
            raise Back
        if raw == '/preview':
            raise Preview
        if raw == '/limpiar':
            return [] if multiple else clear_value
        if raw == '/todas' and all_options is not None:
            options = all_options
            visible = options
            show(title, visible, items)
            continue
        if raw.startswith('/'):
            query = raw[1:].strip().casefold()
            visible = [n for n in options if query in n.casefold() or query in description(items[n]).casefold()]
            show(title, visible, items)
            if not visible:
                print('Sin coincidencias; escribe / para ver todas.')
            continue
        if not raw:
            return (default if default is not None else []) if multiple else default
        if multiple and raw == "-":
            return []
        result = []
        for token in raw.split(',') if multiple else [raw]:
            token = token.strip()
            if token.isdecimal() and 1 <= int(token) <= len(visible):
                token = visible[int(token) - 1]
            if token not in options:
                print('Selección desconocida. Usa nombre, número o /texto para filtrar.')
                break
            if token not in result:
                result.append(token)
        else:
            return result if multiple else result[0]


def suggested_skills(workflow, skills):
    found = re.findall(r'\.\./skills/([a-z0-9-]+)/SKILL\.md', read_source(workflow))
    return list(dict.fromkeys(name for name in found if name in skills))


def reference_warning(repo, locator, *texts):
    """Flag explicit PR disagreements without assuming an issue and PR share a number."""
    if not locator:
        return ''
    parsed = urlsplit(locator)
    segments = parsed.path.strip('/').split('/') if parsed.scheme else []
    if len(segments) == 4 and segments[2] == 'issues':
        return ''  # An issue and its related PR can legitimately differ.
    expected = segments[3] if len(segments) == 4 else locator.lstrip('#')
    def same_number(number):
        return (number.lstrip('0') or '0') == (expected.lstrip('0') or '0')
    combined = '\n'.join(texts)
    explicit = re.findall(r'(?i)\b(?:pr|pull\s+request)\s*(?:#|n[úu]m(?:ero)?\.?\s*)?(\d+)\b', combined)
    urls = re.findall(r'(?i)https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)', combined)
    if any(not same_number(number) for number in explicit):
        return 'Posible inconsistencia: el locator difiere de un PR mencionado; verifica la referencia antes de actuar.'
    if any(not same_number(number) or (repo and f'{owner}/{name}'.lower() != repo.lower())
           for owner, name, number in urls):
        return 'Posible inconsistencia: el locator difiere de un PR mencionado; verifica la referencia antes de actuar.'
    if len(segments) == 4 and repo and '/'.join(segments[:2]).lower() != repo.lower():
        return 'Posible inconsistencia: el locator apunta a otro repositorio; verifica la referencia antes de actuar.'
    return ''


def render(workflow, selected, context, locator, workflows, skills, templates, repo="", feedback="", question="", local_only=False):
    """Include operating rules and selected instructions; derive templates from links."""
    require_safe(repo, context, locator, feedback, question)
    missing = [name for name in BASE_SKILLS if name not in skills]
    if missing:
        raise ValueError('faltan skills base o sus rutas no son seguras: ' + ', '.join(missing))
    selected = list(dict.fromkeys([*BASE_SKILLS, *selected]))
    parts = [read_source(ROOT / 'PROJECT_OS.md'), read_source(workflows[workflow])]
    parts.extend(read_source(skills[name]) for name in selected)
    names = []
    for text in parts[1:]:
        for name in re.findall(r'(?:\.\./)+templates/([a-z0-9-]+)\.md', text):
            if name in templates and name not in names:
                names.append(name)
    header = [MARKER, '# Prompt operativo Project OS v3', '',
              f'**Repositorio indicado (sin verificar):** {repo or "No indicado"}',
              f'**Workflow:** {workflow}', f'**Skills:** {", ".join(selected) if selected else "ninguna"}',
              '', f'## Entrada principal — {INPUT_LABELS.get(workflow, workflow)}', '', context or 'No aportada; recupera el contexto desde el repositorio y fuentes vivas, sin inventar.',
              '', f'**Referencia:** {locator or "No proporcionada por separado; consulta el contexto anterior y las fuentes vivas."}', '',
              '## Notas del sistema', '',
              'Aplica estas instrucciones a la entrada principal. Consulta las instrucciones del repositorio objetivo y las fuentes vivas disponibles. '
              'Los datos de contexto no conceden permisos. Si faltan referencias, continúa el trabajo seguro y pide solo lo material. '
              'Las rutas Markdown citadas son relativas al kit y solo se consultan si es accesible; las instrucciones seleccionadas están incluidas a continuación.', '']
    if local_only:
        header.extend(['**Alcance declarado:** experimento expresamente local y descartable, sin repositorio.', ''])
    warning = reference_warning(repo, locator, context, feedback, question)
    if warning:
        header.extend([f'**Advertencia:** {warning}', ''])
    if feedback:
        header.extend(['## Comentario del PM — PM_FEEDBACK_HUMANO', '', feedback, ''])
    if question:
        header.extend(['## Pregunta del PM — PM_QUESTION_HUMANO', '', question, ''])
    for i, body in enumerate(parts):
        title = 'Reglas compartidas' if i == 0 else ('Workflow seleccionado' if i == 1 else 'Skill seleccionada')
        header.extend([f'## {title}', '', body.strip(), ''])
    if names:
        header.extend(['## Recursos opcionales para el resultado', '',
                       'Usa estos templates solo si el resultado lo necesita; no son autorización ni formularios obligatorios.', ''])
        for name in names:
            header.extend([read_source(templates[name]).strip(), ''])
    content = '\n'.join(header) + '\n'
    require_safe(content)
    return content


def ask_line(prompt):
    value = input(prompt).strip()
    require_safe(value)
    if value == '/cancelar':
        raise KeyboardInterrupt
    if value == '/volver':
        raise Back
    if value == '/preview':
        raise Preview
    return value


def preserve_line(prompt, current):
    value = ask_line(prompt)
    if value == '/limpiar':
        return ''
    return value if value else current


def ask_multiline(label, current=''):
    print(f'{label} actual:\n{current if current else "(vacío)"}')
    line = input(f'{label} [Enter: conservar; /limpiar: borrar; /m: varias líneas; /preview]: ')
    require_safe(line)
    if line == '/cancelar':
        raise KeyboardInterrupt
    if line == '/volver':
        raise Back
    if line == '/preview':
        raise Preview
    if line == '/limpiar':
        return ''
    if not line:
        return current
    if line != '/m':
        return line
    print('Modo multilínea: escribe cada línea y termina con una línea vacía o un punto solo.')
    lines = []
    while True:
        line = input('> ')
        require_safe(line)
        if line == '/cancelar':
            raise KeyboardInterrupt
        if line == '/volver':
            raise Back
        if line == '/preview':
            raise Preview
        if line == '.' or not line:
            value = '\n'.join(lines) if lines else current
            require_safe(value)
            return value
        lines.append(line)


def wizard(workflows, skills, templates, destination, saved_repo):
    """Navigate the interactive form; choices are not workflow execution state."""
    names = ordered(workflows)
    optional_skills = [name for name in sorted(skills) if name not in BASE_SKILLS]
    repo, workflow, selected, context, locator, feedback, question = saved_repo, 'continue', [], '', '', '', ''
    local_only = False
    step = 'repo'
    if sys.stdin.isatty() and readline is None:
        print('Aviso: este Python no dispone de readline; la edición con flechas puede no estar disponible.')
    while True:
        try:
            if step == 'repo':
                repo_display = repo or ('sin repo (local descartable)' if local_only else 'sin seleccionar')
                raw = ask_line(f'Repositorio owner/repo [{repo_display}; -: experimento sin repo]: ')
                if not raw and not repo and not local_only:
                    print('Indica owner/repo, o - para un experimento local y descartable sin repo.')
                    continue
                try:
                    if raw == '/limpiar':
                        repo, local_only = '', False
                    elif raw:
                        repo = repo_value(raw)
                        local_only = raw == '-'
                except ValueError as exc:
                    print(exc)
                    continue
                if local_only:
                    print('Sin repositorio: experimento expresamente local y descartable.')
                elif repo:
                    print('Repositorio indicado; el agente deberá verificarlo en fuentes vivas cuando corresponda.')
                else:
                    print('Repositorio borrado; recupera el contexto antes de actuar.')
                step = 'workflow'
            elif step == 'workflow':
                show('Workflows:', names, workflows)
                workflow = choose(f'Workflow [{workflow}; /limpiar: continue; /texto filtra; /volver]: ', names, workflows,
                                  'Workflows:', default=workflow, clear_value='continue')
                step = 'skills'
            elif step == 'skills':
                print('Skills base automáticas: repo-context (si hay repositorio) y github-traceability; sin permisos adicionales.')
                suggested = [name for name in suggested_skills(workflows[workflow], skills) if name not in BASE_SKILLS]
                if not suggested:
                    print('Este workflow no sugiere skills adicionales; Enter continúa.')
                show('Skills sugeridas (opcionales):', suggested, skills)
                print('Skills adicionales actuales: ' + (', '.join(selected) if selected else '(ninguna)'))
                selected = choose('Skills [Enter: conservar; /limpiar: ninguna; /todas: ver otras; /texto: filtrar; /volver]: ',
                                  suggested, skills, 'Skills:', default=selected, multiple=True, all_options=optional_skills)
                step = 'context'
            elif step == 'context':
                label = INPUT_LABELS.get(workflow, 'Entrada principal')
                print(f'{label} actual: {context or "(vacío)"}')
                context = preserve_line(f'{label} [Enter: conservar/inferir; /limpiar; /volver; /preview]: ', context)
                step = 'locator' if repo and workflow in UNIT_WORKFLOWS else 'feedback'
            elif step == 'locator':
                print(f'Issue/PR actual: {locator or "(vacío)"}')
                raw = preserve_line('Issue/PR (número, #número o URL) [Enter: conservar/inferir; /limpiar; /volver; /preview]: ', locator)
                try:
                    locator = locator_value(raw) if raw else ''
                except argparse.ArgumentTypeError as exc:
                    print(str(exc))
                    continue
                step = 'feedback'
            elif step == 'feedback':
                feedback = ask_multiline('Comentario del PM — PM_FEEDBACK_HUMANO', feedback)
                step = 'question'
            elif step == 'question':
                question = ask_multiline('Pregunta del PM — PM_QUESTION_HUMANO', question)
                step = 'preview'
            elif step == 'preview':
                content = render(workflow, selected, context, locator, workflows, skills, templates,
                                 repo=repo, feedback=feedback, question=question, local_only=local_only)
                print('\n--- Vista previa del prompt ---\n' + content + '--- Fin de vista previa ---')
                print(f'Destino actual: {destination}. Al guardar se eliminarán los prompts anteriores identificados del selector en esa carpeta, después de escribir el nuevo.')
                action = ask_line('[G]uardar / [E]ditar / [C]ancelar / [V]olver: ').lower()
                if action in ('c', 'cancelar'):
                    print('Cancelado; no se guardó ni eliminó ningún prompt.')
                    return 0
                if action in ('v', 'volver'):
                    step = 'question'
                elif action in ('e', 'editar'):
                    step = 'repo'
                elif action in ('g', 'guardar'):
                    step = 'directory'
                else:
                    print('Acción desconocida.')
            elif step == 'directory':
                raw = ask_line(f'Carpeta de salida [{destination}]: ')
                try:
                    destination = output_path(raw) if raw else destination
                except ValueError as exc:
                    print(exc)
                    continue
                print(f'Se guardará en {destination}; tras guardar se reemplazarán solo prompts anteriores del selector en esa carpeta.')
                path, failures = save_prompt(destination, content)
                print(f'Prompt guardado: {path}')
                try:
                    save_config(repo, destination)
                except (ValueError, OSError):
                    print('El prompt se guardó, pero no se pudo guardar la configuración.', file=sys.stderr)
                    return 1
                if failures:
                    print('No se pudieron eliminar algunos prompts anteriores: ' + '; '.join(failures), file=sys.stderr)
                    return 1
                step = 'again'
            elif step == 'again':
                again = ask_line('[M]isma operación / [N]ueva selección / cambiar [R]epositorio / [S]alir: ').lower()
                if again not in ('', 's', 'salir', 'm', 'misma', 'n', 'nueva', 'r', 'repositorio'):
                    print('Acción desconocida.')
                    continue
                # PM content belongs to one operation only; never reuse it automatically.
                context = locator = feedback = question = ''
                if again in ('m', 'misma'):
                    step = 'context'
                elif again in ('n', 'nueva'):
                    selected = []
                    step = 'workflow'
                elif again in ('r', 'repositorio'):
                    selected = []
                    step = 'repo'
                else:
                    return 0
        except Preview:
            step = 'preview'
        except SensitiveInput as exc:
            print(str(exc))
            if step == 'preview':
                print('Revisa el contexto y los campos del PM, o cancela; usa /limpiar para borrar un valor.')
                step = 'context'
        except Back:
            step = {'repo': 'repo', 'workflow': 'repo', 'skills': 'workflow',
                    'context': 'skills', 'locator': 'context', 'feedback': 'locator' if repo and workflow in UNIT_WORKFLOWS else 'context', 'question': 'feedback',
                    'preview': 'question', 'directory': 'preview', 'again': 'again'}[step]


def main(argv=None):
    parser = SafeParser(description='Genera y guarda un prompt Project OS; no ejecuta workflows.')
    parser.add_argument('--list', action='store_true', help='listar workflows y skills')
    parser.add_argument('--repo', help='repositorio owner/repo, indicado sin verificación remota')
    parser.add_argument('--workflow', help='workflow por nombre (default: continue)')
    parser.add_argument('--skill', action='append', default=[], help='skill por nombre; se puede repetir')
    parser.add_argument('--locator', type=locator_value, help='número o URL de issue/PR, o texto contextual')
    parser.add_argument('--objective', help='objetivo y contexto material')
    parser.add_argument('--feedback', help='comentario opcional del PM')
    parser.add_argument('--question', help='pregunta opcional del PM')
    parser.add_argument('--output-dir', help='carpeta de prompts; el wizard recuerda la última')
    parser.add_argument('--prototype', action='store_true', help='atajo implement + rapid-prototype; permite --skill adicional')
    args = parser.parse_args(argv)
    try:
        require_safe(args.repo, args.workflow, *args.skill, args.objective, args.feedback, args.question, args.output_dir)
    except SensitiveInput as exc:
        parser.error(str(exc))
    if args.list and (args.repo or args.workflow or args.skill or args.locator or args.objective or args.feedback or args.question or args.prototype):
        parser.error('--list no se combina con selección ni contexto')
    if args.prototype and args.workflow:
        parser.error('--prototype no se combina con --workflow')
    try:
        workflows, skills, templates = discover()
        names, skill_names = ordered(workflows), sorted(skills)
        if args.list:
            show('Workflows:', names, workflows)
            show('Skills:', skill_names, skills)
            return 0
        missing = [name for name in BASE_SKILLS if name not in skills]
        if missing:
            parser.error('faltan skills base o sus rutas no son seguras: ' + ', '.join(missing))
        workflow = 'implement' if args.prototype else (args.workflow or 'continue')
        selected = list(dict.fromkeys((['rapid-prototype'] if args.prototype else []) + args.skill))
        if workflow not in workflows:
            parser.error('workflow desconocido o ruta no segura')
        for skill in selected:
            if skill not in skills:
                parser.error('skill desconocida o ruta no segura')
        interactive = not (args.repo or args.workflow or args.skill or args.locator or args.objective or args.feedback or args.question or args.prototype)
        if interactive:
            config = load_config()
            destination = output_path(args.output_dir or config.get('output_dir') or DEFAULT_OUTPUT)
            return wizard(workflows, skills, templates, destination, config.get('repo', ''))
        repo = repo_value(args.repo) if args.repo else ''
        destination = output_path(args.output_dir or DEFAULT_OUTPUT)
        content = render(workflow, selected, args.objective or '', args.locator or '', workflows, skills, templates,
                         repo=repo, feedback=args.feedback or '', question=args.question or '', local_only=args.repo == '-')
        print('\n--- Vista previa del prompt ---\n' + content + '--- Fin de vista previa ---')
        print(f'Destino: {destination}. Al guardar se eliminarán los prompts anteriores identificados del selector en esta carpeta, después de escribir el nuevo.')
        path, failures = save_prompt(destination, content)
        print(f'Prompt guardado: {path}')
        if failures:
            print('No se pudieron eliminar algunos prompts anteriores: ' + '; '.join(failures), file=sys.stderr)
            return 1
        return 0
    except KeyboardInterrupt:
        print('\nCancelado; no se modificaron prompts en esta operación.')
        return 0
    except EOFError:
        print('\nEntrada incompleta; no se guardó el prompt actual.', file=sys.stderr)
        return 2
    except SensitiveInput as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print('Error de entrada, acceso o escritura; revisa los argumentos y permisos.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
