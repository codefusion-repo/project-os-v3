# Project OS v3 — producto y dirección de desarrollo

Documento de producto para PM y desarrolladores del kit. La metodología obligatoria para cualquier agente es [PROJECT_OS.md](../PROJECT_OS.md); este documento no la sustituye. Los contratos técnicos viven junto al componente que gobiernan; GitHub conserva decisiones, estado vivo y evidencia. Base de consolidación: [75a392b63ed21a364fc8195ad5dbdd062532df2c](https://github.com/codefusion-repo/project-os-v3/commit/75a392b63ed21a364fc8195ad5dbdd062532df2c), issue [#21](https://github.com/codefusion-repo/project-os-v3/issues/21). Estado de referencia al consolidar, no un registro de ejecución paralelo.

## Propósito y resultados esperados

Project OS v3 reduce fricción entre una intención del PM y un resultado verificable, incluyendo prototipos, desarrollo y continuidad entre agentes. Es un kit Markdown-first, no un SaaS, IDE, flota de agentes ni sistema de gestión de proyectos. La hipótesis es menor tiempo, créditos/tokens, intervención y retrabajo respecto de v2 sin sacrificar calidad ni seguridad; todavía requiere benchmark comparable. La estrategia original fue documentar → implementar → probar en proyecto real; el PM ratificó que el MVP funcional está logrado y que el objetivo actual es producción (LB-PLAN-20261124-28, [#8](https://github.com/codefusion-repo/project-os-v3/issues/8)). No confundir integración de un hito con release o certificación integral.

## Arquitectura y límites ratificados

- Núcleo versionado: [metodología](../PROJECT_OS.md), [5 workflows](../workflows/), [9 skills](../skills/), [14 templates](../templates/), [2 adapters](../adapters/). Selector obligatorio como artefacto del producto, opcional para el agente; no ejecuta workflows. Los cinco workflows son continue, create, implement, review_for_close y release; review/close legados fueron sustituidos por la operación única.
- [Selector](../tools/select.py) Python stdlib, interfaz enriquecida opcional prompt_toolkit, configuración privada [project_local](../tools/project_local.py), guía [provider_setup](../tools/provider_setup.py). Descubre Markdown, no catálogo paralelo. Sin servidor, DB o estado de ejecución en el núcleo; no importa kernel, resolver, catálogo MOS, código ni historia de v2.
- Una instalación central por dispositivo, proyectos separados, AGENTS.md principal por repositorio con SHA canónico; sin copiar kit, perfiles centrales ni repositorio principal en workspace.
- GitHub es la trazabilidad viva; un issue/PR por outcome, no unidades artificiales. Los templates se aplican obligatoriamente a artefactos GitHub y el historial no se reescribe.
- [Local Bridge](../local-bridge/MVP.md) es un proveedor opcional, autenticado, de trabajos locales tipados y acotados, no un motor de coordinación. Su SQLite privado conserva jobs, no reemplaza GitHub. El conector GitHub actúa independientemente y ninguno hereda permisos del otro.

### Ejecución adaptativa

Decisión LB-ARCH-20261124-29, [#8](https://github.com/codefusion-repo/project-os-v3/issues/8), [#18](https://github.com/codefusion-repo/project-os-v3/issues/18), [aclaración -45](https://github.com/codefusion-repo/project-os-v3/pull/20#issuecomment-7149970678): PM → Browser Chat (orquestador) → router pequeño → Codex o Browser Chat directo → estado/evidencia → Browser Chat review y closeout autorizado. Existen dos implementadores: Codex, que se ejecuta en el terminal, y ChatGPT Browser, que utiliza herramientas autorizadas de Project OS v3. Local Bridge y terminal no son implementadores.

Auto prefiere Codex solo con permiso vigente, disponibilidad y capacidad/cuota confirmadas; si no está disponible o agota cuota confirmada, browser directo continúa mediante GitHub Connector y Bridge según permisos. Browser explícito no deriva a Codex; codex explícito no tiene fallback implícito. No menús permanentes ni familia nueva de comandos. Cambio de ejecutor exige reconciliar HEAD, rama, diff, jobs, tests y efectos inciertos, confirmar que el anterior terminó y mantener exclusividad por worktree; no replay incierto ni credenciales transferidas. El handoff conserva identidad del trabajo, estado SQLite cuando corresponda y evidencias compartidas sin recaptura manual por el PM; GitHub/Git y estado durable local son fuentes complementarias. Browser conserva contexto, planificación, coordinación y verificación de permisos y realiza review basada en evidencia, separada de la ejecución, no autoevaluación del ejecutor ni aprobación humana ficticia. El contrato está aprobado, el provider/router Codex aún no están implementados ni habilitados; ejecución actual browser directa, también terminal directo cuando PM lo solicita. Metodología y templates invariantes entre proveedores ([ratificación -44](https://github.com/codefusion-repo/project-os-v3/pull/20#issuecomment-7149887145)).

## Experiencia de usuario

Instalar una vez, adoptar cada proyecto una vez y usar el wizard diariamente. El setup de proveedores guía conexión, configuración y verificación reutilizando herramientas existentes (terminal, ChatGPT o ambos); no sustituye el selector diario. El PM conserva consentimiento OAuth, instalación opcional, preparación de servicio y control de activación. El wizard no ejecuta workflows, adopción, commits ni PR.

El selector comienza por buscar/seleccionar workflow, Enter usa continue; si no hay coincidencia conserva intención en pregunta PM. Pide repositorios solo si faltan; permite skills múltiples, /todas, /alcance, /carpeta, /volver, /cancelar, /limpiar, editar y reutilizar. Los campos PM_FEEDBACK_HUMANO y PM_QUESTION_HUMANO son opcionales, exclusivos de la operación y multilínea; el locator contextual es único y opcional cuando corresponde. Editar recorre secuencialmente los campos y muestra sus valores; permite volver a elegir workflow y skills sin pedir de nuevo el repositorio. Enter conserva valores y /limpiar borra explícitamente; g guarda, e edita, o cambia operación, c cancela. Bracketed paste requiere terminal compatible; CLI acepta valores multilínea. No menú de templates ni formato autocontenido; el agente aplica los templates GitHub pertinentes sin selección manual. Los repositorios ingresados tienen formato owner/repo, no se consideran verificados; '-' permite experimento local descartable. Una referencia contradictoria con el contexto genera advertencia, no sustitución silenciosa. Un prompt único conserva texto PM (normaliza CRLF/CR), separa notas de sistema, indica versión, pasos esenciales, referencias, alcance y límites. El selector añade ambas skills base una sola vez sin pedir selección; el agente recupera las instrucciones y no se copian documentos completos. La interfaz enriquecida ofrece sugerencias dinámicas y edición directa; la alternativa stdlib usa GNU readline. Los nombres, flags y UX reales se consultan con project-os-v3 --help y --list.

## Instalación, proveedores y actualización

Requisitos del selector: Linux/WSL, Git y Python 3.9+. [Inicio rápido](../README.md#instalar-y-actualizar). La instalación normal parte de main integrado, no refs de PR; inspeccionar código antes de ejecutar. install.sh verifica origen, ownership, checkout limpio y fast-forward; no sudo, autoupdate silencioso ni cambios de shell config. Launcher en ~/.local/bin, entorno aislado opcional y fallback stdlib. Repetir el instalador desde el mismo checkout central actualiza explícitamente; no modifica preferencias ni SHA de proyectos. Si falla red, origen, divergencia o protección, conservar datos y diagnosticar sin reset/clean destructivo.

Para setup revisado, definir REVIEWED_SHA como SHA completo previamente autorizado y usar ./install.sh "$REVIEWED_SHA" both. Rechaza deriva de main; usa Python estándar y no descarga prompt_toolkit. Modos terminal, chatgpt, both; sin TTY la guía solo comprueba versiones, con TTY ofrece auth GitHub CLI y Bridge por SHA con consentimiento independiente. Los comandos no prueban conexión, permisos ni aislamiento. PowerShell usa WSL existente y checkout Linux revisado, no instala WSL ni inicia servicios. Ejemplo (ReviewedSha definido por el operador):

    .\local-bridge\scripts\install.ps1 -ReviewedSha $ReviewedSha -Distribution 'Ubuntu-24.04' -Checkout '/home/operator/my kit' -Mode both

Sin Mode conserva wrapper Bridge-only. Ver [instalación Bridge](../local-bridge/README.md), [WorkOS](../local-bridge/WORKOS.md) y [WSL](../local-bridge/WSL-VALIDATION.md). Tras instalación opcional exitosa se ofrece nueva instancia privada y preparación HTTPS/túnel sin activar servicio/fixtures; clave runtime solo en terminal privado mediante getpass, verificar binario y consentir WorkOS externamente. Health autenticado desde conector, no pegar tokens. LB-03 tiene prueba real WSL2 en CI y rollback descartable, no certificación del host del PM.

**Decisión PM CI-WINDOWS-20261126-01 (compatibilidad Windows durante desarrollo):** trasladar temporalmente `powershell-wrapper` del [CI principal](../.github/workflows/selector-ci.yml) al [workflow Windows compatibility](../.github/workflows/windows-compatibility.yml), de ejecución manual (`workflow_dispatch`). Conservar ambas pruebas (forwarding y propagación de fallos del wrapper, e instalación real Windows/WSL2 con fixture descartable), permisos mínimos y timeout. El ruleset `main-production` debe retirar únicamente ese check de los obligatorios, conservando los otros 13 y todas las demás protecciones. Ejecutar el workflow manual cuando cambie el wrapper o el bootstrap Windows/WSL2 y exigir PASS sobre la revisión exacta antes de la primera versión estable con soporte Windows; reincorporar el check obligatorio al completar el desarrollo de producción. No se difieren ni modifican controles de seguridad, certificación del host, OCI ni gates de activación. No requiere una actualización del runtime por este cambio de CI.

Ante interrupción comprobar HEAD, git status, launcher y entornos. No reutilizar venv Bridge parcial. [Decisión LB28-20261125-SINGLE-INSTALLATION-01](https://github.com/codefusion-repo/project-os-v3/issues/28#issuecomment-7159966742): conservar y actualizar la instalación original, con venv limpio en su ruta definitiva, rollback temporal y retiro de copias redundantes solo tras cutover verificado. Ver [mantenimiento](../local-bridge/README.md#single-installation-maintenance); no clones permanentes por PR/issue ni cambios automáticos de estado o grants. Desinstalación no destructiva: dejar de usar launcher, retirarlo manualmente solo tras comprobar identidad/ownership; conservar checkout, preferencias, instancias y entornos. Lifecycle operativo y rollback de servicio quedan en LB-04/LB-05.

### Rollback temporal del selector central

Solo para el checkout central limpio, con launcher revisado de Python estándar y sin operaciones concurrentes. Comprueba el origen canónico, ownership, estado y ambos SHA completos previamente revisados. No modifica main, no reinstala Bridge, no migra instancias ni cambia versiones fijadas de proyectos. Si alguna comprobación falla, detente.

```bash
(
  set -eu
  : "${CURRENT_SHA:?}" "${PREVIOUS_SHA:?}"
  for sha in "$CURRENT_SHA" "$PREVIOUS_SHA"; do
    printf '%s\n' "$sha" | grep -Eq '^[a-f0-9]{40}$'
  done
  test "$(git rev-parse --show-toplevel)" = "$(pwd -P)"
  test "$(git config --local --get remote.origin.url)" = 'https://github.com/codefusion-repo/project-os-v3.git'
  test "$(git symbolic-ref --short HEAD)" = main
  test "$(git rev-parse HEAD)" = "$CURRENT_SHA"
  test "$(git rev-parse --verify "$PREVIOUS_SHA^{commit}")" = "$PREVIOUS_SHA"
  test -z "$(git status --porcelain)"
  git worktree list
  git merge-base --is-ancestor "$PREVIOUS_SHA" "$CURRENT_SHA"
  git checkout --detach --no-overwrite-ignore "$PREVIOUS_SHA"
  test "$(git rev-parse HEAD)" = "$PREVIOUS_SHA"
  python3 tools/select.py --help
)
```

Para restaurar, desde ese mismo checkout y tras comprobar identidad y ausencia de cambios:

```bash
(
  set -eu
  : "${CURRENT_SHA:?}" "${PREVIOUS_SHA:?}"
  test "$(git rev-parse --show-toplevel)" = "$(pwd -P)"
  test "$(git config --local --get remote.origin.url)" = 'https://github.com/codefusion-repo/project-os-v3.git'
  test "$(git rev-parse HEAD)" = "$PREVIOUS_SHA"
  test "$(git rev-parse main)" = "$CURRENT_SHA"
  test -z "$(git status --porcelain)"
  git checkout --no-overwrite-ignore main
  test "$(git rev-parse HEAD)" = "$CURRENT_SHA"
  python3 tools/select.py --help
)
```

No ejecutes el instalador mientras HEAD esté detached. La prueba descartable del recorrido usa commits sintéticos y no certifica rollback de servicios ni el host del PM.

## Adopción, privacidad y actualización de proyecto

Ejecutar comandos desde raíz Git del proyecto; $PWD es ruta absoluta del directorio actual. --configure guarda preferencias, --adopt genera encargo para agente terminal autorizado, no cambia AGENTS.md. Puede usarse /adoptar. Si no existe checkout local, indica owner/repo; no se inventa ruta ni configuración y solo se guarda en un destino externo elegido explícitamente. El agente inspecciona instrucciones, rama y diff, preserva reglas técnicas, adapta AGENTS.md y .gitignore y registra cambios autorizados. Bootstrap mínimo de un proyecto adoptado (reemplazar marcador por SHA real):

    Project OS: codefusion-repo/project-os-v3
    Project-OS-Version: <SHA completo verificable>
    Lee PROJECT_OS.md y documentos pertinentes de ese commit canónico.

Configuración v2 local en .project-os/config.json: nombre, lista no vacía repositories sin jerarquía, checkouts opcionales, destino de prompts. Admite opcionalmente github_context (project, repository y repository_id) para LB-06; no guarda credenciales, campos PM, permisos ni estado de issues. El principal se deriva del OAuth existente y el grant efectivo sigue siendo local y revocable. Default .project-os/prompts/. Antes de escribir, comprueba exclusiones efectivas y archivos ya rastreados; puede preparar info/exclude local y verificarlo. Agente incorpora .project-os/ a .gitignore. Si hay datos privados tracked no leerlos/escribir allí; ignore no los retira de historia. Ante imposibilidad de proteger, conserva preview y pide destino externo explícito y seguro; no uses carpetas temporales compartidas para prompts sensibles. Informa antes de reemplazar y cuando prepara una exclusión local. Guardado atómico, rechazo de traversal/symlinks y patrones heurísticos de secretos sin imprimir valores. Tras escribir reemplaza solo prompts atribuibles al mismo proyecto o conjunto remoto exacto (sin distinguir orden o mayúsculas), en la misma carpeta; conserva ajenos, antiguos sin identificación y anteriores ante fallo o cancelación. Si falla la limpieza posterior lo informa; no elimina symlinks ni archivos ajenos. Sin repositorio identificable no limpia prompts ajenos.

Workspace: --project prevalece, descubrimiento desde cwd/ancestros sin recorrer dispositivo; configuraciones anidadas incompatibles requieren selección, nunca se fusionan. --repo repetido limita operación, con --configure agrega repos; /alcance o /repo limita temporalmente; checkouts privados no se incluyen en prompt. --configure --checkout organizacion/backend=/ruta/al/backend actualiza esa entrada y preserva otras. Verificación, permisos, AGENTS.md y trazabilidad independientes por repo. Documentar solo relaciones verificadas y divulgables.

Migración explícita de configuración central anterior: project-os-v3 --project /ruta/al/proyecto --configure --migrate-legacy --repo organizacion/repositorio. Exige correspondencia, conserva origen y prompts; si existe configuración local o formato desconocido, se detiene. Esquema local v1 reconocido se convierte a v2 deduplicando en orden y preservando rutas/destino; generación CLI convierte en memoria y --configure confirma escritura atómica protegida. Error o conflicto conserva original. No hay proyectos v3 reales cuya migración se haya demostrado; los fixtures no acreditan migración real. Para instrucciones v2/copia anterior el agente hace inventario, reemplaza instrucciones activas y preserva personalizaciones; no elimina componentes desconocidos por nombre.

Actualizar proyecto: project-os-v3 --project /ruta/al/proyecto --adopt --target-version SHA_COMPLETO. El selector verifica objetos Git locales y SHA objetivo en API canónica para adopción/actualización; sin verificación remota produce borrador no verificado y no permite fijarlo hasta confirmarlo. El wizard muestra versión fijada y HEAD del kit y permite escoger SHA objetivo explícito. Señala documentos modificados y versiones no disponibles; no mezcla versiones ni descarga/ejecuta código remoto. Uso normal no exige red. El agente compara versiones, preserva reglas y publica diff autorizado.

### Desarrollar Project OS con su wizard

Usar checkout central instalado y checkout de desarrollo separados. Desde carpeta que contiene el central:

    git clone --branch main https://github.com/codefusion-repo/project-os-v3.git project-os-v3-dev
    project-os-v3 --project "$PWD/project-os-v3-dev" --configure --name 'Project OS v3' --repo codefusion-repo/project-os-v3
    cd project-os-v3-dev
    project-os-v3 --workflow implement --objective 'Describir el cambio'

El central se excluye de autodetección y no puede usarse como --project. El checkout de desarrollo fija SHA si adoptado; si no, prompt identifica procedencia local que debe verificarse. No implica aprobación del SHA.

### Uso no interactivo

    project-os-v3 --list
    project-os-v3 --project /ruta/al/proyecto --workflow implement --skill testing --objective 'Cambio concreto'
    project-os-v3 --project /ruta/al/proyecto --prototype --skill testing --objective 'Validar con datos simulados'
    project-os-v3 --project /ruta/al/proyecto --workflow review_for_close --locator 123
    project-os-v3 --project /ruta/al/proyecto --output-dir /ruta/a/mis-prompts

--prototype selecciona implement + rapid-prototype. Generación CLI no modifica preferencias salvo --configure; sin proyecto local o destino explícito solo preview. Flags desconocidos, incompatibles y locators inválidos fallan; no usar review/close antiguos. Markdown directo funciona sin Python.

## Local Bridge: capacidades, seguridad y evidencia

### Consolidación funcional de producción del Local Bridge

**Autoridad de producto:** esta sección define el propósito, alcance funcional, prioridades y aceptación de producción del Local Bridge. Decisión del PM [LB-PRODUCT-20261126-CAPABILITY-CONSOLIDATION-01](https://github.com/codefusion-repo/project-os-v3/issues/8#issuecomment-7185110551), precisada por el PM el 2026-11-26. Conserva el [alcance original #8](https://github.com/codefusion-repo/project-os-v3/issues/8), [MVP PR #9](https://github.com/codefusion-repo/project-os-v3/pull/9), [LB-PLAN-20261124-28](https://github.com/codefusion-repo/project-os-v3/pull/9#issuecomment-7140747952) y LB-ARCH-20261124-29. [MVP.md](../local-bridge/MVP.md) conserva el contrato técnico y el alcance demostrado del MVP, no un techo funcional de producción. PROJECT_OS.md sigue siendo la autoridad metodológica.

**Objetivo:** transformar una solicitud del PM en software implementado, compilado, probado y entregado desde Browser Chat, reduciendo intervención manual, consultas repetitivas, tiempo, tokens/créditos y retrabajo. El ahorro es una hipótesis que debe medirse, no un resultado demostrado. El MCP complementa GitHub Connector con contexto eficiente y operaciones que requieren ejecución local; no reemplaza el conector ni proporciona una terminal remota genérica.

#### Separación de responsabilidades

| Componente | Responsabilidad |
|---|---|
| ChatGPT Browser | Contexto, razonamiento, implementación directa, orquestación, review y closeout autorizado según PROJECT_OS.md |
| GitHub Connector | Issues y comentarios, código remoto, ramas y commits remotos, PRs y evidencia de review, CI alojado y merge/cierre autorizado |
| Local Bridge MCP | Contexto agrupado, preparación de workspaces, cambios locales acotados cuando sean necesarios, compilación/tests, Android QA y artefactos, ejecución opcional de Codex |
| GitHub | Fuente remota de código, unidades de trabajo, checks y trazabilidad |
| PC del operador / WSL2 | Entorno de ejecución local autorizado; emulador existente en Windows cuando corresponda |

No duplicar en MCP creación/modificación de issues, comentarios, ramas/commits remotos, PRs, consulta individual de código/diffs/checks remotos, merge ni cierre. Browser realiza review con evidencia del conector y de las validaciones locales. Git puede ser mecanismo interno para preparar un worktree, seleccionar un SHA y obtener un diff; no implica exponer cada comando Git. No ofrecer shell, ADB shell, filesystem ni administración general arbitrarios. Los permisos de cada proveedor son independientes.

#### A. Contexto eficiente desde GitHub — LB-06 (#15)

**Dogfooding progresivo ratificado por el PM (2026-11-26):** [decisión #15](https://github.com/codefusion-repo/project-os-v3/issues/15#issuecomment-7186180465). Usar `codefusion-repo/project-os-v3` como primer repositorio real de lectura agrupada, para apoyar el desarrollo de las siguientes capacidades y medir invocaciones Browser, peticiones upstream, latencia, volumen y completitud. La limitación inicial a un único repositorio real se amplía exclusivamente al segundo proyecto privado autorizado por el PM en [decisión posterior](https://github.com/codefusion-repo/project-os-v3/issues/15#issuecomment-7188268606); no autoriza escrituras MCP ni otros repositorios. El [PR #36 integrado](https://github.com/codefusion-repo/project-os-v3/pull/36#issuecomment-7186147361) acredita el incremento descartable, no una instalación. Mantener los gates comunes de host, transporte, credencial, autorización, auditoría, privacidad, review y mantenimiento, y los específicos de lectura. Conforme a la [decisión de gates por capacidad](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7188545344), la certificación OCI de jobs no es prerrequisito para GitHub/metodología de solo lectura sin fixture; sigue siendo obligatoria para ejecución no confiable y cierre integral LB-05. No se convierte esta decisión en un grant permanente ni se presume ahorro. La configuración de LB-06 se consolida en .project-os/config.json; no crear github-context.json separado. Validar el ID numérico una sola vez al inicio de cada batch MCP y después recuperar el contenido solicitado con el lector existente; conservar revalidación local y procedencia sin consultas upstream redundantes. Decisión del PM del 2026-11-26.

**Evolución de UX y contexto metodológico ratificada el 2026-11-26:** [#15](https://github.com/codefusion-repo/project-os-v3/issues/15#issuecomment-7187918362). Primer dogfood observado: una invocación MCP, tres issues y 74 comentarios; #8 filtrado, #14/#15 completos, sin omisiones. No equivale a certificación de producción. La incorporación de proyectos usa el setup existente y la configuración privada de cada proyecto, con una única instancia y catálogo estable. El grant local mantiene el locator y la identidad autorizada de cada proyecto en la configuración privada existente del servicio; no descubre proyectos automáticamente, no amplía el token ni concede acceso por adopción. Revocación por recurso y revalidación durante cada batch. El cambio de proyecto no exige reinicio tras configurar el perfil multirrepo una vez. La incorporación se integra en `project-os-v3 --providers chatgpt --project RUTA`: reutiliza la instancia, la credencial y preferencias existentes, verifica identidad de repositorio y solicita consentimiento explícito para el grant. La migración inicial del perfil anterior requiere el lifecycle detenido y el opt-in GitHub revocado; las altas posteriores no reinician el servicio.

Añadir `methodology_context`: una solicitud tipada de proyecto, workflow, skills y templates devuelve AGENTS.md, PROJECT_OS.md, workflow, skills base y seleccionadas, templates solicitados y adapter browser desde objetos Git exactos. Resuelve el pin de AGENTS.md y verifica procedencia/integridad contra la instalación revisada; para el propio kit usa la base instalada revisada. No acepta rutas, no mezcla versiones, no copia Markdown, no descarga código ni depende de GitHub Connector para esa lectura. Ante versión/documento no disponible falla explícitamente. Mantener GitHub Connector para operaciones remotas no cubiertas. Alcance real autorizado: project-os-v3 y un segundo proyecto privado explícitamente seleccionado por el PM ([decisión](https://github.com/codefusion-repo/project-os-v3/issues/15#issuecomment-7188268606)). Reutilizar una credencial dedicada read-only con alcance suficiente y grants locales independientes; la identidad privada se conserva en la configuración local. Los demás proyectos quedan excluidos de pruebas reales. La compilación, testing de aplicaciones y emulador son objetivos futuros separados, no autorizaciones de ejecución de este incremento.

El primer entregable es contexto real agrupado de issues y comentarios autorizados, reutilizando [GitHubReader](../local-bridge/src/project_os_bridge/github.py). En la base integrada del 2026-11-26, issue_context obtiene issue y comentarios; batch_issues acepta de uno a cinco números, deduplica y usa concurrencia acotada. Existen autorización, límites de respuesta/paginación y metadatos de completitud/frescura. PR #37 registró el lector real bajo configuración y autorización explícitas; el primer batch real está registrado arriba. La extensión multirrepo y metodología sigue siendo candidata hasta su integración y despliegue. No confundir código parcial o mocks con capacidad real habilitada.

| Interfaz candidata | Responsabilidad |
|---|---|
| github_context | Contexto agrupado de issues y comentarios |
| methodology_context | Metodología versionada y documentos operativos seleccionados, en una respuesta local sin GitHub Connector |
| github_pr_context | Contexto agrupado de PR, cambios, findings y checks |
| github_project_context | Contexto pertinente de varias unidades de trabajo autorizadas |

Las extensiones de PR y contexto de proyecto son propuestas; empezar por issues/comentarios y ampliar solo cuando reduzca consultas y aporte valor al workflow. No construir otro GitHub Connector. Aceptación: batch real autorizado y acotado, fuente, tiempo de recuperación, completitud/truncación y errores explícitos; pruebas negativas de autorización, revocación y acceso cruzado. Medir reducción de consultas. Conservar credencial dedicada read-only, grants exactos, saneamiento y demás criterios de [#15](https://github.com/codefusion-repo/project-os-v3/issues/15).

#### B. Preparación de proyectos y ejecución local — LB-07 (#16)

| Interfaz candidata | Responsabilidad |
|---|---|
| project_status | Estado local, SHA, rama y cambios pendientes |
| prepare_workspace | Preparar revisión exacta autorizada para trabajar o validar |
| workspace_context | Recuperar código/contexto y diff local no disponibles remotamente, cuando sea necesario |
| apply_patch | Aplicar cambios locales acotados y guardados cuando sea necesario |
| run_validation | Ejecutar perfiles registrados de tests, lint o análisis |
| build_project | Compilar mediante perfil autorizado |
| workspace_changes | Recuperar diff resultante para review |

El núcleo de preparación, jobs, validación, builds y evidencia es agnóstico al proyecto, framework y plataforma, según aclaración ratificada del PM en #16. Flutter y Expo/React Native son los primeros perfiles de referencia, sin acoplar el núcleo ni imponer Android a otros proyectos. Ejemplos adicionales: frontend (build, typecheck, lint, tests); backend (tests unitarios, integración, comprobaciones de Django); mobile (análisis, tests, compilación APK). Los perfiles definen operaciones y permisos; no son comandos libres ni perfiles ya disponibles. Pueden compartir handlers. Aceptación: Browser solicita una revisión real autorizada y recibe exit codes de build/tests, logs acotados, identidad de artefactos y diff cuando aplique, preservando cambios ajenos y exclusividad del worktree. [#16](https://github.com/codefusion-repo/project-os-v3/issues/16).

#### C. Android QA — LB-08 (#17)

Android QA es agnóstico al framework productor del APK (Flutter, Expo/React Native, Android nativo u otros compatibles). Reutilizar el emulador existente de Android Studio iniciado y autorizado por el PM en Windows. Browser solicita build y QA; Local Bridge en WSL2 compila o selecciona el APK; ADB Attach conecta con ese emulador; se instala, prueba y recupera evidencia y el mismo APK. No iniciar otro emulador, usar dispositivos personales ni cambiar Windows sin autorización.

| Interfaz candidata | Responsabilidad |
|---|---|
| android_status | Detectar emulador autorizado y verificar boot completo |
| android_build | Compilar y registrar el APK |
| android_install | Instalar exactamente el APK identificado |
| android_test | Ejecutar smoke tests y pruebas registradas |
| android_evidence | Recuperar resultados y evidencia de QA |
| get_artifact | Recuperar el mismo APK probado |

Aceptación: identidad autorizada y boot completo, QA real y negativos, APK ligado a SHA/job/package/version/signature y digest idéntico al instalar y recuperar; entregar los bytes probados sin rebuild. Capturas, logs de aplicación y evidencia visual son extensiones útiles; definir y verificar canal de entrega a Browser, sin asumir transporte de binarios por MCP. Ver arquitectura Android Attach y [#17](https://github.com/codefusion-repo/project-os-v3/issues/17).

#### D. Gestión de trabajos y evidencia — transversal

| Capacidad existente | Estado en el alcance actual |
|---|---|
| health | Implementada |
| operational_diagnostics | Implementada, con grant separado |
| get_job_status | Implementada |
| get_job_evidence | Implementada |
| cancel_job | Implementada para trabajos en cola |
| Recuperación e idempotencia | Implementadas para el alcance actual |

Reutilizar jobs autenticados, estado durable, ownership, grants, idempotencia, exclusividad, status/evidence/cancel y reconciliación para builds, tests y Android QA; no crear otro motor de ejecución ni registro paralelo. Los trabajos largos devuelven identidad durable; evidencia vincula revisión, perfil, resultado y digest de artefacto, con logs acotados/saneados y fallos explícitos. La cancelación de trabajos activos requiere semántica segura propia; no se presume implementada.

#### E. Integración opcional de Codex — LB-09 (#18)

| Interfaz o capacidad candidata | Responsabilidad |
|---|---|
| codex_status | Consultar disponibilidad efectiva y señales soportadas de cuota |
| codex_execute | Ejecutar implementación autorizada mediante Codex en terminal |
| codex_execution_status | Consultar progreso y resultado |
| Handoff | Reconciliar estado y continuar en Browser sin transferencia manual de prompts |

Router pequeño auto/browser/codex, no otro motor. Browser sigue siendo implementador directo; Codex es opcional. Aplicar la arquitectura adaptativa anterior, autorización, exclusividad, disponibilidad/cuota verificadas y reconciliación antes de transferir trabajo. Aceptación: fallback browser directo cuando proceda, handoff con evidencia compartida, sin doble ejecución ni efectos inciertos. [#18](https://github.com/codefusion-repo/project-os-v3/issues/18).

**Contrato de interfaces:** los nombres anteriores son candidatos derivados del producto, no APIs congeladas ni capacidades ya implementadas. Elegir el mínimo contrato tipado por entregable; pueden agruparse operaciones y compartir handlers. No introducir herramientas genéricas por anticipación.

#### Recorrido de aceptación de extremo a extremo

Ejemplo de producto: implementar una funcionalidad Flutter y probarla en el emulador del operador, con todos los permisos y gates aplicables.

1. Recuperar requisitos, comentarios, historial y criterios del issue mediante contexto agrupado o GitHub Connector.
2. Implementar el código y preparar la revisión mediante Browser Chat o Codex autorizado.
3. Preparar localmente el SHA exacto a validar mediante Local Bridge.
4. Ejecutar tests reales y compilar el APK con perfil Flutter autorizado.
5. Instalar el APK identificado y ejecutar QA en el emulador existente autorizado mediante ADB Attach.
6. Recuperar evidencia y el artefacto exacto probado, verificando su digest.
7. Browser revisa criterios, diff y pruebas, y completa integración/cierre autorizado mediante GitHub Connector cuando corresponda.

Resultado esperado: software implementado, compilado, probado y entregado sin que el PM copie prompts o logs entre aplicaciones. Medir tiempo transcurrido, tool calls, intervenciones PM, tokens/créditos cuando sean observables, retrabajo y calidad/resultado con evidencia comparable. Un fixture o CI verde por sí solo no demuestra este recorrido.

#### Mantenimiento desde Browser Chat

[Decisión PM 26-11-2026 / #48](https://github.com/codefusion-repo/project-os-v3/issues/48): reducir handoffs de mantenimiento de la instalación central. El candidato reutiliza instalador y lifecycle existentes: health informa receipt observado, maintenance_update solicita SHA integrado/CI y wheel aprobado (contrasta evidencia del digest del intento exacto del probe antes de detener el servicio, además de la validación independiente del instalador), maintenance_status consulta resultado durable y maintenance_rollback restaura el predecesor compatible retenido. Un servicio puntual systemd de usuario sobre Python host, fuera del proceso MCP, coordina la parada y arranque sin otro servidor permanente. Grant específico revocable mediante opt-in local, sin comandos/rutas/URLs libres, cambios de credenciales o pins, ni ampliación de grants. Sin segundo canal no hay progreso remoto durante la parada; recuperación local ante fallo e interrupción. Implementación y CI independientes de #15; los controles de mantenimiento de código revisado no requieren certificar OCI de código no confiable. No activar hasta review, instalación y aceptación específicos. Ver [runbook](../local-bridge/README.md#browser-maintenance-opt-in).

#### Prioridad funcional y certificación

| Orden | Entregable | Valor práctico |
|---|---|---|
| 1 | Resolver mantenimiento pendiente (#14; corrección de pruebas PR #34 ya integrada) | Recuperar base operativa |
| 2 | Contexto GitHub agrupado real (#15) | Reducir consultas repetitivas |
| 3 | Preparación de proyectos locales (#16) | Trabajar sobre revisiones exactas |
| 4 | Compilación y tests locales (#16) | Validar software real |
| 5 | Android Attach y QA (#17) | Probar aplicaciones móviles |
| 6 | Recuperación de artefactos (#17) | Entregar APK efectivamente probado |
| 7 | Codex y routing automático (#18) | Eliminar handoffs manuales |
| 8 | Certificación integral y benchmark (#8) | Verificar preparación para producción |

Preservar la evidencia de LB-05: protege la infraestructura del producto, pero la imagen OCI fixture-only acredita solo un fixture Python fijo, no ejecución general de Flutter, Node.js, Django, Android o Codex. Cada perfil requiere controles proporcionales y evidencia propia. No ampliar certificaciones sin un riesgo concreto y entregable asociado ni repetir evidencia satisfecha salvo cambio material o caducidad.

Según la [decisión PM de mantenimiento offline](https://github.com/codefusion-repo/project-os-v3/pull/40#issuecomment-7189163141), el mantenimiento de una instalación revisada, detenida y protegida por fence no depende de controles exclusivos de activación; permite conservar un rollback completo reconciliado mediante el contrato de mantenimiento, sin borrarlo ni crear otra instalación. Los controles de red se disponen por evidencia efectiva, alcance y cambios materiales conforme a WSL-VALIDATION.md. La implementación y las pruebas descartables/CI de capacidades independientes pueden avanzar sin cerrar fases ajenas. La [decisión PM de gates por capacidad](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7188545344) ratifica gates comunes efectivos y requisitos específicos según el riesgo: LB-06 lectura GitHub/metodología puede activarse en perfil supervisado sin fixture después de acreditar host/transporte, auth, credencial dedicada, grant exacto, integridad/procedencia, privacidad, límites, auditoría, mantenimiento/rollback y revisión independiente; validación live acotada y negativa antes de uso habitual. No se exige aislamiento OCI de jobs para esa lectura. Ejecución no confiable y fixtures requieren su gate OCI/perfil propio; #14 conserva todos los criterios de certificación integral, incluidos OCI vivo y review. #15 se acepta por sus criterios de lectura, no por el cierre administrativo de #14. Cerrar cada issue cuando cumpla sus criterios. Reutilizar evidencia vigente y comprobar carencias materiales, no presumir PASS. Ninguna capacidad nueva, credencial, instalación, grant, ejecución, dispositivo ni release queda autorizada por esta definición.

Contratos: [MVP y arquitectura](../local-bridge/MVP.md), [operación](../local-bridge/README.md), [seguridad](../local-bridge/SECURITY.md), [WorkOS](../local-bridge/WORKOS.md), [validación WSL/HTTPS/systemd](../local-bridge/WSL-VALIDATION.md), [OCI local](../local-bridge/OCI-LOCAL-VALIDATION.md). Mantenerlos como contratos/runbooks técnicos; snapshots de pruebas son históricos. Bridge distribuye código para un operador local y una identidad WorkOS por instancia, no cuentas, infraestructura, credenciales ni datos compartidos; sin SaaS ni RBAC colaborativo. Registra handlers fijos de probe, GitHub sintético, status/evidence/cancel y fixture Git/Podman opt-in; LB-05 incorpora [diagnóstico operativo tipado](../local-bridge/README.md#operational-diagnostics-lb-05) de solo lectura con grant separado, en HTTPS supervisado sin fixture, y colector local previo al arranque; no reemplaza evidencia efectiva ni habilita ejecución; sin shell libre, paths arbitrarios, ejecución general, Android o Codex habilitados. LB-06 integra lectura GitHub real y metodología agrupada bajo grants explícitos (PR #38), no habilitación automática. Las primitivas de cambios Git y perfiles aislados siguen siendo parciales: código o mocks no acreditan activación real. El supervisor HTTPS, preparación de unidad systemd, locks y barrera de reconciliación existen; lifecycle de producción y certificación real siguen pendientes. Jobs SQLite ligados a principal/recurso, idempotencia, límites, autorización por solicitud/claim/dispatch, exclusividad, cancelación y recuperación; no reintentos automáticos de efectos inciertos. Ownership durable y reconciliación conservadora bloquean nuevas operaciones cuando no se verifica cleanup. No asumir que worktree o rootless son sandbox suficiente.

Piloto anterior documentó OAuth, fixture real, restart, replay, revocación y restauración ([#8](https://github.com/codefusion-repo/project-os-v3/issues/8), [PR #9](https://github.com/codefusion-repo/project-os-v3/pull/9#issuecomment-7140584788)); no certifica instalación limpia independiente, host, raw 403/contador ni recursos reales. La ejecución del conector GitHub puede continuar independientemente dentro de permisos. Preparar servicio privado, HTTPS, TLS, túnel y scope WorkOS por consentimiento; no exponer plaintext ni socket privilegiado, no registrar secretos. Identidad dedicada a agentes, aislamiento efectivo de credenciales/mounts/elevación, host trust y revisión de seguridad son gates independientes. Perfil single-operator: el WSL dedicado y su UID existentes pueden reutilizarse bajo evaluación condicional de [WSL-VALIDATION](../local-bridge/WSL-VALIDATION.md#existing-dedicated-wsl-single-operator-profile-conditional-evaluation); no equivale a un host separado. La [decisión LB05-20261125-REUSE-PILOT-INFRA-01](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7155949280) permite la [transición staging exclusiva del mismo operador](../local-bridge/WSL-VALIDATION.md#exclusive-same-operator-staging-transition): conservar WorkOS, identidad OAuth, túnel, clave restringida y conector existentes con piloto detenido y efectos reconciliados, nuevo estado privado/TLS y evidencia live nueva; no equivale a credenciales independientes ni permite concurrencia. El agente local de confianza comparte UID con el servicio y no está aislado de él; handlers y sandbox acotan código no confiable, sin confirmaciones por cada paso autorizado. Sin evidencia efectiva del host/credenciales y revisión independiente no se activa el perfil probe-only; los controles live del proceso/transporte preceden al opt-in autenticado. La [secuencia por capacidad](../local-bridge/WSL-VALIDATION.md#capability-gate-sequence-both-profiles) separa transporte, lectura y ejecución: controles comunes de host/transporte y específicos de lectura antes de LB-06; auditoría/permiso específico antes de la prueba OCI acotada, aislamiento real de jobs antes de uso posterior de fixtures o ejecución no confiable; todos los gates de certificación integral antes de completar LB-05.

La [decisión PM sobre NET-05 acotado](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7190415791) dispone el riesgo residual de rutas LAN no probadas y reglas no inspeccionadas únicamente para el perfil supervisado single-operator sin fixture, probe/diagnóstico y lectura tipada LB-06. La [extensión ratificada #48](https://github.com/codefusion-repo/project-os-v3/issues/48#issuecomment-7193767732) incluye exclusivamente mantenimiento remoto tipado de esa misma instalación revisada: update/status/rollback con grant separado revocable, integridad SHA/CI/wheel, exclusividad, evidencia durable y recuperación local. Revisión y precondiciones antes del enrolamiento inicial para dogfood; validación operativa antes del uso rutinario y cierre de #48. No amplía a otras escrituras ni ejecución arbitraria. La evidencia acumulada favorable es reutilizable como `ACCEPTED_RESIDUAL` si conserva aplicabilidad y no hay discrepancias materiales; no es un PASS de aislamiento LAN. El [criterio finito](../local-bridge/WSL-VALIDATION.md#finite-network-acceptance-and-evidence-reuse) conserva listener loopback, TLS/OAuth, credencial read-only, grants, privacidad, auditoría y revisión independiente; mantiene controles completos de red para ruta estricta, ejecución y cierre integral LB-05, salvo la disposición de transporte acotada de LB-07 descrita al final. No exigir otra prueba LAN ni inventario Windows para las capacidades acotadas por mero reinicio o cambio no material. No implica reinstalar el runtime revisado ni activar recursos por la decisión.

### Política de cadena de suministro y OCI

- LB-01: locks y hashes antes de ejecución, instalación offline revisada, builds reproducibles, auditor estricto. Única disposición PM not_affected/component_not_present: pip 26.3 wheel SHA256 f3b60b20ffaadd4415ed7957212a38ac63fa4c5fa375bd0f4a797777940fad13, CVE-2025-47273, CVE-2026-59890, GHSA-xmj3-9gf7-h52w. Cinco registros/exit 1 crudos preservados; evaluador separado verifica identidad, descripción, componentes, cobertura y errores. No otros artefactos/avisos, ignores ni riesgo aceptado. [#10 decisión -31](https://github.com/codefusion-repo/project-os-v3/issues/10#issuecomment-7141157949).
- LB-02: aceptación CI exclusivamente para digest fixture-only sha256:0c8e915d597f997fc64b7ddfc8e25de93873d06126faccbee1f46446deb30cfb y fixture stdlib fijo. Dos runners, builds reproducibles, locks APK/manifiesto, auditoría fresca sin ignores, cero hallazgos reportados, diez controles, cleanup, replay y reconciliación. Residual rechazado; ambos negativos y agregado obligatorios. Sin aprobación de uso local, binding, distribución o ejecución general; no prueba erasure de capas ni attestation base. [#11 decisión -34](https://github.com/codefusion-repo/project-os-v3/issues/11#issuecomment-7141590004), [cierre R37](https://github.com/codefusion-repo/project-os-v3/issues/11#issuecomment-7149670818).
- Decisión posterior LB-OCI-20261124-51 ([PR #20](https://github.com/codefusion-repo/project-os-v3/pull/20#issuecomment-7150805378)): original Debian descartado como candidato bajo la política vigente; control histórico determinista exacto sobre proyección íntegra de campos requeridos por evaluador, lock r49 y evidencia histórica 228/232/230 preservados. Proyección no es JSON crudo. El auditor fresco original sigue sin cambios, conserva raw, exit codes y metadata; identidad, inventario, scanner y coherencia bloquean; deriva de hallazgos se registra, no bloquea por coincidencia exacta fresca ni puede aprobar imagen. Siempre approved=false/candidate_gate=BLOCKED para original, incluso sin HIGH/CRITICAL. No cambia candidato, residual, bootstrap, aislamiento, locks, reproducibilidad ni reglas. Ver [SECURITY](../local-bridge/SECURITY.md). Local fixture exige nueva revisión, consentimiento y gate independiente; nunca rollback al original rechazado.

## Roadmap de producción y criterios

Estado vivo en [coordinador #8](https://github.com/codefusion-repo/project-os-v3/issues/8); esta tabla orienta desde la base consolidada, no duplica checklist ni autoriza acción. P0 ordena dependencias; P1 no excluye del objetivo.

| Unidad | Estado de referencia | Requisito de producción |
|---|---|---|
| [LB-01 #10](https://github.com/codefusion-repo/project-os-v3/issues/10) | completed | Cadena segura; certificación host en LB-05 |
| [LB-02 #11](https://github.com/codefusion-repo/project-os-v3/issues/11) | completed | OCI CI-only y control negativo; local separado |
| [LB-03 #12](https://github.com/codefusion-repo/project-os-v3/issues/12) | completed | Setup integrado, WSL2 real en CI, rollback descartable; [cierre -55](https://github.com/codefusion-repo/project-os-v3/issues/12#issuecomment-7151195379) |
| [#21](https://github.com/codefusion-repo/project-os-v3/issues/21) | unidad de documentación antes de LB-04 | Dos documentos centrales, continuidad y CI |
| [LB-04 #13](https://github.com/codefusion-repo/project-os-v3/issues/13) | parcial P0 | Lifecycle idempotente y observable: preparación, start/stop/status, autoarranque solo opt-in; readiness TLS/HTTP antes de túnel y dispatch, fallo worker/túnel detiene y preserva estado, restart acotado sin replay incierto, revocación, quiescencia y rollback |
| [LB-05 #14](https://github.com/codefusion-repo/project-os-v3/issues/14) | pendiente P0 | Instalación limpia y evidencia independiente del piloto, identidad dedicada y boundary efectivo (perfil WSL existente condicional o entorno separado), WSL/HTTPS/OAuth/systemd, 200/401/403 sin job, replay, rollback y auditoría local autorizada |
| [LB-06 #15](https://github.com/codefusion-repo/project-os-v3/issues/15) | pendiente P0 | GitHub real read-only tipado, credencial dedicada, grants por principal/repo, revocación, batching y evidencia |
| [LB-07 #16](https://github.com/codefusion-repo/project-os-v3/issues/16) | pendiente P0 | Cambios Git tipados sobre repos autorizados, HEAD/digest, sandbox por perfil, no shell/host fallback, exclusividad y reconciliación |
| [LB-08 #17](https://github.com/codefusion-repo/project-os-v3/issues/17) | pendiente P1 | Android QA Attach y entrega de APK exacto, según arquitectura ratificada abajo |
| [LB-09 #18](https://github.com/codefusion-repo/project-os-v3/issues/18) | pendiente P1 | Router y Codex opt-in con disponibilidad/cuota verificadas, handoff y exclusividad, no doble ejecución |

### Android QA Attach — arquitectura ratificada

Windows (Android Studio y emulador existente gestionado por el PM) ↔ ADB ↔ WSL2 (Local Bridge / Android QA Provider) ↔ MCP autenticado ↔ Browser Chat. [LB-ARCH-20261124-29](https://github.com/codefusion-repo/project-os-v3/issues/8), [criterios #17](https://github.com/codefusion-repo/project-os-v3/issues/17). Reutilizar solo el emulador expresamente autorizado ya iniciado por el PM; no instalar otro en WSL2, iniciar/administrar otro ni cambiar Windows sin autorización separada. Validar transporte sin exponer ADB indiscriminadamente, identidad estable, conexión operativa y boot completo antes de instalar o ejecutar QA. Offline, unauthorized, boot incompleto, timeout o ambigüedad bloquean; no seleccionar otro dispositivo automáticamente.

El provider WSL2 usa operaciones tipadas para build/selección, instalación y smoke tests; no ADB shell libre, dispositivos personales ni cleanup de recursos ajenos. Vincular APK, revisión, job, SHA-256, package/version/signature y resultados; verificar digest antes de instalar y recuperar/entregar exactamente el APK probado por canal autorizado, sin rebuild ni sustitución. Pruebas reales y negativas en emulador descartable autorizado, no confundir inventario o build con QA. #17 depende de #14 y #16; #18 depende de #14 y #16, de #17 solo cuando Android forme parte del perfil de routing. No se habilita ninguna capacidad en este documento.

Antes de finalizar producción: completar criterios de cada unidad, boundary de host y credenciales según perfil aprobado (independencia estricta o transición exclusiva staging del mismo operador, sin afirmar independencia no demostrada), auditorías frescas, evidencia positiva/negativa real, seguridad de CI y pinning de acciones, rollback, review y cierre autorizado por unidad. No cerrar #8 al integrar una unidad; release/deploy son acciones separadas. Licensing requiere decisión del maintainer. [Ruleset 28036856](https://github.com/codefusion-repo/project-os-v3/rules/28036856) y 14 checks requeridos (App 15368, strict, PR obligatorio, sin force push, eliminación ni bypass) ratificados en [#8](https://github.com/codefusion-repo/project-os-v3/issues/8); verificar condiciones reales antes de cada merge. La operación review_for_close solicitada por el PM, incluso mediante botón, resuelve PASS con cierre y BLOCKED con comentario; el mismo agente puede implementar y revisar. El contrato de operación solicitada de [PROJECT_OS.md](../PROJECT_OS.md) sustituye la formulación histórica DOC-09, sin confirmaciones adicionales ni ampliación de recursos. DOC-17/18/19 ratificados en #21: resolver automáticamente ambas ramas del outcome autorizado, conservar fuente, alcance y restricciones al reanudar y distinguir regresión textual de aceptación conductual independiente, conforme a la metodología central. El ruleset exigía cero approvals; GO operativo no es enforcement nativo ni aprobación humana independiente. No reutilizar autorización histórica. Si la unidad exige CI post-merge, verificar checks sobre el SHA integrado, no los del PR. #8 coordina las unidades de producción, no se cierra al integrar hitos.

## Aceptación del kit, continuidad y dogfood

Validar estructura, links, 5/9/14/2, selector CLI e interactivo, fallback stdlib, deduplicación de skills, versión fijada e integridad, PM multilínea, edición/cancelación, aislamiento/privacidad, configuración v2 y migraciones, guardado atómico, instalación y adopción. CI y pruebas unitarias/fixtures no prueban que otro agente haya seguido instrucciones. Un cold start independiente recibe solo repo/locator y recupera AGENTS.md, versión, metodología, workflow, skills, template, issue/PR, decisiones, autorización vigente y restricciones, HEAD/checks, blockers y siguiente paso sin chat anterior. La aceptación conductual de GO/NO GO y reanudación se verifica aparte mediante el protocolo de tests/test_closeout_contract.py en entorno aislado autorizado. Validar terminal y browser según capacidades reales; no afirmar coordinación multirrepo ni adopción real sin evidencia.

Dogfood en proyecto real autorizado: instalación separada, adopción versionada, tarea hasta draft PR, review con blocker y corrección en mismo PR, cambio de agente, selector, prototipo, incertidumbre secundaria no bloqueante y acción sensible correctamente detenida. Usar [dogfood](../templates/dogfood.md) con tiempo, tokens/créditos si medibles, tool calls, intervención PM, locators, falsos bloqueos, pruebas, retrabajo y calidad de handoff. Comparar tareas/modelo/alcance equivalentes; no inferir ahorro ni causalidad sin datos. Pruebas automatizadas e integración funcional MVP no sustituyen dogfood o producción. El cambio de agente y la aceptación conductual del kit son escenarios de evaluación del producto, no gates por issue ni requisito de review_for_close.

## Fuentes de decisiones y preservación histórica

La consolidación recupera estos documentos en el SHA de base, conservados íntegros en Git, no instrucciones activas:
- [Especificación MVP](https://github.com/codefusion-repo/project-os-v3/blob/75a392b63ed21a364fc8195ad5dbdd062532df2c/docs/V3_SPEC.md): propósito, arquitectura, selector, aceptación, benchmark, adopción y multirrepo.
- [Addendum](https://github.com/codefusion-repo/project-os-v3/blob/75a392b63ed21a364fc8195ad5dbdd062532df2c/docs/V3_ADDENDUM.md): wizard-first, templates, prompt único, skills y trazabilidad; decisiones posteriores prevalecen.
- [Encargo MVP](https://github.com/codefusion-repo/project-os-v3/blob/75a392b63ed21a364fc8195ad5dbdd062532df2c/docs/IMPLEMENTATION_TASK.md): alcance y entrega histórica.
- [Adopción](https://github.com/codefusion-repo/project-os-v3/blob/75a392b63ed21a364fc8195ad5dbdd062532df2c/docs/ADOPTION.md): configuración, protección, versiones, migración y workspace.
- [Validación](https://github.com/codefusion-repo/project-os-v3/blob/75a392b63ed21a364fc8195ad5dbdd062532df2c/docs/VALIDATION.md): pruebas y límites históricos, no resultados del HEAD nuevo.

Fuentes de evolución: [PR #1](https://github.com/codefusion-repo/project-os-v3/pull/1) (MVP, wizard, prompt acotado, repos equivalentes; [review multirrepo](https://github.com/codefusion-repo/project-os-v3/pull/1#issuecomment-6867239743)); [#2](https://github.com/codefusion-repo/project-os-v3/issues/2)/[PR #3](https://github.com/codefusion-repo/project-os-v3/pull/3) (closeout y publicación autorizada); [#4](https://github.com/codefusion-repo/project-os-v3/issues/4)/[PR #5](https://github.com/codefusion-repo/project-os-v3/pull/5) (main y operación review_for_close); [#6](https://github.com/codefusion-repo/project-os-v3/issues/6)/[PR #7](https://github.com/codefusion-repo/project-os-v3/pull/7) (primer proyecto y PATH); [#8](https://github.com/codefusion-repo/project-os-v3/issues/8)/[PR #9](https://github.com/codefusion-repo/project-os-v3/pull/9) (Bridge, decisiones y producción); [PR #19](https://github.com/codefusion-repo/project-os-v3/pull/19) (reconciliación histórica R37); [PR #20](https://github.com/codefusion-repo/project-os-v3/pull/20) (setup, invariancia, arquitectura, política R49 y WSL). Referencias directas de decisiones del kit: [wizard y edición](https://github.com/codefusion-repo/project-os-v3/pull/1#issuecomment-6863426549), [adopción y SHA canónico](https://github.com/codefusion-repo/project-os-v3/pull/1#issuecomment-6867041227), [prompt acotado](https://github.com/codefusion-repo/project-os-v3/pull/1#issuecomment-6867116377), [templates y validación independiente histórica](https://github.com/codefusion-repo/project-os-v3/pull/1#issuecomment-6867231165), [aislamiento de prompts](https://github.com/codefusion-repo/project-os-v3/pull/1#issuecomment-6868056756), [checkouts separados](https://github.com/codefusion-repo/project-os-v3/pull/1#issuecomment-6868394386), [operación única review_for_close](https://github.com/codefusion-repo/project-os-v3/pull/5#issuecomment-6869554981). Los comentarios y revisiones originales permanecen en sus unidades; no copiar registros de ejecución ni convertir permisos históricos en actuales. Consultar estado vivo para toda acción.


### Aceptación funcional LB-07

[Decisión PM](https://github.com/codefusion-repo/project-os-v3/issues/16#issuecomment-7226677675): separar aceptación funcional single-operator y certificación integral LB-05. Reutilizar evidencia vigente y evaluar solo carencias materiales. La disposición NET-05 residual se limita al transporte HTTPS del mismo entorno revisado y no acredita aislamiento LAN ni OCI. Mantener controles efectivos por job, identidad de imagen, auditoría de riesgos, grants, privacidad, integridad y reconciliación. Dogfood acotado con worker secuencial, perfiles agnósticos y sin fallback host; no exige cerrar #14. Aplicar SECURITY.md y WSL-VALIDATION.md; no habilitar recursos por esta decisión.


### Android Build v1 — QA default and explicit Production

[Ratified PM decision](https://github.com/codefusion-repo/project-os-v3/issues/16#issuecomment-7227042738). Supersedes the historical debug APK as operational QA default; synthetic debug profiles remain regression evidence. QA produces one standalone release APK for arm64-v8a and x86_64, with an automatically provisioned persistent project-specific QA signing identity and an authenticated link in the producing PR to a GitHub Actions artifact ZIP containing the exact signed APK. No Metro, emulator prerequisite, public release, or binary committed to Git. Production is explicit opt-in: release AAB with the authorized project's private official upload signing configuration; no automatic activation or distribution. Production implementation is not required for LB-07 QA acceptance. [Later PM delivery decision](https://github.com/codefusion-repo/project-os-v3/issues/16#issuecomment-7227684635): GitHub ZIP is the primary QA channel; the operator extracts the APK on Android and installs it manually. Google Drive private archival for traceability and Resend email notifications with a download link (no APK attachment) are deferred until after LB-09 and the production phase identified by the PM. Neither is an LB-07/08/09 dependency or authorized for activation now.

The adopted project declares its toolchain, dependency lock, native/managed layout and public QA configuration; Flutter and Expo adapters reuse the same sequential worker, isolated Podman contexts, durable Jobs and reconciliation. No repository-specific core code or host fallback. Preserve native source; managed prebuild occurs only on isolated snapshot. Keep signing keys and publisher credentials outside untrusted build execution, images, Git and logs; do not reuse production signing for QA. Preserve the QA certificate across builds, check application identity, version compatibility, signature, both ABIs and final digest. Publish the exact verified signed APK inside a GitHub Actions ZIP in the authorized producing repository and link it in the current PR, with source SHA, snapshot/job, APK digest, size, test outcome and artifact identity. Verify the extracted APK digest and size against the local signing receipt; record the ZIP digest when available. No raw download requirement, rebuild masquerading as delivery, Git commit of binaries or release. Reuse existing project workflows where compatible; an actual authorized Actions upload context must exist. Reuse prior evidence, validate real Flutter and Expo projects, and do not require integral LB-05 certification or LB-08 emulator acceptance. This is the ratified target, not an assertion that signing, local acquisition, binary transport or dogfood is implemented.
