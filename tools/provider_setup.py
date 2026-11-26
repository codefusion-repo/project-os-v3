"""Operator-controlled setup helpers; never execute workflows or enable services."""
import os
import json
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



def enroll_project(root, project, local, *, interactive, out=print, ask=input,
                   launch=execute, run=probe):
    """Reuse the existing project-local preference writer and installed setup."""
    if not interactive:
        out("Sin TTY: no se modifica la configuración ni se conceden grants.")
        return 1
    try:
        project = local.path(project)
        if project == root or local.git_root(project) != project:
            out("Selecciona el checkout Git del proyecto, separado de la instalación central.")
            return 1
        if local.private_tracked(project / ".project-os"):
            out("BLOCKED: configuración privada rastreada.")
            return 1
        config = local.read_config(project)
        if config is None or config["version"] != 2:
            out("Configura/adopta primero el proyecto mediante el selector existente.")
            return 1
        instance = local.path(ask("Instancia Bridge existente [~/.project-os-bridge]: ").strip()
                              or "~/.project-os-bridge")
        python = root / "local-bridge/.venv/bin/python"
        if not python.is_file() or not instance.is_dir():
            out("BLOCKED: falta la instalación o instancia existente; no se reinstalará.")
            return 1
        receipt = python.parent.parent / ".project-os-bridge-install.json"
        try:
            if receipt.is_symlink() or receipt.stat().st_size > 1024:
                raise ValueError("Invalid receipt")
            installed = json.loads(receipt.read_text(encoding="utf-8"))
            sha = installed["sha"]
            if (not isinstance(installed["wheel_sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", installed["wheel_sha256"])
                    or not reviewed_checkout(root, sha, run)):
                raise ValueError("Unverified installation")
        except (OSError, ValueError, KeyError, TypeError):
            out("BLOCKED: instalación revisada no verificable; no se modificó el proyecto.")
            return 1
        command = [str(python), "-I", "-m", "project_os_bridge.setup_instance", "--root", str(instance)]
        binding = config.get("github_context")
        if binding is None:
            for index, repository in enumerate(config["repositories"], 1):
                out(f"{index}. {repository}")
            choice = ask("Repositorio autorizado (número, vacío cancela): ").strip()
            if not choice:
                return 0
            if not choice.isascii() or not choice.isdecimal() or not 1 <= int(choice) <= len(config["repositories"]):
                out("Selección inválida.")
                return 1
            repository = config["repositories"][int(choice) - 1]
            default = repository.rsplit("/", 1)[-1]
            alias = ask(f"Identificador MCP [{default}]: ").strip() or default
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", alias):
                out("Identificador inválido.")
                return 1
            if not approved("¿Verificar la credencial dedicada existente para " + repository + "?", ask):
                return 0
            rc, output = run(command + ["--github-repository", repository], timeout=25)
            value = output.strip()
            if rc or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 2**63 - 1:
                out("BLOCKED: la credencial dedicada no acredita ese repositorio.")
                return 1
            binding = {"project": alias, "repository": repository, "repository_id": int(value)}
        if not approved("¿Preparar lectura MCP de " + binding["repository"]
                        + " como " + binding["project"]
                        + ", con credencial dedicada read-only y controles aplicables satisfechos?", ask):
            return 0
        if config.get("github_context") != binding:
            updated = {**config, "github_context": binding}
            out(local.save_config(project, updated, expected=config))
        rc = launch(command + ["--github-project", str(project / ".project-os/config.json")])
        if rc:
            out("Grant no confirmado; se conserva la preferencia local. No se modifican credenciales ni se reinicia.")
            return 1
        out("Usa el identificador del proyecto en las herramientas MCP. No se amplió el token ni se activaron marcadores.")
        return 0
    except (OSError, ValueError, EOFError, KeyboardInterrupt):
        out("Configuración interrumpida o bloqueada; conserva el estado y revisa antes de reintentar.")
        return 1


def guide(mode, root, run=probe, out=print, ask=input, interactive=False, launch=execute, project=None, local=None):
    if mode not in MODES:
        raise ValueError("Modo inválido")
    root = Path(root).resolve()
    out("Project OS — configuración de proveedores")
    if project is not None:
        if mode == "terminal" or local is None:
            return 1
        return enroll_project(root, project, local, interactive=interactive,
                              out=out, ask=ask, launch=launch, run=run)
    out("Para incorporar un proyecto existente: --providers chatgpt --project RUTA")
    out("Python: " + ("AVAILABLE" if sys.version_info >= (3, 9) else "BLOCKED"))
    for name in ("git", "gh", "python3"):
        rc, _ = run([name, "--version"])
        out(name + ": " + ("AVAILABLE" if rc == 0 else "UNAVAILABLE_OR_FAILED"))
    out("GitHub: verifica identidad y alcance autorizado; no compartas tokens.")
    out("Consulta README.md y docs/PRODUCT.md para instalación y adopción.")
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
