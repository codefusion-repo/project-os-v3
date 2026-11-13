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
4. Para cambios destinados a integración, prepara un commit significativo y publícalo si hay autorización y capacidad; reutiliza el PR existente y verifica SHA remoto y checks disponibles.
## Evidencia y validación
Muestra demo o pruebas reales y exit codes. Aplica [github-traceability](../skills/github-traceability/SKILL.md): sin publicación verificable informa trazabilidad pendiente; solo un experimento expresamente local y descartable se exceptúa. Skills sugeridas: [implement-change](../skills/implement-change/SKILL.md), [rapid-prototype](../skills/rapid-prototype/SKILL.md), [debug](../skills/debug/SKILL.md), [testing](../skills/testing/SKILL.md).
## Salida
Rutas, resultado observable, validación, SHA/URL remotos verificados o trazabilidad pendiente con bloqueo, riesgos y próximo paso; [prototype](../templates/prototype.md) y [comment](../templates/comment.md) ayudan si se necesita una demo o actualización en el issue/PR existente.
## Escalación localizada
Detén solo acciones sensibles no autorizadas; no confundas datos simulados con producción.
