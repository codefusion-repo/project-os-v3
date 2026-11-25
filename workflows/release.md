# release

Evaluar la preparación de una entrega y sus riesgos de producción.

## Objetivo
Preparar una decisión de release basada en evidencia.
## Cuándo usar
Evaluación de publicación, versión o despliegue.
## Ruta rápida
1. Identifica ref, alcance, checks y estado real de revisión.
2. Evalúa compatibilidad, migraciones, datos, seguridad y rollback cuando apliquen.
3. Registra riesgos y preparación; ejecuta una acción de producción solo con autorización explícita.
## Evidencia y validación
Usa checks y controles observados; indica los no disponibles. Skills sugeridas: [security-review](../skills/security-review/SKILL.md), [documentation](../skills/documentation/SKILL.md).
## Salida
Ref, readiness, riesgos, rollback y pendientes. Aplica [release](../templates/release.md) obligatoriamente al artefacto GitHub correspondiente, conforme a [selección de templates](../PROJECT_OS.md#selección-de-templates); no crees una publicación solo para completar el template.
## Escalación localizada
La preparación no autoriza publicar, desplegar, cambiar configuración o hacer merge.
