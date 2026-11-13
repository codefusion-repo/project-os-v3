# Skill: repo-context

## Para qué sirve
Recuperar contexto técnico y estado vivo de un repositorio para empezar o retomar trabajo sin recapturar información.

## Cuándo conviene
Cold start, cambio de agente, petición que menciona issue/PR o stack desconocido.

## Entradas mínimas
Repositorio o checkout accesible; locator primario si no se deduce del contexto.

## Procedimiento concreto
1. Comprobar repo, branch y objetivo; leer README/AGENTS y archivos de entrada pertinentes, no recorrer todo el árbol.
2. Inspeccionar issues/PR/commits/checks relevantes si GitHub está disponible; priorizar datos vivos a resúmenes anteriores.
3. Identificar stack, comandos de verificación y archivos de alcance por evidencia; distinguir incertidumbres secundarias.
4. Proponer o ejecutar el próximo paso seguro sin exigir metadata inferible.

## Validación y salida
Refs, archivos y comandos observados; siguiente acción y límites de acceso. No afirmar estado remoto si no fue consultado.

## Riesgos/limitaciones
No exponer configuración ni secretos. Leer solo lo necesario para la tarea.
