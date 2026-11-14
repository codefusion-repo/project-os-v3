# Skill: code-review

## Para qué sirve
Detectar defectos, regresiones y problemas de mantenibilidad mediante inspección real.

## Cuándo conviene
Review de PR, diff significativo o verificación posterior a corrección.

## Entradas mínimas
Base/head o archivos/diff, criterios, checks reales.

## Procedimiento concreto
1. Leer diff y el código final alrededor de áreas modificadas; inspeccionar tests y checks asociados.
2. Buscar fallos concretos de lógica, edge cases, auth, permisos, desempeño y DX/mantenibilidad.
3. Reproducir o fundamentar cada hallazgo con path/línea/escenario; evitar preferencias estilísticas como blockers.
4. Ordenar por severidad/impacto y separar bloqueante/no bloqueante.
5. Indicar decisión y limitaciones. Las correcciones vuelven al mismo PR.

## Validación y salida
`templates/review.md` como ayuda opcional; findings específicos y evidencia, nunca aprobación basada solo en informe.

## Riesgos/limitaciones
No divulgar secretos del diff ni etiquetar tests como pasados sin observar CI/comandos.
