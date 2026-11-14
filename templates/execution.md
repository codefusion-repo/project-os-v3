# Ejecución — {{outcome}}

Resumir cambios, comandos ejecutados y resultados observados.

**Unidad viva:** {{issue_pr_commit_si_existen}}

## Entregado
{{cambios_con_rutas}}

## Comandos y validación real
| Comando | Exit code / resultado |
|---|---|
| {{comando}} | {{salida_relevante_sin_secretos}} |

## Riesgos y trabajo pendiente
{{pendientes_y_límites}}

**Trazabilidad remota:** {{sha_o_url_verificados_y_pr_checks_disponibles_o_trazabilidad_pendiente_con_bloqueo}}
**Comentario nuevo de ejecución:** {{url_verificada_o_borrador_pendiente_con_motivo}}

> Cuando exista unidad y esté autorizado publicar, crear una entrada nueva por ejecución material; incluir también intentos, bloqueos y validaciones fallidas. No editar entradas históricas.

> Un commit local sin push no acredita publicación; una consulta read-only no requiere commit.

> Nunca usar “tests pasaron” sin comandos, resultados o CI real.
