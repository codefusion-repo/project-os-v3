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

## Instalación central y proyectos — ejecución posterior

La línea base antes de esta ampliación fue `python3 -m unittest discover -s tests` con exit 0: 30 tests, uno omitido por faltar el paquete opcional. Durante la integración, una ejecución intermedia terminó con exit 1: el descubrimiento intentó interpretar una configuración central antigua y los marcadores `.git` vacíos del entorno de pruebas se trataron como repositorios inválidos. Se corrigieron el aislamiento de la configuración central y la detección; las pruebas posteriores verifican repositorios reales, worktrees y bare repositorios.

La suite ampliada prueba instalación y reinstalación en carpetas temporales, preservación de launchers y venv ajenos, fallback sin dependencia, launcher desde otro directorio, exclusión Git previa a escritura, negaciones de ignore, archivos privados rastreados, dos proyectos, configuración anidada, selección explícita, worktrees, preferencias relacionadas locales, migración de configuración antigua sin sobrescribir, SHA fijado y documentos locales modificados o no rastreados. Los tests de `.env` comprueban que un valor sintético no aparece en el prompt ni la salida; no constituyen una auditoría completa de lecturas del sistema. La detección de secretos continúa siendo heurística.

`python3 tests/smoke_local.py` terminó con exit 0 en un entorno temporal: creó un kit y un repo Git sintéticos, instaló el entorno real y launcher, ejecutó el launcher desde `/`, configuró el proyecto y verificó `git check-ignore`, generó un encargo de adopción, aplicó **manualmente en el fixture** cambios simulados en `AGENTS.md` y `.gitignore`, creó un commit local y generó un prompt con el SHA del kit sintético. El fixture no contiene un PR, checks ni comentario de GitHub y no demuestra que un agente distinto haya hecho la adopción. Los SHAs del fixture no son versiones canónicas. El test no declara un recorrido end-to-end completo.

La suite usa una rueda sintética sin red para probar la instalación y un fallo de dependencia controlado; el smoke instala la dependencia real en un entorno temporal. No se han probado una migración real de v2, publicación de relaciones multirrepositorio, una adopción real por un agente distinto ni el recorrido completo de GitHub y cold start de un proyecto piloto. El dogfood de rendimiento no se ha ejecutado.

Comandos finales observados para esta ampliación:

| Comando | Exit | Resultado |
|---|---:|---|
| `python3 -m unittest discover -s tests -q` | 0 | 58 tests; uno omitido porque ese Python no tiene `prompt_toolkit`. |
| `.project-os/venv/bin/python -m unittest discover -s tests -q` | 0 | 58 tests con `prompt_toolkit`, sin omisiones. El venv es una instalación local anterior y no se copia a proyectos. |
| `python3 tests/smoke_local.py` | 0 | Recorrido local parcial en repositorios sintéticos; instalación real, launcher, exclusión, encargo y prompt posterior. Adopción simulada manualmente. |
| `sh -n install.sh` | 0 | Sintaxis shell válida. |
| `python3 -m py_compile tools/select.py tools/project_local.py tests/smoke_local.py` | 0 | Sintaxis Python válida. |
| `git diff --check` | 0 | Sin errores de whitespace en el diff observado. |

CI debe verificarse para el SHA realmente publicado. La continuidad desde un agente nuevo y los escenarios browser se reportan por separado, solo si se ejecutan y observan.

## Review del selector y prompt único — ejecución posterior

Se recuperaron las revisiones del PR #1 sobre el SHA `719ecfd0938b33ddb9503a18d1a604a02a7e82ae`. La adopción consulta la API del repositorio canónico para confirmar que el SHA local es recuperable; si la consulta falla, el resultado es un borrador explícitamente no verificado y no indica fijar ese SHA. El wizard permite introducir un SHA objetivo diferente y elegir repositorios relacionados o escribir otro. El prompt operativo es único, autocontenido y breve, sin copiar documentos completos; conserva pasos esenciales y referencias para que el agente recupere las reglas verificables.

Para la misma operación `review`, skills `testing` y `code-review`, locator `1`, entrada y comentario, se generó el prompt de `719ecfd` y el actual. Ambos comandos terminaron con exit 0 y se comprobaron solicitud, locator y SHA idénticos: **23.417 bytes antes y 2.047 bytes después**, una reducción del 91,3 % en esa muestra. No se midieron tokens. La primera clonación de comparación falló con exit 128 por enlaces duros entre dispositivos; se repitió con `git clone --no-hardlinks` y terminó correctamente.

Se comprobó el commit `719ecfd0938b33ddb9503a18d1a604a02a7e82ae` en la API de GitHub con `gh api repos/codefusion-repo/project-os-v3/commits/719ecfd0938b33ddb9503a18d1a604a02a7e82ae --jq .sha`, exit 0. En un repositorio temporal se creó un commit exclusivamente local y la API del repositorio canónico respondió HTTP 422 y el verificador no confirmó ese SHA. Las pruebas también simulan falta de red, respuesta incompatible y borrador no verificado sin atribuir el SHA al repositorio canónico.

Durante el cambio del formato, una ejecución intermedia de la suite terminó con exit 1 porque varias aserciones aún esperaban documentos completos en el prompt; se actualizaron para comprobar referencias, contexto intacto e integridad sin duplicación. El smoke local mantiene la adopción simulada: una adopción piloto real por otro agente y su recorrido GitHub completo siguen pendientes, al igual que las pruebas reales de browser y el dogfood de rendimiento.

| Comando | Exit | Resultado |
|---|---:|---|
| `python3 -m unittest discover -s tests -q` | 0 | 69 tests; uno omitido por no estar instalado `prompt_toolkit` en ese Python. |
| `.project-os/venv/bin/python -m unittest discover -s tests -q` | 0 | 69 tests, sin omisiones. |
| `python3 tests/smoke_local.py` | 0 | Instalación y flujo local parcial; SHA `719ecfd` confirmado en GitHub y adopción del fixture simulada manualmente. |
| `python3 -m py_compile tools/select.py tools/project_local.py` | 0 | Sintaxis válida. |
| `git diff --check` | 0 | Sin errores de whitespace en el diff observado. |

CI y SHA final deben verificarse tras el push de esta corrección.
