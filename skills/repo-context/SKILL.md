# Skill: repo-context

## Para qué sirve
Recuperar contexto técnico y estado vivo de un repositorio para empezar o retomar trabajo sin recapturar información.

## Cuándo conviene
Siempre que la tarea involucre un repositorio: cold start, continuidad, issue/PR o stack desconocido.

## Entradas mínimas
Repositorio o checkout accesible; locator primario solo ante ambigüedad material no resoluble. Si el experimento es expresamente local y descartable y no hay repo, omite inspección de repositorio y GitHub.

## Procedimiento concreto
1. Comprobar repo, branch y objetivo; leer instrucciones y archivos de entrada pertinentes. Hacer cold start completo solo si se necesita; al continuar, acotar la inspección a lo cambiado o relevante y no recorrer todo el árbol.
2. Inspeccionar issues, PRs, commits, diffs, checks, findings y blockers relevantes si GitHub está disponible; priorizar datos vivos al historial o resúmenes anteriores y no consultar todos los issues/PRs sin justificación.
3. Identificar stack, comandos de verificación y archivos de alcance por evidencia; distinguir incertidumbres secundarias.
4. Recuperar objetivo, estado, referencias, validación, blockers y siguiente paso seguro; pedir como máximo un locator primario solo ante ambigüedad material no resoluble.

## Validación y salida
Refs, archivos y comandos observados; siguiente acción y límites de acceso. No afirmar estado remoto si no fue consultado.

## Riesgos/limitaciones
No exponer configuración ni secretos. Leer solo lo necesario para la tarea.

## Adopción y contexto multirrepositorio
Leer el `AGENTS.md` principal y su `Project-OS-Version: <SHA>`; obtener instrucciones del repositorio canónico en esa referencia y verificar la integridad de los archivos efectivos. No usar HEAD modificado como si fuera el commit. La instalación del kit es central y no se copia a los proyectos.

Para repositorios equivalentes, aplicar el alcance, comprobaciones independientes y protección de relaciones privadas de [PROJECT_OS.md](../../PROJECT_OS.md#instalación-adopción-y-versión-del-proyecto). Recuperar relaciones desde documentación versionada accesible, no desde preferencias privadas inexistentes para el agente remoto.
