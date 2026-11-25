# review_for_close

Revisar un PR y ejecutar su closeout autorizado en el mismo recorrido.

## Objetivo
Detectar defectos y, si la revisión pasa y existe intención de closeout autorizada para ese PR y su issue identificado, completar y verificar el cierre sin otra operación.
## Cuándo usar
Review de código, tests y preparación de cierre de un PR concreto; sin autorización, la review puede terminar en PASS pendiente.
## Ruta rápida
1. Recupera repo, PR, issue vinculado y su estado, HEAD completo, base, diff, commits, checks, reviews, findings, permisos y reglas desde fuentes vivas. Recupera la intención autorizada vigente de review o closeout según [PROJECT_OS.md](../PROJECT_OS.md); no solicites SHA o evidencia disponible.
2. Examina código, tests, riesgos y criterios. Registra SHA e identificador único de la review; publica como acción inherente a la review autorizada si existe capacidad y no hay restricción explícita. Ante defecto, incertidumbre material, CI fallido o HEAD cambiado, entrega **BLOCKED** con evidencia y no hagas merge ni cierre.
3. Si pasa pero falta autorización de cualquier acción sensible, entrega **PASS / CLOSEOUT PENDIENTE DE AUTORIZACIÓN** precisando lo que falta, sin mutaciones no concedidas. PASS, el workflow y un conector no autorizan acciones.
4. Con PASS y autorización completa vigente, ejecuta en la misma operación el closeout disponible sin segunda confirmación: ready si procede, merge con HEAD revisado protegido atómicamente, verifica PR, SHA de merge, base y checks; cierra el issue identificado como completed y verifica. Aplica idempotencia, reintentos y fallback del [adapter](../adapters/browser-chat.md).
## Evidencia y validación
Usa código y checks reales; identifica findings, SHA, límites y autorización verificable. No inventes aprobación, ejecución ni pruebas. Una review de solo lectura no crea commits; aplica [github-traceability](../skills/github-traceability/SKILL.md). Skills sugeridas: [code-review](../skills/code-review/SKILL.md), [security-review](../skills/security-review/SKILL.md), [testing](../skills/testing/SKILL.md).
## Salida
BLOCKED con findings o PASS pendiente con permiso faltante; en éxito resultado y URLs verificadas, más comandos seguros de limpieza local si proceden. Si falta capacidad, aplica el fallback de comandos del adapter. Aplica [review](../templates/review.md), [review-comment](../templates/review-comment.md), [comment](../templates/comment.md), [merge](../templates/merge.md) y [close](../templates/close.md) según el artefacto que corresponda; su estructura es obligatoria en GitHub conforme a [selección de templates](../PROJECT_OS.md#selección-de-templates), sin duplicar entradas ni ampliar permisos.
## Escalación localizada
No infieras autorización de la selección ni del PASS. Merge y cierre heredan autorización de la intención de closeout con alcance; respeta instrucciones superiores y detén solo acciones no autorizadas.
