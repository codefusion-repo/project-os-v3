# Skill: debug

## Para qué sirve
Aislar un fallo, proponer causa raíz respaldada y corregir con mínima regresión.

## Cuándo conviene
Error reproducible, CI fallido, regresión, crash o comportamiento inesperado.

## Entradas mínimas
Síntoma, entorno si se conoce y código/logs relevantes.

## Procedimiento concreto
1. Reproducir el síntoma o documentar por qué no fue posible.
2. Reducir superficie: inputs, trace, cambios recientes y ruta de ejecución.
3. Separar hechos de hipótesis; comprobar la causa probable mediante test o inspección concreta.
4. Introducir fix mínimo y un test de regresión cuando corresponda.
5. Reejecutar validación y reportar el estado real, sin declarar resolución no verificada.

## Validación y salida
Pasos de reproducción, causa confirmada/probable, diff, tests y límites.

## Riesgos/limitaciones
No manipular datos productivos ni desactivar controles para hacer pasar tests.
