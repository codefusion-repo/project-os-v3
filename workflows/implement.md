# implement

Construir un cambio o prototipo mínimo y validarlo con evidencia.

## Objetivo
Entregar un resultado funcional y revisable dentro del alcance autorizado.
## Cuándo usar
Feature, corrección, refactor acotado o idea que necesita un slice vertical.
## Ruta rápida
1. Inspecciona requisitos, instrucciones, estado y código relevante; conserva cambios existentes.
2. Elige una solución simple; para prototipo define hipótesis y un camino entrada → lógica → salida visible.
3. Implementa y ejecuta la comprobación más útil; corrige fallos y revisa el diff.
4. Para cambios destinados a integración, prepara y publica un commit significativo dentro del alcance solicitado; reutiliza el PR existente o abre uno draft, aplica el template pull-request a su descripción vigente y execution o comment al registro material, y verifica contenido publicado, SHA remoto y checks disponibles. Aplica la autorización por intención de [PROJECT_OS.md](../PROJECT_OS.md) a estos pasos.
## Evidencia y validación
Muestra demo o pruebas reales y exit codes. Aplica [github-traceability](../skills/github-traceability/SKILL.md): sin publicación verificable informa trazabilidad pendiente; solo un experimento expresamente local y descartable se exceptúa. Skills sugeridas: [implement-change](../skills/implement-change/SKILL.md), [rapid-prototype](../skills/rapid-prototype/SKILL.md), [debug](../skills/debug/SKILL.md), [testing](../skills/testing/SKILL.md), [security-review](../skills/security-review/SKILL.md).
## Salida
Rutas, resultado observable, validación, SHA/URL remotos verificados o trazabilidad pendiente con bloqueo, riesgos y próximo paso; usa [prototype](../templates/prototype.md) si hay prototipo y [execution](../templates/execution.md) o [comment](../templates/comment.md) para el registro material autorizado en el issue/PR existente, conforme a [selección de templates](../PROJECT_OS.md#selección-de-templates).
## Escalación localizada
Detén solo acciones sensibles no autorizadas; no confundas datos simulados con producción.
