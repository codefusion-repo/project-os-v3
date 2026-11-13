# Project OS v3

Kit Markdown-first para llevar una intención a un resultado verificable con workflows, skills, templates y un selector local. La hipótesis de ahorro frente a v2 aún no se ha medido en un piloto.

## Abrir el selector

Plataforma soportada: Linux con Python 3.9 o superior y un sistema de archivos que admita enlaces duros y apertura de directorios sin seguir symlinks. La interfaz enriquecida usa `prompt_toolkit` opcional: ofrece sugerencias mientras escribes y edición directa de valores, como el wizard de v2. Desde la raíz del kit:

```bash
python3 -m venv .project-os/venv
.project-os/venv/bin/python -m pip install 'prompt_toolkit>=3.0.43,<4'
.project-os/venv/bin/python tools/select.py
```

Sin instalar paquetes también puedes ejecutar `python3 tools/select.py`; usa la interfaz de terminal de la biblioteca estándar. Para pegar reportes con saltos de línea en cualquiera de las dos interfaces, la terminal debe admitir *bracketed paste*. Se comprobó con un pseudo-terminal compatible; una terminal que no respete ese protocolo puede interpretar un pegado como varias respuestas. La alternativa segura en ese caso es usar los flags del CLI.

1. Busca una operación escribiendo su nombre, un número o parte de su descripción; Enter selecciona `continue`. Si escribes una intención sin coincidencia, se usa `continue` y se conserva como pregunta del PM. El wizard pide el repositorio `owner/repo` si no está guardado; valida solo su formato, no su existencia remota. Para un experimento local descartable sin repositorio escribe `-`.
2. Selecciona cero o varias skills sugeridas, separadas por comas; `/todas` muestra otras. `repo-context` y `github-traceability` se incluyen automáticamente y se aplican según el contexto. Completa la entrada específica del workflow; cuando corresponda puedes indicar una referencia opcional de issue/PR por separado. El comentario y la pregunta del PM son opcionales en todos los workflows. Pega reportes y texto multilínea directamente en el campo y pulsa Enter para confirmarlos. Las flechas permiten editar. El texto conserva los saltos de línea, con CRLF o CR normalizados a LF; las notas del sistema aparecen por separado.
3. Revisa el prompt completo: `g` guarda, `e` vuelve a elegir workflow y skills y editar los campos sin volver a pedir el repositorio, `o` elige otra operación y `c` cancela. Al editar, Enter conserva los valores y `/limpiar` borra el campo. `/volver` vuelve a operaciones y `/cancelar` sale. Después de guardar puedes crear otra operación (`n`), reutilizar la misma (`m`), editar (`e`), mostrar la ruta (`p`) o salir (`s`). Una operación nueva no reutiliza el contexto ni los campos PM anteriores.

El repositorio y la carpeta se muestran al empezar. Usa `/repo` o `/carpeta` en la selección de operación para cambiarlos. Se recuerdan en `.project-os/config.json`, ignorado por Git; no se guardan campos PM ni credenciales en la configuración. Sin preferencia, la carpeta es `.project-os/prompts/`. También puedes elegirla al iniciar:

```bash
.project-os/venv/bin/python tools/select.py --output-dir "/ruta/a/mis-prompts"
```

El selector rechaza patrones comunes de credenciales antes de previsualizar o guardar y no reproduce su contenido en los errores. La detección es heurística y no identifica todos los secretos; revisa el prompt antes de compartirlo.

Al guardar, se eliminan **solo después de escribir el nuevo** los prompts anteriores identificados del selector en la carpeta elegida. Conserva Markdown manuales, archivos de otras carpetas y symlinks; cancelar o fallar la escritura conserva el anterior. La carpeta no admite `..` ni componentes symlink. La publicación atómica requiere soporte de directorios sin seguimiento de symlinks y enlaces duros. Los prompts incluyen el contenido del PM; si eliges una carpeta fuera de `.project-os/`, protege y excluye ese destino de Git según corresponda.

## Uso directo y prototipo

```bash
python3 tools/select.py --list
python3 tools/select.py --repo ORGANIZACION/REPOSITORIO --workflow review --skill code-review --skill testing --locator 123 --objective "Revisar el PR"
python3 tools/select.py --prototype --skill testing --skill security-review --objective "Validar un filtro de tareas con datos simulados"
python3 tools/select.py --help
```

En modo no interactivo se muestra la vista previa y se guarda directamente, sin leer ni modificar la configuración local; añade `--output-dir` si quieres elegir destino. `--skill` se puede repetir y `--prototype` equivale a `implement` más `rapid-prototype`; admite skills especializadas adicionales y ambos incluyen automáticamente las dos skills base, sin duplicarlas. El prompt contiene reglas compartidas, instrucciones seleccionadas y contexto; los templates pertinentes se incorporan automáticamente como recursos opcionales. No ejecuta workflows, llama GitHub ni concede permisos.

Sin selector, pide al agente leer [PROJECT_OS.md](PROJECT_OS.md), el workflow, las skills base [repo-context](skills/repo-context/SKILL.md) y [github-traceability](skills/github-traceability/SKILL.md), y solo las skills especializadas pertinentes; por ejemplo, [continue](workflows/continue.md) para recuperar estado vivo o [review](workflows/review.md) para revisar un diff. La trazabilidad remota es obligatoria para cambios destinados a integración cuando existan autorización y capacidad; si faltan, informa trazabilidad pendiente. Solo un experimento expresamente local y descartable se exceptúa; si no tiene repositorio, no requiere consultas GitHub. El selector es parte del kit, pero no es obligatorio para operar.

## Contenido y adopción

El kit distribuye seis [workflows](workflows/), nueve [skills](skills/), catorce [templates](templates/) y [adapters](adapters/). Los templates se usan solo cuando aportan valor. Consulta la [guía de adopción](docs/ADOPTION.md), el [contrato MVP](docs/V3_SPEC.md), el [encargo](docs/IMPLEMENTATION_TASK.md) y sus [addenda](docs/V3_ADDENDUM.md). Valida el paquete con `python3 -m unittest discover -s tests -v`.
