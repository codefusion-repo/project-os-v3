#!/bin/sh
# Installs only inside this checkout and a user-owned launcher; never edits shell files.
set -eu
umask 077
case "$(uname -s)" in Linux) ;; *) printf '%s\n' 'Se requiere Linux o WSL.' >&2; exit 1;; esac
command -v git >/dev/null 2>&1 || { printf '%s\n' 'Falta Git.' >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { printf '%s\n' 'Falta Python 3.9 o superior.' >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { printf '%s\n' 'Se requiere Python 3.9 o superior.' >&2; exit 1; }
KIT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if [ "${1-}" != '--project-os-internal' ]; then
    # Load the script before a fast-forward can replace this file on disk.
    exec sh -c "$(cat -- "$KIT_DIR/install.sh")" project-os-install --project-os-internal "$KIT_DIR"
fi
KIT_DIR=$2
BIN_DIR=${PROJECT_OS_BIN_DIR:-"${HOME:?}/.local/bin"}
case "$BIN_DIR" in /*) ;; *) printf '%s\n' 'La carpeta del launcher debe ser absoluta.' >&2; exit 1;; esac
# Refuse symlinked or traversal paths and check hard-link / no-follow support.
python3 - "$KIT_DIR" "$BIN_DIR" <<'PY'
import os, pathlib, stat, tempfile, sys
for value in sys.argv[1:]:
    p = pathlib.Path(value)
    if '..' in p.parts:
        raise SystemExit('Ruta inválida.')
    current = pathlib.Path(p.anchor)
    for part in p.parts[1:]:
        current /= part
        if current.is_symlink():
            raise SystemExit('Ruta con enlace simbólico no permitida.')
if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
    raise SystemExit('El filesystem no ofrece las capacidades requeridas.')
fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
try:
    current = pathlib.Path('/')
    for part in pathlib.Path(sys.argv[2]).parts[1:]:
        current /= part
        try:
            os.mkdir(part, 0o700, dir_fd=fd)
        except FileExistsError:
            pass
        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        info = os.fstat(child)
        if info.st_mode & 0o022 and not (info.st_mode & stat.S_ISVTX and (info.st_uid == 0 or current == pathlib.Path('/tmp'))):
            os.close(child)
            raise SystemExit('Directorio de launcher inseguro; se conserva.')
        os.close(fd)
        fd = child
    if os.fstat(fd).st_uid != os.getuid():
        raise SystemExit('La carpeta del launcher no pertenece al usuario.')
finally:
    os.close(fd)
with tempfile.TemporaryDirectory(prefix='.project-os-check-', dir=sys.argv[1]) as d:
    a, b = pathlib.Path(d)/'a', pathlib.Path(d)/'b'
    a.write_text('check')
    os.link(a, b)
PY
LAUNCHER=$BIN_DIR/project-os-v3
KIT_ID=$(python3 -c 'import hashlib,os,sys; print(hashlib.sha256(os.fsencode(sys.argv[1])).hexdigest())' "$KIT_DIR")
python3 - "$KIT_DIR" "$LAUNCHER" "$KIT_ID" <<'PY'
import os, pathlib, shlex, stat, sys
kit, launcher, kit_id = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
if kit.stat().st_uid != os.getuid():
    raise SystemExit('El checkout central no pertenece al usuario.')
gitdir = kit / '.git'
if gitdir.is_symlink() or not gitdir.is_dir():
    raise SystemExit('La instalación central requiere un clon Git propio, sin enlaces.')
gitinfo = gitdir.stat()
if gitinfo.st_uid != os.getuid() or gitinfo.st_mode & 0o022:
    raise SystemExit('Directorio Git inseguro; se conserva.')
if any((gitdir / name).exists() for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'BISECT_LOG')):
    raise SystemExit('Hay una operación Git en curso; termínala antes de actualizar.')
if launcher.is_symlink():
    raise SystemExit('El launcher es un enlace; se conserva.')
if launcher.exists():
    info = launcher.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise SystemExit('Launcher inseguro o ajeno; se conserva.')
    prefix = '#!/bin/sh\n# project-os-v3 launcher\n# kit-id: ' + kit_id + '\nexec '
    suffix = ' ' + shlex.quote(str(kit / 'tools/select.py')) + ' "$@"\n'
    allowed = {prefix + shlex.quote(python) + suffix for python in ('python3', str(kit / '.venv/bin/python'))}
    if launcher.read_text(encoding='utf-8', errors='replace') not in allowed:
        raise SystemExit('Launcher ajeno o modificado; se conserva.')
PY
if [ -L "$LAUNCHER" ]; then printf '%s\n' 'El launcher es un enlace; se conserva.' >&2; exit 1; fi
if [ -e "$LAUNCHER" ] && ! grep -q '^# project-os-v3 launcher$' "$LAUNCHER"; then
    printf '%s\n' 'Ya existe un archivo ajeno en la ruta del launcher; se conserva.' >&2; exit 1
fi
if [ -e "$LAUNCHER" ] && ! grep -q "^# kit-id: $KIT_ID$" "$LAUNCHER"; then
    printf '%s\n' 'El launcher pertenece a otra instalación; se conserva.' >&2; exit 1
fi
# Only the canonical main branch is an update source. Never merge local work.
[ "$(git -C "$KIT_DIR" rev-parse --show-toplevel 2>/dev/null || :)" = "$KIT_DIR" ] || { printf '%s\n' 'La instalación central debe ser un checkout Git completo.' >&2; exit 1; }
[ "$(git -C "$KIT_DIR" config --local --get remote.origin.url || :)" = 'https://github.com/codefusion-repo/project-os-v3.git' ] || { printf '%s\n' 'Origen no esperado; se conserva la instalación.' >&2; exit 1; }
[ "$(git -C "$KIT_DIR" symbolic-ref --quiet --short HEAD || :)" = main ] || { printf '%s\n' 'La instalación central debe estar en main.' >&2; exit 1; }
CHANGES=$(git -C "$KIT_DIR" status --porcelain --untracked-files=normal) || { printf '%s\n' 'No se pudo comprobar el checkout; se conserva.' >&2; exit 1; }
[ -z "$CHANGES" ] || { printf '%s\n' 'Hay cambios locales; consérvalos y usa un checkout central limpio.' >&2; exit 1; }
git -C "$KIT_DIR" fetch --no-tags origin main || { printf '%s\n' 'No se pudo consultar main; se conserva la instalación anterior.' >&2; exit 1; }
TARGET=$(git -C "$KIT_DIR" rev-parse --verify 'FETCH_HEAD^{commit}')
git -C "$KIT_DIR" merge-base --is-ancestor HEAD "$TARGET" || { printf '%s\n' 'main no avanza limpiamente; se conserva la instalación anterior.' >&2; exit 1; }
git -C "$KIT_DIR" merge --ff-only "$TARGET" || { printf '%s\n' 'No se pudo actualizar; revisa el checkout central.' >&2; exit 1; }
[ "$(git -C "$KIT_DIR" rev-parse HEAD)" = "$TARGET" ] || { printf '%s\n' 'No se pudo verificar la versión instalada.' >&2; exit 1; }
PYTHON=python3
if [ -L "$KIT_DIR/.venv" ]; then
    printf '%s\n' 'El entorno .venv es un enlace; se conserva y se usa Python estándar.' >&2
elif [ -f "$KIT_DIR/.venv/.project-os-v3" ] && [ ! -L "$KIT_DIR/.venv/.project-os-v3" ] && [ "$(cat "$KIT_DIR/.venv/.project-os-v3")" = 'project-os-v3 isolated environment' ] && [ -x "$KIT_DIR/.venv/bin/python" ] && "$KIT_DIR/.venv/bin/python" -c 'import prompt_toolkit' >/dev/null 2>&1; then
    PYTHON=$KIT_DIR/.venv/bin/python
elif [ -e "$KIT_DIR/.venv" ]; then
    printf '%s\n' 'El entorno .venv existente no es utilizable; se conserva y se usa Python estándar.' >&2
else
    TEMP_VENV=$(mktemp -d "$KIT_DIR/.venv-install.XXXXXXXX")
    if python3 -m venv "$TEMP_VENV" && "$TEMP_VENV/bin/python" -m pip install 'prompt_toolkit==3.0.53'; then
        # The temporary path is newly created by this invocation. venv executables are
        # invoked via Python, avoiding assumptions about pip entrypoint shebangs.
        printf '%s\n' 'project-os-v3 isolated environment' > "$TEMP_VENV/.project-os-v3"
        mv -- "$TEMP_VENV" "$KIT_DIR/.venv"
        PYTHON=$KIT_DIR/.venv/bin/python
        printf '%s\n' 'Entorno enriquecido instalado.'
    else
        printf '%s\n' "Falló la dependencia opcional; se conserva $TEMP_VENV y se usa Python estándar." >&2
    fi
fi
TEMP_LAUNCHER=$(mktemp "$BIN_DIR/.project-os-v3.XXXXXXXX")
python3 - "$TEMP_LAUNCHER" "$PYTHON" "$KIT_DIR/tools/select.py" "$KIT_ID" <<'PY'
import shlex, sys
with open(sys.argv[1], 'w', encoding='utf-8') as f:
    f.write('#!/bin/sh\n# project-os-v3 launcher\n# kit-id: ' + sys.argv[4] + '\nexec ' + shlex.quote(sys.argv[2]) + ' ' + shlex.quote(sys.argv[3]) + ' "$@"\n')
PY
chmod 700 "$TEMP_LAUNCHER"
if [ -f "$LAUNCHER" ] && cmp -s "$TEMP_LAUNCHER" "$LAUNCHER" && [ "$(stat -c %a "$LAUNCHER")" = 700 ]; then
    rm -- "$TEMP_LAUNCHER"
else
    mv -f -- "$TEMP_LAUNCHER" "$LAUNCHER"
fi
printf '%s\n' "Launcher instalado: $LAUNCHER"
case ":${PATH:-}:" in *":$BIN_DIR:"*) ;; *) printf '%s\n' "Agrega $BIN_DIR a PATH en tu shell para ejecutar project-os-v3.";; esac
