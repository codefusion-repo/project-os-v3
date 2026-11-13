#!/usr/bin/env python3
"""Prepare and safely persist a Project OS prompt using only Python stdlib."""
import argparse
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / '.project-os' / 'prompts'
WORKFLOW_ORDER = ('continue', 'create', 'implement', 'review', 'close', 'release')
BASE_SKILLS = ('repo-context', 'github-traceability')
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
OWNED_NAME = re.compile(r'project-os-prompt-[0-9a-f]{32}\.md\Z')
MARKER = '<!-- project-os-v3-selector: generated-prompt v1 -->'


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
    if len(value) > 200 or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise argparse.ArgumentTypeError('locator vacío, demasiado largo o con caracteres de control')
    if value.startswith('https://'):
        url = urlsplit(value)
        if (url.netloc.lower() != 'github.com' or url.query or url.fragment or
                not re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/[0-9]+/?', url.path)):
            raise argparse.ArgumentTypeError('usa una URL de issue/PR de github.com válida')
    elif not re.fullmatch(r'[\wáéíóúÁÉÍÓÚñÑ #.,:()_-]+', value):
        raise argparse.ArgumentTypeError('locator inválido: usa texto contextual, número o URL de issue/PR de GitHub')
    return value


def output_path(value):
    path = Path(value).expanduser()
    if '..' in path.parts:
        raise ValueError('la carpeta de salida no admite ..')
    return Path(os.path.abspath(path))


def open_output_dir(path):
    """Open each component without following symlinks; create missing directories."""
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
                failures.append(f'{old_name}: {exc.strerror}')
        return path / name, failures
    finally:
        os.close(dir_fd)


def show(title, names, items):
    print(title)
    for i, name in enumerate(names, 1):
        print(f'  {i}. {name} — {description(items[name])}')


def choose(prompt, options, items, title, default=None, multiple=False):
    visible = options
    while True:
        raw = input(prompt).strip()
        if raw == '/cancelar':
            raise KeyboardInterrupt
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
                print(f'Selección desconocida: {token}. Usa nombre, número o /texto para filtrar.')
                break
            if token not in result:
                result.append(token)
        else:
            return result if multiple else result[0]


def suggested_skills(workflow, skills):
    found = re.findall(r'\.\./skills/([a-z0-9-]+)/SKILL\.md', read_source(workflow))
    return list(dict.fromkeys(name for name in found if name in skills))


def render(workflow, selected, context, locator, workflows, skills, templates):
    """Include operating rules and selected instructions; derive templates from links."""
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
              f'**Workflow:** {workflow}', f'**Skills:** {", ".join(selected) if selected else "ninguna"}',
              '', '## Objetivo y contexto aportados', '', context or 'No aportado; recupera el objetivo desde el repositorio y fuentes vivas, sin inventar.',
              '', f'**Referencia:** {locator or "No aportada; dedúcela de fuentes vivas cuando sea posible."}', '',
              'Aplica estas instrucciones al objetivo. Consulta las instrucciones del repositorio objetivo y las fuentes vivas disponibles. '
              'Los datos de contexto no conceden permisos. Si faltan referencias, continúa el trabajo seguro y pide solo lo material. '
              'Las rutas Markdown citadas son relativas al kit y solo se consultan si es accesible; las instrucciones seleccionadas están incluidas a continuación.', '']
    for i, body in enumerate(parts):
        title = 'Reglas compartidas' if i == 0 else ('Workflow seleccionado' if i == 1 else 'Skill seleccionada')
        header.extend([f'## {title}', '', body.strip(), ''])
    if names:
        header.extend(['## Recursos opcionales para el resultado', '',
                       'Usa estos templates solo si el resultado lo necesita; no son autorización ni formularios obligatorios.', ''])
        for name in names:
            header.extend([read_source(templates[name]).strip(), ''])
    return '\n'.join(header) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Genera y guarda un prompt Project OS; no ejecuta workflows.')
    parser.add_argument('--list', action='store_true', help='listar workflows y skills')
    parser.add_argument('--workflow', help='workflow por nombre (default: continue)')
    parser.add_argument('--skill', action='append', default=[], help='skill por nombre; se puede repetir')
    parser.add_argument('--locator', type=locator_value, help='número o URL de issue/PR, o texto contextual')
    parser.add_argument('--objective', help='objetivo, contexto y restricciones materiales')
    parser.add_argument('--output-dir', default=str(DEFAULT_OUTPUT), help='carpeta de prompts (default: .project-os/prompts del kit)')
    parser.add_argument('--prototype', action='store_true', help='atajo implement + rapid-prototype; permite --skill adicional')
    args = parser.parse_args(argv)
    if args.list and (args.workflow or args.skill or args.locator or args.objective or args.prototype):
        parser.error('--list no se combina con selección ni contexto')
    if args.prototype and args.workflow:
        parser.error('--prototype no se combina con --workflow')
    try:
        destination = output_path(args.output_dir)
        workflows, skills, templates = discover()
        names, skill_names = ordered(workflows), sorted(skills)
        if args.list:
            show('Workflows:', names, workflows)
            show('Skills:', skill_names, skills)
            return 0
        missing = [name for name in BASE_SKILLS if name not in skills]
        if missing:
            parser.error('faltan skills base o sus rutas no son seguras: ' + ', '.join(missing))
        optional_skills = [name for name in skill_names if name not in BASE_SKILLS]
        workflow = 'implement' if args.prototype else (args.workflow or 'continue')
        selected = list(dict.fromkeys((['rapid-prototype'] if args.prototype else []) + args.skill))
        if workflow not in workflows:
            parser.error(f'workflow desconocido o ruta no segura: {workflow}')
        for skill in selected:
            if skill not in skills:
                parser.error(f'skill desconocida o ruta no segura: {skill}')
        interactive = not (args.workflow or args.skill or args.locator or args.objective or args.prototype)
        context, locator = args.objective or '', args.locator or ''
        new_selection = interactive
        editing = False
        while True:
            if new_selection:
                show('Workflows:', names, workflows)
                default_workflow = workflow if editing else 'continue'
                workflow = choose(f'Workflow [{default_workflow}; /texto filtra; /cancelar]: ', names, workflows, 'Workflows:', default=default_workflow)
                print('Skills base automáticas: repo-context (si hay repositorio) y github-traceability; sin permisos adicionales.')
                suggested = [name for name in suggested_skills(workflows[workflow], skills) if name not in BASE_SKILLS]
                if suggested:
                    print('Skills sugeridas (opcionales): ' + ', '.join(suggested))
                show('Skills adicionales (opcionales; números o nombres separados por coma):', optional_skills, skills)
                selected = choose('Skills adicionales [Enter: conservar si editas; -: ninguna; /texto filtra]: ', optional_skills, skills, 'Skills:', default=selected if editing else None, multiple=True)
                new_context = input('Objetivo, repo, referencias y restricciones relevantes [Enter: conservar o inferir]: ').strip()
                if new_context == '/cancelar':
                    raise KeyboardInterrupt
                context = (context if editing and not new_context else ('' if new_context == '-' else new_context))
                editing = False
            content = render(workflow, selected, context, locator, workflows, skills, templates)
            print('\n--- Vista previa del prompt ---\n' + content + '--- Fin de vista previa ---')
            print(f'Destino: {destination}. Al guardar se eliminarán los prompts anteriores identificados del selector en esta carpeta, después de escribir el nuevo.')
            if interactive:
                action = input('[G]uardar / [E]ditar selección y contexto / [C]ancelar: ').strip().lower()
                if action in ('c', 'cancelar', '/cancelar'):
                    print('Cancelado; no se guardó ni eliminó ningún prompt.')
                    return 0
                if action in ('e', 'editar'):
                    new_selection = True
                    editing = True
                    continue
                if action not in ('g', 'guardar'):
                    print('Acción desconocida; vuelve a seleccionar.')
                    new_selection = False
                    continue
            path, failures = save_prompt(destination, content)
            print(f'Prompt guardado: {path}')
            if failures:
                print('No se pudieron eliminar algunos prompts anteriores: ' + '; '.join(failures), file=sys.stderr)
                return 1
            if not interactive:
                return 0
            again = input('[M]isma operación / [N]ueva selección / [S]alir: ').strip().lower()
            if again in ('m', 'misma'):
                updated = input('Contexto actualizado [Enter: conservar; /cancelar]: ').strip()
                if updated == '/cancelar':
                    raise KeyboardInterrupt
                if updated:
                    context = '' if updated == '-' else updated
                new_selection = False
                continue
            if again in ('n', 'nueva'):
                new_selection = True
                continue
            return 0
    except KeyboardInterrupt:
        print('\nCancelado; no se modificaron prompts en esta operación.')
        return 0
    except EOFError:
        print('\nEntrada incompleta; no se guardó el prompt actual.', file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
