# Adopción, migración y actualización

## Una instalación y un proyecto

Para empezar desde cero utiliza el [recorrido de instalación y primer proyecto](../README.md#instalar-y-actualizar) del README; esta guía cubre detalles avanzados de adopción, protección, migración y versiones. Ejecuta los comandos de proyecto desde **la raíz de su checkout Git**: en Bash, `$PWD` contiene la ruta absoluta del directorio actual. El checkout central del kit y los proyectos son carpetas separadas.

Instala y actualiza el checkout central desde `main` siguiendo el [inicio rápido](../README.md#instalar-y-actualizar) y ejecuta `project-os-v3 --project /ruta/al/proyecto`. Selecciona `/adoptar`; el wizard prepara configuración local si puede protegerla y genera un único encargo. Si el proyecto ya tiene una versión fijada, muestra esa versión y el HEAD local del kit y permite indicar otro SHA objetivo. Entrega el prompt a un agente terminal con acceso al checkout y autorización. No copies workflows, skills, templates ni el wizard al proyecto. En un repo sin checkout local, indica `owner/repo`: el selector no inventa una ruta ni configuración local y solo guarda en una carpeta externa elegida expresamente.

El agente inspecciona rama, diff e instrucciones existentes; adapta el `AGENTS.md` principal y `.gitignore` dentro del alcance autorizado. La configuración local es responsabilidad del wizard en el dispositivo donde se ejecuta; el agente no debe crearla suponiendo que comparte ese filesystem. No debe abrir secretos ni eliminar archivos desconocidos. Registra en GitHub commit, PR, checks y un comentario histórico nuevo cuando esté autorizado.

## Desarrollar Project OS con su wizard

El checkout que ejecuta el kit es la instalación central, no un proyecto autodetectable. Para trabajar sobre Project OS usa otro checkout del mismo repositorio como proyecto: instala el central desde `main` y configura explícitamente el checkout de desarrollo con `--project`, nombre y `--repo codefusion-repo/project-os-v3`. El [ejemplo completo](../README.md#desarrollar-project-os-con-su-wizard) genera después un prompt desde dentro del checkout de desarrollo, donde se detecta su configuración protegida. El wizard rechaza usar la instalación central como `--project`; no hay un modo compartido del mismo checkout.

La versión aplicable procede de `AGENTS.md` del checkout de desarrollo cuando está fijada; de lo contrario el prompt señala la procedencia local del kit y exige verificarla. Esta separación no implica que la revisión, los checks o la procedencia del SHA estén aprobados automáticamente, ni demuestra un piloto real.

Un bootstrap versionado puede contener, con el SHA real elegido:

```markdown
# Instrucciones del proyecto

Project OS: codefusion-repo/project-os-v3
Project-OS-Version: <SHA completo de un commit verificable>
Lee PROJECT_OS.md, el workflow aplicable y las skills repo-context y github-traceability desde ese commit del repositorio canónico. Respeta las reglas técnicas y autorizaciones propias de este proyecto.
```

Añade reglas técnicas válidas, restricciones y referencias versionadas pertinentes. Para un agente sin instalación central, los documentos se recuperan desde GitHub en el SHA fijado. Sin acceso a los documentos aplicables, informa el límite y continúa solo lo que sea seguro.

## Archivos locales y protección

En el primer proyecto, `--configure --repo OWNER/REPO` registra preferencias y `--adopt` prepara el prompt para un agente; **ninguno ejecuta la adopción ni crea un PR por sí solo**. Tras aplicar el encargo, comprueba el SHA canónico fijado en `AGENTS.md`, la revisión de `AGENTS.md` y `.gitignore`, el resultado de `git check-ignore -v .project-os/config.json .project-os/prompts/example.md` y que `git ls-files -- .project-os/` no muestre archivos. El [quickstart](../README.md#comprobar-la-adopción) contiene los comandos. Si se detectan datos privados rastreados, no los publiques ni confíes en que añadir `.gitignore` los desversiona.

La configuración se aloja en `proyecto/.project-os/config.json`; el destino predeterminado es `proyecto/.project-os/prompts/`. Antes de escribir, el wizard usa Git para detectar archivos ya rastreados y comprobar exclusiones efectivas para los nombres reales. Si la carpeta no está ignorada, puede agregar una regla estrictamente local a Git `info/exclude` y verifica el resultado. Informa esa protección; el agente incorpora `.project-os/` a `.gitignore`. Una regla de ignore no elimina archivos ya rastreados: si existen, no se lee su configuración ni se escribe allí; prepara una corrección revisable y evalúa exposición histórica sin mostrar contenidos.

La configuración v2 admite nombre, una lista no vacía `repositories` de repositorios equivalentes, rutas locales de checkout y carpeta de prompts; no existe un repositorio principal. No admite credenciales, contenido PM ni estado de issues/PR. Preferencias explícitas se guardan así:

```bash
project-os-v3 --project /ruta/al/workspace --configure --repo organizacion/frontend --repo organizacion/backend --checkout organizacion/backend=/ruta/al/backend
```

Al configurar un checkout se conservan los demás; indicar nuevamente un repositorio actualiza solo su ruta local. Ninguna de estas rutas se incorpora automáticamente al prompt.

Si una carpeta contiene configuración desconocida, el wizard la conserva y no la reemplaza. Ante errores o rutas inseguras, corrige la protección o elige un destino externo seguro de forma explícita. No uses carpetas temporales compartidas para prompts sensibles.

## Workspace y precedencia

Un workspace puede agrupar varios repositorios y conservar una sola configuración local. Cada repo conserva su propio `AGENTS.md`. `--project` tiene prioridad; sin él, el wizard busca configuraciones en el directorio actual y ancestros, sin recorrer el dispositivo. Si dos configuraciones anidadas difieren materialmente en repo o destino de prompts, solicita selección interactiva o exige `--project` en CLI; nunca las fusiona. El agente decide qué repositorios necesita. `/alcance` (o el alias `/repo`) limita solo la operación actual sin alterar la lista; `--repo` puede repetirse para hacer lo mismo en CLI. El prompt incluye repositorios conocidos para esa tarea, pero nunca rutas de checkout y pide no divulgar asociaciones privadas.

Para continuidad remota, documenta en `AGENTS.md` o arquitectura solo las relaciones entre repositorios que sean verificadas, necesarias y adecuadas a la visibilidad y autorización. Si una relación no puede divulgarse, informa la limitación y usa un canal autorizado. Cada repo requiere permisos propios.

## Migración y recuperación

Para preferencias antiguas del selector central, selecciona explícitamente el proyecto y confirma el repo que figura en el formato antiguo:

```bash
project-os-v3 --project /ruta/al/proyecto --configure --migrate-legacy --repo organizacion/repositorio
```

Para el esquema local v1 reconocido, el wizard combina sus repositorios en v2, deduplica sin perder orden y conserva checkouts, carpeta y archivos; la migración se escribe atómicamente tras proteger Git. En CLI, una generación normal usa la conversión en memoria sin modificar la configuración; `--configure` la confirma. Ante ambigüedad o error se conserva el original. Para la configuración central anterior, se conserva también el archivo de origen y los prompts antiguos; el nuevo destino por defecto pertenece al proyecto. Si el repo no coincide, el formato es desconocido o ya existe configuración local, la migración se detiene sin sobrescribir. No se borran archivos desconocidos ni prompts. Ante un fallo conserva los archivos y corrige la causa antes de reintentar.

Para v2 o una copia previa de v3, el agente hace inventario de instrucciones y componentes, sustituye referencias operativas contradictorias preservando reglas técnicas y prepara un diff. No borra directorios por nombre ni elimina datos personalizados; solicita autorización para retiros destructivos. El wizard solo prepara el encargo; esta guía no afirma que una migración real ya se haya ejecutado.

## Actualización de versión

El proyecto conserva su SHA hasta una actualización explícita. El prompt acotado incluye la tarea y pasos esenciales, referencia esa versión y pide al agente verificar y recuperar los documentos; no copia el kit completo. El selector comprueba los documentos utilizados contra los objetos Git locales cuando están disponibles y señala diferencias sin incluirlas. Al generar un encargo de adopción o actualización consulta si el SHA exacto está disponible en la API del repositorio canónico; si falta conexión, acceso o verificación, genera un borrador marcado como no verificado que exige comprobarlo antes de fijarlo. Abrir el wizard y preparar otras operaciones no requiere red. Si el SHA fijado no está disponible localmente, el prompt indica esa limitación y el agente debe verificarlo. Para preparar una actualización, proporciona un SHA objetivo real disponible:

```bash
project-os-v3 --project /ruta/al/proyecto --adopt --target-version SHA_COMPLETO
```

El encargo pide comparar versiones, preservar personalizaciones, preparar diff y validar; no modifica el `AGENTS.md` por sí solo. No hay descarga ni ejecución de código remoto para resolver documentos.

## Aceptación en uso real

Con un proyecto piloto autorizado, valida instalación desde otra carpeta, exclusión Git previa a escritura, adopción por un agente terminal sin copiar el kit, una tarea acotada con el SHA correcto y GitHub autorizado. En una sesión independiente entrega solo el repo o locator y comprueba recuperación de instrucciones, relaciones divulgables, PR, checks, bloqueos y siguiente paso. Comprueba además el wizard y los controles de secretos. Registra comandos, exit codes, SHA, checks y límites. Los tests aislados no demuestran por sí solos esta prueba integral; el dogfood de rendimiento es posterior.

El wizard utiliza un único formato de prompt; conserva el texto del PM sin copiar documentos operativos completos.
