# Adapter: agente de terminal

Aplica [PROJECT_OS.md](../PROJECT_OS.md) como autoridad metodológica. En ejecución adaptativa, este adapter corresponde a Codex ejecutado en terminal; también permite uso directo de terminal solicitado por el PM. Para roles y fallback aplica la [invariancia](../PROJECT_OS.md#invariancia-de-la-metodología-entre-proveedores).

## Capacidades de la superficie

Si la sesión lo permite, inspecciona y edita el checkout, ejecuta comandos y consulta GitHub mediante Git/gh. Comprueba identidad del checkout, rama, git status y worktrees antes de escribir; en ciclo PR usa work/* en el checkout existente, no main; no crees copias, clones ni worktrees adicionales. Aplica la regla central de reutilización de recursos. Respeta el sandbox y conserva cambios ajenos. Registra comandos, exit codes y resultados observados; distingue ejecución local de publicación remota. Para publicación usa guardas SHA y verifica refs remotas según [trazabilidad](../PROJECT_OS.md#trazabilidad-github-obligatoria).

Reutiliza el contexto agrupado ya verificado si está disponible y consulta fuentes vivas para lo faltante o desactualizado. Si preparas un checkout para un Job, verifica origin, rama, HEAD y SHA exacto; un fetch ordinario autorizado no cambia por sí mismo la rama ni acredita que un Job haya ejecutado. Conserva index y cambios existentes y reconcilia cualquier efecto incierto antes de repetirlo.

En el provider Codex, comprueba el SHA y rama de entrada y conserva cambios preexistentes; `target_branch` opcional autoriza preparar únicamente esa rama work/* en el mismo checkout. El resultado exige rama final y descendencia verificadas. Examina evidencia antes/después y reconcilia efectos inciertos; los digests no prueban el contenido de archivos no rastreados.

## Referencias operativas

Aplica obligatoriamente la [selección de templates](../PROJECT_OS.md#selección-de-templates), [adopción y versión](../PROJECT_OS.md#instalación-adopción-y-versión-del-proyecto) y [seguridad y límites](../PROJECT_OS.md#seguridad-transversal-y-límites). Comprueba exclusiones y seguimiento Git mediante git check-ignore y git ls-files antes de escribir archivos privados; no presupongas que el checkout pertenece al dispositivo del PM. Si faltan permisos de sandbox o herramientas, informa la capacidad ausente y conserva el trabajo seguro.

La inspección Git candidata de Browser utiliza el grant independiente `workspace_git_read` además de `workspace_prepare`, y respeta la exclusividad y reconciliación existentes. El fetch directo aún no está implementado; una lectura no reserva el checkout ni acredita que un fetch haya ocurrido.
