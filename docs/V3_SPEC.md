# Project OS v3 — Especificación implementable del MVP

> Esta especificación incorpora las decisiones del PM y sus [addenda](V3_ADDENDUM.md); prevalecen las instrucciones más recientes ante contradicciones.

**Estado:** borrador para implementación, no adoptado ni validado en producción.

**Destino:** `codefusion-repo/project-os-v3`. **Fuente:** handoff de v3 + correcciones expresas del PM (13-11-2026).

**Proceso de construcción:** documentar → implementar → probar en proyecto real.

## 1. Producto y prueba de éxito

Project OS v3 es un **kit operativo Markdown-first** de **workflows + skills + templates + selector**, adaptable a agentes terminales y browser chat. Su propósito es llevar una intención a un resultado útil (incluidos prototipos) más rápido y con menos fricción, conservando evidencia, seguridad y continuidad.

**Hipótesis por medir, no promesa:** menor tiempo, tokens/créditos e intervenciones humanas que v2 en tareas equivalentes, sin empeorar calidad o seguridad. No construir infraestructura propia para justificar la hipótesis.

**Decisiones que sustituyen al handoff inicial:** (a) el **selector se entrega obligatoriamente** en el MVP; (b) hay una biblioteca utilizable de skills, no un directorio vacío; (c) se entregan **catorce templates**, incluidos los diez base y cuatro operativos GitHub. Los workflows siguen siendo seis. Son obligatorios como *artefactos distribuidos*, no una barrera de acceso: un agente con una intención clara puede leer los Markdown directamente sin ejecutar un script.

## 2. Modelo operativo

- **Workflow = resultado y recorrido breve.** Describe cuándo usarlo, qué evidencia inspeccionar, qué hacer, qué entregar y cuándo detener *solo* una acción sensible. No es máquina de estados.
- **Skill = capacidad reusable y especializada.** Instrucciones de ejecución para una técnica concreta (prototipar, depurar, testear, revisar seguridad), invocables desde distintos workflows o directamente por intención.
- **Template = estructura mínima de un artefacto.** Se usa cuando ese resultado existe; nunca obliga a crear issue/PR/informe solo para rellenar un formulario.
- **Selector = interfaz de descubrimiento y preparación.** Se incluye siempre, descubre Markdown, propone combinaciones workflow/skills y guarda un prompt copiable. No ejecuta workflows ni concede permisos.
- **Adapter = capacidades reales de la superficie.** Terminal y browser comparten reglas; sus diferencias están en acceso al filesystem, shell, GitHub y acciones disponibles.
- **GitHub = fuente de trazabilidad viva**, nunca registry o estado propio. Mantener una unidad de trabajo y un mismo issue/PR para implementación, review y correcciones de un outcome.

**Fast path:** petición clara → workflow y skills adicionales útiles, con `repo-context` y `github-traceability` transversales según su ámbito → inspección mínima del repo/GitHub → trabajar/validar → evidencia remota o bloqueo explícito. Solo un experimento expresamente local y descartable puede finalizar sin publicación; no se exige crear issue/PR si no aporta valor o no está autorizado.

## 3. Estructura mínima entregable

```text
AGENTS.md
PROJECT_OS.md
README.md
workflows/
  continue.md
  create.md
  implement.md
  review.md
  close.md
  release.md
skills/
  repo-context/SKILL.md
  rapid-prototype/SKILL.md
  implement-change/SKILL.md
  debug/SKILL.md
  testing/SKILL.md
  security-review/SKILL.md
  code-review/SKILL.md
  github-traceability/SKILL.md
  documentation/SKILL.md
adapters/
  terminal-agent.md
  browser-chat.md
templates/
  task.md
  issue.md
  pull-request.md
  review.md
  execution.md
  decision.md
  prototype.md
  handoff.md
  release.md
  dogfood.md
  merge.md
  close.md
  comment.md
  review-comment.md
tools/
  select.py
tests/
  test_select.py
  test_structure.py
docs/
  V3_SPEC.md
  ADOPTION.md
```

Los nombres son la interfaz inicial. Se permiten ajustes pequeños de organización, **no eliminar selector, biblioteca de skills ni los catorce templates**. No se admiten duplicados de reglas centrales en cada archivo, catálogo paralelo obligatorio ni dependencia de v2.

`AGENTS.md` es un bootstrap breve; `PROJECT_OS.md` concentra reglas compartidas. `README.md` enseña un inicio en 30 segundos, selección interactiva, invocación directa de Markdown y prototipo rápido. `docs/ADOPTION.md` explica cómo integrar este kit a un repositorio existente sin sobrescribir instrucciones propias ni copiar historia Git.

## 4. Workflows (seis, conservados)

| Archivo | Outcome | Skills especializadas sugeridas; `repo-context` y `github-traceability` son base |
|---|---|---|
| `continue.md` | Cold start y continuación desde evidencia viva | — |
| `create.md` | Convertir idea en outcome con criterios verificables; issue o borrador si aporta valor | `rapid-prototype`, `documentation` |
| `implement.md` | Construir feature, fix o **prototipo rápido**, validar y registrar cambios autorizados | `implement-change`, `rapid-prototype`, `debug`, `testing` |
| `review.md` | Revisar diff/código/tests/riesgos y entregar findings accionables | `code-review`, `security-review`, `testing` |
| `close.md` | Verificar readiness y preparar/realizar únicamente acciones permitidas | `testing` |
| `release.md` | Evaluar release-readiness y preparar ejecución con controles de producción | `security-review`, `documentation` |

Cada archivo define en lenguaje natural: `Objetivo`, `Cuándo usar`, `Ruta rápida` (máximo 5 pasos prácticos), `Evidencia y validación`, `Salida` y `Escalación localizada`. Debe funcionar sin selector y sin crear subissues/handoffs automáticos. La combinación sugerida es una ayuda de UX, no un grafo de aprobaciones.

## 5. Skills de primera clase

Cada `skills/<nombre>/SKILL.md` debe ser **ejecutable como instrucción para un agente**: `Para qué sirve`, `Cuándo conviene`, `Entradas mínimas`, `Procedimiento concreto`, `Validación y salida`, `Riesgos/limitaciones`. Contenido breve, con acciones prácticas y referencias opcionales solo cuando aportan valor. Una skill no autoriza acciones y no modifica la política del workflow ni del adapter.

| Skill | Aporta valor concreto |
|---|---|
| `repo-context` | Ubicar stack, entrypoints, comandos, issue/PR y cambios relevantes para cold start |
| `rapid-prototype` | Convertir hipótesis en **thin vertical slice**, demo comprobable y siguiente decisión; no sobrearquitectura |
| `implement-change` | Cambios acotados y reversibles con pruebas, documentación y diff controlado |
| `debug` | Reproducción, causa raíz plausible, fix mínimo y prevención de regresión |
| `testing` | Selección de pruebas por riesgo, ejecución real y evidencia de fallos/cobertura disponible |
| `security-review` | Inspección proporcional de auth, permisos, inputs, secretos, dependencias y OWASP relevante |
| `code-review` | Hallazgos reproducibles por prioridad, paths y líneas; no aprobar solo por un reporte |
| `github-traceability` | Issue/PR/commit/checks, continuidad del mismo PR, registros breves y verificables |
| `documentation` | README, contratos y handoff útiles; reducir documentación que no sirva para operar |

**Regla de carga:** aplicar `repo-context` en tareas con repositorio y `github-traceability` según su contrato, incluso sin selector; leer el workflow y solo las skills especializadas útiles. El selector incluye ambas skills base sin pedirlas. Cold start completo solo cuando haga falta; al continuar, inspección acotada y sin recorrer todo el repo o todos los issues/PRs sin justificación. Para experimento expresamente local y descartable sin repo, no exigir GitHub ni publicación. Una instrucción explícita `usa skill X` tiene prioridad como selección de capacidad, pero no concede autoridad extra. No introducir un framework de plugins ni manifiestos de dependencias.

## 6. Selector requerido (`tools/select.py`)

CLI Python stdlib obligatorio para generar prompts operativos Markdown, sin servicios ni ejecución de workflows. Markdown directo sigue disponible sin ejecutar el selector.

```bash
python3 tools/select.py --output-dir /ruta/a/prompts
python3 tools/select.py --list
python3 tools/select.py --workflow implement --skill rapid-prototype --objective "Validar una idea"
python3 tools/select.py --prototype
python3 tools/select.py --workflow review --locator 123
```

1. El wizard es la interfaz principal: repositorio → workflow → skills → contexto PM → preview → guardar. Solicita `owner/repo` la primera vez, valida el formato sin afirmar verificación remota y permite `-` para experimento local descartable sin repo. Descubre Markdown sin catálogo paralelo; admite búsqueda, selección múltiple, volver, editar, cancelar y reutilizar. Incluye las dos skills base sin pedirlas ni duplicarlas.
2. En todos los workflows ofrece `PM_FEEDBACK_HUMANO` y `PM_QUESTION_HUMANO` como campos opcionales multilínea; no son autorizaciones y no se reutilizan. El objetivo o una referencia material issue/PR puede omitirse para recuperación desde GitHub. Previsualiza el prompt con contexto, reglas compartidas, workflow, skills y templates internos antes de guardar; no pide seleccionar templates.
3. `--repo`, `--workflow`, `--skill`, `--locator`, `--objective`, `--feedback`, `--question`, `--output-dir`, `--list`, `--prototype` y `--help` permiten uso no interactivo. `--prototype` preselecciona implement + rapid-prototype y admite `--skill` adicionales. El modo no interactivo previsualiza y guarda directamente; combinaciones incompatibles, nombres desconocidos y locators inválidos fallan con mensaje claro.
4. Tras guardar, persiste solamente último repositorio y carpeta de salida en `.project-os/config.json`, ignorado por Git; nunca guarda los campos PM, credenciales ni autorizaciones allí. La siguiente sesión propone esas preferencias; sin destino guardado usa `.project-os/prompts/`. El CLI no interactivo no lee ni modifica esta configuración. Informa antes de reemplazar: tras publicar atómicamente el nuevo archivo, elimina solo los prompts anteriores identificables mediante nombre reservado y marcador del selector en la misma carpeta. Nunca elimina Markdown ajenos, symlinks ni archivos de otras carpetas. Si se cancela o falla la escritura, conserva los anteriores; informa si la limpieza posterior falla.
5. Rechaza traversal y symlinks en rutas de destino y fuentes externas. Usa escritura temporal seguida de publicación atómica sin sobrescribir archivos existentes; no ejecuta código derivado del Markdown ni llama GitHub. Requiere soporte del sistema para abrir directorios sin seguir symlinks y enlaces duros en la carpeta destino.
6. El selector se entrega y prueba obligatoriamente, pero su uso no es requisito para operar con Markdown. No concede permisos ni ejecuta workflows.

## 7. Catorce templates livianos

**Todos se distribuyen**, pero se llenan **solo cuando producen un artefacto útil**:

| Template | Uso |
|---|---|
| `task.md` | Brief mínimo para intención, outcome y alcance (sin forzar issue) |
| `issue.md` | Unidad cohesiva con criterios y restricciones verificables |
| `pull-request.md` | Cambios, evidencia, riesgos, relación con issue y pendientes |
| `review.md` | Findings priorizados, ubicación, evidencia y decisión |
| `execution.md` | Lo realmente cambiado, comandos/tests y resultado verificable |
| `decision.md` | Decisión material pendiente, opciones y próximo paso seguro |
| `prototype.md` | Hipótesis, demo/slice, validación rápida y qué descartar/evolucionar |
| `handoff.md` | Cold start entre sesiones/agentes: refs vivas, hechos, pendientes |
| `release.md` | Readiness y checklist de acciones de riesgo; nunca autorización implícita |
| `dogfood.md` | Datos observados de v3 vs benchmark comparable v2 |
| `merge.md` | Readiness y mensaje de merge; acción y confirmación separadas |
| `close.md` | Readiness y mensaje para cerrar la unidad existente |
| `comment.md` | Avance, bloqueo, corrección o readiness en issue/PR |
| `review-comment.md` | Finding o respuesta de corrección en PR/hilo existente |

Los campos irrelevantes se omiten; indicar `no ejecutado` o `sin evidencia` en vez de inventar. Evitar secciones kilométricas, recibos y múltiples reportes para un mismo cambio. No usar templates como sustituto de leer el código/diff real.

## 7.1 Garantías operativas compartidas

- **Cold start:** con solo el repositorio identificado, inspeccionar instrucciones y fuentes GitHub vivas relevantes: issues, PRs, commits, diffs, checks, findings y blockers. Identificar objetivo y siguiente paso sin historial; solicitar como máximo un locator primario solo si hay ambigüedad material que no se puede resolver con evidencia. Si no hay acceso o fuentes suficientes, informar el límite y continuar lo seguro.
- **Respuestas comunes:** usar según el resultado [Ejecución](../templates/execution.md), [Review](../templates/review.md) o [Decisión pendiente](../templates/decision.md): resultado y validación; findings con ubicación, impacto y evidencia; o acción bloqueada, hechos, opciones y trabajo seguro, respectivamente. Aplicar criterios idénticos de evidencia y veracidad en terminal y browser; respuestas breves por defecto, sin generar un informe por paso.
- **Trazabilidad y continuidad obligatorias:** toda implementación, corrección o modificación versionada destinada a integrarse en GitHub prepara un commit significativo con cambios propios y exige evidencia remota verificable. Reutilizar issue/PR existentes, publicar con autorización y capacidad, y verificar SHA remoto, PR y checks disponibles. Un commit solo local no satisface trazabilidad remota: reportar **trazabilidad pendiente** y el bloqueo si no puede publicarse; no declarar entrega completa en GitHub. Una consulta de solo lectura no genera commits. Solo experimentos expresamente locales y descartables pueden finalizar sin publicación; si no hay repo, tampoco exigen consultas GitHub. La excepción no aplica a cambios destinados a integración. La obligación no concede permisos. Conservar relaciones verificables entre issue, PR, commits, diff, checks, findings, decisiones y correcciones cuando existan. El handoff mínimo recupera objetivo, estado, referencias vivas, validaciones, blockers materiales y próxima acción segura. Persistir un resumen en el issue/PR existente solo cuando aporte contexto difícil de recuperar, esté autorizado y no duplique comentarios.
- **Permisos:** los templates no autorizan acciones; separar preparación, ejecución y comprobación. Detener exclusivamente la acción sensible sin permiso y continuar trabajo seguro ante incertidumbre secundaria.

## 8. Autonomía, evidencia y permisos

**Siempre** distinguir entre hecho observado, inferencia técnica, propuesta y acción autorizada:

- Consultas factuales: verificar la fuente primaria y responder, incluso cuando un documento prescribe un estado deseado diferente.
- Scope autorizado: decidir de forma autónoma lo técnico reversible, aplicar ediciones, ejecutar pruebas y corregir. No preguntar por metadata que se obtiene de GitHub/repositorio.
- Falta de evidencia secundaria: continuar lo seguro, explicitar limitación, no inventar checks, outputs ni cobertura.
- Antes de escritura: preflight de target, rama, cambios ajenos, capacidad real de herramienta, visibilidad y scope de autorización. Un workflow/skill/template jamás concede permisos.
- **Acción sensible = confirmación concreta separada:** merge, cierre final sin autorización, release/publicación, despliegue de producción, borrado destructivo, cambiar secrets, credenciales, permisos, repo settings, configuración productiva de auth/pagos y equivalentes. Detener solo esa acción y seguir la parte segura.
- Secretos: nunca mostrar sus valores ni volcados de entorno; usar `[REDACTED]` y reportar ruta/nombre de variable/tipo de riesgo únicamente. Para web/API considerar riesgos OWASP aplicables.
- GitHub: reutilizar issue/PR del outcome cuando existan; un blocker se corrige y valida en **el mismo PR**. Publicar commits autorizados y verificar SHA, PR y checks disponibles; si no es posible, informar trazabilidad pendiente. No crear unidades ni comentarios redundantes, falsificar aprobaciones ni inventar estado remoto.

**Repositorio público autorizado:** el PM autoriza desarrollar y publicar el código y documentación del MVP en `codefusion-repo/project-os-v3`, incluido push y draft PR. La visibilidad pública por sí sola no bloquea estas acciones. No incluir secretos ni datos privados; merge, release, deploy y cambios sensibles siguen sujetos a autorización específica.

## 9. Adaptadores por superficie

**Terminal:** puede inspeccionar y editar checkout, ejecutar shell/Git/tests y operar GitHub solo cuando las capacidades y autorización reales lo permiten. Comprobar repo/branch/status antes de cambios; trabajar en `work/*`, no sobre `main` en un ciclo PR; no pisar cambios del usuario. Reportar comandos, exit code y resultados reales.

**Browser chat:** leer estado vivo, revisar, decidir, redactar artefactos y aprovechar conectores de GitHub en **acciones acotadas si** la sesión tiene capacidad y autorización. No afirmar shell, filesystem, edición de checkout, push o permisos sin evidencia. Si su contrato actual es read-only/draft-only, producir borradores y delegar terminal; esto es una restricción del actor, **no** un veto universal de diseño de v3.

Otros agentes: Markdown directo. Añadir adapter cuando una diferencia real lo exija, no por producto/editor.

## 10. Validación mínima y aceptación del MVP

- Existencia y enlaces correctos de **6 workflows, 9 skills, 14 templates, 2 adapters, selector y tests**, además de `AGENTS.md`, `PROJECT_OS.md`, `README.md`, esta spec y `docs/ADOPTION.md`.
- `tools/select.py`: primera sesión y configuración existente, validación de repo, contexto PM multilínea sin reutilización ni filtración a config, selección y navegación, preview, guardado en carpeta temporal, reemplazo seguro, cancelación, fallos, locator, discovery y protección de rutas. Pruebas stdlib (`unittest`), sin red ni writes de producción.
- Pruebas de estructura/referencias Markdown y revisión humana de legibilidad; **no** tests frágiles de wording.
- Ejemplo documentado y reproducible de inicio `continue`, de prototipo rápido y de review. Se puede usar el kit leyendo los Markdown sin Python; Python se usa para el selector entregado.
- Un chat nuevo recibe solo el repositorio y recupera el trabajo relevante desde GitHub; otro agente retoma sin repetir preguntas respondibles desde evidencia. Verificar el objetivo, referencias, checks, blockers y siguiente acción; si faltan fuentes, registrar el límite.
- Terminal y browser chat aplican los mismos formatos y criterios de evidencia con sus capacidades reales; una acción sensible no autorizada se detiene sin bloquear el resto del trabajo.
- Selector interactivo: workflow y skills producen prompt reutilizable que incluye una vez cada skill base; `continue` es default y Markdown directo aplica la misma regla. Comprobar deduplicación y skill base ausente o insegura.
- Agente terminal autorizado: tarea normal → diff validado → commit → **un draft PR**, y corrección de findings en mismo PR. Si falta capacidad o permiso para una acción remota, reportarlo sin fingir aceptación completa.
- No inventar test/permiso/estado; no realizar acciones de riesgo no autorizadas; inspeccionar riesgos del cambio.

**Criterio para empezar dogfood:** selector y biblioteca funcionan, Markdown directo funciona, trazabilidad/cold start están documentados y la implementación terminal tiene validación verificable. **No declarar el MVP probado antes del proyecto piloto.**

## 11. Dogfood, benchmark y ajuste

El PM seleccionará un **proyecto real existente** después de preparar el MVP. Hacer al menos: cold start en chat nuevo; localizar issue/PR; tarea normal hasta draft PR; review con blocker y corrección del mismo PR; cambio de agente/sesión; uso del selector; camino `--prototype`; incertidumbre secundaria no bloqueante; acción sensible correctamente detenida; acción browser GitHub solo si efectivamente disponible/autorizada.

Registrar **datos observados** con `templates/dogfood.md`: tarea/complejidad comparables, tiempo de reloj, tokens/créditos si hay métricas, tool calls, intervenciones PM, locators solicitados, falsos bloqueos, pruebas, fallas, retrabajo y calidad del handoff. Marcar lo no disponible y evitar conclusiones causales si v2/v3 usaron distinta tarea/modelo/alcance. Corregir lo que falle, **sin** agregar kernel o resolver salvo evidencia posterior de beneficio neto.

## 12. Límites de implementación

Un solo encargo integral al agente terminal, rama `work/*`, una unidad/issue si aporta valor, un draft PR autorizado cuando la visibilidad lo permite. Sin etapas intermedias de gobernanza. No copiar ni ejecutar kernel, resolver, catálogo MOS, workflows, historial Git o estructura de v2. Sin JSON de orquestación, state machine, permisos autoemitidos, daemon, scheduler, DB, plugin framework, wizard pesado, backend, deploy automático ni dependencias pip.

El resultado esperado es un **kit realmente usable** para desarrollar y prototipar, no una colección de contratos de proceso.
