# MVP contract — one installation, one operator

Project OS is a Markdown-first coordination kit, not a SaaS, IDE or agent fleet. Browser Chat implements directly using authorized tools. GitHub Connector handles remote GitHub changes and evidence independently; Local Bridge handles bounded local jobs; neither grants permissions to the other. Terminal agents and Codex are optional. The approved target is adaptive execution; current MVP is browser-direct only.

## Approved adaptive execution architecture

The PM approved this direction on 2026-11-24. Browser Chat remains the orchestrator, reviewer and direct executor. Future strategies: auto (prefer authorized available Codex, otherwise browser), browser (direct), codex (explicitly authorized Codex). No extra user-facing menu or command family. A router is a small selection policy, not a second workflow engine. Quota exhaustion must be based on verified signals, not guessed from arbitrary error text. Before switching executors, reconcile issue/PR, branch and full HEAD, pending diffs, job state, tests and uncertain side effects. Never run both against the same worktree; stop if previous execution cannot be verified. Same policy and security gates apply to both. No automatic retry of uncertain effects. Codex provider and routing are deferred, not implemented or invoked in this MVP. Use GitHub Connector and registered Local Bridge handlers directly.

## User experience

Keep the existing selector and central installation. Two entrypoints (Linux/WSL shell and Windows PowerShell via WSL2) use one runtime. No new permanent menu or command family. First-run setup asks how the operator works (terminal, ChatGPT or both), reuses dependencies, and offers optional components with explicit approval. Existing installations are preserved. External OAuth consent and system changes remain operator-controlled. PowerShell and fully automated setup are deferred until the pilot; do not claim they exist.

## Capability boundary

- GitHub Connector: authorized reads, commits, PR and checks; explicit separate closeout authorization.
- Authenticated bridge: fixed probe, synthetic GitHub batch, job status/evidence/cancel; optional fixed Git/Podman fixture with local image binding. No remote commands, paths, image choice, arbitrary patches, real GitHub provider or device tools.
- SQLite stores owner, request key, workflow, resource, result and transitions. Replay returns the same job; interruption is not auto-retried.
- The operator's real repo work can proceed directly via GitHub Connector while local real-resource capability is blocked. Do not pretend a local test ran or use an agent fallback without authorization.

## Pilot sequence

1. Verify reviewed full SHA and both CI checks; stop existing bridge/tunnel before updating. Install in existing dedicated venv and run pip check and tests.
2. Run fixed local fixture against the already approved digest in a new private state; require SUCCEEDED, negative checks and cleanup evidence. Replay and retrieve evidence.
3. Restart authenticated HTTP using existing private state and the same approved digest only after local success. Reconnect existing tunnel, refresh tools; verify health, submit fixture, retrieve status/evidence, replay and restart persistence. Revoke local opt-in, verify authenticated 403 and no new job, restore explicitly. No tokens in logs.
4. Dogfood a bounded real issue through GitHub Connector directly. Local real resources stay disabled until all gates in SECURITY.md pass. Report unavailable local tests, do not route work to another agent automatically.

## Frozen scope

Complete disposable end-to-end path, security gates, traceability and minimal existing setup. No new infrastructure, central registry, collaborative RBAC, arbitrary shell, auto merge/deploy or additional UI. Android QA, production real-resource grants, complete dependency lock and independent install certification remain separate gates or deferred features; source licensing requires maintainer decision. A pilot is not a production release.
