# Validación del MVP

Resultados observados durante la implementación local:

| Comando | Exit code | Resultado |
|---|---:|---|
| `python3 -m unittest discover -s tests -v` | 0 | 13 tests: selector, interacción, composición de skills y templates, errores, locator, discovery, symlinks externos, estructura, enlaces y referencia común de formatos en ambos adapters. |
| `python3 tools/select.py --prototype` | 0 | Prompt con `workflows/implement.md` y `skills/rapid-prototype/SKILL.md`. |
| `python3 tools/select.py --workflow review --locator 123` | 0 | Prompt de review con locator contextual. |
| `python3 tools/select.py --list` | 0 | Seis workflows, nueve skills y catorce templates descubiertos. |
| `python3 tools/select.py --workflow review --skill github-traceability --template review-comment --locator 123` | 0 | Prompt con workflow, skill y template de review. |
| `python3 tools/select.py --workflow close --template merge --template close` | 0 | Prompt con ambos templates de cierre. |
| `gh repo view codefusion-repo/project-os-v3 --json nameWithOwner,visibility,url` | 0 | GitHub reportó `PUBLIC`; el addendum autoriza este desarrollo público. |

Las comprobaciones automatizadas no sustituyen una prueba en un proyecto real. El dogfood de rendimiento, comparación con v2 y validación de continuidad entre agentes quedan para el piloto posterior; no se han ejecutado.

## Evidencia adicional de fuentes vivas

- `gh repo view codefusion-repo/project-os-v3 --json nameWithOwner,visibility,defaultBranchRef,url` — exit 0: repositorio público y rama predeterminada `main`.
- `gh pr list --repo codefusion-repo/project-os-v3 --state open --json number,title,isDraft,headRefName,url` — exit 0: se observó el draft PR #1 en `work/project-os-v3-mvp`.
- `gh issue list --repo codefusion-repo/project-os-v3 --state open --json number,title,url` — exit 0: no se observaron issues abiertos.
- `gh pr view 1 --repo codefusion-repo/project-os-v3 --json title,headRefOid,commits,reviews,statusCheckRollup,url` — exit 0: se observaron los commits de la unidad; no había reviews ni checks reportados al consultar. La consulta precedió al commit de estas garantías.
- `python3 tools/select.py --workflow continue` — exit 0: prompt de cold start copiable.

Estas consultas verifican acceso a fuentes reales desde esta sesión, no prueban un chat nuevo ni otro agente. Los escenarios de aceptación de continuidad, comparación entre superficies y detención de acción sensible en una sesión real siguen sin ejecutar.
