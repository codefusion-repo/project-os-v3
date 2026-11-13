# Addendum — Project OS v3 MVP

Complementa [V3_SPEC.md](V3_SPEC.md). Ante contradicciones, prevalecen estas decisiones del PM:

- El selector es obligatorio y conserva una experiencia familiar: selección interactiva de workflows y skills, composición, prompts listos para el agente, `continue` predeterminado y navegación rápida con pocas decisiones. Simplificar la implementación no debe degradar la experiencia útil. No importar resolver, kernel ni catálogo MOS de v2.
- El PM autoriza desarrollar `codefusion-repo/project-os-v3` como repositorio público, subir el código y documentación de este MVP y abrir su draft PR. No incluir secretos, credenciales, datos privados ni material interno de otros repositorios. Merge, releases, deploys, permisos, settings y otras acciones sensibles siguen requiriendo autorización específica.
- La entrega sigue siendo una unidad cohesiva y práctica, validada y lista para revisión, sin añadir burocracia.

## Templates operativos GitHub

La biblioteca se amplía de diez a catorce templates: [merge](../templates/merge.md), [close](../templates/close.md), [comment](../templates/comment.md) y [review-comment](../templates/review-comment.md) preparan mensajes y acciones con referencias y resultados verificados. Se integran con implement, review, close y github-traceability y se descubren mediante el selector. Preparación, ejecución y confirmación son distintas; merge y cierre requieren autorización específica. Se reutilizan la unidad y conversación existentes.
