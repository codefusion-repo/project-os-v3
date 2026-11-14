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

Se recuperaron las revisiones del PR #1 sobre el SHA `719ecfd0938b33ddb9503a18d1a604a02a7e82ae`. La adopción consulta la API del repositorio canónico para confirmar que el SHA local es recuperable; si la consulta falla, el resultado es un borrador explícitamente no verificado y no indica fijar ese SHA. En esa revisión, el wizard permitía introducir otro SHA y elegir repositorios; la jerarquía de repositorios se sustituyó posteriormente por el esquema v2. El prompt operativo es único y acotado, sin copiar documentos completos; conserva pasos esenciales y referencias para que el agente recupere las reglas verificables.

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

## Templates y terminología — revisión posterior

Se sustituyó la terminología anterior por **prompt acotado** en la documentación actual: un solo formato que conserva tarea, contexto y pasos esenciales y referencia las instrucciones aplicables sin copiar el kit completo. La tabla de selección de [PROJECT_OS.md](../PROJECT_OS.md#selección-de-templates) enumera los 14 templates; ambos adapters indican consultarlos cuando aporten valor, omitir campos irrelevantes o desconocidos y no inventar evidencia. Las comprobaciones de estructura validan enlaces e instrucciones; no prueban por sí solas el comportamiento de agentes.

Un agente terminal independiente, en una sesión de solo lectura, consultó los 14 archivos y el estado vivo del [PR #1](https://github.com/codefusion-repo/project-os-v3/pull/1) en `cb1539a2dd8b6251515780e27c135088c2ce7e3f`. Informó que preparó resultados o borradores adaptados para `task`, `pull-request`, `review`, `review-comment`, `execution`, `decision`, `handoff`, `release`, `merge`, `close` y `comment`, con evidencia real del PR y sin ejecutar acciones sensibles. Consultó `issue`, `prototype` y `dogfood`, pero no produjo artefactos: respectivamente, no aportaba valor abrir otro issue, no había un prototipo ejecutado con evidencia y no se había realizado dogfood. No rellenó esas ausencias con resultados inventados.

El agente consultó el check remoto exitoso del SHA citado y los comentarios existentes; no ejecutó tests locales, no revisó integralmente el diff ni publicó sus borradores. La instrucción nueva del adapter que evaluó estaba en el árbol de trabajo aún sin publicar, por lo que el check remoto citado no valida este cambio. El PM indicó que está realizando por separado las pruebas reales de browser chat; sus resultados no están disponibles en esta ejecución. Por tanto, no se afirma validación funcional de browser ni del piloto completo.

| Comando | Exit | Resultado |
|---|---:|---|
| `python3 -m unittest discover -s tests -q` | 0 | 70 tests; uno omitido porque ese Python no tiene `prompt_toolkit`. |
| `.project-os/venv/bin/python -m unittest discover -s tests -q` | 0 | 70 tests sin omisiones. |
| `python3 -m unittest discover -s tests -p test_structure.py -v` | 0 | 8 tests de estructura y enlaces, tras documentar la validación terminal. |
| `git diff --check` | 0 | Sin errores de whitespace en el diff observado. |

El CI de este cambio debe verificarse en el SHA publicado. Las pruebas browser se realizan por separado y no se atribuyen a esta sesión.

## Repositorios equivalentes — revisión posterior

El esquema local v2 conserva una lista no vacía `repositories` sin jerarquía. El prompt identifica los repositorios conocidos y permite al agente decidir cuáles necesita; `/alcance` y `--repo` repetido limitan únicamente la operación, sin persistir el alcance. En un alcance limitado se omiten del prompt los repositorios conocidos que quedan fuera. El prompt exige comprobar permisos, visibilidad, rama, cambios, versión de instrucciones y trazabilidad por repositorio; no incluye rutas de checkout ni autoriza publicar asociaciones privadas.

Las pruebas usan únicamente proyectos temporales. Cubren un repositorio y tres repositorios, tareas transversales y alcances explícitos, ausencia de selección obligatoria, persistencia intacta, aislamiento, privacidad, Git, formato desconocido, conflictos y conversión v1 a v2 con deduplicación, checkouts, destino, archivos ajenos y conservación ante fallo de escritura o cambio concurrente. Como indicó el PM, **no hay proyectos reales de v3 que migrar**; no se migró ni modificó ningún proyecto real. La conversión v1 se comprobó solo con fixtures.

Dos proyectos que comparten carpeta de salida conservan sus prompts de forma independiente: se sustituye únicamente el prompt atribuible al proyecto actual. Los archivos anteriores sin identificación de proyecto se preservan, y las invocaciones sin raíz local no eliminan prompts de otras invocaciones. También se comprueba la advertencia al proporcionar una URL de issue fuera de un alcance explícito.

Una revisión posterior detectó que `--configure --checkout` podía descartar otras rutas locales ya guardadas. La corrección conserva las demás rutas y permite actualizar la indicada; se agregó un test de regresión.

Las pruebas comprueban el contenido del prompt y la configuración del wizard; no demuestran que un agente independiente haya coordinado realmente varios repositorios. Esa ejecución sigue pendiente. La validación terminal de los 14 templates y las pruebas de browser que realiza el PM por separado conservan los límites descritos en la sección anterior. El smoke local sigue siendo parcial y no es dogfood de rendimiento.

Durante la integración se observaron fallos de regresión: inicialmente los fixtures aún usaban el esquema v1 de escritura; después, siete aserciones contaban dos veces rutas de skills cuando también aparecían en el aviso de archivos modificados. Al reforzar el aislamiento, una prueba adicional asumía que invocaciones sin proyecto borraban prompts anteriores y falló en ambas suites; se cambió para comprobar cada operación en su propia carpeta. Se actualizaron los fixtures y las aserciones para comprobar el comportamiento efectivo.

| Comando | Exit | Resultado |
|---|---:|---|
| `python3 -m unittest discover -s tests -q` | 0 | 82 tests; uno omitido por no estar instalado `prompt_toolkit` en ese Python. |
| `.project-os/venv/bin/python -m unittest discover -s tests -q` | 0 | 82 tests sin omisiones. |
| `python3 tests/smoke_local.py` | 0 | Instalación y flujo local parcial con configuración v2 y SHA canónico comprobado; adopción simulada en fixture. |
| `python3 -m py_compile tools/select.py tools/project_local.py` | 0 | Sintaxis válida. |
| `git diff --check` | 0 | Sin errores de whitespace en el diff observado. |

El SHA y CI de este cambio deben verificarse tras el push.
