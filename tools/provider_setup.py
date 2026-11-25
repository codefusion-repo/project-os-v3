"""Operator-controlled setup helpers; never execute workflows or grant access."""
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

MODES = ("terminal", "chatgpt", "both")
ORIGIN = "https://github.com/codefusion-repo/project-os-v3.git"


def probe(args, timeout=10):
    """Return exit status and bounded-use output; never print raw tool output."""
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=timeout, check=False)
        return result.returncode, result.stdout
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return 1, ""


def approved(question, ask):
    return ask(question + " [s/N]: ").strip().lower() == "s"


def reviewed_checkout(root, sha, run=probe):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return False
    prefix = ["git", "-C", str(root)]
    for command, expected in (
        (["rev-parse", "--show-toplevel"], str(root)),
        (["rev-parse", "HEAD"], sha),
        (["config", "--local", "--get", "remote.origin.url"], ORIGIN),
        (["status", "--porcelain", "--untracked-files=normal"], ""),
    ):
        code, output = run(prefix + command)
        if code or output.strip() != expected:
            return False
    return True


def execute(args):
    # Interactive local process: no shell, no capture or persistence of credentials.
    return subprocess.run(args, check=False).returncode


def private_setup(root, sha, run, out, ask, launch):
    """Delegate private configuration to the installed, reviewed Bridge."""
    if not approved("¿Inicializar una instancia privada nueva de WorkOS?", ask):
        return 0
    value = ask("Ruta absoluta nueva fuera de Git (vacío cancela): ").strip()
    if not value:
        return 0
    instance = Path(value)
    if not instance.is_absolute() or os.path.lexists(instance):
        out("BLOCKED: instancia existente o ruta no absoluta; se conserva.")
        return 1
    python = root / "local-bridge/.venv/bin/python"
    if not reviewed_checkout(root, sha, run) or not python.is_file():
        out("BLOCKED: instalación revisada no verificable.")
        return 1
    command = [str(python), "-I", "-m", "project_os_bridge.setup_instance", "--root", str(instance)]
    if launch(command):
        out("BLOCKED: inicialización fallida; conserva el estado parcial.")
        return 1
    if approved("¿Preparar HTTPS y túnel privado sin iniciar servicios ni activar acceso?", ask):
        if not reviewed_checkout(root, sha, run):
            out("BLOCKED: checkout cambió.")
            return 1
        if launch(command + ["--prepare-service", "--no-fixture"]):
            out("BLOCKED: preparación fallida; conserva la instancia.")
            return 1
    out("Verifica el conector OAuth desde ChatGPT mediante health; no equivale a activar acceso.")
    return 0


def guide(mode, root, run=probe, out=print, ask=input, interactive=False, launch=execute):
    if mode not in MODES:
        raise ValueError("Modo inválido")
    root = Path(root).resolve()
    out("Project OS — configuración de proveedores")
    out("Python: " + ("AVAILABLE" if sys.version_info >= (3, 9) else "BLOCKED"))
    for name in ("git", "gh", "python3"):
        rc, _ = run([name, "--version"])
        out(name + ": " + ("AVAILABLE" if rc == 0 else "UNAVAILABLE_OR_FAILED"))
    out("GitHub: verifica identidad y alcance autorizado; no compartas tokens.")
    out("Consulta README.md y docs/ADOPTION.md para instalación y adopción.")
    if mode in ("terminal", "both"):
        out("Terminal: utiliza un agente autorizado en el checkout; el selector no ejecuta workflows.")
    if mode in ("chatgpt", "both"):
        out("ChatGPT: conecta GitHub Connector y comprueba lectura del repositorio autorizado.")
        out("Local Bridge es opcional; GitHub Connector funciona independientemente.")
        for name in ("podman", "tunnel-client", "systemctl"):
            rc, _ = run([name, "--version"])
            out(name + ": " + ("AVAILABLE" if rc == 0 else "UNAVAILABLE_OR_FAILED"))
        out("Local Bridge: sigue local-bridge/README.md para instalación por SHA y preflight.")
        out("WorkOS y túnel: sigue local-bridge/WORKOS.md; consentimiento OAuth externo y privado.")
        out("HTTPS: usa --bridge-setup únicamente con instancia privada existente e instalación revisada.")
        out("Verifica health autenticado y evidencia descartable según local-bridge/WSL-VALIDATION.md.")
        out("ADB y Codex: capacidades futuras, no se activan aquí.")
    out("AVAILABLE indica comando exitoso; versiones exactas, autenticación y aislamiento no verificados.")
    if not interactive:
        out("Sin TTY: no se solicitaron credenciales ni se iniciaron instalaciones.")
        return 0
    try:
        if approved("¿Comprobar autenticación GitHub CLI (consulta a github.com)?", ask):
            rc, _ = run(["gh", "auth", "status", "--hostname", "github.com"])
            out("GitHub CLI auth: " + ("PASS" if rc == 0 else "BLOCKED; usa gh auth login --hostname github.com en tu terminal"))
            out("No acredita permisos sobre un repo ni conexión GitHub Connector.")
        if mode == "terminal":
            return 0
        if not approved("¿Configurar Local Bridge opcional?", ask):
            return 0
        sha = ask("SHA completo revisado por el PM (vacío cancela): ").strip()
        if not sha:
            out("Cancelado.")
            return 0
        if not reviewed_checkout(root, sha, run):
            out("BLOCKED: SHA, origen o checkout limpio no verificados.")
            return 1
        rc, _ = run(["python3", "-I", "-c",
                     "import sys,platform; sys.exit(not (sys.version_info[:2]==(3,12) and sys.platform=='linux' and platform.machine()=='x86_64'))"])
        if rc or os.getuid() == 0:
            out("BLOCKED: Bridge requiere Python 3.12, Linux x86_64 y usuario no root.")
            return 1
        venv = root / "local-bridge/.venv"
        if os.path.lexists(venv):
            out("Entorno Bridge existente o parcial preservado. No se ejecutará ni sobrescribirá; usa el runbook para verificarlo.")
            return 1
        if not approved("¿Ejecutar instalador Bridge revisado? Descarga paquetes con locks y crea el entorno privado, sin iniciar servicios", ask):
            out("Cancelado.")
            return 0
        if not reviewed_checkout(root, sha, run) or os.path.lexists(venv):
            out("BLOCKED: estado cambió; no se instala.")
            return 1
        rc = launch(["bash", str(root / "local-bridge/scripts/install.sh"), sha])
        if rc:
            out("BLOCKED: instalación parcial posible; conserva el entorno y sigue WSL-VALIDATION.md. No reintentar automáticamente.")
            return 1
        out("Instalador Bridge completado. No se activó acceso.")
        if approved("¿Ejecutar preflight existente? Puede iniciar el servidor local ADB; no autoriza dispositivos", ask):
            if launch(["bash", str(root / "local-bridge/scripts/preflight.sh")]):
                out("BLOCKED: preflight falló.")
                return 1
        out("Configura WorkOS y el túnel mediante WORKOS.md; no copies secretos al chat.")
        return private_setup(root, sha, run, out, ask, launch)
    except (EOFError, KeyboardInterrupt):
        out("Interrumpido: revisa el estado antes de reintentar; no se realiza rollback destructivo.")
        return 1
    except OSError:
        out("BLOCKED: no se pudo iniciar la acción; conserva el estado.")
        return 1
