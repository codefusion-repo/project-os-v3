# Project OS v3

Kit Markdown-first con workflows, skills, templates y un wizard para preparar prompts verificables. Se instala una vez; cada proyecto mantiene instrucciones versionadas y preferencias privadas propias. El selector no ejecuta workflows ni concede permisos.

## Instalar una vez

En Linux o WSL, con Git y Python 3.9 o superior, desde un checkout inspeccionado del kit:

```bash
git clone https://github.com/codefusion-repo/project-os-v3.git
cd project-os-v3
./install.sh
```

Durante el desarrollo del MVP usa la rama del draft PR: la rama de distribución puede no contener aún estos cambios. El instalador crea `.venv` aislado con `prompt_toolkit` y `~/.local/bin/project-os-v3`; no usa sudo, paquetes globales ni modifica archivos del shell. Si el destino no está en `PATH`, añade esa carpeta de forma explícita. Si falla la dependencia opcional, informa el fallo y prepara un launcher que usa Python estándar. No sobrescribe un launcher ajeno. Requiere apertura segura de directorios y enlaces duros en el filesystem.

## Adaptar un proyecto

```bash
project-os-v3 --project /ruta/al/proyecto
```

Elige `/adoptar` en la selección de operación. Si ya hay una versión fijada, puedes seleccionar explícitamente otro SHA. El wizard comprueba en GitHub que el SHA objetivo se puede recuperar del repositorio canónico; si no puede verificarlo, genera un borrador marcado como no verificado que exige comprobar el SHA antes de fijarlo. El wizard crea o valida la configuración local cuando Git permite protegerla, muestra un encargo para un agente terminal y permite guardarlo. El agente inspecciona instrucciones existentes, conserva reglas técnicas, sustituye instrucciones operativas antiguas, prepara un único `AGENTS.md` principal con SHA canónico completo y actualiza `.gitignore`. No copia el kit y no crea la configuración privada del dispositivo del PM. Consulta [adopción y migración](docs/ADOPTION.md).

## Usar diariamente

Desde el proyecto o una carpeta hija ejecuta `project-os-v3`; también puedes seleccionar explícitamente `--project /ruta/al/proyecto`. Si hay configuraciones anidadas en conflicto, elige la apropiada; no se fusionan. El agente determina qué repositorios necesita; `/alcance` permite restringir una operación a uno o varios sin cambiar la configuración. Si solo conoces `owner/repo`, puedes obtener una vista previa y elegir explícitamente una carpeta segura para guardarla.

Busca el workflow por nombre, número o descripción; Enter usa `continue`. Elige varias skills sugeridas separadas por comas (`/todas` muestra otras); las dos skills base se incorporan automáticamente. Completa la entrada contextual, referencia opcional y campos PM. Pega reportes multilínea directamente en una terminal compatible con *bracketed paste* y pulsa Enter. En preview: `g` guarda, `e` permite editar workflow, skills y campos, `o` elige otra operación y `c` cancela. `/limpiar` borra un valor; `/volver` y `/cancelar` permiten navegar. Tras guardar puedes crear otra operación, reutilizarla, editarla o salir.

El destino por defecto es `.project-os/prompts/` del proyecto o workspace, no del kit central. Para elegir otra carpeta:

```bash
project-os-v3 --project /ruta/al/proyecto --output-dir /ruta/a/mis-prompts
```

Antes de guardar, el wizard comprueba las reglas Git efectivas y si existen archivos privados bajo seguimiento. Cuando es seguro, prepara y verifica una exclusión local en Git; el agente debe agregar la exclusión versionada a `.gitignore`. Si no puede proteger el proyecto, conserva la vista previa y solicita un destino externo explícito. Los prompts identificados del mismo proyecto se reemplazan solo después de escribir el nuevo, incluso en una carpeta compartida. Se conservan los archivos ajenos y los prompts antiguos que no pueden atribuirse a un proyecto. Sin proyecto local identificable, se conservan los prompts de otras invocaciones. El detector de secretos es heurístico y no sustituye revisar lo que se comparte.

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

Para uso directo, lee [PROJECT_OS.md](PROJECT_OS.md), el workflow y las skills base [repo-context](skills/repo-context/SKILL.md) y [github-traceability](skills/github-traceability/SKILL.md). El kit incluye seis workflows, nueve skills, catorce templates y dos adapters. La [especificación](docs/V3_SPEC.md) y el [addendum](docs/V3_ADDENDUM.md) describen el contrato. Ejecuta `python3 -m unittest discover -s tests -v` para comprobar el kit.
