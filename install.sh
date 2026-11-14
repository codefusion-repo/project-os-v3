#!/bin/sh
# Installs only inside this checkout and a user-owned launcher; never edits shell files.
set -eu
umask 077
case "$(uname -s)" in Linux) ;; *) printf '%s\n' 'Se requiere Linux o WSL.' >&2; exit 1;; esac
command -v git >/dev/null 2>&1 || { printf '%s\n' 'Falta Git.' >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { printf '%s\n' 'Falta Python 3.9 o superior.' >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { printf '%s\n' 'Se requiere Python 3.9 o superior.' >&2; exit 1; }
KIT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
BIN_DIR=${PROJECT_OS_BIN_DIR:-"${HOME:?}/.local/bin"}
case "$BIN_DIR" in /*) ;; *) printf '%s\n' 'La carpeta del launcher debe ser absoluta.' >&2; exit 1;; esac
# Refuse symlinked or traversal paths and check hard-link / no-follow support.
python3 - "$KIT_DIR" "$BIN_DIR" <<'PY'
import os, pathlib, tempfile, sys
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
with tempfile.TemporaryDirectory(prefix='.project-os-check-', dir=sys.argv[1]) as d:
    a, b = pathlib.Path(d)/'a', pathlib.Path(d)/'b'
    a.write_text('check')
    os.link(a, b)
PY
mkdir -p -- "$BIN_DIR"
LAUNCHER=$BIN_DIR/project-os-v3
KIT_ID=$(python3 -c 'import hashlib,os,sys; print(hashlib.sha256(os.fsencode(sys.argv[1])).hexdigest())' "$KIT_DIR")
if [ -L "$LAUNCHER" ]; then printf '%s\n' 'El launcher es un enlace; se conserva.' >&2; exit 1; fi
if [ -e "$LAUNCHER" ] && ! grep -q '^# project-os-v3 launcher$' "$LAUNCHER"; then
    printf '%s\n' 'Ya existe un archivo ajeno en la ruta del launcher; se conserva.' >&2; exit 1
fi
if [ -e "$LAUNCHER" ] && ! grep -q "^# kit-id: $KIT_ID$" "$LAUNCHER"; then
    printf '%s\n' 'El launcher pertenece a otra instalación; se conserva.' >&2; exit 1
fi
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
mv -f -- "$TEMP_LAUNCHER" "$LAUNCHER"
printf '%s\n' "Launcher instalado: $LAUNCHER"
case ":${PATH:-}:" in *":$BIN_DIR:"*) ;; *) printf '%s\n' "Agrega $BIN_DIR a PATH en tu shell para ejecutar project-os-v3.";; esac
