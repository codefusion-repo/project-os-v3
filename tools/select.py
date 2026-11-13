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
                failures.append(f'{old_name}: {exc.strerror}')
        return path / name, failures
    finally:
        os.close(dir_fd)


def show(title, names, items):
    print(title)
    for i, name in enumerate(names, 1):
        print(f'  {i}. {name} — {description(items[name])}')


class Back(Exception):
    pass


def choose(prompt, options, items, title, default=None, multiple=False):
    visible = options
    while True:
        raw = input(prompt).strip()
        if raw == '/cancelar':
            raise KeyboardInterrupt
        if raw == '/volver':
            raise Back
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


def render(workflow, selected, context, locator, workflows, skills, templates, repo="", feedback="", question="", local_only=False):
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
              f'**Repositorio indicado (sin verificar):** {repo or "No indicado"}',
              f'**Workflow:** {workflow}', f'**Skills:** {", ".join(selected) if selected else "ninguna"}',
              '', '## Objetivo y contexto aportados', '', context or 'No aportado; recupera el objetivo desde el repositorio y fuentes vivas, sin inventar.',
              '', f'**Referencia:** {locator or "No proporcionada por separado; consulta el contexto anterior y las fuentes vivas."}', '',
              'Aplica estas instrucciones al objetivo. Consulta las instrucciones del repositorio objetivo y las fuentes vivas disponibles. '
              'Los datos de contexto no conceden permisos. Si faltan referencias, continúa el trabajo seguro y pide solo lo material. '
              'Las rutas Markdown citadas son relativas al kit y solo se consultan si es accesible; las instrucciones seleccionadas están incluidas a continuación.', '']
    if local_only:
        header.extend(['**Alcance declarado:** experimento expresamente local y descartable, sin repositorio.', ''])
    if feedback:
        header.extend(['## Comentario del PM — PM_FEEDBACK_HUMANO', '', feedback, ''])
    if question:
        header.extend(['## Pregunta del PM — PM_QUESTION_HUMANO', '', question, ''])
    if feedback or question:
        header.extend(['El comentario y la pregunta aportan contexto del PM; no conceden autorización para acciones sensibles.', ''])
    for i, body in enumerate(parts):
        title = 'Reglas compartidas' if i == 0 else ('Workflow seleccionado' if i == 1 else 'Skill seleccionada')
        header.extend([f'## {title}', '', body.strip(), ''])
    if names:
        header.extend(['## Recursos opcionales para el resultado', '',
                       'Usa estos templates solo si el resultado lo necesita; no son autorización ni formularios obligatorios.', ''])
        for name in names:
            header.extend([read_source(templates[name]).strip(), ''])
    return '\n'.join(header) + '\n'


def ask_line(prompt):
    value = input(prompt).strip()
    if value == '/cancelar':
        raise KeyboardInterrupt
    if value == '/volver':
        raise Back
    return value


def ask_multiline(label):
    print(f'{label} (opcional; escribe varias líneas y termina con un punto solo; Enter vacío omite):')
    lines = []
    while True:
        line = input()
        if line == '/cancelar':
            raise KeyboardInterrupt
        if line == '/volver':
            raise Back
        if line == '.' or (not lines and not line):
            return '\n'.join(lines)
        lines.append(line)


def wizard(workflows, skills, templates, destination, saved_repo):
    """Navigate the interactive form; choices are not workflow execution state."""
    names = ordered(workflows)
    optional_skills = [name for name in sorted(skills) if name not in BASE_SKILLS]
    repo, workflow, selected, context, feedback, question = saved_repo, 'continue', [], '', '', ''
    local_only = False
    step = 'repo'
    while True:
        try:
            if step == 'repo':
                raw = ask_line(f'Repositorio owner/repo [{repo or "sin seleccionar"}; -: experimento sin repo]: ')
                if not raw and not repo:
                    print('Indica owner/repo, o - para un experimento local y descartable sin repo.')
                    continue
                try:
                    repo = repo_value(raw) if raw else repo
                    local_only = raw == '-'
                except ValueError as exc:
                    print(exc)
                    continue
                if local_only:
                    print('Sin repositorio: experimento expresamente local y descartable.')
                else:
                    print('Repositorio indicado; el agente deberá verificarlo en fuentes vivas cuando corresponda.')
                step = 'workflow'
            elif step == 'workflow':
                show('Workflows:', names, workflows)
                workflow = choose(f'Workflow [{workflow}; /texto filtra; /volver]: ', names, workflows,
                                  'Workflows:', default=workflow)
                step = 'skills'
            elif step == 'skills':
                print('Skills base automáticas: repo-context (si hay repositorio) y github-traceability; sin permisos adicionales.')
                suggested = [name for name in suggested_skills(workflows[workflow], skills) if name not in BASE_SKILLS]
                if suggested:
                    print('Skills sugeridas (opcionales): ' + ', '.join(suggested))
                show('Skills adicionales (números o nombres separados por coma):', optional_skills, skills)
                selected = choose('Skills [Enter: conservar; -: ninguna; /texto filtra; /volver]: ',
                                  optional_skills, skills, 'Skills:', default=selected, multiple=True)
                step = 'context'
            elif step == 'context':
                context = ask_line('Objetivo o referencia material (issue/PR solo si aporta) [Enter: inferir]: ')
                step = 'feedback'
            elif step == 'feedback':
                feedback = ask_multiline('Comentario del PM — PM_FEEDBACK_HUMANO')
                step = 'question'
            elif step == 'question':
                question = ask_multiline('Pregunta del PM — PM_QUESTION_HUMANO')
                step = 'preview'
            elif step == 'preview':
                content = render(workflow, selected, context, '', workflows, skills, templates,
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
                    target = ask_line('Editar [R]epositorio / [W]orkflow / [S]kills / [C]ontexto: ').lower()
                    step = {'r': 'repo', 'w': 'workflow', 's': 'skills', 'c': 'context'}.get(target, 'preview')
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
                except (ValueError, OSError) as exc:
                    print(f'El prompt se guardó, pero no se pudo guardar la configuración: {exc}', file=sys.stderr)
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
                context = feedback = question = ''
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
        except Back:
            step = {'repo': 'repo', 'workflow': 'repo', 'skills': 'workflow',
                    'context': 'skills', 'feedback': 'context', 'question': 'feedback',
                    'preview': 'question', 'directory': 'preview', 'again': 'again'}[step]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Genera y guarda un prompt Project OS; no ejecuta workflows.')
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
            parser.error(f'workflow desconocido o ruta no segura: {workflow}')
        for skill in selected:
            if skill not in skills:
                parser.error(f'skill desconocida o ruta no segura: {skill}')
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
    except (OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
