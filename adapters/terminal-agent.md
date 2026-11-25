# Adapter: agente de terminal

Aplica [PROJECT_OS.md](../PROJECT_OS.md) como autoridad metodológica. En ejecución adaptativa, este adapter corresponde a Codex ejecutado en terminal; también permite uso directo de terminal solicitado por el PM. Para roles y fallback aplica la [invariancia](../PROJECT_OS.md#invariancia-de-la-metodología-entre-proveedores).

## Capacidades de la superficie

Si la sesión lo permite, inspecciona y edita el checkout, ejecuta comandos y consulta GitHub mediante Git/gh. Comprueba identidad del checkout, rama, git status y worktrees antes de escribir; en ciclo PR usa work/*, no main. Respeta el sandbox y conserva cambios ajenos. Registra comandos, exit codes y resultados observados; distingue ejecución local de publicación remota. Para publicación usa guardas SHA y verifica refs remotas según [trazabilidad](../PROJECT_OS.md#trazabilidad-github-obligatoria).

## Referencias operativas

Aplica obligatoriamente la [selección de templates](../PROJECT_OS.md#selección-de-templates), [adopción y versión](../PROJECT_OS.md#instalación-adopción-y-versión-del-proyecto) y [seguridad y límites](../PROJECT_OS.md#seguridad-transversal-y-límites). Comprueba exclusiones y seguimiento Git mediante git check-ignore y git ls-files antes de escribir archivos privados; no presupongas que el checkout pertenece al dispositivo del PM. Si faltan permisos de sandbox o herramientas, informa la capacidad ausente y conserva el trabajo seguro.
