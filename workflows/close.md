# close

Verificar preparación para cierre y ejecutar únicamente acciones permitidas.

## Objetivo
Dejar claro qué está completo y qué falta para cerrar la unidad.
## Cuándo usar
Después de implementación y revisión, cuando se evalúa cierre.
## Ruta rápida
1. Consulta criterios, diff, issue/PR y checks actuales cuando estén disponibles.
2. Identifica el issue vinculado y comprueba su estado, findings, validación y pendientes; documenta cualquier límite. El cierre del issue requiere GO específico y verificación tras el merge; no lo infieras del vínculo.
3. En browser chat, con un PR concreto y GO explícito de closeout con merge, ejecuta las acciones autorizadas disponibles y verifica el resultado siguiendo el [adapter](../adapters/browser-chat.md#closeout-de-un-pr). Sin GO, no mutaciones; aplica allí el fallback y la salida mínima.
4. En otros casos prepara el cierre y realiza solo las acciones explícitamente autorizadas.
## Evidencia y validación
Referencias y resultados vivos, sin inferir aprobación o checks. Skills sugeridas: [testing](../skills/testing/SKILL.md).
## Salida
Readiness, evidencia, pendientes y acción concreta siguiente. Para closeout en browser chat prevalece la salida mínima del adapter. Usa [merge](../templates/merge.md), [close](../templates/close.md) o [comment](../templates/comment.md) internamente cuando aporten valor; preparar, ejecutar y verificar son pasos distintos.
## Escalación localizada
Merge y cierre final requieren autorización; prepara lo demás sin ejecutarlos.
