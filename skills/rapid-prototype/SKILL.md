# Skill: rapid-prototype

## Para qué sirve
Transformar una idea en un prototipo funcional mínimo que permita validar una hipótesis rápidamente.

## Cuándo conviene
PoC, spike, exploración de UX, validación de integración o un flujo nuevo de punta a punta.

## Entradas mínimas
Problema, usuario/uso esperado y criterio observable de éxito; deducir tecnología del repo si existe.

## Procedimiento concreto
1. Formular la hipótesis y seleccionar una sola ruta vertical de uso (entrada → lógica → salida visible).
2. Reusar stack, componentes y convenciones existentes; evitar capas, abstracciones y servicios nuevos sin necesidad.
3. Construir el slice mínimo ejecutable con datos simulados seguros cuando corresponda; separar explícitamente el mock de producción.
4. Ejecutar la comprobación más corta que realmente demuestre el flujo (demo, test, comando o captura con evidencia).
5. Entregar resultado, límite, deuda asumida y decisión siguiente: descartar, iterar o endurecer para producción.

## Validación y salida
Demo/comando, archivos, resultado observado y riesgos. Usar `templates/prototype.md` solo si mejora el handoff.

## Riesgos/limitaciones
No confundir PoC con feature productiva; no usar secretos/credenciales reales ni introducir bypass de auth o datos sensibles.
