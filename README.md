# Project OS v3

Kit Markdown-first con workflows, skills, templates y un wizard para preparar prompts verificables. Se instala una vez; cada proyecto mantiene instrucciones versionadas y preferencias privadas propias. El selector no ejecuta workflows ni concede permisos.

## Instalar una vez

Para el piloto previo al merge, en Linux o WSL con Git y Python 3.9 o superior, consulta el [draft PR](https://github.com/codefusion-repo/project-os-v3/pull/1) y selecciona el SHA completo revisado y aprobado para tu piloto. Compáralo con el head y los checks del PR; si eliges uno anterior, confirma que es la versión que quieres probar. El siguiente ejemplo verifica que el SHA elegido sea un commit alcanzable desde el head actual del PR y que el checkout coincida antes de instalar:

```bash
git clone --no-checkout https://github.com/codefusion-repo/project-os-v3.git project-os-v3-central &&
  cd project-os-v3-central &&
  git fetch origin refs/pull/1/head:refs/remotes/origin/project-os-pilot &&
  read -r -p 'SHA completo revisado y aprobado: ' PROJECT_OS_PILOT_SHA &&
  [[ "$PROJECT_OS_PILOT_SHA" =~ ^[0-9a-f]{40}$ ]] &&
  git cat-file -e "$PROJECT_OS_PILOT_SHA^{commit}" &&
  git merge-base --is-ancestor "$PROJECT_OS_PILOT_SHA" refs/remotes/origin/project-os-pilot &&
  git checkout --detach "$PROJECT_OS_PILOT_SHA" &&
  test "$(git rev-parse HEAD)" = "$PROJECT_OS_PILOT_SHA" &&
  test -f install.sh &&
  ./install.sh
```

El bloque usa Bash y se detiene si falla alguna comprobación. La pertenencia al historial del PR no acredita revisión, aprobación ni checks: compruébalos en GitHub para el SHA seleccionado. `main` todavía no contiene el instalador. El instalador crea `.venv` aislado con `prompt_toolkit` y `~/.local/bin/project-os-v3`; no usa sudo, paquetes globales ni modifica archivos del shell. Si el destino no está en `PATH`, añade esa carpeta de forma explícita. Si falla la dependencia opcional, informa el fallo y prepara un launcher que usa Python estándar. No sobrescribe un launcher ajeno. Requiere apertura segura de directorios y enlaces duros en el filesystem.

## Adaptar un proyecto

```bash
project-os-v3 --project /ruta/al/proyecto
```

Elige `/adoptar` en la selección de operación. Si ya hay una versión fijada, puedes seleccionar explícitamente otro SHA. El wizard comprueba en GitHub que el SHA objetivo se puede recuperar del repositorio canónico; si no puede verificarlo, genera un borrador marcado como no verificado que exige comprobar el SHA antes de fijarlo. El wizard crea o valida la configuración local cuando Git permite protegerla, muestra un encargo para un agente terminal y permite guardarlo. El agente inspecciona instrucciones existentes, conserva reglas técnicas, sustituye instrucciones operativas antiguas, prepara un único `AGENTS.md` principal con SHA canónico completo y actualiza `.gitignore`. No copia el kit y no crea la configuración privada del dispositivo del PM. Consulta [adopción y migración](docs/ADOPTION.md).

## Desarrollar Project OS con su wizard

Usa una instalación central y un checkout de desarrollo separados. Desde la carpeta que contiene `project-os-v3-central`:

```bash
git clone --branch work/project-os-v3-mvp https://github.com/codefusion-repo/project-os-v3.git project-os-v3-dev
project-os-v3 --project "$PWD/project-os-v3-dev" --configure --name 'Project OS v3' --repo codefusion-repo/project-os-v3
cd project-os-v3-dev
project-os-v3 --workflow implement --locator 1 --objective 'Corregir el PR'
```

El último comando detecta la configuración del checkout de desarrollo y guarda el prompt allí, sin crear configuración ni prompts en la instalación central. Examina el PR y el estado de la rama antes de trabajar. La versión de instrucciones proviene del SHA fijado por el proyecto si existe; si no, el prompt identifica el commit de la instalación central y exige verificar su procedencia. La instalación central se excluye de la autodetección y no puede usarse como `--project`; no se admite compartir el mismo checkout para ambos roles. Consulta [adopción](docs/ADOPTION.md#desarrollar-project-os-con-su-wizard).

## Usar diariamente

Desde el proyecto o una carpeta hija ejecuta `project-os-v3`; también puedes seleccionar explícitamente `--project /ruta/al/proyecto`. Si hay configuraciones anidadas en conflicto, elige la apropiada; no se fusionan. El agente determina qué repositorios necesita; `/alcance` permite restringir una operación a uno o varios sin cambiar la configuración. Si solo conoces `owner/repo`, puedes obtener una vista previa y elegir explícitamente una carpeta segura para guardarla.

Busca el workflow por nombre, número o descripción; Enter usa `continue`. Elige varias skills sugeridas separadas por comas (`/todas` muestra otras); las dos skills base se incorporan automáticamente. Completa la entrada contextual, referencia opcional y campos PM. Pega reportes multilínea directamente en una terminal compatible con *bracketed paste* y pulsa Enter. En preview: `g` guarda, `e` permite editar workflow, skills y campos, `o` elige otra operación y `c` cancela. `/limpiar` borra un valor; `/volver` y `/cancelar` permiten navegar. Tras guardar puedes crear otra operación, reutilizarla, editarla o salir.

El destino por defecto es `.project-os/prompts/` del proyecto o workspace, no del kit central. Para elegir otra carpeta:

```bash
project-os-v3 --project /ruta/al/proyecto --output-dir /ruta/a/mis-prompts
```

Antes de guardar, el wizard comprueba las reglas Git efectivas y si existen archivos privados bajo seguimiento. Cuando es seguro, prepara y verifica una exclusión local en Git; el agente debe agregar la exclusión versionada a `.gitignore`. Si no puede proteger el proyecto, conserva la vista previa y solicita un destino externo explícito. Los prompts identificados del mismo proyecto se reemplazan solo después de escribir el nuevo, incluso en una carpeta compartida. Sin proyecto local, el conjunto exacto de repositorios identifica la operación; conjuntos distintos quedan aislados. Se conservan archivos ajenos y prompts antiguos que no pueden atribuirse con seguridad, incluidos los generados antes de esta identificación remota. Sin proyecto ni repositorios identificables se conservan prompts de otras invocaciones. El detector de secretos es heurístico y no sustituye revisar lo que se comparte.

Los repositorios de un proyecto son equivalentes; la configuración usa una lista `repositories` sin principal. El selector genera un único prompt acotado: conserva el contexto del PM y los pasos esenciales para iniciar; señala también los documentos y la versión que el agente debe verificar. No copia el kit completo en el prompt.

Para usar el selector sin la dependencia opcional: `python3 /ruta/al/kit/tools/select.py --project /ruta/al/proyecto`. Con una terminal que no soporte bracketed paste, usa flags para entrada multilínea.

## Automatización

```bash
project-os-v3 --list
project-os-v3 --project /ruta/al/proyecto --workflow review --skill code-review --skill testing --locator 123 --objective 'Revisar el PR'
project-os-v3 --project /ruta/al/proyecto --prototype --skill testing --objective 'Validar un filtro con datos simulados'
project-os-v3 --project /ruta/al/proyecto --configure --repo organizacion/frontend --repo organizacion/backend
project-os-v3 --help
```

La generación no interactiva puede leer preferencias del proyecto, pero no las cambia; `--repo` repetido limita solo la operación y, con `--configure`, agrega repositorios a la lista; `--configure` solicita explícitamente modificarlas. `--prototype` combina `implement` con `rapid-prototype` y admite más skills. El prompt referencia documentos e indica al agente que verifique su procedencia y disponibilidad. Si la versión fijada falta localmente, señala ese límite sin mezclar otra versión. Si todavía no hay SHA fijado se indica la procedencia disponible sin afirmar que el proyecto ya está adaptado.

Para uso directo, lee [PROJECT_OS.md](PROJECT_OS.md), el workflow y las skills base [repo-context](skills/repo-context/SKILL.md) y [github-traceability](skills/github-traceability/SKILL.md). El kit incluye seis workflows, nueve skills, catorce templates y dos adapters. La [especificación](docs/V3_SPEC.md), el [addendum](docs/V3_ADDENDUM.md) y la [validación histórica](docs/VALIDATION.md) son evidencia consultable cuando la tarea la requiera; no se cargan por defecto en el trabajo diario. Ejecuta `python3 -m unittest discover -s tests -v` para comprobar el kit.
