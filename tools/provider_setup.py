"""Read-only provider guidance; no authentication, installation or activation."""
import shutil
import sys

MODES = ("terminal", "chatgpt", "both")


def guide(mode, locate=shutil.which, out=print):
    if mode not in MODES:
        raise ValueError("Modo inválido")
    out("Project OS — configuración de proveedores (sin cambios)")
    out("Python: " + ("AVAILABLE" if sys.version_info >= (3, 9) else "BLOCKED"))
    for name in ("git", "gh", "python3"):
        out(name + ": " + ("AVAILABLE" if locate(name) else "NOT_DETECTED"))
    out("GitHub: verifica la identidad y alcance autorizado con gh auth status; no compartas tokens.")
    out("Consulta README.md y docs/ADOPTION.md para instalación y adopción.")
    if mode in ("terminal", "both"):
        out("Terminal: utiliza un agente autorizado en el checkout; el selector no ejecuta workflows.")
    if mode in ("chatgpt", "both"):
        out("ChatGPT: conecta GitHub Connector y comprueba lectura del repositorio autorizado.")
        out("Local Bridge es opcional; GitHub Connector funciona independientemente.")
        for name in ("podman", "tunnel-client", "systemctl"):
            out(name + ": " + ("AVAILABLE" if locate(name) else "NOT_DETECTED"))
        out("Local Bridge: sigue local-bridge/README.md para instalación por SHA y preflight.")
        out("WorkOS y túnel: sigue local-bridge/WORKOS.md; consentimiento OAuth externo y privado.")
        out("HTTPS: usa --bridge-setup únicamente con instancia privada existente e instalación revisada.")
        out("Verifica health autenticado y evidencia descartable según local-bridge/WSL-VALIDATION.md.")
        out("ADB y Codex: capacidades futuras, no se activan aquí.")
    out("AVAILABLE solo indica presencia en PATH; autenticación, versión, aislamiento y acceso no verificados.")
    out("No se concedieron permisos, instalaron componentes ni iniciaron servicios.")
    return 0
