# Skill: testing

## Para qué sirve
Escoger y ejecutar validaciones proporcionales al riesgo del cambio.

## Cuándo conviene
Antes de entregar feature, fix, prototipo, review o release.

## Entradas mínimas
Diff/resultado, stack y comandos disponibles.

## Procedimiento concreto
1. Identificar los caminos cambiados y los fallos relevantes (happy path, bordes, permisos y regresiones).
2. Usar pruebas existentes; añadir pruebas focalizadas si el comportamiento nuevo lo requiere.
3. Ejecutar comandos realmente disponibles, capturando exit code y errores sin secretos.
4. Diferenciar ejecutado, observado, no ejecutado y no disponible.
5. Resumir confianza y cobertura limitada sin inventar porcentajes.

## Validación y salida
Comando/check, resultado real, fallas, huecos y próximo test útil.

## Riesgos/limitaciones
No ejecutar suites destructivas contra producción ni exponer fixtures sensibles.
