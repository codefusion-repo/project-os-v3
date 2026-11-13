#!/usr/bin/env python3
"""Asistente local de prompts Project OS; no ejecuta operaciones ni usa la red."""
import argparse
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
DEFAULT_DIR = ROOT / '.project-os' / 'prompts'
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
        path.resolve(strict=True).relative_to(ROOT.resolve(strict=True))
        if path.is_file():
            return path.read_text(encoding='utf-8')
    except (OSError, ValueError, RuntimeError):
        pass
    raise InputError('No se pudo leer un documento del kit de forma segura.')


def discover():
    operations, skills, templates = {}, {}, {}
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


def load_config():
    try:
        fd = directory_fd(ROOT / '.project-os')
    except FileNotFoundError:
        return {}
    try:
        try:
            config_fd = os.open('config.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return {}
        with os.fdopen(config_fd, encoding='utf-8') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise InputError('La configuración local no es un archivo regular.')
            data = json.load(stream)
        if not isinstance(data, dict) or set(data) - {'repo', 'output_dir'} or any(not isinstance(v, str) for v in data.values()):
            raise InputError('La configuración local contiene valores no admitidos.')
        if data.get('repo'):
            data['repo'] = repo_value(data['repo'])
        if data.get('output_dir'):
            data['output_dir'] = str(safe_path(data['output_dir']))
        return data
    finally:
        os.close(fd)


def save_config(repo, folder):
    prefs = {'output_dir': str(safe_path(folder))}
    if repo:
        prefs['repo'] = repo_value(repo)
    fd = directory_fd(ROOT / '.project-os', create=True)
    temporary = '.config-' + uuid.uuid4().hex
    try:
        try:
            existing = os.stat('config.json', dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(existing.st_mode):
                raise InputError('La configuración local no es un archivo regular seguro.')
        except FileNotFoundError:
            pass
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump(prefs, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, 'config.json', src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
            raise
    finally:
        os.close(fd)


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
    fd = directory_fd(folder, create=True)
    temporary = '.prompt-' + uuid.uuid4().hex
    name = 'project-os-prompt-' + uuid.uuid4().hex + '.md'
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
    check_sensitive(repo, context, locator, feedback, question)
    missing = [name for name in BASE if name not in skills]
    if missing:
        raise InputError('Falta una skill base o su ruta no es segura.')
    selected = list(dict.fromkeys([*BASE, *selected]))
    documents = [source(ROOT / 'PROJECT_OS.md'), source(operations[operation])]
    documents.extend(source(skills[name]) for name in selected)
    resources = []
    for document in documents[1:]:
        for name in re.findall(r'(?:\.\./)+templates/([a-z0-9-]+)\.md', document):
            if name in templates and name not in resources:
                resources.append(name)
    out = [MARKER, '# Prompt operativo Project OS v3', '',
           f'**Repositorio indicado (sin verificar):** {repo or "No indicado"}',
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
        for name in resources:
            out.extend([source(templates[name]).strip(), ''])
    text = '\n'.join(out) + '\n'
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
        print('Usa /repo para cambiar repositorio o /carpeta para cambiar destino.')
    while True:
        for index, name in enumerate(visible, 1):
            print(f'  {index}. {name} — {description(operations[name])}')
        complete_from(names, {name: description(operations[name]) for name in names})
        try:
            query = ask(f'Operación [{current}]: ', current=current, strip=True)
        finally:
            clear_completion()
        if session_controls and query in ('/repo', '/carpeta'):
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


def interactive(operations, skills, templates, folder, repo):
    if sys.stdin.isatty() and terminal_prompt is None and not prepare_terminal():
        print('Este Python no dispone de edición segura de terminal; usa los flags del CLI para texto multilínea.', file=sys.stderr)
        return 1
    operation, last_path = 'continue', None
    values = {'repo': repo, 'local_only': False, 'skills': [], 'context': '', 'locator': '', 'feedback': '', 'question': ''}
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
            if not values['repo'] and not values['local_only']:
                values['repo'] = ask_repo('')
                values['local_only'] = not values['repo']
            values = fill_fields(operation, operations, skills, values)
            while True:
                content = operation_prompt(operation, operations, skills, templates, values)
                action = preview(operation, content, folder)
                if action == 'operation':
                    values.update(skills=[], context='', locator='', feedback='', question='')
                    break
                if action == 'edit':
                    # Keep repo and all current fields; operation and skills remain editable.
                    operation = choose_operation(operations, current=operation, session_controls=False)
                    values = fill_fields(operation, operations, skills, values, edit=True)
                    continue
                last_path, failures = save_prompt(folder, content)
                print(f'Prompt guardado: {last_path}')
                try:
                    save_config(values['repo'], folder)
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
                        values = fill_fields(operation, operations, skills, values, edit=True)
                        break
                    elif action in ('n', 'nueva', 'new'):
                        values.update(skills=[], context='', locator='', feedback='', question='')
                        break
                    elif action in ('m', 'misma', 'same'):
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


def main(argv=None):
    parser = Parser(description='Genera prompts Markdown sin ejecutar operaciones.')
    parser.add_argument('--list', action='store_true', help='listar operaciones y skills')
    parser.add_argument('--repo', help='repositorio owner/repo')
    parser.add_argument('--workflow', help='operación (default: continue)')
    parser.add_argument('--skill', action='append', default=[])
    parser.add_argument('--locator', help='número o URL de issue/PR')
    parser.add_argument('--objective', help='entrada principal de la operación')
    parser.add_argument('--feedback', help='comentario del PM')
    parser.add_argument('--question', help='pregunta del PM')
    parser.add_argument('--output-dir', help='carpeta de salida')
    parser.add_argument('--prototype', action='store_true', help='implement + rapid-prototype')
    args = parser.parse_args(argv)
    try:
        check_sensitive(args.repo, args.workflow, *args.skill, args.locator, args.objective, args.feedback, args.question, args.output_dir)
        if args.list and (args.repo or args.workflow or args.skill or args.locator or args.objective or args.feedback or args.question or args.prototype):
            parser.error('--list no se combina con selección ni contexto')
        if args.prototype and args.workflow:
            parser.error('--prototype no se combina con --workflow')
        operations, skills, templates = discover()
        if args.list:
            for name in ORDER:
                if name in operations:
                    print(f'{name} — {description(operations[name])}')
            for name in sorted(skills):
                print(f'{name} — {description(skills[name])}')
            return 0
        if any(name not in skills for name in BASE):
            parser.error('Faltan skills base o sus rutas no son seguras.')
        operation = 'implement' if args.prototype else (args.workflow or 'continue')
        selected = list(dict.fromkeys((['rapid-prototype'] if args.prototype else []) + args.skill))
        if operation not in operations or any(name not in skills for name in selected):
            parser.error('Operación o skill desconocida.')
        cli = bool(args.repo or args.workflow or args.skill or args.locator or args.objective or args.feedback or args.question or args.prototype)
        if not cli:
            config = load_config()
            folder = safe_path(args.output_dir or config.get('output_dir') or DEFAULT_DIR)
            return interactive(operations, skills, templates, folder, config.get('repo', ''))
        repo = repo_value(args.repo) if args.repo else ''
        locator = locator_value(args.locator or '')
        folder = safe_path(args.output_dir or DEFAULT_DIR)
        content = render(operation, selected, args.objective or '', locator, operations, skills, templates,
                         repo=repo, feedback=args.feedback or '', question=args.question or '', local_only=args.repo == '-')
        print('\n--- Vista previa ---\n' + content)
        print('Se reemplazarán solo prompts anteriores del selector después de escribir el nuevo.')
        path, failures = save_prompt(folder, content)
        print(f'Prompt guardado: {path}')
        if failures:
            print('No se pudieron quitar algunos prompts anteriores.', file=sys.stderr)
            return 1
        return 0
    except InputError as exc:
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
