# Project OS v3

Kit Markdown-first para pasar de una intención a un resultado verificable con la menor fricción útil. Un workflow describe un resultado; una skill aporta una técnica; un template ayuda cuando existe un artefacto; el selector previsualiza y guarda prompts Markdown, sin ejecutar workflows ni autorizar acciones. Aplica las skills base [repo-context](skills/repo-context/SKILL.md) para tareas con repositorio y [github-traceability](skills/github-traceability/SKILL.md) según su contrato, también sin selector; carga solo las skills especializadas útiles. En un experimento local y descartable sin repositorio, no exijas consultas GitHub ni publicación remota. Una skill pedida explícitamente se selecciona, pero no amplía permisos.

## Ruta común

1. Con el repositorio identificado, recupera objetivo y estado desde instrucciones, archivos y fuentes GitHub vivas disponibles: issues, PRs, commits, diffs, checks, findings y blockers pertinentes. No dependas del historial del chat: haz un cold start completo solo cuando sea necesario y una comprobación acotada al continuar, sin recorrer todo el repo ni consultar todos los issues/PRs sin justificación. Distingue hechos, inferencias y propuestas; pide como máximo un locator primario solo ante ambigüedad material no resoluble con evidencia y continúa el trabajo seguro.
2. Comprueba target, rama, cambios existentes, capacidades, visibilidad y alcance autorizado antes de escribir. Conserva trabajo ajeno; toma decisiones técnicas reversibles sin pedir metadata disponible.
3. Trabaja y valida proporcionalmente al riesgo. Registra comandos, resultados y exit codes reales; identifica lo no probado y no inventes cobertura, aprobaciones ni estado remoto.
4. Entrega resultado, rutas o referencias, evidencia, riesgos y siguiente paso. Reutiliza el issue/PR existente durante implementación, review y correcciones; si no existe, crea uno solo cuando aporte valor y esté autorizado. Relaciona las referencias verificadas de issue, PR, commits, diff, checks, findings, decisiones y correcciones.

Para un prototipo, [implement](workflows/implement.md) con [rapid-prototype](skills/rapid-prototype/SKILL.md) recorre idea → slice vertical → validación; un experimento expresamente local y descartable puede terminar sin publicación. Los [templates](templates/) son adaptables, nunca formularios obligatorios.

## Trazabilidad GitHub obligatoria

Toda implementación, corrección o modificación versionada destinada a integrarse en un proyecto GitHub debe dejar evidencia remota identificable. Aplica siempre [github-traceability](skills/github-traceability/SKILL.md), también al operar directamente con Markdown. Esta regla y la skill no conceden autorización para escribir, hacer push, merge, cierre, release ni deploy.

1. Recupera el issue y PR existentes cuando los haya; implementa y valida el alcance autorizado sin alterar trabajo ajeno.
2. Prepara un commit significativo con los cambios propios, sin commits vacíos. Con capacidad y autorización, publica el commit y actualiza el mismo PR si existe; no abras otro PR para corregir el mismo outcome.
3. Verifica el SHA en el remoto, el PR y los checks disponibles. Informa SHA o URL reales, comandos/tests y resultados, riesgos y el estado remoto observado. Si falta acceso, permiso o autorización, conserva el trabajo seguro e informa **trazabilidad pendiente**, bloqueo y siguiente paso; un commit local sin push no satisface trazabilidad remota ni permite declarar entrega en GitHub.
4. Una consulta o review de solo lectura no crea commits artificiales. Solo un experimento expresamente local y descartable puede terminar sin publicación; si no tiene repositorio, tampoco exige consultas GitHub; la excepción no aplica a cambios destinados a integrarse. Persiste decisiones o bloqueos en el hilo existente solo cuando ayuden al cold start y estén autorizados, sin comentarios redundantes.

## Respuesta y continuidad

Usa una respuesta breve en el formato que corresponda, sin exigir un reporte por paso:

- **Ejecución:** resultado y rutas o refs; comandos/checks y resultados observados; riesgos y pendientes. Guía: [execution](templates/execution.md).
- **Review:** findings priorizados con ubicación, impacto y evidencia; checks y límites. Si no hay findings, indícalo sin inventar aprobación. Guía: [review](templates/review.md).
- **Decisión pendiente:** acción material bloqueada, hechos, opciones y próximo trabajo seguro. Guía: [decision](templates/decision.md).

Estos criterios de evidencia y veracidad son comunes a todos los workflows y adapters: distingue preparado, ejecutado y confirmado; indica lo no probado y nunca inventes resultados. Para continuidad, [handoff](templates/handoff.md) recoge objetivo, estado, refs vivas, validaciones, blockers materiales y siguiente acción segura. GitHub es la fuente persistente cuando está disponible: agrega un resumen al issue/PR existente solo si aporta contexto difícil de recuperar, está autorizado y no duplica comentarios.

## Límites

Las capacidades de una herramienta no son autorización. Detén solo la acción sensible que carezca de permiso explícito: merge, cierre final, release o publicación, despliegue, borrado destructivo, cambios de permisos, settings, secrets, credenciales o auth/pagos productivos. Continúa el trabajo seguro y explica la decisión pendiente. No expongas valores de secretos; usa `[REDACTED]`. Si una fuente no está disponible, informa el límite sin inventar.

Elige el [adapter de terminal](adapters/terminal-agent.md) o [browser chat](adapters/browser-chat.md) según capacidades reales. El kit no mantiene estado, no es un motor de workflows y no depende de v2.
