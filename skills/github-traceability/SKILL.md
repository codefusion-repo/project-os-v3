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
5. Si existe issue/PR y publicar está autorizado, crear y verificar un comentario nuevo por cada ejecución material, incluidos intentos fallidos, bloqueos y validaciones fallidas. Registrar resultado, cambios o intento, SHA si existe, tests/checks observados, riesgos y siguiente paso. Nunca editar ni reemplazar entradas anteriores ni usar la descripción del PR como sustituto; evitar duplicar el mismo resultado. Sin acceso o autorización, preparar borrador e informar trazabilidad pendiente. Las consultas o reviews de solo lectura no producen commits. Solo los experimentos expresamente locales y descartables se exceptúan de publicación; si además no hay repositorio, no requieren consultas GitHub. Los cambios destinados a integración no se exceptúan.

## Publicación de review desde browser chat

Aplicar el [adapter browser](../../adapters/browser-chat.md) y [review](../../workflows/review.md).

- Distinguir `review.read` de `review.publish`: publicar requiere capacidad real y autorización explícita vigente del PM para repo/PR, respaldada por la configuración real del adaptador. Una autorización previa dentro de ese alcance se reutiliza; la existencia de conector no autoriza. Comentar no autoriza review formal, cambios de código, merge ni deploy.
- Entregar primero el review al PM con findings, severidad, ubicación, evidencia, corrección, límites y SHA inspeccionado. Para cada revisión material, asignar un identificador único estable durante reintentos; incluirlo con el SHA en un comentario nuevo sin datos sensibles.
- Comprobar head antes/después de publicar; indicar cualquier cambio frente al SHA revisado. Verificar comentario y URL permanente en GitHub. Si una respuesta es ambigua, buscar el identificador y contenido en el historial completo accesible antes de reintentar; si no puede comprobarse, no reenviar. Cada revisión material nueva usa identificador nuevo, sin editar ni borrar historia.
- Tras confirmar, preparar prompt compacto para terminal con repo, número/URL del PR, SHA revisado y URL del comentario: corregir los findings en el mismo PR, validar, publicar commits autorizados y registrar nueva ejecución. Si no se puede publicar, entregar review completo y borrador, decir **review no publicado**, no inventar URL y continuar lo seguro; ante resultado ambiguo aclarar que la publicación no está confirmada y podría existir.

## Validación y salida
SHA o URL remotos verificados, issue/PR, enlace al comentario nuevo confirmado o borrador pendiente, checks, tests, fallos y riesgos reales. No inventar resultados ni declarar publicación sin evidencia.

## Riesgos/limitaciones
La skill no concede permisos. Merge, cierre, release y deploy requieren autorización separada; no mutar por la sola existencia de APIs de escritura.

## Publicación y continuidad seguras
Antes de enviar un commit, review o comentario, inspeccionar proporcionalmente su contenido real por secretos, datos privados y relaciones entre repositorios que no puedan divulgarse. Verificar si los archivos privados ya están bajo seguimiento; `.gitignore` no los retira. Sin autorización o ante posible exposición detener esa publicación y conservar un borrador seguro. Las relaciones técnicas necesarias para continuidad remota deben estar documentadas en Git solo cuando su divulgación esté autorizada; los checkouts y configuraciones locales nunca se publican automáticamente.
