# Skill: security-review

## Para qué sirve
Encontrar riesgos de seguridad relevantes para el cambio sin bloquear trabajo inocuo.

## Cuándo conviene
Web/API, auth, permisos, secretos, almacenamiento, dependencias, despliegues o datos sensibles.

## Entradas mínimas
Diff/arquitectura afectada y superficie de confianza.

## Procedimiento concreto
1. Identificar inputs, trust boundaries, roles, secretos y datos procesados por el cambio.
2. Revisar controles OWASP aplicables: validación, authz/authn, exposición, inyección, logging, dependencias y CSRF/SSRF si corresponde.
3. Priorizar hallazgos explotables o con impacto, con path/línea y escenario de riesgo.
4. Distinguir defectos de riesgos hipotéticos; proponer mitigación proporcional y test.
5. Elevar solo acciones sensibles y no incluir valores de secretos.

## Validación y salida
Hallazgos con severidad, evidencia, mitigaciones y áreas no inspeccionadas.

## Riesgos/limitaciones
Redactar valores como `[REDACTED]`; reportar únicamente path, variable y tipo de exposición.
