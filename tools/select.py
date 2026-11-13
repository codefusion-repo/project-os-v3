#!/usr/bin/env python3
"""Asistente local de prompts Project OS; no ejecuta operaciones ni usa la red."""
import argparse
import importlib.util
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

# The script is named select.py; do not shadow Python's select extension when
# optional terminal libraries import asyncio/selectors from this entry point.
if sys.path and Path(sys.path[0]).resolve() == Path(__file__).resolve().parent:
    sys.path.pop(0)

try:
    import readline
except ImportError:
    readline = None

try:
    from prompt_toolkit import prompt as terminal_prompt
    from prompt_toolkit.completion import Completer, Completion
except ImportError:
    terminal_prompt = None
    Completer = object

ROOT = Path(__file__).resolve().parent.parent
_support_spec = importlib.util.spec_from_file_location('project_local', ROOT / 'tools/project_local.py')
project_local = importlib.util.module_from_spec(_support_spec)
_support_spec.loader.exec_module(project_local)
SOURCE_VERSION = None
SOURCE_DESCRIPTION = 'contenido local no equivalente a un SHA canónico verificado'
SOURCE_CHANGED = set()
TRACK_SOURCE = False
BASE = ('repo-context', 'github-traceability')
ORDER = ('continue', 'create', 'implement', 'review', 'close', 'release')
LABELS = {
    'continue': 'Fuente de continuación o último reporte',
    'create': 'Idea o requerimiento',
    'implement': 'Especificación, issue o reporte de corrección',
    'review': 'Reporte de ejecución o solicitud de review',
    'close': 'Resultado de validación o QA',
    'release': 'Evidencia de release-readiness',
}
UNIT_OPERATIONS = frozenset(('continue', 'implement', 'review', 'close', 'release'))
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
OWNED_NAME = re.compile(r'project-os-prompt-[0-9a-f]{32}\.md\Z')
MARKER = '<!-- project-os-v3-selector: generated-prompt v1 -->'
COMPLETIONS = ()
COMPLETION_DESCRIPTIONS = {}
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


class InputError(ValueError):
    pass


class Cancel(Exception):
    pass


class Back(Exception):
    pass


def check_sensitive(*values):
    if any(pattern.search(str(value)) for value in values if value is not None for pattern in SECRET_PATTERNS):
        raise InputError('Se detectó posible información sensible; retírala antes de continuar.')


def safe_path(value):
    check_sensitive(value)
    path = Path(value).expanduser()
    if '..' in path.parts:
        raise InputError('La carpeta no puede contener ..')
    return Path(os.path.abspath(path))


def directory_fd(value, create=False):
    """Open directory components without following symlinks."""
    path = safe_path(value)
    if not hasattr(os, 'O_DIRECTORY') or not hasattr(os, 'O_NOFOLLOW'):
        raise OSError('La plataforma no permite comprobar enlaces simbólicos.')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def repo_value(value):
    check_sensitive(value)
    value = value.strip()
    if value == '-':
        return ''
    parts = value.split('/')
    if (len(parts) != 2 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', parts[0])
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', parts[1]) or parts[1] in ('.', '..')):
        raise InputError('Usa owner/repo, o - para un experimento local sin repositorio.')
    return value


def locator_value(value):
    check_sensitive(value)
    value = value.strip()
    if not value or re.fullmatch(r'#?[1-9][0-9]*', value):
        return value
    url = urlsplit(value)
    if (url.scheme == 'https' and url.netloc.lower() == 'github.com' and not url.query and not url.fragment
            and re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/[1-9][0-9]*/?', url.path)):
        return value
    raise InputError('Usa número, #número o URL de issue/PR de github.com.')


def source(path):
    try:
        relative = path.relative_to(ROOT).as_posix()
        if SOURCE_VERSION:
            document = project_local.git_document(ROOT, SOURCE_VERSION, relative)
            if TRACK_SOURCE:
                try:
                    directory = project_local.open_directory(path.parent)
                    try:
                        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                        with os.fdopen(fd, 'rb') as stream:
                            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read() != document.encode('utf-8'):
                                SOURCE_CHANGED.add(relative)
                    finally:
                        os.close(directory)
                except (OSError, project_local.ProjectError):
                    SOURCE_CHANGED.add(relative)
            return document
        path.resolve(strict=True).relative_to(ROOT.resolve(strict=True))
        if path.is_file():
            return path.read_text(encoding='utf-8')
    except (OSError, ValueError, RuntimeError, project_local.ProjectError):
        pass
    raise InputError('No se pudo leer un documento del kit de forma segura.')


def discover():
    operations, skills, templates = {}, {}, {}
    if SOURCE_VERSION:
        tree = project_local.git(ROOT, 'ls-tree', '-r', '--name-only', SOURCE_VERSION, '--', 'workflows', 'skills', 'templates')
        for entry in tree.stdout.decode('utf-8').splitlines():
            parts = Path(entry).parts
            if len(parts) == 2 and parts[0] == 'workflows' and entry.endswith('.md') and NAME.fullmatch(Path(entry).stem):
                operations[Path(entry).stem] = ROOT / entry
            elif len(parts) == 3 and parts[0] == 'skills' and parts[2] == 'SKILL.md' and NAME.fullmatch(parts[1]):
                skills[parts[1]] = ROOT / entry
            elif len(parts) == 2 and parts[0] == 'templates' and entry.endswith('.md') and NAME.fullmatch(Path(entry).stem):
                templates[Path(entry).stem] = ROOT / entry
        return operations, skills, templates
    for path in (ROOT / 'workflows').glob('*.md'):
        if NAME.fullmatch(path.stem):
            try:
                source(path)
            except InputError:
                continue
            operations[path.stem] = path
    for path in (ROOT / 'skills').glob('*/SKILL.md'):
        if NAME.fullmatch(path.parent.name):
            try:
                source(path)
            except InputError:
                continue
            skills[path.parent.name] = path
    for path in (ROOT / 'templates').glob('*.md'):
        if NAME.fullmatch(path.stem):
            try:
                source(path)
            except InputError:
                continue
            templates[path.stem] = path
    return operations, skills, templates


def description(path):
    for line in source(path).splitlines():
        line = line.strip()
        if line and not line.startswith(('#', '<!--')):
            return line
    return 'Sin descripción.'


def project_preferences(project):
    if project_local.private_tracked(project / '.project-os'):
        print('Hay archivos privados bajo seguimiento Git; no se leerá ni escribirá la configuración. Evalúa exposición histórica.', file=sys.stderr)
        return {'_blocked': True}
    data = project_local.read_config(project)
    if data is None:
        return None
    check_sensitive(data)
    if data.get('primary_repo'):
        repo_value(data['primary_repo'])
    for repo in data.get('related_repos', []):
        repo_value(repo)
    for repo, checkout in data.get('checkouts', {}).items():
        repo_value(repo)
        project_local.path(checkout)
    preference_folder(project, data)
    return data


def preference_folder(project, config):
    value = config.get('prompt_dir', '.project-os/prompts') if config else '.project-os/prompts'
    check_sensitive(value)
    return project_local.path(value if Path(value).is_absolute() else project / value)


def save_project_preferences(project, config, repo, folder):
    preferences = dict(config or {'version': 1, 'name': project.name, 'related_repos': []})
    preferences['primary_repo'] = repo
    try:
        preferences['prompt_dir'] = folder.relative_to(project).as_posix()
    except ValueError:
        preferences['prompt_dir'] = str(folder)
    check_sensitive(preferences)
    print(project_local.save_config(project, preferences))
    return preferences


def owned_files(fd):
    found = []
    for name in os.listdir(fd):
        if not OWNED_NAME.fullmatch(name):
            continue
        try:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(handle, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if stat.S_ISREG(info.st_mode) and stream.readline(256).rstrip(b'\n') == MARKER.encode():
                    found.append((name, info.st_dev, info.st_ino))
        except OSError:
            continue
    return found


def save_prompt(folder, content):
    folder = safe_path(folder)
    check_sensitive(content)
    temporary = '.prompt-' + uuid.uuid4().hex
    name = 'project-os-prompt-' + uuid.uuid4().hex + '.md'
    project_local.preflight(folder, prepare=False, names=(temporary, name))
    fd = directory_fd(folder, create=True)
    try:
        previous = owned_files(fd)
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=fd)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
            raise
        failures = []
        still_owned = set(owned_files(fd))
        for old_name, device, inode in previous:
            if (old_name, device, inode) not in still_owned:
                continue
            try:
                info = os.stat(old_name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == (device, inode):
                    os.unlink(old_name, dir_fd=fd)
            except FileNotFoundError:
                continue
            except OSError:
                failures.append(old_name)
        return folder / name, failures
    finally:
        os.close(fd)


def reference_warning(repo, locator, *values):
    if not locator:
        return ''
    parts = urlsplit(locator).path.strip('/').split('/') if locator.startswith('https://') else []
    if len(parts) == 4 and parts[2] == 'issues':
        return ''
    expected = (parts[3] if len(parts) == 4 else locator.lstrip('#')).lstrip('0') or '0'
    text = '\n'.join(values)
    numbers = re.findall(r'(?i)\b(?:pr|pull\s+request)\s*(?:#|n[úu]m(?:ero)?\.?\s*)?(\d+)\b', text)
    urls = re.findall(r'(?i)https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)', text)
    if (any((n.lstrip('0') or '0') != expected for n in numbers)
            or any((n.lstrip('0') or '0') != expected or (repo and f'{o}/{r}'.lower() != repo.lower()) for o, r, n in urls)
            or (len(parts) == 4 and repo and '/'.join(parts[:2]).lower() != repo.lower())):
        return 'Posible inconsistencia entre el locator y el PR indicado; verifica antes de actuar.'
    return ''


def render(operation, selected, context, locator, operations, skills, templates, repo='', feedback='', question='', local_only=False):
    global TRACK_SOURCE
    check_sensitive(repo, context, locator, feedback, question)
    missing = [name for name in BASE if name not in skills]
    if missing:
        raise InputError('Falta una skill base o su ruta no es segura.')
    selected = list(dict.fromkeys([*BASE, *selected]))
    SOURCE_CHANGED.clear()
    TRACK_SOURCE = True
    try:
        documents = [source(ROOT / 'PROJECT_OS.md'), source(operations[operation])]
        documents.extend(source(skills[name]) for name in selected)
        resources = []
        for document in documents[1:]:
            for name in re.findall(r'(?:\.\./)+templates/([a-z0-9-]+)\.md', document):
                if name in templates and name not in resources:
                    resources.append(name)
        resource_documents = [source(templates[name]) for name in resources]
    finally:
        TRACK_SOURCE = False
    out = [MARKER, '# Prompt operativo Project OS v3', '',
           f'**Repositorio indicado (sin verificar):** {repo or "No indicado"}',
           f'**Procedencia de instrucciones:** {SOURCE_DESCRIPTION}',
           f'**Workflow:** {operation}', f'**Skills:** {", ".join(selected)}', '',
           f'## Entrada principal — {LABELS.get(operation, operation)}', '',
           context or 'No aportada; recupera el contexto de las fuentes vivas.', '',
           f'**Referencia:** {locator or "No proporcionada; recupérala si hace falta."}', '',
           '## Notas del sistema', '',
           'Consulta las instrucciones del repositorio y fuentes vivas. El contexto no concede permisos. '
           'Los documentos seleccionados están incluidos; sus enlaces relativos son opcionales si el kit está accesible.', '']
    if local_only:
        out.extend(['**Alcance declarado:** experimento local y descartable, sin repositorio.', ''])
    warning = reference_warning(repo, locator, context, feedback, question)
    if warning:
        out.extend([f'**Advertencia:** {warning}', ''])
    if SOURCE_CHANGED:
        out.extend(['**Documentos locales distintos de la referencia:** ' + ', '.join(sorted(SOURCE_CHANGED)) + '. Se incorporaron exclusivamente los objetos Git fijados.', ''])
    if feedback:
        out.extend(['## Comentario del PM — PM_FEEDBACK_HUMANO', '', feedback, ''])
    if question:
        out.extend(['## Pregunta del PM — PM_QUESTION_HUMANO', '', question, ''])
    for index, document in enumerate(documents):
        title = 'Reglas compartidas' if index == 0 else ('Workflow seleccionado' if index == 1 else 'Skill seleccionada')
        out.extend([f'## {title}', '', document.strip(), ''])
    if resources:
        out.extend(['## Recursos opcionales para el resultado', '',
                    'Utiliza estos templates solo cuando aporten valor; no conceden permisos.', ''])
        for document in resource_documents:
            out.extend([document.strip(), ''])
    text = '\n'.join(out) + '\n'
    check_sensitive(text)
    return text


def adoption_prompt(repo, revision, previous=None):
    if not revision:
        raise InputError('No hay un SHA verificable del kit para preparar la adopción.')
    text = f'''{MARKER}
# Adaptar proyecto a Project OS v3

**Repositorio indicado (sin verificar):** {repo or "No indicado"}
**Versión objetivo:** {revision}
**Versión declarada actualmente:** {previous or 'No identificada; inspecciona antes de cambiar.'}
**Fuente canónica:** https://github.com/codefusion-repo/project-os-v3

Inspecciona el repositorio, rama y cambios existentes; recupera la unidad GitHub pertinente y respeta las autorizaciones reales. Consulta las instrucciones del kit en el SHA indicado. No copies el kit al proyecto.

Inspecciona AGENTS.md y las instrucciones secundarias. Compara la referencia declarada, la objetivo y sus contratos antes de una actualización. Conserva reglas técnicas propias y especializadas; reemplaza instrucciones operativas v2 o copias antiguas contradictorias por un único bootstrap principal. Incluye en AGENTS.md la línea `Project-OS-Version: {revision}`, el repositorio canónico, la ruta PROJECT_OS.md, carga de workflows y skills pertinentes, seguridad, permisos y trazabilidad. No insertes rutas locales. No elimines archivos desconocidos; inventaría componentes obsoletos y solicita autorización si retirarlos es destructivo.

Incorpora `.project-os/` a .gitignore; verifica si ya hay archivos privados versionados sin leerlos ni exponerlos y prepara una corrección revisable. No crees configuración privada del dispositivo del PM desde otro entorno. Documenta relaciones multirrepositorio solo si son verificadas, necesarias y su divulgación está autorizada. Preserva instrucciones y archivos ajenos.

Presenta el diff, valida y registra evidencia; publica commits y una nueva entrada histórica en el issue/PR existente solo con autorización. Merge, cierre, release y deploy requieren autorización separada. Si no dispones de la versión canónica o acceso, explica el límite y continúa lo seguro.
'''
    check_sensitive(text)
    return text


def prepare_terminal():
    """Ask compatible terminals to send a paste as a single editing event."""
    if readline is None:
        return False
    try:
        readline.parse_and_bind('set enable-bracketed-paste on')
        readline.parse_and_bind('tab: complete')
        return True
    except (AttributeError, ValueError):
        return False


def ask(prompt, current='', allow_back=True, strip=False, editable=False):
    """Read one logical input. Bracketed paste can contain multiple lines."""
    while True:
        if terminal_prompt is not None and sys.stdin.isatty() and sys.stdout.isatty():
            value = terminal_prompt(prompt, default=current if editable else '',
                                    completer=LiveCompleter() if COMPLETIONS else None,
                                    complete_while_typing=bool(COMPLETIONS))
        else:
            value = input(prompt)
        value = value.replace('\r\n', '\n').replace('\r', '\n')
        try:
            check_sensitive(value)
        except InputError as exc:
            print(str(exc))
            continue
        if value == '/cancelar':
            raise Cancel
        if value == '/volver' and allow_back:
            raise Back
        if value == '/limpiar':
            return ''
        if not value:
            return current
        return value.strip() if strip else value


def complete_from(candidates, descriptions=None):
    """Offer name completion in the stdlib terminal editor when available."""
    global COMPLETIONS, COMPLETION_DESCRIPTIONS
    COMPLETIONS = tuple(candidates)
    COMPLETION_DESCRIPTIONS = descriptions or {}
    if readline is None:
        return
    def complete(text, index):
        matches = [name for name in candidates if name.lower().startswith(text.lower())]
        return matches[index] if index < len(matches) else None
    readline.set_completer(complete)


class LiveCompleter(Completer):
    """Live suggestions for the current input, without a parallel catalog."""
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        prefix = text.rsplit(',', 1)[-1].lstrip()
        for name in COMPLETIONS:
            details = COMPLETION_DESCRIPTIONS.get(name, '')
            if prefix.casefold() in name.casefold() or prefix.casefold() in details.casefold():
                yield Completion(name, start_position=-len(prefix), display_meta=details)


def clear_completion():
    global COMPLETIONS, COMPLETION_DESCRIPTIONS
    COMPLETIONS = ()
    COMPLETION_DESCRIPTIONS = {}
    if readline is not None:
        readline.set_completer(None)


def choose_operation(operations, current='continue', session_controls=True):
    names = sorted(operations, key=lambda name: (ORDER.index(name) if name in ORDER else len(ORDER), name))
    visible = names
    print('\n1/3 — Buscar y seleccionar operación')
    print('Escribe nombre, número o texto para buscar. Enter conserva la operación; /cancelar sale.')
    if session_controls:
        print('Usa /adoptar para adaptar proyecto, /repo para cambiar repositorio o /carpeta para cambiar destino.')
    while True:
        for index, name in enumerate(visible, 1):
            print(f'  {index}. {name} — {description(operations[name])}')
        complete_from(names, {name: description(operations[name]) for name in names})
        try:
            query = ask(f'Operación [{current}]: ', current=current, strip=True)
        finally:
            clear_completion()
        if session_controls and query in ('/repo', '/carpeta', '/adoptar'):
            return query
        if query == '/':
            visible = names
            continue
        if query.isdecimal() and 1 <= int(query) <= len(visible):
            return visible[int(query) - 1]
        if query in operations:
            return query
        matches = [name for name in names if query.casefold() in name.casefold() or query.casefold() in description(operations[name]).casefold()]
        if not matches:
            if session_controls:
                print('Sin coincidencias: se usará continue y el texto como pregunta del PM.')
                return ('continue', query)
            print('Sin coincidencias. Prueba otra búsqueda o / para ver todas.')
            visible = names
        else:
            visible = matches


def choose_skills(operation, operations, skills, current, edit=False):
    selected = list(dict.fromkeys(name for name in current if name not in BASE))
    suggested = list(dict.fromkeys(name for name in re.findall(r'\.\./skills/([a-z0-9-]+)/SKILL\.md', source(operations[operation]))
                                   if name in skills and name not in BASE))
    choices = suggested
    print('\nSkills base: repo-context y github-traceability (automáticas).')
    while True:
        print('Skills sugeridas:')
        for index, name in enumerate(choices, 1):
            print(f'  {index}. {name} — {description(skills[name])}')
        print('Actuales:', ', '.join(selected) if selected else '(ninguna)')
        complete_from(choices, {name: description(skills[name]) for name in choices})
        try:
            raw = ask('Skills [Enter conserva; /todas; /limpiar; /volver]: ', current=','.join(selected), strip=True, editable=edit)
        finally:
            clear_completion()
        if raw == '/todas':
            choices = sorted(name for name in skills if name not in BASE)
            continue
        if not raw:
            return []
        values = []
        for item in raw.split(','):
            item = item.strip()
            if item.isdecimal() and 1 <= int(item) <= len(choices):
                item = choices[int(item) - 1]
            if item not in skills or item in BASE:
                print('Skill desconocida; usa nombre, número o /todas.')
                break
            if item not in values:
                values.append(item)
        else:
            return values


def ask_repo(current):
    while True:
        raw = ask(f'Repositorio owner/repo [{current or "sin seleccionar"}; -: local descartable]: ', current=current, strip=True)
        try:
            return repo_value(raw)
        except InputError as exc:
            print(str(exc))


def ask_locator(current, edit=False):
    while True:
        raw = ask(f'Issue/PR opcional [{current or "sin referencia"}]: ', current=current, strip=True, editable=edit)
        try:
            return locator_value(raw)
        except InputError as exc:
            print(str(exc))


def fill_fields(operation, operations, skills, values, edit=False):
    print('\n2/3 — Completar datos de la operación')
    print('Pega texto directamente; Enter confirma. /limpiar borra, /volver cambia operación, /cancelar sale.')
    values['skills'] = choose_skills(operation, operations, skills, values['skills'], edit=edit)
    label = LABELS.get(operation, 'Contexto')
    for key, prompt in (('context', label), ('locator', 'Issue/PR'),
                        ('feedback', 'Comentario del PM'), ('question', 'Pregunta del PM')):
        if key == 'locator':
            if values['repo'] and operation in UNIT_OPERATIONS:
                values[key] = ask_locator(values[key], edit=edit)
            continue
        current = values[key]
        print(f'\n{prompt} actual: {current if current else "(vacío)"}')
        values[key] = ask(f'{prompt} [Enter conserva/omite]: ', current=current, editable=edit)
    return values


def operation_prompt(operation, operations, skills, templates, values):
    return render(operation, values['skills'], values['context'], values['locator'], operations, skills, templates,
                  repo=values['repo'], feedback=values['feedback'], question=values['question'], local_only=values['local_only'])


def preview(operation, content, folder):
    print('\n3/3 — Vista previa')
    print(f'Operación: {operation} | Carpeta: {folder}')
    print('Al guardar se reemplazan solo los prompts anteriores del selector de esta carpeta, después de escribir el nuevo.')
    print('\n' + content + '\n--- Fin de vista previa ---')
    while True:
        action = ask('[G]uardar / [E]ditar / [O]tra operación / [C]ancelar: ', strip=True).lower()
        if action in ('g', 'guardar', 'write', 'w'):
            return 'write'
        if action in ('e', 'editar', 'edit'):
            return 'edit'
        if action in ('o', 'otra', 'operation'):
            return 'operation'
        if action in ('c', 'cancelar', 'cancel'):
            raise Cancel
        print('Elige guardar, editar, otra operación o cancelar.')


def interactive(operations, skills, templates, folder, repo, project=None, config=None):
    if sys.stdin.isatty() and terminal_prompt is None and not prepare_terminal():
        print('Este Python no dispone de edición segura de terminal; usa los flags del CLI para texto multilínea.', file=sys.stderr)
        return 1
    operation, last_path = 'continue', None
    protection_checked = False
    values = {'repo': repo, 'local_only': False, 'skills': [], 'context': '', 'locator': '', 'feedback': '', 'question': ''}
    if project is not None and project_local.version(project) is None:
        print('Proyecto sin versión fijada: usa /adoptar para preparar su integración.')
    while True:
        print(f'\nRepositorio: {values["repo"] or "(sin seleccionar)"} | Carpeta: {folder}')
        try:
            selection = choose_operation(operations, current=operation)
            if isinstance(selection, tuple):
                operation, values['question'] = selection
            else:
                operation = selection
            if operation == '/repo':
                values['repo'] = ask_repo(values['repo'])
                values['local_only'] = not values['repo']
                operation = 'continue'
                continue
            if operation == '/carpeta':
                while True:
                    try:
                        folder = safe_path(ask(f'Carpeta [{folder}]: ', current=str(folder), strip=True))
                        break
                    except (InputError, ValueError):
                        print('Carpeta inválida.')
                operation = 'continue'
                continue
            adopting = operation == '/adoptar'
            if not values['repo'] and not values['local_only']:
                values['repo'] = ask_repo('')
                values['local_only'] = not values['repo']
            if project is not None and config is None:
                try:
                    config = save_project_preferences(project, config, values['repo'], folder)
                    protection_checked = True
                except (project_local.ProjectError, OSError):
                    print('No se pudo proteger la configuración local; solo se permite guardar en un destino externo protegido.', file=sys.stderr)
                    config = {'_blocked': True}
                    protection_checked = True
            elif project is not None and not protection_checked and not (config or {}).get('_blocked'):
                try:
                    print(project_local.preflight(project / '.project-os', prepare=True))
                except (project_local.ProjectError, OSError):
                    print('No se pudo proteger la configuración local; solo se permite guardar en un destino externo protegido.', file=sys.stderr)
                    config = {'_blocked': True}
                protection_checked = True
            if not adopting:
                values = fill_fields(operation, operations, skills, values)
            while True:
                content = adoption_prompt(values['repo'], SOURCE_VERSION) if adopting else operation_prompt(operation, operations, skills, templates, values)
                action = preview(operation, content, folder)
                if action == 'operation':
                    values.update(skills=[], context='', locator='', feedback='', question='')
                    break
                if action == 'edit':
                    # Keep repo and all current fields; operation and skills remain editable.
                    operation = choose_operation(operations, current=operation, session_controls=False)
                    adopting = False
                    values = fill_fields(operation, operations, skills, values, edit=True)
                    continue
                if folder is None or (config or {}).get('_blocked'):
                    folder = safe_path(ask('Selecciona carpeta externa para guardar: ', strip=True))
                if project is not None and not (config or {}).get('_blocked'):
                    project_local.preflight(project / '.project-os', prepare=False)
                if project is not None and (config or {}).get('_blocked'):
                    try:
                        folder.relative_to(project)
                    except ValueError:
                        pass
                    else:
                        raise InputError('Selecciona un destino fuera del proyecto desprotegido.')
                print(project_local.preflight(folder, prepare=False))
                last_path, failures = save_prompt(folder, content)
                print(f'Prompt guardado: {last_path}')
                try:
                    if project is not None and not (config or {}).get('_blocked'):
                        config = save_project_preferences(project, config, values['repo'], folder)
                except (OSError, ValueError):
                    print('El prompt se guardó, pero no se pudo guardar la configuración.', file=sys.stderr)
                    return 1
                if failures:
                    print('No se pudieron quitar algunos prompts anteriores.', file=sys.stderr)
                    return 1
                while True:
                    action = ask('[N]ueva / [M]isma / [E]ditar / [P]ath / [S]alir: ', strip=True).lower()
                    if action in ('p', 'path'):
                        print(f'Prompt actual: {last_path}')
                    elif action in ('e', 'editar', 'edit'):
                        operation = choose_operation(operations, current=operation, session_controls=False)
                        adopting = False
                        values = fill_fields(operation, operations, skills, values, edit=True)
                        break
                    elif action in ('n', 'nueva', 'new'):
                        adopting = False
                        operation = 'continue'
                        values.update(skills=[], context='', locator='', feedback='', question='')
                        break
                    elif action in ('m', 'misma', 'same'):
                        if adopting:
                            break
                        values.update(context='', locator='', feedback='', question='')
                        values = fill_fields(operation, operations, skills, values)
                        break
                    elif action in ('s', 'salir', 'exit'):
                        return 0
                    else:
                        print('Elige nueva, misma, editar, path o salir.')
                if action in ('n', 'nueva', 'new'):
                    break
        except Back:
            print('Volviendo a elegir operación; se conservan los valores.')
            continue
        except Cancel:
            print('Cancelado; no se escribió el prompt actual.')
            return 0
        except InputError as exc:
            print(str(exc))
            continue


class Parser(argparse.ArgumentParser):
    def error(self, message):
        if message.startswith('unrecognized arguments:') or any(pattern.search(message) for pattern in SECRET_PATTERNS):
            message = 'Argumentos inválidos o información sensible detectada; consulta --help.'
        super().error(message)


def select_project(explicit, interactive_mode):
    if explicit:
        root = project_local.path(explicit)
        if not root.is_dir():
            raise InputError('La ruta del proyecto no es un directorio accesible.')
        if root == ROOT:
            raise InputError('Selecciona un proyecto separado de la instalación central.')
        return root, project_preferences(root), ''
    candidates = project_local.discover_projects(Path.cwd(), exclude=ROOT)
    # The installation is not a persistent project profile.
    candidates = [(root, project_preferences(root)) for root, _ in candidates if root != ROOT]
    if any(data.get('_blocked') for _, data in candidates):
        print('Hay archivos privados bajo seguimiento Git; no se leerá esa configuración.', file=sys.stderr)
    if candidates:
        if len(candidates) > 1:
            signatures = {(data.get('primary_repo', ''), str(preference_folder(root, data))) for root, data in candidates}
            if len(signatures) > 1:
                if not interactive_mode:
                    raise InputError('Configuraciones anidadas en conflicto; usa --project para elegir.')
                print('Hay proyectos anidados con preferencias distintas:')
                for index, (root, _) in enumerate(candidates, 1):
                    print(f'  {index}. {root}')
                while True:
                    choice = ask('Elige proyecto por número: ', strip=True)
                    if choice.isdecimal() and 1 <= int(choice) <= len(candidates):
                        return (*candidates[int(choice) - 1], '')
                    print('Selecciona un número válido.')
        return (*candidates[0], '')
    if not interactive_mode:
        return None, None, ''
    while True:
        value = ask('Ruta del proyecto o repositorio owner/repo: ', strip=True)
        try:
            root = project_local.path(value)
            if value and root.is_dir():
                if root == ROOT:
                    print('Selecciona un proyecto separado de la instalación central.')
                    continue
                return root, project_preferences(root), ''
        except (project_local.ProjectError, OSError):
            pass
        if value and not value.startswith(('/', '.', '~')) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
            return None, None, repo_value(value)
        print('Indica un directorio local accesible o owner/repo.')


def choose_sources(project):
    global SOURCE_VERSION, SOURCE_DESCRIPTION
    requested = project_local.version(project) if project is not None else None
    if requested:
        SOURCE_VERSION = project_local.commit(ROOT, requested)
        SOURCE_DESCRIPTION = f'commit {SOURCE_VERSION}, documentos recuperados íntegramente de objetos Git locales (versión fijada por el proyecto)'
        head = project_local.git(ROOT, 'rev-parse', '--verify', 'HEAD', check=False).stdout.decode('ascii', 'ignore').strip()
        if head != SOURCE_VERSION:
            print(f'Versión fijada {SOURCE_VERSION}; instalación en {head or "HEAD no disponible"}. Se usarán los documentos fijados; para actualizar usa --adopt --target-version <SHA>.')
        return
    result = project_local.git(ROOT, 'rev-parse', '--show-toplevel', check=False)
    if result.returncode == 0 and Path(os.fsdecode(result.stdout).strip()) == ROOT:
        head = project_local.git(ROOT, 'rev-parse', '--verify', 'HEAD', check=False)
        revision = head.stdout.decode('ascii', 'ignore').strip()
        if re.fullmatch(r'[0-9a-f]{40}', revision):
            SOURCE_VERSION = project_local.commit(ROOT, revision)
            SOURCE_DESCRIPTION = f'commit {SOURCE_VERSION}, documentos recuperados íntegramente de objetos Git locales; proyecto sin versión fijada'
            return
    SOURCE_VERSION = None
    SOURCE_DESCRIPTION = 'contenido local no equivalente a un SHA canónico verificado; proyecto sin versión fijada'


def configure_project(project, config, args):
    if project is None or (config or {}).get('_blocked'):
        raise InputError('Selecciona un proyecto local sin archivos privados bajo seguimiento Git.')
    data = dict(config or {'version': 1, 'name': project.name, 'related_repos': []})
    if args.migrate_legacy:
        try:
            directory = project_local.open_directory(ROOT / '.project-os')
            try:
                fd = os.open('config.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, encoding='utf-8') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise InputError('La configuración antigua no es un archivo regular.')
                    legacy = json.load(stream)
            finally:
                os.close(directory)
        except (OSError, ValueError):
            raise InputError('La configuración antigua no es válida; se conserva.')
        if not isinstance(legacy, dict) or set(legacy) - {'repo', 'output_dir'} or not all(isinstance(x, str) for x in legacy.values()):
            raise InputError('La configuración antigua no es reconocida; se conserva.')
        check_sensitive(legacy)
        if not args.repo or repo_value(args.repo) != legacy.get('repo'):
            raise InputError('Indica --repo con el repositorio antiguo para asociarlo explícitamente al proyecto.')
        if config is not None:
            raise InputError('Ya existe una configuración del proyecto; no se reemplazará mediante migración.')
        if legacy.get('output_dir') and not args.output_dir:
            previous_folder = project_local.path(legacy['output_dir'])
            try:
                data['prompt_dir'] = previous_folder.relative_to(project).as_posix()
            except ValueError:
                print('El destino antiguo no pertenece al proyecto; se conserva sin reutilizar para evitar mezclar proyectos.')
        print('Se conservarán la configuración y prompts anteriores. El destino central no se comparte con el proyecto.')
    if args.repo is not None:
        data['primary_repo'] = repo_value(args.repo)
    if args.name is not None:
        data['name'] = args.name
    if args.related_repo is not None:
        data['related_repos'] = list(dict.fromkeys(repo_value(value) for value in args.related_repo))
    if args.checkout is not None:
        paths = {}
        for entry in args.checkout:
            name, separator, location = entry.partition('=')
            if not separator:
                raise InputError('Usa --checkout owner/repo=/ruta/local.')
            paths[repo_value(name)] = str(project_local.path(location))
        data['checkouts'] = paths
    if args.output_dir:
        folder = project_local.path(args.output_dir)
        try:
            data['prompt_dir'] = folder.relative_to(project).as_posix()
        except ValueError:
            data['prompt_dir'] = str(folder)
    else:
        data.setdefault('prompt_dir', '.project-os/prompts')
    check_sensitive(data)
    print(project_local.save_config(project, data))
    print('Configuración local guardada en el proyecto; las instrucciones versionadas no se han modificado.')


def main(argv=None):
    parser = Parser(description='Genera prompts Markdown sin ejecutar operaciones.')
    parser.add_argument('--list', action='store_true', help='listar operaciones y skills')
    parser.add_argument('--project', help='raíz local del proyecto o workspace')
    parser.add_argument('--adopt', action='store_true', help='preparar encargo de adaptación')
    parser.add_argument('--target-version', help='SHA completo objetivo de adaptación o actualización')
    parser.add_argument('--configure', action='store_true', help='guardar preferencias locales explícitamente')
    parser.add_argument('--migrate-legacy', action='store_true', help='migrar preferencias centrales antiguas al proyecto elegido')
    parser.add_argument('--name', help='nombre local del proyecto (con --configure)')
    parser.add_argument('--related-repo', action='append', help='repositorio relacionado local (con --configure)')
    parser.add_argument('--checkout', action='append', help='checkout local owner/repo=/ruta (con --configure)')
    parser.add_argument('--repo', help='repositorio owner/repo')
    parser.add_argument('--workflow', help='operación (default: continue)')
    parser.add_argument('--skill', action='append', default=[])
    parser.add_argument('--locator', help='número o URL de issue/PR')
    parser.add_argument('--objective', help='entrada principal de la operación')
    parser.add_argument('--feedback', help='comentario del PM')
    parser.add_argument('--question', help='pregunta del PM')
    parser.add_argument('--output-dir', help='carpeta de salida explícita')
    parser.add_argument('--prototype', action='store_true', help='implement + rapid-prototype')
    args = parser.parse_args(argv)
    try:
        check_sensitive(args.project, args.repo, args.workflow, *args.skill, args.locator, args.objective, args.feedback, args.question, args.output_dir, args.name, args.related_repo, args.checkout, args.target_version)
        if args.list:
            operations, skills, templates = discover()
            for name in ORDER:
                if name in operations:
                    print(f'{name} — {description(operations[name])}')
            for name in sorted(skills):
                print(f'{name} — {description(skills[name])}')
            return 0
        if args.prototype and args.workflow:
            parser.error('--prototype no se combina con --workflow')
        if args.adopt and (args.workflow or args.prototype or args.skill or args.locator or args.objective or args.feedback or args.question):
            parser.error('--adopt no se combina con opciones de operación')
        if args.target_version and not args.adopt:
            parser.error('--target-version requiere --adopt')
        if (args.name or args.related_repo or args.checkout) and not args.configure:
            parser.error('--name, --related-repo y --checkout requieren --configure')
        if args.migrate_legacy and not args.configure:
            parser.error('--migrate-legacy requiere --configure')
        if args.configure and (args.adopt or args.workflow or args.skill or args.locator or args.objective or args.feedback or args.question or args.prototype):
            parser.error('--configure no se combina con generación de prompts')
        cli = bool(args.repo or args.workflow or args.skill or args.locator or args.objective or args.feedback or args.question or args.prototype or args.adopt or args.configure)
        project, config, remote = select_project(args.project, not cli)
        if args.configure:
            configure_project(project, config, args)
            return 0
        choose_sources(None if args.adopt and args.target_version else project)
        operations, skills, templates = discover()
        if any(name not in skills for name in BASE):
            parser.error('Faltan skills base o sus rutas no son seguras.')
        operation = 'implement' if args.prototype else (args.workflow or 'continue')
        selected = list(dict.fromkeys((['rapid-prototype'] if args.prototype else []) + args.skill))
        if operation not in operations or any(name not in skills for name in selected):
            parser.error('Operación o skill desconocida.')
        if args.output_dir:
            folder = safe_path(args.output_dir)
        elif project is not None:
            folder = preference_folder(project, config)
        else:
            folder = None
        repo = repo_value(args.repo) if args.repo else (config or {}).get('primary_repo', remote)
        if not cli:
            if (ROOT / '.project-os/config.json').exists():
                print('Hay configuración central antigua; no se utiliza automáticamente. Conserva sus archivos hasta migrar preferencias de forma explícita.')
            return interactive(operations, skills, templates, folder, repo, project, config)
        locator = locator_value(args.locator or '')
        target_version = project_local.commit(ROOT, args.target_version) if args.target_version else SOURCE_VERSION
        content = adoption_prompt(repo, target_version, project_local.version(project) if project else None) if args.adopt else render(
            operation, selected, args.objective or '', locator, operations, skills, templates,
            repo=repo, feedback=args.feedback or '', question=args.question or '', local_only=args.repo == '-')
        print('\n--- Vista previa ---\n' + content)
        if folder is None:
            print('Solo vista previa: selecciona explícitamente --output-dir o un proyecto local para guardar.')
            return 0
        if project is not None and not (config or {}).get('_blocked'):
            try:
                print(project_local.preflight(project / '.project-os', prepare=False))
            except project_local.ProjectError:
                config = {'_blocked': True}
                print('La configuración del proyecto no está protegida; solo se admite un destino externo explícito.', file=sys.stderr)
        if project is not None and (config or {}).get('_blocked'):
            if not args.output_dir:
                print('Solo vista previa: la configuración local está bajo seguimiento Git; elige --output-dir externo.')
                return 0
            try:
                folder.relative_to(project)
            except ValueError:
                pass
            else:
                raise InputError('El destino debe estar fuera del proyecto desprotegido.')
        print(project_local.preflight(folder, prepare=False))
        print('Se reemplazarán solo prompts anteriores del selector después de escribir el nuevo.')
        output, failures = save_prompt(folder, content)
        print(f'Prompt guardado: {output}')
        if failures:
            print('No se pudieron quitar algunos prompts anteriores.', file=sys.stderr)
            return 1
        return 0
    except (InputError, project_local.ProjectError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print('No se pudo leer o escribir de forma segura; revisa los permisos y la plataforma.', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt, Cancel):
        print('\nCancelado; no se escribió el prompt actual.')
        return 0


if __name__ == '__main__':
    sys.exit(main())
