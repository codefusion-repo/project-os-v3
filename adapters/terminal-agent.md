# Adapter: agente de terminal

Si la sesión lo permite, inspecciona y edita el checkout, ejecuta comandos y consulta GitHub. Verifica repo, rama y cambios existentes antes de escribir; en un ciclo PR usa `work/*`, no `main`. Conserva cambios ajenos y respeta permisos del sandbox. Shell, Git o credenciales disponibles no autorizan por sí solos acciones remotas. Revisa visibilidad y alcance antes de publicar; reporta comandos, exit codes y estado observado. Aplica [PROJECT_OS.md](../PROJECT_OS.md).
