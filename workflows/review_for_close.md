# review_for_close

Revisar un PR y ejecutar su closeout en el mismo recorrido.

## Objetivo
Detectar defectos y resolver el outcome completo al solicitar este workflow: PASS implica cierre; BLOCKED implica publicación de findings sin cierre.
## Cuándo usar
Review y cierre de un PR concreto. Solo una exclusión expresa de cierre o solo lectura limita ese outcome.
## Ruta rápida
1. Recupera repo, PR, issue vinculado y su estado, HEAD completo, base, diff, commits, checks, reviews, findings, permisos y reglas desde fuentes vivas. Aplica [PROJECT_OS.md](../PROJECT_OS.md#implementación-testing-y-review); la solicitud del workflow autoriza sus dos ramas. No solicites otro GO, ni SHA o evidencia ya recuperables.
2. Examina código, tests, riesgos y criterios. El mismo agente implementador puede revisar en la misma sesión. Registra SHA e identificador único. Ante defecto, incertidumbre material, CI fallido o HEAD cambiado, entrega **BLOCKED**, publica findings si existe capacidad y no hay restricción explícita, y no hagas merge ni cierre.
3. Con PASS ejecuta en la misma operación el closeout sin segunda confirmación: ready si procede, merge con HEAD revisado protegido atómicamente, verifica PR, SHA de merge, base y checks; cierra el issue identificado como completed y verifica. Aplica idempotencia, reintentos y fallback del [adapter](../adapters/browser-chat.md). Si la solicitud excluye el cierre, termina en PASS / REVIEW SIN CIERRE; si un gate o capacidad lo impide, informa la causa real.
## Evidencia y validación
Usa código y checks reales; identifica findings, SHA y límites. No inventes aprobación, ejecución ni pruebas. Una review de solo lectura no crea commits; aplica [github-traceability](../skills/github-traceability/SKILL.md). Skills sugeridas: [code-review](../skills/code-review/SKILL.md), [security-review](../skills/security-review/SKILL.md), [testing](../skills/testing/SKILL.md).
## Salida
BLOCKED con findings o resultado de cierre y URLs verificadas, más comandos seguros de limpieza local si proceden. Si falta capacidad, aplica el fallback de comandos del adapter. Aplica [review](../templates/review.md), [review-comment](../templates/review-comment.md), [comment](../templates/comment.md), [merge](../templates/merge.md) y [close](../templates/close.md) según el artefacto que corresponda; su estructura es obligatoria en GitHub conforme a [selección de templates](../PROJECT_OS.md#selección-de-templates), sin duplicar entradas ni ampliar alcance.
## Escalación localizada
Aplica los límites de [PROJECT_OS.md](../PROJECT_OS.md#implementación-testing-y-review); no detengas la operación solicitada para pedir aprobación adicional. Respeta restricciones explícitas, políticas y gates técnicos.
