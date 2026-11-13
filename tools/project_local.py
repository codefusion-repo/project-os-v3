"""Project-local preferences and Git privacy preflight; no central project registry."""
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path


class ProjectError(ValueError):
    pass


def path(value):
    value = Path(value).expanduser()
    if '..' in value.parts:
        raise ProjectError('La ruta no puede contener ..')
    value = Path(os.path.abspath(value))
    current = Path(value.anchor)
    for part in value.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ProjectError('La ruta no admite enlaces simbólicos.')
    return value


def git(root, *args, check=True):
    environment = dict(os.environ)
    for key in tuple(environment):
        if key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR', 'GIT_OBJECT_DIRECTORY',
                   'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_REPLACE_REF_BASE', 'GIT_CONFIG_COUNT') or key.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_')):
            environment.pop(key, None)
    environment['GIT_NO_REPLACE_OBJECTS'] = '1'
    try:
        result = subprocess.run(['git', '-C', str(root), '-c', 'core.fsmonitor=false', *args],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, env=environment)
    except OSError as exc:
        raise ProjectError('Git no está disponible; no se puede comprobar la protección.') from exc
    if check and result.returncode:
        raise ProjectError('Git no pudo comprobar la ruta o referencia indicada.')
    return result


def git_root(location):
    location = path(location)
    existing = location
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    # Do not use a nonexistent path as git -C, and reject links in the whole path.
    result = git(existing, 'rev-parse', '--show-toplevel', check=False)
    if result.returncode == 0:
        return path(os.fsdecode(result.stdout).strip())
    bare = git(existing, 'rev-parse', '--is-bare-repository', check=False)
    if bare.returncode == 0 and bare.stdout.strip() == b'true':
        raise ProjectError('No se guardan datos privados dentro de un repositorio Git bare.')
    # A visible .git marker with failed Git access is not proof of safety.
    for ancestor in (existing, *existing.parents):
        marker = ancestor / '.git'
        if marker.is_symlink() or marker.is_file() or (marker.is_dir() and ((marker / 'HEAD').exists() or (marker / 'config').exists())):
            raise ProjectError('No se puede verificar el repositorio Git de destino.')
    return None


def preflight(target, prepare=False, names=None):
    """Check exact destination, including tracked descendants, before private writes."""
    target = path(target)
    root = git_root(target)
    if root is None:
        return 'Fuera de Git; destino local seleccionado.'
    try:
        relative = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ProjectError('El destino no pertenece al repositorio detectado.') from exc
    tracked = git(root, 'ls-files', '-z', '--', relative).stdout
    if tracked:
        raise ProjectError('Hay archivos privados bajo seguimiento Git; no se escribirá en este destino. Prepara una corrección y evalúa exposición histórica.')
    if names is None:
        names = ('config.json', '.config-' + 'a' * 32, 'prompts/project-os-prompt-' + 'a' * 32 + '.md') if target.name == '.project-os' else ('.prompt-' + 'a' * 32, 'project-os-prompt-' + 'a' * 32 + '.md')
    probes = [relative.rstrip('/') + '/' + name for name in names]
    def all_ignored():
        for probe in probes:
            result = git(root, 'check-ignore', '-q', '--no-index', '--', probe, check=False)
            if result.returncode not in (0, 1):
                raise ProjectError('No se pudo verificar la exclusión Git.')
            if result.returncode:
                return False
        return True
    if all_ignored():
        return 'Exclusión Git verificada.'
    if not prepare:
        raise ProjectError('Destino no ignorado por Git; selecciona un destino protegido.')
    # Only .project-os can receive the strictly local provisional exclusion.
    if target.name != '.project-os':
        raise ProjectError('El destino no está ignorado; selecciona otro explícitamente.')
    exclude_raw = os.fsdecode(git(root, 'rev-parse', '--git-path', 'info/exclude').stdout).strip()
    exclude = path(exclude_raw if os.path.isabs(exclude_raw) else root / exclude_raw)
    parent = exclude.parent
    if not parent.is_dir():
        raise ProjectError('No se puede preparar la exclusión local.')
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    try:
        directory = open_directory(parent)
        try:
            fd = os.open(exclude.name, flags, 0o600, dir_fd=directory)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ProjectError('La exclusión local no es un archivo regular.')
                # Literal path: reject Git pattern characters instead of changing semantics.
                if any(c in relative for c in '*?[]!\\\n\r'):
                    raise ProjectError('La ruta necesita una exclusión manual.')
                os.write(fd, ('\n/' + relative + '/\n').encode())
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            os.close(directory)
    except OSError as exc:
        raise ProjectError('No se pudo preparar la exclusión local.') from exc
    if not all_ignored():
        raise ProjectError('La exclusión local no es efectiva; no se escribirán datos privados.')
    return 'Protección local preparada en Git info/exclude y verificada; añade .project-os/ a .gitignore en la adopción.'


def private_tracked(target):
    target = path(target)
    root = git_root(target)
    if root is None:
        return False
    return bool(git(root, 'ls-files', '-z', '--', target.relative_to(root).as_posix()).stdout)


def open_directory(value, create=False):
    value = path(value)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(value.anchor, flags)
    try:
        for component in value.parts[1:]:
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


def _read_config_dir(directory):
    try:
        fd = os.open('config.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProjectError('La configuración local no es accesible de forma segura.') from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ProjectError('La configuración no es un archivo regular.')
        with os.fdopen(fd, encoding='utf-8') as stream:
            fd = -1
            data = json.load(stream)
    except (ValueError, UnicodeError, OSError) as exc:
        raise ProjectError('Configuración local inválida; se preservará sin cambios.') from exc
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1 or set(data) - {'version', 'name', 'primary_repo', 'related_repos', 'prompt_dir', 'checkouts'}:
        raise ProjectError('Formato local desconocido; no se sobrescribirá automáticamente.')
    if not isinstance(data.get('name', ''), str) or not isinstance(data.get('primary_repo', ''), str):
        raise ProjectError('Configuración local inválida.')
    if not isinstance(data.get('prompt_dir', '.project-os/prompts'), str):
        raise ProjectError('Configuración local inválida.')
    if not isinstance(data.get('related_repos', []), list) or not all(isinstance(x, str) for x in data.get('related_repos', [])):
        raise ProjectError('Configuración local inválida.')
    if not isinstance(data.get('checkouts', {}), dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.get('checkouts', {}).items()):
        raise ProjectError('Configuración local inválida.')
    return data


def read_config(project):
    try:
        directory = open_directory(path(project) / '.project-os')
    except FileNotFoundError:
        return None
    try:
        return _read_config_dir(directory)
    finally:
        os.close(directory)


def save_config(project, data):
    project = path(project)
    temporary_name = '.config-' + uuid.uuid4().hex
    message = preflight(project / '.project-os', prepare=True, names=('config.json', temporary_name))
    directory = open_directory(project / '.project-os', create=True)
    try:
        # Never replace a symlink, unknown or incompatible configuration.
        _read_config_dir(directory)
        fd = os.open(temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, 'config.json', src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory)
    return message


def discover_projects(start, exclude=None):
    start = path(start)
    if not start.is_dir():
        raise ProjectError('La ruta de proyecto debe ser un directorio accesible.')
    found = []
    for candidate in (start, *start.parents):
        if exclude is not None and candidate == exclude:
            continue
        if (candidate / '.project-os' / 'config.json').exists():
            config = {'_blocked': True} if private_tracked(candidate / '.project-os') else read_config(candidate)
            if config is not None:
                found.append((candidate, config))
    return found


def version(project):
    directory = open_directory(project)
    try:
        try:
            fd = os.open('AGENTS.md', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ProjectError('AGENTS.md no es un archivo regular seguro.') from exc
        with os.fdopen(fd, encoding='utf-8') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ProjectError('AGENTS.md no es un archivo regular seguro.')
            text = stream.read()
    finally:
        os.close(directory)
    markers = re.findall(r'(?im)^\s*(?:<!--\s*)?Project-OS-Version\s*:\s*(.*?)\s*$', text)
    refs = [value.removesuffix('-->').strip() for value in markers]
    if any(not re.fullmatch(r'[0-9a-fA-F]{40}', value) for value in refs):
        raise ProjectError('AGENTS.md declara una versión inválida; se requiere SHA completo.')
    refs = [value.lower() for value in refs]
    if len(set(refs)) > 1:
        raise ProjectError('AGENTS.md contiene versiones de Project OS contradictorias.')
    if refs and 'codefusion-repo/project-os-v3' not in text.lower():
        raise ProjectError('AGENTS.md fija un SHA sin identificar el repositorio canónico de Project OS.')
    return refs[0].lower() if refs else None


def commit(root, revision):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ProjectError('La referencia del kit debe ser un SHA completo.')
    result = git(root, 'rev-parse', '--verify', revision + '^{commit}', check=False)
    if result.returncode or result.stdout.decode('ascii', 'ignore').strip() != revision:
        raise ProjectError('La versión fijada no está disponible localmente; no se mezclaron instrucciones.')
    return revision


def git_document(root, revision, relative):
    if not re.fullmatch(r'[a-zA-Z0-9_./-]+', relative) or '..' in Path(relative).parts:
        raise ProjectError('Ruta operativa inválida.')
    tree = git(root, 'ls-tree', '-z', revision, '--', relative, check=False)
    entry = tree.stdout.rstrip(b'\0').split(b'\t', 1)
    if tree.returncode or len(entry) != 2 or entry[1] != relative.encode('utf-8') or not entry[0].startswith((b'100644 blob ', b'100755 blob ')):
        raise ProjectError('El documento operativo no es un archivo regular de la versión fijada.')
    result = git(root, 'show', revision + ':' + relative, check=False)
    if result.returncode:
        raise ProjectError('Falta un documento operativo en la versión fijada.')
    try:
        return result.stdout.decode('utf-8')
    except UnicodeError as exc:
        raise ProjectError('Documento operativo no válido.') from exc
