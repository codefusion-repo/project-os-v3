# review

Revisar código y evidencia para encontrar defectos accionables.

## Objetivo
Identificar riesgos concretos antes de continuar.
## Cuándo usar
Review de diff, PR o cambio ya implementado.
## Ruta rápida
1. Identifica base/head, alcance y criterios; inspecciona diff y código circundante.
2. Examina casos límite, seguridad y tests pertinentes; reproduce hallazgos cuando sea viable.
3. Ordena findings por impacto con ubicación y escenario; indica validación y límites.
4. Si corresponde y está autorizado, corrige en el mismo PR y vuelve a validar.
## Evidencia y validación
Usa código y checks reales, no solo la descripción del PR. Skills sugeridas: [code-review](../skills/code-review/SKILL.md), [security-review](../skills/security-review/SKILL.md), [testing](../skills/testing/SKILL.md).
## Salida
Findings con ruta/línea, impacto y evidencia; indica si no hay hallazgos y qué no se revisó. [review](../templates/review.md) y [review-comment](../templates/review-comment.md) ayudan a preparar findings o respuestas en el hilo existente.
## Escalación localizada
No inventes aprobaciones ni realices merge; eleva solo la acción sin autorización.
