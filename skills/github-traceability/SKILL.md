# Skill: github-traceability

## Para qué sirve
Mantener continuidad verificable con issues, PRs, commits y checks sin state machine propia.

## Cuándo conviene
Crear unidad de trabajo, implementar, revisar, cambiar de agente o preparar cierre.

## Entradas mínimas
Repo, scope autorizado y locator de issue/PR si existe.

## Procedimiento concreto
1. Para tareas con repositorio, consultar issue, PR, commits, diff, checks, findings y bloqueos pertinentes; en un experimento expresamente local y descartable sin repo, omitir consultas GitHub; recuperar la unidad existente y no crear otro PR para el mismo outcome.
2. Para cambios versionados destinados a integración, implementar y validar el alcance autorizado; preparar un commit significativo solo con cambios propios, sin commits vacíos.
3. Si hay autorización y capacidad, publicar el commit y actualizar el mismo PR existente. Verificar el SHA en GitHub, estado del PR y checks disponibles; registrar comandos/tests, resultados y riesgos reales.
4. Si falta acceso, permiso o autorización, continuar el trabajo seguro y reportar **trazabilidad pendiente**, bloqueo y siguiente paso. Un commit solo local no es publicación remota ni entrega completa en GitHub.
5. Persistir decisiones o bloqueos en el hilo existente solo si aportan al cold start y está autorizado; evitar comentarios redundantes. Las consultas o reviews de solo lectura no producen commits. Solo los experimentos expresamente locales y descartables se exceptúan de publicación; si además no hay repositorio, no requieren consultas GitHub. Los cambios destinados a integración no se exceptúan.

## Validación y salida
SHA o URL remotos verificados, issue/PR y checks disponibles, tests ejecutados, riesgos y estado real. No inventar resultados ni declarar publicación sin evidencia.

## Riesgos/limitaciones
La skill no concede permisos. Merge, cierre, release y deploy requieren autorización separada; no mutar por la sola existencia de APIs de escritura.
