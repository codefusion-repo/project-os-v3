# Project OS v3

Kit operativo Markdown-first para llevar una intención a un resultado verificable con workflows, skills, templates y un selector local. La hipótesis de ahorro frente a v2 aún no se ha medido en un piloto.

## Inicio en 30 segundos

En la raíz de este kit, ejecuta con Python 3 estándar:

```bash
python3 tools/select.py --workflow continue
```

Copia el prompt, añade tu objetivo y entrégalo a un agente con acceso al kit y al proyecto. Para comenzar sin contexto: «Retoma el trabajo de este repositorio; identifica el issue/PR si existe, verifica los checks y continúa con el siguiente paso seguro». El agente lee [PROJECT_OS.md](PROJECT_OS.md), [continue](workflows/continue.md) y las instrucciones del proyecto; busca fuentes vivas en vez de depender del chat anterior.

## Elegir una operación

```bash
python3 tools/select.py                  # menú; Enter elige continue, luego skills opcionales
python3 tools/select.py --list           # descubre workflows y skills
python3 tools/select.py --workflow review --skill code-review --skill testing --locator 123
python3 tools/select.py --help
```

Repite `--skill` para componer capacidades; el locator es contexto, no una orden. En el menú se aceptan nombres o números, separados por comas para skills; `/texto` filtra por nombre o descripción y `/` restablece la lista. Se muestran skills sugeridas desde el workflow, sin seleccionarlas automáticamente. La salida es texto copiable; el selector no llama al agente, GitHub ni ejecuta workflows. Sin Python, indica directamente: «Lee `PROJECT_OS.md` y `workflows/review.md`; revisa el diff del PR 123 y entrega findings con evidencia». Lee solo las skills útiles.

## Prototipo rápido

```bash
python3 tools/select.py --prototype
```

Añade, por ejemplo: «Quiero comprobar si un PM encuentra una tarea: crea una pantalla mínima con una lista de datos simulados y un filtro; demuestra que filtrar cambia el resultado». El agente aplica [implement](workflows/implement.md) y [rapid-prototype](skills/rapid-prototype/SKILL.md): hipótesis → una ruta vertical → demo o test real → decisión de iterar, descartar o endurecer. No se exige issue ni PR para el resultado local.

## Contenido y adopción

Los seis [workflows](workflows/), nueve [skills](skills/), diez [templates](templates/) y [adapters](adapters/) son independientes del selector. Los templates se rellenan solo cuando aportan valor. Consulta [adopción](docs/ADOPTION.md), [reglas compartidas](PROJECT_OS.md) y el [contrato MVP](docs/V3_SPEC.md) y su [addendum](docs/V3_ADDENDUM.md). Valida el paquete con `python3 -m unittest discover -s tests -v`.
