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

Configuración v2 local en .project-os/config.json: nombre, lista no vacía repositories sin jerarquía, checkouts opcionales, destino de prompts. No guarda credenciales, campos PM, permisos ni estado de issues. Default .project-os/prompts/. Antes de escribir, comprueba exclusiones efectivas y archivos ya rastreados; puede preparar info/exclude local y verificarlo. Agente incorpora .project-os/ a .gitignore. Si hay datos privados tracked no leerlos/escribir allí; ignore no los retira de historia. Ante imposibilidad de proteger, conserva preview y pide destino externo explícito y seguro; no uses carpetas temporales compartidas para prompts sensibles. Informa antes de reemplazar y cuando prepara una exclusión local. Guardado atómico, rechazo de traversal/symlinks y patrones heurísticos de secretos sin imprimir valores. Tras escribir reemplaza solo prompts atribuibles al mismo proyecto o conjunto remoto exacto (sin distinguir orden o mayúsculas), en la misma carpeta; conserva ajenos, antiguos sin identificación y anteriores ante fallo o cancelación. Si falla la limpieza posterior lo informa; no elimina symlinks ni archivos ajenos. Sin repositorio identificable no limpia prompts ajenos.

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

**Fuente de verdad funcional vigente (PM, 2026-11-26):** [decisión ratificada](https://github.com/codefusion-repo/project-os-v3/issues/8#issuecomment-7185110551) y [consolidación de capacidades en MVP.md](../local-bridge/MVP.md#production-capability-consolidation--authoritative-product-scope). El MCP complementa GitHub Connector con contexto agrupado, preparación local y validación/build, Android QA/artefactos y Codex opcional; no replica Git remoto ni ofrece shell general. Prioridad: resolver mantenimiento existente, #15, #16, #17, #18, certificación integral y benchmark. La tabla histórica de roadmap conserva criterios de producción; sus dependencias no impiden implementar y probar capacidades independientes en estado descartable. Activación real conserva todos los gates vigentes. No extender validaciones sin riesgo concreto y entregable funcional asociado; reutilizar evidencia satisfecha salvo cambio material/caducidad.


Contratos: [MVP y arquitectura](../local-bridge/MVP.md), [operación](../local-bridge/README.md), [seguridad](../local-bridge/SECURITY.md), [WorkOS](../local-bridge/WORKOS.md), [validación WSL/HTTPS/systemd](../local-bridge/WSL-VALIDATION.md), [OCI local](../local-bridge/OCI-LOCAL-VALIDATION.md). Mantenerlos como contratos/runbooks técnicos; snapshots de pruebas son históricos. Bridge distribuye código para un operador local y una identidad WorkOS por instancia, no cuentas, infraestructura, credenciales ni datos compartidos; sin SaaS ni RBAC colaborativo. Registra handlers fijos de probe, GitHub sintético, status/evidence/cancel y fixture Git/Podman opt-in; LB-05 incorpora [diagnóstico operativo tipado](../local-bridge/README.md#operational-diagnostics-lb-05) de solo lectura con grant separado, en HTTPS supervisado sin fixture, y colector local previo al arranque; no reemplaza evidencia efectiva ni habilita ejecución; sin shell libre, paths arbitrarios, real GitHub MCP, ejecución general, Android o Codex habilitados. El lector GitHub real local, las primitivas de cambios Git y los perfiles aislados son parciales: la existencia de código o mocks no habilita handlers sobre repositorios reales. El supervisor HTTPS, preparación de unidad systemd, locks y barrera de reconciliación existen; lifecycle de producción y certificación real siguen pendientes. Jobs SQLite ligados a principal/recurso, idempotencia, límites, autorización por solicitud/claim/dispatch, exclusividad, cancelación y recuperación; no reintentos automáticos de efectos inciertos. Ownership durable y reconciliación conservadora bloquean nuevas operaciones cuando no se verifica cleanup. No asumir que worktree o rootless son sandbox suficiente.

Piloto anterior documentó OAuth, fixture real, restart, replay, revocación y restauración ([#8](https://github.com/codefusion-repo/project-os-v3/issues/8), [PR #9](https://github.com/codefusion-repo/project-os-v3/pull/9#issuecomment-7140584788)); no certifica instalación limpia independiente, host, raw 403/contador ni recursos reales. La ejecución del conector GitHub puede continuar independientemente dentro de permisos. Preparar servicio privado, HTTPS, TLS, túnel y scope WorkOS por consentimiento; no exponer plaintext ni socket privilegiado, no registrar secretos. Identidad dedicada a agentes, aislamiento efectivo de credenciales/mounts/elevación, host trust y revisión de seguridad son gates independientes. Perfil single-operator: el WSL dedicado y su UID existentes pueden reutilizarse bajo evaluación condicional de [WSL-VALIDATION](../local-bridge/WSL-VALIDATION.md#existing-dedicated-wsl-single-operator-profile-conditional-evaluation); no equivale a un host separado. La [decisión LB05-20261125-REUSE-PILOT-INFRA-01](https://github.com/codefusion-repo/project-os-v3/issues/14#issuecomment-7155949280) permite la [transición staging exclusiva del mismo operador](../local-bridge/WSL-VALIDATION.md#exclusive-same-operator-staging-transition): conservar WorkOS, identidad OAuth, túnel, clave restringida y conector existentes con piloto detenido y efectos reconciliados, nuevo estado privado/TLS y evidencia live nueva; no equivale a credenciales independientes ni permite concurrencia. El agente local de confianza comparte UID con el servicio y no está aislado de él; handlers y sandbox acotan código no confiable, sin confirmaciones por cada paso autorizado. Sin evidencia efectiva del host/credenciales y revisión independiente no se activa el perfil probe-only; los controles live del proceso/transporte preceden al opt-in autenticado. La [secuencia por capacidad](../local-bridge/WSL-VALIDATION.md#capability-gate-sequence-both-profiles) separa la certificación OCI live del transporte probe-only, sin eliminar requisitos: auditoría/permiso específico antes de la prueba OCI acotada, aislamiento real de jobs antes de habilitar uso posterior de fixtures o ejecución no confiable; todos los gates antes de completar LB-05 o habilitar recursos reales.

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
