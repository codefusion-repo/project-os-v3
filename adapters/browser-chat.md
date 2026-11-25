# Adapter: browser chat

Aplica [PROJECT_OS.md](../PROJECT_OS.md) como autoridad metodológica y recupera su versión según AGENTS.md. Este adapter concreta mecanismos de la superficie, no redefine reglas.

## Implementación directa

Usa GitHub Connector para operaciones remotas y Local Bridge para acceso autorizado al terminal. Codex se ejecuta en el terminal como implementador; Local Bridge y terminal no son implementadores. Para roles y fallback aplica la [invariancia](../PROJECT_OS.md#invariancia-de-la-metodología-entre-proveedores) y el [contrato MVP](../local-bridge/MVP.md). No presupongas shell general ni acceso al checkout del PM. Jobs: handlers registrados, health, clave idempotente estable, consulta de estado y evidencia; un fixture no acredita recursos reales.

## Capacidades de review

Mapea review.read a consultas reales del conector y review.publish a creación de comentario nuevo (no review formal). Aplica [trazabilidad y autorización](../PROJECT_OS.md#trazabilidad-github-obligatoria) y [review_for_close](../workflows/review_for_close.md). Comprueba HEAD mediante lectura remota antes y después de publicar. Usa identificador único para reconciliar historial completo ante reintento ambiguo; si no se confirma, indica review no publicado (publicación no confirmada). En BLOCKED con publicación confirmada, entrega repo/PR, SHA y <url_permanente_del_comentario> para corregir en el mismo PR.

## Review y closeout en una operación

Aplica los gates de [implementación, testing y review](../PROJECT_OS.md#implementación-testing-y-review). Para merge mediante conector exige expected_head_sha atómico igual al SHA revisado. Si no existe capacidad efectiva para una acción autorizada, distingue la causa y entrega solo un bloque gh/Git con comentarios breves y preflight: compara HEAD con el SHA revisado, usa gh pr merge --match-head-commit con método permitido, ready si procede, verifica merge, SHA, base y checks y cierra únicamente el issue identificado cuando los gates centrales lo permitan. No uses --admin ni --force. Ante resultado ambiguo consulta estado e historial antes de reintentar.

Para limpieza local autorizada sin checkout accesible, entrega comandos de identidad, git status, git worktree list y ancestry hacia base integrada; usa git branch -d solo si corresponde y está integrada, detente si falla. Aplica [seguridad y límites](../PROJECT_OS.md#seguridad-transversal-y-límites).

En éxito entrega resultado, enlaces verificados y comandos locales restantes; en BLOCKED o PASS pendiente, findings o permiso faltante y evidencia. Sin capacidad aplica el fallback anterior; sin bundles.

## Referencias operativas

Aplica obligatoriamente la [selección de templates](../PROJECT_OS.md#selección-de-templates), [github-traceability](../skills/github-traceability/SKILL.md) y [adopción y versión](../PROJECT_OS.md#instalación-adopción-y-versión-del-proyecto). Si el conector no permite leer o verificar un artefacto, declara el límite.
