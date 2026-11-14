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
3. La solicitud de implementación o corrección autoriza al agente terminal a publicar esos cambios, actualizar el mismo PR o abrir uno draft y registrar la ejecución, salvo restricciones superiores o instrucciones contrarias. Con capacidad, hacerlo sin pedir autorización redundante. Verificar el SHA en GitHub, estado del PR y checks disponibles; registrar comandos/tests, resultados y riesgos reales.
4. Si falta acceso, permiso o autorización, continuar el trabajo seguro y reportar **trazabilidad pendiente**, bloqueo y siguiente paso. Un commit solo local no es publicación remota ni entrega completa en GitHub.
5. Si existe issue/PR y publicar está autorizado, crear y verificar un comentario nuevo por cada ejecución material, incluidos intentos fallidos, bloqueos y validaciones fallidas. Registrar resultado, cambios o intento, SHA si existe, tests/checks observados, riesgos y siguiente paso. En el closeout de browser chat, cuando el merge ya proporciona trazabilidad suficiente, no se exige un comentario redundante salvo que el PM lo haya pedido. Nunca editar ni reemplazar entradas anteriores ni usar la descripción del PR como sustituto; evitar duplicar el mismo resultado. Sin acceso o autorización, preparar borrador e informar trazabilidad pendiente. Las consultas o reviews de solo lectura no producen commits. Solo los experimentos expresamente locales y descartables se exceptúan de publicación; si además no hay repositorio, no requieren consultas GitHub. Los cambios destinados a integración no se exceptúan.

## Publicación de review desde browser chat

El [adapter browser](../../adapters/browser-chat.md) es la fuente del procedimiento de `review.read` y `review.publish`: autorización, SHA, identificador, reintentos y estado **review no publicado**. Aplica también [review](../../workflows/review.md).

Para closeout de un PR en browser chat, el [adapter](../../adapters/browser-chat.md#closeout-de-un-pr) define la ejecución, idempotencia, fallback y salida mínima; aplica también [close](../../workflows/close.md). Una entrada de merge suficiente no necesita comentario redundante.

## Validación y salida
SHA o URL remotos verificados, issue/PR, enlace al comentario nuevo confirmado o borrador pendiente, checks, tests, fallos y riesgos reales. No inventar resultados ni declarar publicación sin evidencia.

## Riesgos/limitaciones
La skill no concede permisos. Merge, cierre, release y deploy requieren autorización separada; no mutar por la sola existencia de APIs de escritura.

## Publicación y continuidad seguras
Antes de enviar un commit, review o comentario, inspeccionar proporcionalmente su contenido real por secretos, datos privados y relaciones entre repositorios que no puedan divulgarse. Verificar si los archivos privados ya están bajo seguimiento; `.gitignore` no los retira. Sin autorización o ante posible exposición detener esa publicación y conservar un borrador seguro. Las relaciones técnicas necesarias para continuidad remota deben estar documentadas en Git solo cuando su divulgación esté autorizada; los checkouts y configuraciones locales nunca se publican automáticamente.


## Trazabilidad por repositorio
Cuando una tarea involucre varios repositorios equivalentes, recuperar y reutilizar las unidades existentes de cada uno. Verificar por separado permisos, visibilidad, ramas, modificaciones, commits, PRs, checks y comentarios autorizados. Una autorización o publicación en un repositorio no concede permisos ni acredita resultados en otro. No divulgar rutas locales ni asociaciones privadas.
