# Project OS v3

Kit Markdown-first para pasar de una intención a un resultado verificable con la menor fricción útil. Un workflow describe un resultado; una skill aporta una técnica; un template ayuda cuando existe un artefacto; el selector descubre y prepara texto, sin ejecutar ni autorizar acciones. Lee solo lo que sirva a la tarea. Una skill pedida explícitamente se selecciona, pero no amplía permisos.

## Ruta común

1. Entiende el resultado y consulta evidencia viva: instrucciones del repositorio, archivos pertinentes y, si existe acceso, issue/PR y checks. Distingue hechos, inferencias y propuestas.
2. Comprueba target, rama, cambios existentes, capacidades, visibilidad y alcance autorizado antes de escribir. Conserva trabajo ajeno; toma decisiones técnicas reversibles sin pedir metadata disponible.
3. Trabaja y valida proporcionalmente al riesgo. Registra comandos, resultados y exit codes reales; identifica lo no probado y no inventes cobertura, aprobaciones ni estado remoto.
4. Entrega resultado, rutas o referencias, evidencia, riesgos y siguiente paso. Un issue/PR es opcional si aporta trazabilidad y está autorizado; reutiliza el mismo para revisión y correcciones.

Para un prototipo, [implement](workflows/implement.md) con [rapid-prototype](skills/rapid-prototype/SKILL.md) recorre idea → slice vertical → validación, sin exigir issue ni PR. Los [templates](templates/) son adaptables, nunca formularios obligatorios.

## Límites

Las capacidades de una herramienta no son autorización. Detén solo la acción sensible que carezca de permiso explícito: merge, cierre final, release o publicación, despliegue, borrado destructivo, cambios de permisos, settings, secrets, credenciales o auth/pagos productivos. Continúa el trabajo seguro y explica la decisión pendiente. No expongas valores de secretos; usa `[REDACTED]`. Si una fuente no está disponible, informa el límite sin inventar.

Elige el [adapter de terminal](adapters/terminal-agent.md) o [browser chat](adapters/browser-chat.md) según capacidades reales. El kit no mantiene estado, no es un motor de workflows y no depende de v2.
