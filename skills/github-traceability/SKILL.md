# Skill: github-traceability

## Para qué sirve
Mantener continuidad verificable con issues, PRs, commits y checks sin state machine propia.

## Cuándo conviene
Crear unidad de trabajo, implementar, revisar, cambiar de agente o preparar cierre.

## Entradas mínimas
Repo, scope autorizado y locator de issue/PR si existe.

## Procedimiento concreto
1. Verificar estado actual del repo/issue/PR/checks con GitHub, sin asumirlo desde una nota.
2. Reusar issue/PR del outcome existente; crear uno nuevo solo si agrega trazabilidad y está autorizado.
3. Preparar actualizaciones con [comment](../../templates/comment.md) o findings/respuestas con [review-comment](../../templates/review-comment.md); comprobar el hilo antes de publicar para evitar duplicados.
4. Ante findings, corregir en el mismo PR y revalidar; no cerrar/mergear sin autorización específica.
5. Usar [merge](../../templates/merge.md) o [close](../../templates/close.md) para preparar readiness y mensajes cuando corresponda. Con autorización específica, ejecutar y verificar el estado real por separado; preparar handoff con links y próximo paso seguro.

## Validación y salida
Links GitHub, estado verificado, evidencia y acciones pendientes.

## Riesgos/limitaciones
Capacidad del conector no equivale a permiso del PM; no mutar por la sola existencia de APIs de escritura.
