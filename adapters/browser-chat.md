# Adapter: browser chat

Aplica [PROJECT_OS.md](../PROJECT_OS.md) como autoridad metodológica y recupera su versión según AGENTS.md. Este adapter concreta mecanismos de la superficie, no redefine reglas. Si se pega como texto en una sesión nueva, identifica el repositorio mediante el locator del PM, lee AGENTS.md y recupera y verifica PROJECT_OS.md desde la referencia aplicable antes de cualquier mutación. Si no puedes recuperar o verificar la metodología, detén toda mutación y entrega solo diagnóstico de lectura y el bloqueo; no uses el texto pegado como sustituto.

## Recuperación agrupada de metodología (LB-06)

Cuando `methodology_context` esté disponible en el Bridge autorizado, úsalo para recuperar en una llamada el AGENTS.md del proyecto, PROJECT_OS.md, workflow elegido, skills base y adicionales pertinentes, templates aplicables y adapter. Indica el identificador del proyecto y, si se conoce, el SHA completo esperado mediante `expected_revision`. Comprueba procedencia de cada documento, SHA fijado o base integrada aplicable, integridad de blobs y `complete` antes de mutar; el servicio usa objetos Git de la instalación revisada, no archivos de trabajo. Para AGENTS.md de un proyecto adoptado comprueba que la revisión local devuelta corresponde a la aplicable; no confundas HEAD local con una referencia remota verificada. Si falta versión, documento o capacidad, recupera la referencia exacta con los mecanismos existentes; no mezcles versiones ni sustituyas metodología por texto externo. No hagas llamadas separadas al GitHub Connector para documentos ya recuperados y verificados. GitHub Connector sigue siendo necesario para operaciones remotas no cubiertas; la disponibilidad del método no amplía permisos.

## Implementación directa

Usa GitHub Connector para operaciones remotas y Local Bridge para acceso autorizado al terminal. Codex se ejecuta en el terminal como implementador; Local Bridge y terminal no son implementadores. Para roles y fallback aplica la [invariancia](../PROJECT_OS.md#invariancia-de-la-metodología-entre-proveedores) y el [contrato MVP](../local-bridge/MVP.md). No presupongas shell general ni acceso al checkout del PM. Jobs: handlers registrados, health, clave idempotente estable, consulta de estado y evidencia; un fixture no acredita recursos reales.

## Capacidades de review

Mapea review.read a consultas reales del conector y review.publish a creación de comentario nuevo (no review formal). Aplica [trazabilidad y autorización](../PROJECT_OS.md#trazabilidad-github-obligatoria) y [review_for_close](../workflows/review_for_close.md). Comprueba HEAD mediante lectura remota antes y después de publicar. Usa identificador único para reconciliar historial completo ante reintento ambiguo; si no se confirma, indica review no publicado (publicación no confirmada). En BLOCKED con publicación confirmada, entrega repo/PR, SHA y <url_permanente_del_comentario> para corregir en el mismo PR.

## Review y closeout en una operación

Aplica los gates de [implementación, testing y review](../PROJECT_OS.md#implementación-testing-y-review). Para merge mediante conector exige expected_head_sha atómico igual al SHA revisado. Si no existe capacidad efectiva para una acción autorizada, distingue la causa y entrega solo un bloque gh/Git con comentarios breves y preflight: compara HEAD con el SHA revisado, usa gh pr merge --match-head-commit con método permitido, ready si procede, verifica merge, SHA, base y checks y cierra únicamente el issue identificado cuando los gates centrales lo permitan. No uses --admin ni --force. Ante resultado ambiguo consulta estado e historial antes de reintentar.

Para limpieza local autorizada sin checkout accesible, entrega comandos de identidad, git status, git worktree list y ancestry hacia base integrada; Si corresponde y la rama local está integrada, usa `git branch -d <rama>` tras las comprobaciones; si falla, detente y conserva la rama. Aplica [seguridad y límites](../PROJECT_OS.md#seguridad-transversal-y-límites).

En éxito entrega resultado, enlaces verificados y comandos locales restantes; en BLOCKED o cierre impedido, findings o causa técnica/restricción aplicable y evidencia. Sin capacidad aplica el fallback anterior; sin bundles.

## Referencias operativas

Aplica obligatoriamente la [selección de templates](../PROJECT_OS.md#selección-de-templates), [github-traceability](../skills/github-traceability/SKILL.md) y [adopción y versión](../PROJECT_OS.md#instalación-adopción-y-versión-del-proyecto). Si el conector no permite leer o verificar un artefacto, declara el límite.

Si la superficie interrumpe la ejecución, aplica [Respuesta y continuidad](../PROJECT_OS.md#respuesta-y-continuidad); distingue límite técnico de decisión del PM y no presentes un checkpoint como resultado final.

Cuando una interrupción técnica obligue a devolver el control, ofrece un botón de continuación si la interfaz lo permite; al finalizar, ofrece un botón de siguiente operación recomendada cuando aporte valor. El botón envía un prompt contextualizado según el contrato central de continuidad: conserva fuente, alcance y restricciones vigentes, sin inventar exclusiones ni solicitar renovación; al pulsarlo, el PM solicita y autoriza la operación indicada, conforme a PROJECT_OS.md; el agente ejecuta sus pasos sin otra confirmación. Si no hay botones, entrega el prompt breve listo para usar. No esperes clics en checkpoints internos.
