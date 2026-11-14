# Project OS v3

Kit Markdown-first con workflows, skills, templates y un wizard para preparar prompts verificables. Se instala una vez; cada proyecto mantiene instrucciones versionadas y preferencias privadas propias. El selector no ejecuta workflows ni concede permisos.

## Instalar y actualizar

**Requisitos:** Linux o WSL, Git y Python 3.9 o superior. El kit central se instala **una sola vez**, separado de los proyectos. El selector prepara prompts; no ejecuta workflows ni concede autorizaciones.

### Primera instalación

En una terminal Bash, antes de ejecutar el instalador, inspecciona el clon y su código:

```bash
git --version
python3 --version
git clone --branch main https://github.com/codefusion-repo/project-os-v3.git "$HOME/project-os-v3-central"
cd "$HOME/project-os-v3-central"
git rev-parse HEAD
sed -n '1,220p' install.sh
```

Si el código es el esperado, instala y verifica:

```bash
./install.sh
export PATH="$HOME/.local/bin:$PATH"
command -v project-os-v3
project-os-v3 --help
project-os-v3 --list
```

`export PATH=...` agrega el launcher solo a **esta sesión de shell**. Si abres otra terminal y no se encuentra `project-os-v3`, repite ese `export` o configura tu PATH manualmente. El instalador no modifica `~/.bashrc` ni requiere `sudo`. `prompt_toolkit` es opcional; ante fallo de instalación, el launcher puede usar Python estándar.

### Actualización posterior

Desde el **mismo checkout central** (no desde un proyecto adoptado):

```bash
cd "$HOME/project-os-v3-central"
git status --short
./install.sh
git rev-parse HEAD
```

`./install.sh` verifica el origen canónico, permisos, checkout limpio y avance rápido hasta el `main` integrado; si no hay red, hay divergencia o archivos ajenos, se detiene sin descartar cambios locales. No actualiza automáticamente al abrir el wizard. Si no encuentra el launcher, comprueba el PATH; si rechaza el checkout, revisa `git status --short` y `git remote -v` antes de volver a intentarlo. No uses `reset --hard`, `clean -fdx` ni `sudo` como solución.

Actualizar el kit **no** modifica `Project-OS-Version` de `AGENTS.md`, `.project-os/` ni prompts de proyectos ya adoptados: esa actualización se solicita por separado con `/adoptar`.

## Adaptar un proyecto

### Primer proyecto real

Los siguientes comandos se ejecutan **en la raíz del repositorio Git de tu proyecto**, nunca en `project-os-v3-central`. Si no está clonado, clónalo primero con `git clone https://github.com/OWNER/REPO.git /ruta/al/proyecto`.

```bash
cd /ruta/al/proyecto
git rev-parse --show-toplevel
git status --short
pwd
```

`$PWD` significa *Present Working Directory*: la ruta absoluta de la carpeta actual. Usa `cd` para situarte en la raíz correcta antes de ejecutar estos comandos. Sustituye `OWNER/REPO` por el identificador real del repositorio en GitHub y el nombre por el de tu proyecto:

```bash
project-os-v3 --project "$PWD" --configure \
  --name "Mi proyecto" \
  --repo OWNER/REPO

project-os-v3 --project "$PWD" --adopt
```

`--configure` guarda las preferencias locales protegidas en `.project-os/config.json`; `--adopt` **genera un prompt**, no crea ni modifica `AGENTS.md` directamente. Como alternativa, ejecuta `project-os-v3 --project "$PWD"` y selecciona `/adoptar` en el menú interactivo.

Ubica el encargo generado (destino predeterminado, salvo que hayas elegido uno distinto):

```bash
find .project-os/prompts -maxdepth 1 -type f -name 'project-os-prompt-*.md' -print
```

Abre ese archivo y entrégalo a un **agente terminal con acceso autorizado al checkout**. El agente revisa las instrucciones existentes, propone cambios versionados en `AGENTS.md` y `.gitignore`, fija un SHA completo verificable de `codefusion-repo/project-os-v3`, valida y publica sus cambios mediante rama/PR cuando corresponda. El wizard no hace commits, PR, merge ni adopción por su cuenta. No copies el kit al repositorio del proyecto.

### Comprobar la adopción

Después de que el agente termine, comprueba desde la raíz del proyecto:

```bash
git status --short
git diff -- AGENTS.md .gitignore
grep '^Project-OS-Version:' AGENTS.md
git check-ignore -v .project-os/config.json .project-os/prompts/example.md
git ls-files -- .project-os/
```

Revisa también los **archivos nuevos** indicados por `git status` (no aparecen en `git diff` si todavía no están rastreados). El SHA de `Project-OS-Version` debe ser completo (40 caracteres hexadecimales) y verificable en el repositorio canónico. `git check-ignore` debe mostrar la regla que protege las rutas locales; `git ls-files -- .project-os/` debe estar vacío. Si hay archivos privados rastreados, detén la publicación y revisa su posible exposición: `.gitignore` no los elimina del historial. Consulta los controles avanzados en [docs/ADOPTION.md](docs/ADOPTION.md#archivos-locales-y-protección).

### Primera tarea y PR

Una vez adoptado el proyecto, crea un encargo real para el agente:

```bash
project-os-v3 --project "$PWD" --workflow implement \
  --objective "Implementar una tarea concreta del proyecto"
```

Cuando exista un PR, sustituye `123` por su número real:

```bash
project-os-v3 --project "$PWD" --workflow review_for_close \
  --locator 123 --objective "Revisar este PR"
```

`review_for_close` revisa código y checks; solo con autorización explícita **vigente** para ese PR, su merge y el cierre del issue identificado ejecuta el closeout en la misma operación. Sin permiso devuelve PASS pendiente; con defectos, BLOCKED. El selector únicamente prepara el encargo. Esta guía define cómo hacer el piloto, **no afirma que ya se haya ejecutado una adopción real**. Para migraciones, múltiples repositorios y versiones fijadas consulta [docs/ADOPTION.md](docs/ADOPTION.md).

## Desarrollar Project OS con su wizard

Usa una instalación central y un checkout de desarrollo separados. Desde la carpeta que contiene `project-os-v3-central`:

```bash
git clone --branch main https://github.com/codefusion-repo/project-os-v3.git project-os-v3-dev
project-os-v3 --project "$PWD/project-os-v3-dev" --configure --name 'Project OS v3' --repo codefusion-repo/project-os-v3
cd project-os-v3-dev
project-os-v3 --workflow implement --objective 'Describir el cambio'
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
project-os-v3 --project /ruta/al/proyecto --workflow review_for_close --skill code-review --skill testing --locator 123 --objective 'Revisar el PR'
project-os-v3 --project /ruta/al/proyecto --prototype --skill testing --objective 'Validar un filtro con datos simulados'
project-os-v3 --project /ruta/al/proyecto --configure --repo organizacion/frontend --repo organizacion/backend
project-os-v3 --help
```

La generación no interactiva puede leer preferencias del proyecto, pero no las cambia; `--repo` repetido limita solo la operación y, con `--configure`, agrega repositorios a la lista; `--configure` solicita explícitamente modificarlas. `--prototype` combina `implement` con `rapid-prototype` y admite más skills. El prompt referencia documentos e indica al agente que verifique su procedencia y disponibilidad. Si la versión fijada falta localmente, señala ese límite sin mezclar otra versión. Si todavía no hay SHA fijado se indica la procedencia disponible sin afirmar que el proyecto ya está adaptado.

Para uso directo, lee [PROJECT_OS.md](PROJECT_OS.md), el workflow y las skills base [repo-context](skills/repo-context/SKILL.md) y [github-traceability](skills/github-traceability/SKILL.md). El kit incluye cinco workflows, nueve skills, catorce templates y dos adapters. `review_for_close` revisa y, con autorización explícita vigente para el PR y su issue, ejecuta el cierre en la misma operación; sin ella informa PASS pendiente. Los nombres legados `review` y `close` se rechazan: usa `review_for_close` y, si la versión fijada no lo contiene, actualiza el proyecto explícitamente. La [especificación](docs/V3_SPEC.md), el [addendum](docs/V3_ADDENDUM.md) y la [validación histórica](docs/VALIDATION.md) son evidencia consultable cuando la tarea la requiera; no se cargan por defecto en el trabajo diario. Ejecuta `python3 -m unittest discover -s tests -v` para comprobar el kit.
