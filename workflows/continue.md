# continue

Retomar un outcome desde evidencia viva y elegir el próximo paso seguro.

## Objetivo
Recuperar contexto suficiente para actuar sin depender del historial del chat.
## Cuándo usar
Cold start, cambio de sesión o continuación de un issue/PR.
## Ruta rápida
1. Con solo el repo identificado, inspecciona instrucciones y fuentes accesibles; recupera objetivo y restricciones sin historial del chat.
2. Consulta issues, PRs, commits, diffs, checks, findings y blockers relevantes en GitHub si está disponible; inspecciona rama y cambios locales cuando existan.
3. Reúne objetivo, estado, refs, validaciones, blockers y próximo paso seguro; continúa sin repetir preguntas respondibles desde evidencia.
## Evidencia y validación
Cita refs, estado y checks observados; no afirmes estado remoto sin consultarlo. Skills sugeridas: [repo-context](../skills/repo-context/SKILL.md), [github-traceability](../skills/github-traceability/SKILL.md).
## Salida
Estado actual, evidencia, limitaciones y próximo paso o resultado realizado.
## Escalación localizada
Pide como máximo un locator primario si existe ambigüedad material no resoluble; explica falta de acceso y continúa lo seguro. Detén solo la acción sensible sin autorización.
