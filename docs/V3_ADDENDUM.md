# Addendum — Project OS v3 MVP

Complementa [V3_SPEC.md](V3_SPEC.md). La decisión consolidada de instalación central y adopción por proyecto al final de este documento prevalece sobre decisiones anteriores contradictorias:

- El selector es obligatorio y conserva una experiencia familiar: selección interactiva de workflows y skills, composición, prompts listos para el agente, `continue` predeterminado y navegación rápida con pocas decisiones. Simplificar la implementación no debe degradar la experiencia útil. No importar resolver, kernel ni catálogo MOS de v2.
- El PM autoriza desarrollar `codefusion-repo/project-os-v3` como repositorio público, subir el código y documentación de este MVP y abrir su draft PR. No incluir secretos, credenciales, datos privados ni material interno de otros repositorios. Merge, releases, deploys, permisos, settings y otras acciones sensibles siguen requiriendo autorización específica.
- La entrega sigue siendo una unidad cohesiva y práctica, validada y lista para revisión, sin añadir burocracia.

## Templates operativos GitHub

La biblioteca se amplía de diez a catorce templates: [merge](../templates/merge.md), [close](../templates/close.md), [comment](../templates/comment.md) y [review-comment](../templates/review-comment.md) preparan mensajes y acciones con referencias y resultados verificados. Se integran con implement, review_for_close y github-traceability y los agentes los utilizan cuando aportan valor, sin selección manual en el wizard. Preparación, ejecución y confirmación son distintas; merge y cierre requieren autorización específica. Se reutilizan la unidad y conversación existentes.

## Garantías esenciales

El PM requiere cold start desde el repositorio y GitHub, respuestas comunes de Ejecución, Review y Decisión pendiente, trazabilidad de toda la unidad y continuidad entre agentes con fuentes vivas. El selector y los catorce templates permanecen obligatorios como artefactos; su uso no es un gate. Continuar lo seguro ante incertidumbre secundaria y detener solo acciones sensibles sin autorización. Los escenarios de aceptación y sus límites se describen en [V3_SPEC.md](V3_SPEC.md) y [ADOPTION.md](ADOPTION.md).

## Corrección del selector tras review

El selector previsualiza y guarda prompts Markdown operativos en `--output-dir` o en su carpeta local ignorada por Git. Tras guardar, reemplaza solo sus prompts anteriores identificados en la misma carpeta, con escritura atómica y protección de archivos ajenos, traversal y symlinks. Permite editar, cancelar y reutilizar la operación. No solicita selección de templates; véase [V3_SPEC.md](V3_SPEC.md).

## Trazabilidad GitHub obligatoria

`github-traceability` es una skill base transversal: el selector la incluye una vez sin pedir selección, y [PROJECT_OS.md](../PROJECT_OS.md) obliga a aplicarla también con Markdown directo. Cambios versionados destinados a integración necesitan commit significativo y evidencia remota verificada; si falta acceso, permiso o autorización, se reporta trazabilidad pendiente, sin declarar entrega remota. Reutilizar issue/PR existentes, no crear commits ni comentarios artificiales y verificar SHA, PR y checks disponibles. Solo un experimento expresamente local y descartable se exceptúa. La política no concede permisos de push, merge, cierre, release o deploy.

## Skills base y composición múltiple

`repo-context` se aplica a tareas con repositorio y ajusta la profundidad a la evidencia necesaria; `github-traceability` conserva su contrato. El selector incorpora ambas una sola vez sin pedir selección, y admite varias skills especializadas opcionales incluso con `--prototype`. En un experimento expresamente local y descartable sin repo no se requieren consultas GitHub ni publicación. El uso directo de Markdown aplica las mismas reglas.

## Wizard-first y configuración local

El wizard comienza por buscar o seleccionar el workflow y luego solicita una lista de repositorios solo si falta, skills, contexto del PM, preview y guardado. Recuerda preferencias no sensibles en `.project-os/config.json` del proyecto o workspace, protegido de Git; un repositorio indicado no se considera verificado. Comentario y pregunta del PM son opcionales, multilínea y exclusivos de la operación; no se guardan en la configuración ni se reutilizan. El selector no exige referencias issue/PR que puedan recuperarse. Los flags pueden leer la configuración del proyecto sin modificarla; `--configure` solicita cambios explícitos.

## Correcciones de review del selector

El wizard conserva la entrada principal y el locator en campos separados cuando corresponde. La edición preserva los valores y `/limpiar` los elimina explícitamente. Antes de previsualizar o persistir se rechazan patrones comunes de secretos sin imprimirlos en errores; la detección es heurística. La plataforma validada y el check CI están descritos en [V3_SPEC.md](V3_SPEC.md).

## Wizard y trazabilidad histórica

Editar recorre secuencialmente los campos mostrando valores actuales; Enter conserva y `/limpiar` borra. Cada workflow tiene una etiqueta propia y una sola referencia contextual opcional cuando usa una unidad. Los campos PM contienen solo lo proporcionado; las notas automáticas se separan. Por cada ejecución material con unidad y autorización se crea y verifica un comentario nuevo, incluidos fallos y bloqueos; nunca se reemplaza el historial ni lo sustituye la descripción del PR. Sin autorización o acceso se prepara un borrador y se informa trazabilidad pendiente.

## Reviews de browser chat

El [adapter browser](../adapters/browser-chat.md), [review_for_close](../workflows/review_for_close.md) y [github-traceability](../skills/github-traceability/SKILL.md) distinguen `review.read` y `review.publish`, reutilizan la autorización previa efectiva de su alcance, publican reviews materiales como comentarios nuevos verificables y previenen duplicados al reintentar. El prompt de corrección solo referencia repo, PR, SHA y URL confirmada; ante falta de permiso o error ambiguo se entrega review/borrador con `review no publicado` y sin URL inventada.

## Rediseño del wizard según la experiencia de v2

La decisión posterior del PM sustituye el orden original: seleccionar operación primero, completar skills y campos, previsualizar, guardar o editar y reutilizar la sesión. Editar vuelve a permitir elegir workflow y skills sin preguntar el repositorio. La interfaz opcional con `prompt_toolkit` incorpora sugerencias dinámicas y edición directa; la alternativa stdlib continúa disponible. Ambas aceptan pegado de reportes mediante bracketed paste de una terminal compatible. La implementación se rehace en v3 sin importar ni ejecutar el código, resolver, kernel o catálogo de v2.

## Decisión consolidada: instalación central y adopción ligera

Instalar una vez, adaptar cada proyecto una vez y utilizar el wizard diariamente. No copiar el kit ni mantener perfiles centrales. `--project` selecciona explícitamente el proyecto o workspace; configuraciones anidadas incompatibles no se fusionan. El wizard protege y administra configuración y prompts locales; el agente adapta los archivos versionados y registra la trazabilidad autorizada. Cada repositorio fija un SHA verificable en su `AGENTS.md`. El selector utiliza documentos de ese commit mediante Git y no presenta archivos locales alterados como equivalentes. El SHA objetivo de un encargo de adopción se confirma también contra el repositorio canónico; si no puede verificarse, se prepara únicamente un borrador marcado como no verificado, que no permite fijar el SHA sin confirmación. La seguridad y la protección antes de publicar son transversales. Véanse [especificación](V3_SPEC.md) y [adopción](ADOPTION.md).

## Prompt acotado

El selector produce un único prompt con tarea, contexto, versión, límites y pasos esenciales. No copia el kit completo. El agente verifica y recupera las instrucciones aplicables y reporta cualquier límite de acceso.

## Repositorios equivalentes

El esquema local v2 utiliza `repositories` sin jerarquía. El agente determina los repos necesarios; `/alcance` o `--repo` repetido restringe solo la operación. La migración v1 reconocida conserva datos y es atómica; el CLI de generación no modifica preferencias. Se verifican permisos y trazabilidad por repositorio y no se publican rutas o asociaciones privadas.
