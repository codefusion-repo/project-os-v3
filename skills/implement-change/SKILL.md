# Skill: implement-change

## Para qué sirve
Implementar una unidad cohesiva con cambios pequeños, pruebas útiles y diff revisable.

## Cuándo conviene
Features normales, refactors acotados, tareas sobre issue/PR existente.

## Entradas mínimas
Outcome, criterios de aceptación y repo/archivos pertinentes.

## Procedimiento concreto
1. Verificar rama, cambios ajenos, referencias y alcance autorizado; revisar convenciones existentes.
2. Elegir la solución reversible más simple que cubra criterios; señalar solo trade-offs materiales.
3. Editar la superficie mínima; no mezclar refactors no solicitados ni secretos.
4. Ejecutar tests/lint/build pertinentes y revisar diff para detectar regresiones.
5. La solicitud de implementación autoriza commit y push de los cambios propios y actualización del **mismo** PR o creación de uno draft, salvo restricciones superiores o instrucciones contrarias; ejecutarlos con capacidad y documentar evidencia real.

## Validación y salida
Rutas, diff/commit, comandos y resultados, defectos y pendientes.

## Riesgos/limitaciones
No escribir en main durante flujo PR ni asumir permiso remoto por tener credenciales locales.
