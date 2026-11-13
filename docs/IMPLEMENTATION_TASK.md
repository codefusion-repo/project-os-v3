# Encargo de implementación — Project OS v3

Implementar el MVP descrito en [V3_SPEC.md](V3_SPEC.md) y sus [addenda](V3_ADDENDUM.md), en una unidad cohesiva y sin etapas nuevas. Ante contradicciones, prevalecen las instrucciones más recientes del PM.

- Distribuir seis workflows, nueve skills, catorce templates, dos adapters y selector Python stdlib con tests. La selección de workflow y skills produce un prompt autocontenido, previsualizado y guardado de forma segura en la carpeta elegida; los templates son recursos internos; `continue` es default y Markdown directo siempre funciona.
- Hacer operativo el cold start con solo el repo identificado, usando instrucciones y fuentes GitHub vivas para recuperar objetivo, estado, refs, validaciones, blockers y próximo paso. Pedir como máximo un locator primario solo ante ambigüedad material no resoluble; informar límites reales de acceso.
- Compartir los formatos breves de Ejecución, Review y Decisión pendiente y los mismos criterios de evidencia entre superficies. Conservar las relaciones verificables de la unidad y reutilizar issue/PR existentes para implementación, revisión y correcciones. Persistir contexto adicional únicamente cuando aporte valor y esté autorizado.
- Separar preparación, ejecución y verificación. Continuar lo seguro ante incertidumbres secundarias; detener exclusivamente acciones sensibles sin autorización específica. Proteger secretos y no inventar resultados.
- La publicación de este MVP en el repositorio público y su draft PR están autorizados. Merge, release, deploy y configuración sensible no lo están por defecto.
- Ejecutar pruebas reales, registrar comandos y resultados, y conservar explícitamente como pendientes las pruebas de aceptación que necesiten otro chat, agente o superficie si no se ejecutaron. No construir kernel, resolver, catálogo MOS, estado propio, gates generalizados ni handoffs mecánicos.
