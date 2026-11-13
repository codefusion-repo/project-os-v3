# Validación del MVP

Resultados observados al reconstruir el selector, en Linux con Python 3.12.13:

| Comando | Exit | Resultado |
|---|---:|---|
| `python3 -m unittest discover -s tests -v` | 0 | 30 tests; uno omitido porque `prompt_toolkit` no está instalado en el Python del sistema. |
| `.project-os/venv/bin/python -m unittest discover -s tests -v` | 0 | 30 tests sin omisiones con `prompt_toolkit` 3.0.53. |
| `git check-ignore -v .project-os/config.json .project-os/prompts/example.md .project-os/venv/bin/python` | 0 | Configuración, prompts y entorno local ignorados por Git. |
| `git diff --check` | 0 | Sin errores de whitespace en el diff comprobado. |
| `gh pr view 1 --json number,headRefName,headRefOid,url,state,isDraft,statusCheckRollup` | 0 | Draft PR #1 y checks existentes recuperados; consultar nuevamente tras el push. |

Ambas ejecuciones de la suite incluyen una sesión en pseudo-terminal: pega un reporte con líneas vacías y líneas que parecen opciones de menú, comprueba que no se avanza hasta Enter, pega un comentario, usa las flechas, guarda y edita el prompt preservando el contenido. La prueba simula una terminal que envía el protocolo bracketed paste; no demuestra el comportamiento de terminales incompatibles. También se comprueban selección y edición de workflow y múltiples skills, preferencias entre sesiones sin reutilizar campos PM, cancelación, reemplazo, errores de escritura, rutas, detección heurística de secretos y ausencia de llamadas Git/GitHub artificiales. El test de sugerencias dinámicas solo se ejecuta con el paquete opcional.

Se generó un prompt `review` real en una carpeta temporal, con repositorio `codefusion-repo/project-os-v3`, referencia `https://github.com/codefusion-repo/project-os-v3/pull/1`, las dos skills base, `code-review`, `testing` y contexto explícito; el comando terminó con exit 0. La ruta temporal pertenece a esta sesión y puede desaparecer. Las pruebas verifican el contenido, pero no se ejecutó un chat nuevo con ese archivo.

Durante la reconstrucción hubo fallos intermedios: una suite anterior con 43 tests falló por una expectativa interactiva; la primera suite de la reimplementación falló en un test por una entrada de prueba incompleta; otra ejecución detectó un error de sintaxis en el test editado. Al añadir el paquete opcional, la primera suite falló porque `tools/select.py` ocultaba el módulo estándar `select` al cargar `asyncio`. Se corrigieron y se ejecutaron las suites indicadas arriba. Estos intentos no representan validaciones exitosas.

## Límites y CI

El selector base usa Python stdlib; la interfaz enriquecida requiere instalar `prompt_toolkit` en el entorno elegido. El pegado multilinea requiere una terminal que soporte bracketed paste; para terminales incompatibles se pueden usar los flags. La protección de secretos es heurística y no exhaustiva. Se requiere soporte POSIX para apertura sin seguir symlinks y enlaces duros en destino.

El workflow de GitHub Actions ejecuta la suite con stdlib y luego con el paquete opcional; el resultado del nuevo commit debe verificarse en GitHub después del push. Las pruebas de publicación de reviews de browser, fallos remotos y recuperación en otra sesión real continúan pendientes. No se ha ejecutado dogfood de rendimiento ni comparación de rendimiento con v2.
