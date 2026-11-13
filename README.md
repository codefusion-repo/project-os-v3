# Project OS v3

Kit Markdown-first para llevar una intención a un resultado verificable con workflows, skills, templates y un selector local. La hipótesis de ahorro frente a v2 aún no se ha medido en un piloto.

## Abrir el selector

Desde la raíz del kit, con Python 3 estándar:

```bash
python3 tools/select.py
```

En la primera sesión indica el repositorio como `owner/repo`; el wizard valida el formato, pero el agente deberá verificarlo en GitHub. En siguientes sesiones Enter confirma el último repositorio. Para un experimento expresamente local y descartable sin repositorio escribe `-`.

Elige un workflow (Enter usa `continue`) y las skills adicionales útiles. `repo-context` y `github-traceability` se incluyen sin pedir selección y se aplican según el contexto. El wizard pregunta un objetivo o referencia solo si aporta; el agente puede recuperar el issue/PR desde fuentes vivas. Ofrece en todos los workflows **Comentario del PM** y **Pregunta del PM**, ambos opcionales: escribe varias líneas y termina con un punto `.` en una línea propia; Enter vacío omite el campo. Su contenido no autoriza acciones sensibles.

Revisa el prompt completo y pulsa `g` para guardarlo, `e` para editar o `c` para cancelar. `/volver` retrocede, `/cancelar` cancela y `/texto` filtra los menús. Después puedes reutilizar la operación, seleccionar otra o cambiar de repositorio; el comentario y la pregunta no se reutilizan.

Al guardar, el wizard permite elegir la carpeta. Recuerda ese destino y el último repositorio en `.project-os/config.json`, ignorado por Git; solo guarda esas preferencias, no los campos del PM ni credenciales. Sin preferencia guardada, el destino es `.project-os/prompts/`. También puedes indicar una carpeta al iniciar:

```bash
python3 tools/select.py --output-dir "/ruta/a/mis-prompts"
```

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
