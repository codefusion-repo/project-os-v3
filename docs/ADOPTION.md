# Adopción en un proyecto existente

1. Inspecciona las instrucciones y convenciones del proyecto, rama y cambios existentes. Decide dónde alojar el kit; copia sus archivos sin copiar `.git` ni sobrescribir instrucciones propias. Si hay `AGENTS.md`, conserva su contenido y añade una referencia a `PROJECT_OS.md` del kit. Ajusta rutas relativas si el kit vive en un subdirectorio.
2. Da al agente acceso al proyecto y al kit. Comprueba que sus permisos y herramientas reales permitan las acciones deseadas; las reglas existentes y las instrucciones del usuario prevalecen. No incluyas secretos en prompts ni handoffs.
3. Desde la raíz del kit ejecuta `python3 -m unittest discover -s tests -v` y `python3 tools/select.py --list`. Indica el destino con `--output-dir` si corresponde y proporciona repo, objetivo y restricciones materiales. Previsualiza y guarda el prompt Markdown generado antes de entregarlo al agente.
4. Para un chat nuevo usa `python3 tools/select.py --workflow continue --objective "Retoma el issue 123 de ORGANIZACION/REPOSITORIO y consulta el PR y checks actuales"` y comprueba que el agente consulta fuentes vivas. Si no hay issue o acceso remoto, informa el límite y continúa con evidencia local.
5. Prueba `python3 tools/select.py --prototype --objective "Validar un filtro de tareas simuladas en ORGANIZACION/REPOSITORIO"` con una hipótesis y criterio observable: por ejemplo, filtrar una lista de tareas simuladas y demostrar el resultado. No hace falta issue/PR. Para review usa `python3 tools/select.py --workflow review --skill code-review --locator 123` y pide findings con ruta, impacto y evidencia. Los templates de comentarios, merge y cierre son recursos internos seleccionados a partir de los workflows y skills, sin preguntar al PM.
6. Para una tarea normal acuerda alcance y autorización; valida el diff, y usa un solo issue/PR si aporta valor y está permitido. Las correcciones de review siguen en el mismo PR. Publicar, mergear, cerrar o desplegar requiere la autorización aplicable.

Sin Python, pide al agente leer directamente `PROJECT_OS.md`, un archivo de `workflows/` y solo las skills pertinentes. Si se desea medir rendimiento frente a v2, selecciona después un piloto comparable y usa [dogfood](../templates/dogfood.md); la adopción del kit no constituye ese experimento.

## Comprobación de aceptación en uso real

Registra referencias, resultados observados y límites, sin abrir unidades ni comentarios solo para este ejercicio:

1. En un chat nuevo con acceso al proyecto, entrega únicamente el identificador del repo y pide continuar. Comprueba que consulte instrucciones, issues, PRs, commits, checks y blockers pertinentes en fuentes vivas, recupere el siguiente paso y solo pida un locator primario si hay ambigüedad material no resoluble.
2. En otra sesión o con otro agente, retoma la misma unidad. Comprueba que no repita preguntas respondibles desde evidencia y que reconstruya objetivo, estado, refs, validación, blockers y próxima acción. Si falta acceso, registra el límite en vez de simularlo.
3. Con una tarea real y autorización pertinente, verifica que implementación, review y corrección conserven el mismo issue y PR cuando existan, y que commits, diff, checks y findings queden vinculados por referencias reales.
4. Pide a terminal y browser chat el mismo resultado basado en las mismas fuentes; compara el formato compartido y los criterios de evidencia, teniendo en cuenta las capacidades disponibles en cada sesión.
5. Comprueba la selección interactiva de workflow y skills y copia el prompt resultante; repite por lectura directa de Markdown si corresponde.
6. En un escenario controlado, solicita trabajo seguro junto con una acción sensible sin autorizar. Verifica que el agente prepare y continúe lo permitido, y detenga solo la acción sin permiso. No ejecutes merge, cierre ni despliegue como parte de esta comprobación.

Estas son pruebas de comportamiento en sesiones reales, no una afirmación de que ya se hayan ejecutado ni una condición para crear reportes separados por paso.
