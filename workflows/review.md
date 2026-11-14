# review

Revisar código y evidencia para encontrar defectos accionables.

## Objetivo
Identificar riesgos concretos antes de continuar.
## Cuándo usar
Review de diff, PR o cambio ya implementado.
## Ruta rápida
1. Identifica base/head, alcance y criterios; inspecciona diff y código circundante.
2. Examina casos límite, seguridad y tests pertinentes; reproduce hallazgos cuando sea viable.
3. Entrega al PM findings por impacto con ubicación, evidencia, corrección, SHA revisado, checks y límites.
4. En browser chat, sigue el procedimiento de publicación y corrección del [adapter](../adapters/browser-chat.md).
## Evidencia y validación
Usa código y checks reales, no solo la descripción del PR. Identifica cada review material de forma única y evita duplicados en reintentos; no sustituyas ni edites historia. Una review de solo lectura no crea commits. Aplica [github-traceability](../skills/github-traceability/SKILL.md) a las correcciones versionadas. Skills sugeridas: [code-review](../skills/code-review/SKILL.md), [security-review](../skills/security-review/SKILL.md), [testing](../skills/testing/SKILL.md).
## Salida
Findings con ruta/línea, impacto y evidencia; indica si no hay hallazgos y qué no se revisó. Si se publicó la review, aporta URL permanente verificada y prompt de corrección con referencias; si no, entrega review y borrador, sin inventar URL. Si hubo correcciones, aporta SHA/URL verificados o informa trazabilidad pendiente con bloqueo. [review](../templates/review.md) y [review-comment](../templates/review-comment.md) ayudan a preparar findings o respuestas en el hilo existente.
## Escalación localizada
No infieras permisos del conector: comentar no autoriza review formal, cambios de código, merge ni despliegue. Detén solo la acción no autorizada.
