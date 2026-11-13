# Project OS v3

Kit Markdown-first para llevar una intención a un resultado verificable con workflows, skills, templates y un selector local. La hipótesis de ahorro frente a v2 aún no se ha medido en un piloto.

## Abrir el selector

Desde la raíz del kit, con Python 3 estándar:

```bash
python3 tools/select.py
```

Elige un workflow (Enter usa `continue`) y las skills adicionales útiles. `repo-context` y `github-traceability` se incluyen siempre sin pedir selección; sus procedimientos se aplican según el contexto. Escribe solo el objetivo, repositorio, referencias o restricciones que el agente necesite y no pueda inferir. El selector muestra el prompt completo para revisión: guarda con `g`, edita con `e` o cancela con `c`. Después de guardar puedes reutilizar la operación con contexto nuevo, elegir otra o salir. En los menús, `/texto` filtra, `/` restablece y `/cancelar` cancela.

Por defecto los prompts se guardan en `.project-os/prompts/` dentro del kit, carpeta ignorada por Git. Para elegir otra carpeta:

```bash
python3 tools/select.py --output-dir "/ruta/a/mis-prompts"
```

El selector avisa antes de guardar: **cuando la escritura del nuevo prompt termina correctamente, elimina los prompts anteriores creados por el selector en esa misma carpeta**. Identifica sus archivos por nombre reservado y marcador interno. Conserva Markdown manuales, archivos de otras carpetas y symlinks; una cancelación o un fallo de escritura conserva el anterior. La carpeta no admite `..` ni componentes symlink. El guardado requiere un sistema con soporte de directorios sin seguimiento de symlinks y enlaces duros en la carpeta de destino.

## Uso directo y prototipo

```bash
python3 tools/select.py --list
python3 tools/select.py --workflow review --skill code-review --skill testing --locator 123 --objective "Revisar el PR del repo identificado"
python3 tools/select.py --prototype --skill testing --skill security-review --objective "Validar un filtro de tareas con datos simulados"
python3 tools/select.py --help
```

En modo no interactivo se muestra la vista previa y se guarda directamente; añade `--output-dir` si quieres elegir destino. `--skill` se puede repetir y `--prototype` equivale a `implement` más `rapid-prototype`; admite skills especializadas adicionales y ambos incluyen automáticamente las dos skills base, sin duplicarlas. El prompt contiene reglas compartidas, instrucciones seleccionadas y contexto; los templates pertinentes se incorporan automáticamente como recursos opcionales. No ejecuta workflows, llama GitHub ni concede permisos.

Sin selector, pide al agente leer [PROJECT_OS.md](PROJECT_OS.md), el workflow, las skills base [repo-context](skills/repo-context/SKILL.md) y [github-traceability](skills/github-traceability/SKILL.md), y solo las skills especializadas pertinentes; por ejemplo, [continue](workflows/continue.md) para recuperar estado vivo o [review](workflows/review.md) para revisar un diff. La trazabilidad remota es obligatoria para cambios destinados a integración cuando existan autorización y capacidad; si faltan, informa trazabilidad pendiente. Solo un experimento expresamente local y descartable se exceptúa; si no tiene repositorio, no requiere consultas GitHub. El selector es parte del kit, pero no es obligatorio para operar.

## Contenido y adopción

El kit distribuye seis [workflows](workflows/), nueve [skills](skills/), catorce [templates](templates/) y [adapters](adapters/). Los templates se usan solo cuando aportan valor. Consulta la [guía de adopción](docs/ADOPTION.md), el [contrato MVP](docs/V3_SPEC.md), el [encargo](docs/IMPLEMENTATION_TASK.md) y sus [addenda](docs/V3_ADDENDUM.md). Valida el paquete con `python3 -m unittest discover -s tests -v`.
