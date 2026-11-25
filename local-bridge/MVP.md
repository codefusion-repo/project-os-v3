# MVP contract — one installation, one operator

Project OS is a Markdown-first coordination kit, not a SaaS, IDE or agent fleet. Browser Chat implements directly using authorized tools. GitHub Connector handles remote GitHub changes and evidence independently; Local Bridge handles bounded local jobs; neither grants permissions to the other. The approved adaptive flow has two implementers: Codex running in the terminal, or ChatGPT Browser directly using Project OS v3 tools. Local Bridge is the controlled local-access tool; the terminal is an execution environment, not an implementer. Current MVP is browser-direct only.

## Methodology invariant

Local Bridge is an optional capability provider, not a replacement for the Project OS coordination methodology. All agents must preserve the versioned rules, workflows, skills, templates and adapters specified in [PROJECT_OS.md](../PROJECT_OS.md), regardless of execution provider. GitHub artifacts must use the applicable template and verified evidence; local job success does not waive review, authorization or closeout gates. No provider may silently change the pinned methodology version of an adopted repository.

## Approved adaptive execution architecture

The PM approved this direction on 2026-11-24 (LB-ARCH-20261124-29, [#8](https://github.com/codefusion-repo/project-os-v3/issues/8), [#18](https://github.com/codefusion-repo/project-os-v3/issues/18)). Browser Chat remains the orchestrator and reviewer, uses Project OS v3 tools for authorized terminal interaction, and is the direct implementer when Codex is unavailable or its quota is exhausted in auto mode. Codex runs in the terminal as implementer only with explicit authorization, verified availability and remaining capacity. Future strategies: auto (prefer eligible Codex, otherwise browser), browser (direct), codex (explicitly authorized Codex; no implicit fallback). No extra user-facing menu or command family. A router is a small selection policy, not a second workflow engine. Quota exhaustion must be based on verified signals, not guessed from arbitrary error text. Before switching executors, reconcile issue/PR, branch and full HEAD, pending diffs, job state, tests and uncertain side effects. Never run both against the same worktree; stop if previous execution cannot be verified. Same policy and security gates apply to both. No automatic retry of uncertain effects. Codex provider and routing are deferred, not implemented or invoked in this MVP. Use GitHub Connector and registered Local Bridge handlers directly.

## User experience

Keep the existing selector and central installation. Two entrypoints (Linux/WSL shell and Windows PowerShell via WSL2) use one runtime. No new permanent menu or command family. First-run setup asks how the operator works (terminal, ChatGPT or both), reuses dependencies, and offers optional components with explicit approval. Existing installations are preserved. LB-03 guides the operator to connect, configure and verify required Project OS tools using existing components, not a new UX architecture; independent host and OAuth certification is LB-05. See [#12](https://github.com/codefusion-repo/project-os-v3/issues/12) and [#14](https://github.com/codefusion-repo/project-os-v3/issues/14). External OAuth consent and system changes remain operator-controlled. The PowerShell wrapper and optional private HTTPS service preparation are implemented. LB-03 completed with real WSL2 CI and disposable rollback evidence ([closeout](https://github.com/codefusion-repo/project-os-v3/issues/12#issuecomment-7151195379)); independent host installation and supervised service certification remain LB-05; no automatic activation.

## Capability boundary

- GitHub Connector: authorized reads, commits, PR and checks; explicit separate closeout authorization.
- Authenticated bridge: fixed probe, synthetic GitHub batch, job status/evidence/cancel; optional fixed Git/Podman fixture with local image binding. No remote commands, paths, image choice, arbitrary patches, real GitHub provider or device tools.
- SQLite stores owner, request key, workflow, resource, result and transitions. Replay returns the same job; interruption is not auto-retried.
- The operator's real repo work can proceed directly via GitHub Connector while local real-resource capability is blocked. Do not pretend a local test ran or use an agent fallback without authorization.

## Pilot sequence

1. Verify the reviewed full SHA and applicable CI jobs; preserve the rejected original and its deterministic historical negative control plus fresh evidence; the exact fixture-only digest is CI-only, not local approval. See SECURITY.md for the ratified R49 policy. Follow WSL-VALIDATION.md for a fresh independent checkout and hash-verified installation. The installer refuses an existing venv; preserve the pilot and do not overwrite or migrate it.
2. Only after independent local rebuild/import and fresh audit of the exact digest under the separately authorized [OCI runbook](OCI-LOCAL-VALIDATION.md), obtain explicit local binding and fixture execution approval. CI-only acceptance is not local approval. Run the fixed fixture in new private state; require SUCCEEDED, negative checks and cleanup evidence; replay and retrieve evidence.
3. For the earlier pilot, restart authenticated HTTP using its existing private state and same approved digest only after local success; for independent validation use new private state and the HTTPS runbook. Reconnect existing tunnel, refresh tools; verify health, submit fixture, retrieve status/evidence, replay and restart persistence. Revoke local opt-in, verify authenticated 403 and no new job, restore explicitly. No tokens in logs.
4. Dogfood a bounded real issue through GitHub Connector directly. Local real resources stay disabled until all gates in SECURITY.md pass. Report unavailable local tests, do not route work to another agent automatically.

## Frozen scope

Complete disposable end-to-end path, security gates, traceability and minimal existing setup. No new infrastructure, central registry, collaborative RBAC, arbitrary shell, auto merge/deploy or additional UI. Android QA, production real-resource grants, lifecycle and independent install certification remain separate production gates; locked dependency evidence is integrated under LB-01, not host certification; source licensing requires maintainer decision. A pilot is not a production release.
