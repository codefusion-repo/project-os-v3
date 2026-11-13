# Validación del MVP

Resultados observados durante las correcciones del wizard y la trazabilidad histórica:

| Comando | Exit code | Resultado |
|---|---:|---|
| `python3 -m unittest discover -s tests -v` | 0 | 43 tests: edición secuencial, locator, campos PM, advertencias, contrato de historial y browser, PTY, configuración, secretos, persistencia y estructura. |
| `python3 tools/select.py --workflow review --skill code-review --locator 1 --objective 'Revisar el PR 1 de codefusion-repo/project-os-v3, incluyendo selector y pruebas; no hacer merge.' > /tmp/project-os-v3-selector-preview.txt` | 0 | Vista previa y archivo Markdown real en `.project-os/prompts/`, carpeta ignorada por Git. |
| `python3 tools/select.py --prototype --skill testing --skill security-review --output-dir /tmp/project-os-v3-validation-20261113 --objective 'Experimento local y descartable sin repositorio: validar un filtro.' > /tmp/project-os-v3-validation-preview.txt` | 0 | Prompt guardado con ambas skills base, rapid-prototype, testing y security-review una vez cada una. |
| `git check-ignore -v .project-os/config.json .project-os/prompts/example.md` | 0 | Ambos paths están cubiertos por `.project-os/`. |
| `git diff --check` | 0 | Sin errores de whitespace en los cambios observados. |

Durante el desarrollo, tres ejecuciones de la suite terminaron con exit 1: una detectó exposición de una cadena sintética dividida en líneas, y dos detectaron aserciones del contrato demasiado estrictas. Se corrigieron y la suite final terminó con exit 0. Se realizó una demostración PTY aislada de edición secuencial, con valores preservados y exit 0.

Se ejecutaron dos sesiones interactivas adicionales en una copia aislada del kit: ambas terminaron con exit 0; la segunda recuperó repo y carpeta sin reutilizar los campos PM. Un proceso independiente leyó únicamente un prompt generado y resolvió mediante GitHub el PR #1 incluido en su locator; no se ejecutó un chat nuevo. El reemplazo y los fallos de escritura se comprobaron en carpetas temporales mediante la suite, sin borrar archivos ajenos ni usar datos de producción. La publicación atómica requiere soporte de enlaces duros en la carpeta de salida; el selector falla si la plataforma no ofrece apertura de directorios sin seguimiento de symlinks.

## Evidencia adicional de fuentes vivas

En la implementación previa, las consultas `gh repo view`, `gh pr list`, `gh issue list` y `gh pr view` terminaron con exit 0 desde esta sesión y recuperaron el repositorio y draft PR #1. Las pruebas automáticas verifican el contenido y los enlaces de las instrucciones, pero no prueban el comportamiento de un chat nuevo ni otro agente. Los escenarios de aceptación de continuidad, comparación entre superficies y detención de acción sensible en una sesión real siguen sin ejecutar. El dogfood de rendimiento y la comparación con v2 tampoco se han ejecutado.

## Plataforma y CI

Validación local observada: Linux, Python 3.12.13. La plataforma soportada es Linux con Python 3.9 o superior y un filesystem con soporte POSIX de apertura sin seguir symlinks y enlaces duros. El check GitHub Actions ejecuta `python3 -m unittest discover -s tests -v` en Ubuntu; su resultado remoto debe consultarse tras el push. La detección de secretos usa patrones comunes y no es exhaustiva.

## Límite de aceptación de browser chat

La suite comprueba la conexión estructural de las instrucciones de `review.read`, `review.publish`, SHA, reintentos y fallback; no ejecuta un agente browser ni simula sus permisos. Las pruebas de publicación de review, falta de permiso, fallos remotos, reintentos, cambio de SHA y recuperación desde otra sesión siguen pendientes de una sesión browser con las capacidades y autorizaciones reales.
