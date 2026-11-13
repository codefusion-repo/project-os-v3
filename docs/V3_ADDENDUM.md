# Addendum — Project OS v3 MVP

Complementa [V3_SPEC.md](V3_SPEC.md). Ante contradicciones, prevalecen estas decisiones del PM:

- El selector es obligatorio y conserva una experiencia familiar: selección interactiva de workflows y skills, composición, prompts listos para el agente, `continue` predeterminado y navegación rápida con pocas decisiones. Simplificar la implementación no debe degradar la experiencia útil. No importar resolver, kernel ni catálogo MOS de v2.
- El PM autoriza desarrollar `codefusion-repo/project-os-v3` como repositorio público, subir el código y documentación de este MVP y abrir su draft PR. No incluir secretos, credenciales, datos privados ni material interno de otros repositorios. Merge, releases, deploys, permisos, settings y otras acciones sensibles siguen requiriendo autorización específica.
- La entrega sigue siendo una unidad cohesiva y práctica, validada y lista para revisión, sin añadir burocracia.

## Templates operativos GitHub

La biblioteca se amplía de diez a catorce templates: [merge](../templates/merge.md), [close](../templates/close.md), [comment](../templates/comment.md) y [review-comment](../templates/review-comment.md) preparan mensajes y acciones con referencias y resultados verificados. Se integran con implement, review, close y github-traceability y el selector los incorpora automáticamente cuando corresponda, sin selección manual. Preparación, ejecución y confirmación son distintas; merge y cierre requieren autorización específica. Se reutilizan la unidad y conversación existentes.

## Garantías esenciales

El PM requiere cold start desde el repositorio y GitHub, respuestas comunes de Ejecución, Review y Decisión pendiente, trazabilidad de toda la unidad y continuidad entre agentes con fuentes vivas. El selector y los catorce templates permanecen obligatorios como artefactos; su uso no es un gate. Continuar lo seguro ante incertidumbre secundaria y detener solo acciones sensibles sin autorización. Los escenarios de aceptación y sus límites se describen en [V3_SPEC.md](V3_SPEC.md) y [ADOPTION.md](ADOPTION.md).

## Corrección del selector tras review

El selector previsualiza y guarda prompts Markdown operativos en `--output-dir` o en su carpeta local ignorada por Git. Tras guardar, reemplaza solo sus prompts anteriores identificados en la misma carpeta, con escritura atómica y protección de archivos ajenos, traversal y symlinks. Permite editar, cancelar y reutilizar la operación. No solicita selección de templates; véase [V3_SPEC.md](V3_SPEC.md).
