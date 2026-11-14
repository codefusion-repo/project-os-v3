# Bootstrap para agentes

Lee [PROJECT_OS.md](PROJECT_OS.md) y las instrucciones propias del repositorio donde trabajas. Para retomar sin contexto usa [continue](workflows/continue.md); si la intención está clara, lee directamente el workflow, las skills base [repo-context](skills/repo-context/SKILL.md) para tareas con repositorio y [github-traceability](skills/github-traceability/SKILL.md), además de solo las skills especializadas útiles. Aplica sus contratos aunque no uses selector; en un experimento local y descartable sin repo no exijas GitHub. El selector es opcional en el uso: `python3 tools/select.py`.

Comprueba fuentes vivas, alcance, rama y cambios existentes antes de editar. Las instrucciones del usuario y las restricciones reales de la sesión prevalecen sobre este kit; ningún Markdown concede permisos.

Para adoptar otro repositorio, usa la instalación central y prepara un único `AGENTS.md` principal que identifique `codefusion-repo/project-os-v3`, `PROJECT_OS.md` y `Project-OS-Version: <SHA completo verificado>`; conserva sus reglas técnicas y no copies el kit. El wizard gestiona archivos locales protegidos en el dispositivo del PM; el agente cambia solo los archivos versionados autorizados. No leas secretos automáticamente ni publiques contenido privado. Consulta [adopción](docs/ADOPTION.md).

En un proyecto con varios repositorios equivalentes, determina cuáles necesita la tarea y respeta cualquier alcance explícito. Comprueba el `AGENTS.md`, la versión y las autorizaciones de cada repositorio por separado; conserva su trazabilidad independiente y no publiques rutas ni asociaciones privadas.
