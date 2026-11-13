# Validación del MVP

Resultados observados durante la incorporación de las skills base y la trazabilidad:

| Comando | Exit code | Resultado |
|---|---:|---|
| `python3 -m unittest discover -s tests -v` | 0 | 21 tests: skills base y deduplicación, composición múltiple y prototipo, selección interactiva, generación y reemplazo seguros, errores, rutas, Markdown directo y ausencia de llamadas Git/GitHub del selector en un experimento local. |
| `python3 tools/select.py --workflow review --skill code-review --locator 1 --objective 'Revisar el PR 1 de codefusion-repo/project-os-v3, incluyendo selector y pruebas; no hacer merge.' > /tmp/project-os-v3-selector-preview.txt` | 0 | Vista previa y archivo Markdown real en `.project-os/prompts/`, carpeta ignorada por Git. |
| `python3 tools/select.py --prototype --skill testing --skill security-review --output-dir /tmp/project-os-v3-validation-20261113 --objective 'Experimento local y descartable sin repositorio: validar un filtro.' > /tmp/project-os-v3-validation-preview.txt` | 0 | Prompt guardado con ambas skills base, rapid-prototype, testing y security-review una vez cada una. |
| `git diff --check` | 0 | Sin errores de whitespace en los cambios observados. |

El reemplazo y los fallos de escritura se comprobaron en carpetas temporales mediante la suite, sin borrar archivos ajenos ni usar datos de producción. La publicación atómica requiere soporte de enlaces duros en la carpeta de salida; el selector falla si la plataforma no ofrece apertura de directorios sin seguimiento de symlinks.

## Evidencia adicional de fuentes vivas

En la implementación previa, las consultas `gh repo view`, `gh pr list`, `gh issue list` y `gh pr view` terminaron con exit 0 desde esta sesión y recuperaron el repositorio y draft PR #1. Las pruebas automáticas verifican el contenido y los enlaces de las instrucciones, pero no prueban el comportamiento de un chat nuevo ni otro agente. Los escenarios de aceptación de continuidad, comparación entre superficies y detención de acción sensible en una sesión real siguen sin ejecutar. El dogfood de rendimiento y la comparación con v2 tampoco se han ejecutado.
