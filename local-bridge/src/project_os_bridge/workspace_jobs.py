"""Durable preparation jobs for the dedicated disposable workspace profile.

Registered workspace preparation and direct WSL execution use the same durable queue.
"""
import os
import hashlib
import re
import json
import subprocess
import uuid

from .github_context import PROJECT
from .github_operational import _private_bytes, _unique_object, registry_entries
from .core import Policy
from .methodology import SHA
from .workspace_preflight import (_binding, binding_digest, materialize_workspace,
                                  prepare_workspace, normalize_changes, describe_changes, read_workspace_context, project_checkout)
from .workspace_profiles import PROFILES, profile_for, execution_route, QA_PROFILES, artifact_identity, CODEX_PROFILE
from .workos_auth import private_directory, private_file

MARKER = "local-workspace-mode"
RUNTIME = "workspace-runtime.json"


SUPERVISED_GRANTS = "workspace-grants.json"
SUPERVISED_EXECUTION = "workspace-execution.json"
PREPARATION_OPS = frozenset({"workspace_prepare", "workspace_materialize",
                             "workspace_change", "workspace_context", "workspace_dirty_context", "workspace_git_read", "workspace_git_fetch", *PROFILES, CODEX_PROFILE})
WORKSPACE_OPS = PREPARATION_OPS | {"workspace_execute", "workspace_delivery"}


class SupervisedWorkspacePolicy(Policy):
    """Explicit private grants; execution additionally requires the frozen local binding."""
    def __init__(self, verifier, base_grants):
        super().__init__(base_grants)
        self.verifier = verifier
        self.root = verifier.state_dir
        self.runtime = self.root.parent / "service" / "runtime.json"
        self.initial_entries = registry_entries(self.runtime)
        self.initial = self.current(startup=True)
        self.execution_binding = None
        self.backend = None

    def execution_available(self, project=None):
        if self.execution_binding is None or self.backend is None or not self.verifier.enabled():
            return False
        try:
            if _private_bytes(self.root / SUPERVISED_EXECUTION, 65536) != self.execution_binding:
                return False
            current = self.current()
            for alias, initial in self.initial.items():
                if project is not None and alias != project:
                    continue
                ops = initial & current.get(alias, frozenset())
                if {"workspace_prepare", "workspace_materialize", "workspace_execute"} <= ops:
                    if any(execution_route(profile, alias) in self.backend.routes
                           for profile in (*PROFILES, CODEX_PROFILE) if profile in ops):
                        return True
            return False
        except (OSError, ValueError, TypeError):
            return False

    def current(self, *, startup=False):
        try:
            data = json.loads(_private_bytes(self.root / SUPERVISED_GRANTS, 65536),
                              object_pairs_hook=_unique_object)
            entries = registry_entries(self.runtime)
            if (not isinstance(data, dict) or not data
                    or (startup and not set(data) <= set(entries))
                    or any(not PROJECT.fullmatch(key) for key in data)):
                raise ValueError("Invalid workspace grants")
            for ops in data.values():
                if (not isinstance(ops, list) or not ops
                        or not all(isinstance(op, str) for op in ops)
                        or len(set(ops)) != len(ops) or not set(ops) <= WORKSPACE_OPS):
                    raise ValueError("Invalid workspace grants")
            # A removed or retargeted alias denies only that project.
            return {key: frozenset(ops) for key, ops in data.items()
                    if key in entries and entries[key] == self.initial_entries.get(key)}
        except (OSError, ValueError, TypeError):
            raise PermissionError("WORKSPACE_GRANTS_UNAVAILABLE") from None

    def available(self):
        if not self.verifier.enabled():
            return False
        try:
            current = self.current()
            return any(ops & current.get(project, frozenset())
                       for project, ops in self.initial.items())
        except PermissionError:
            return False

    def require(self, principal, operation, resource):
        if resource == "workspace" or operation in WORKSPACE_OPS:
            if principal != self.verifier.subject or not self.verifier.enabled():
                raise PermissionError("DENIED")
            current = self.current()
            if resource == "workspace" and operation in {"submit", "read", "cancel"}:
                if any(ops & current.get(project, frozenset())
                       for project, ops in self.initial.items()):
                    return
            elif (operation in WORKSPACE_OPS and operation in self.initial.get(resource, ())
                  and operation in current.get(resource, ())
                  and (operation not in {"workspace_execute", "workspace_delivery"} or self.execution_available(resource))):
                return
            raise PermissionError("DENIED")
        super().require(principal, operation, resource)


def load_supervised_workspace_policy(verifier, base_grants, *, supervised, multi):
    if not os.path.lexists(verifier.state_dir / SUPERVISED_GRANTS):
        return None
    if (not supervised or not multi or verifier.state_dir.name != "state"
            or any(os.path.lexists(verifier.state_dir / name) for name in
                   (MARKER, "local-fixture-mode", "local-package-mode", "fixture-image", "fixture-context"))):
        raise PermissionError("Supervised preparation profile required")
    return SupervisedWorkspacePolicy(verifier, base_grants)


def load_supervised_workspace_backend(policy):
    """Load only the private direct WSL profile bindings; no legacy fallback."""
    from .execution import WorkspaceWSL
    from .android_qa import QASignerBinding
    if type(policy) is not SupervisedWorkspacePolicy:
        return None
    path = policy.root / SUPERVISED_EXECUTION
    if not os.path.lexists(path):
        return None
    raw = _private_bytes(path, 65536)
    data = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or not data or not set(data) <= set(policy.initial):
        raise ValueError("Invalid workspace execution bindings")
    toolchains, plans, signers = {}, {}, {}
    for project, profiles in data.items():
        if not isinstance(profiles, dict) or not profiles or not set(profiles) <= {*PROFILES, CODEX_PROFILE}:
            raise ValueError("Invalid workspace execution profiles")
        for profile, entry in profiles.items():
            fields = {"toolchain"} | ({"qa", "qa_signing"} if profile in QA_PROFILES else set())
            if (not isinstance(entry, dict) or set(entry) != fields
                    or not {"workspace_prepare", "workspace_materialize", "workspace_execute", profile}
                           <= policy.initial[project]):
                raise ValueError("Invalid workspace execution binding")
            route = execution_route(profile, project)
            toolchains[route] = entry["toolchain"]
            if profile in QA_PROFILES:
                plans[route] = entry["qa"]
                signers[route] = QASignerBinding(entry["qa_signing"])
    backend = WorkspaceWSL(toolchains, qa_plans=plans, qa_signers=signers)
    if _private_bytes(path, 65536) != raw:
        raise PermissionError("WORKSPACE_BINDING_CHANGED")
    policy.execution_binding, policy.backend = raw, backend
    return backend


def workspace_resource(policy):
    return "workspace" if type(policy) is SupervisedWorkspacePolicy else "disposable"


def local_runtime(root, policy=None):
    private_directory(root)
    if type(policy) is SupervisedWorkspacePolicy:
        if root != policy.root or not policy.available():
            raise PermissionError("Workspace opt-in unavailable")
        return policy.runtime
    try:
        marker = private_file(root / MARKER)
    except FileNotFoundError:
        raise PermissionError("Workspace opt-in unavailable") from None
    if (marker.st_size != 0 or any(os.path.lexists(root / name) for name in
            ("allow-authenticated-probe", "local-fixture-mode", "local-package-mode",
             "fixture-image", "fixture-context"))):
        raise PermissionError("Dedicated workspace state required")
    runtime = root / RUNTIME
    private_file(runtime)
    return runtime


def direct_operation(policy, principal, request, request_key):
    from .execution import command_steps
    if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_key):
        raise ValueError("INVALID_REQUEST_KEY")
    profile, project = request["profile"], request["project"]
    backend = policy.backend
    if backend is None:
        raise PermissionError("DENIED")
    route = backend.route(profile, project)
    plan = backend.qa_plans.get(route)
    signer = backend.qa_signers.get(route)
    identity, context = backend.binding(profile, project)
    if (request.get("execution_id") != identity or request.get("context_id") != context
            or request.get("qa_plan_sha256") != (plan.digest() if plan else None)
            or request.get("qa_signer_sha256") != (signer.digest if signer else None)):
        raise PermissionError("EXECUTION_BINDING_CHANGED")
    steps = command_steps(profile, plan)
    frozen = {k: v for k, v in request.items() if k != "operation_sha256"}
    digest = hashlib.sha256(json.dumps(
        ["supervised-direct-v1", principal, request_key, frozen, steps],
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    commands = [{"argv": ["--dart-define=[configured value]"
                            if arg.startswith("--dart-define=") else arg for arg in argv],
                 "cwd": relative} for argv, relative in steps]
    return {"operation_sha256": digest, "project": project, "expected_sha": request["expected_sha"],
            "profile": profile, "request_key": request_key, "commands": commands,
            "configuration_bound": plan is not None, "saved_changes": "changes" in request,
            "changes_sha256": hashlib.sha256(json.dumps(request["changes"], sort_keys=True,
                separators=(",", ":")).encode()).hexdigest() if "changes" in request else None,
            "delivery_pr": request.get("delivery_target", {}).get("pr"),
            "impact": "Registered tools run against a committed Job snapshot; may write generated files and caches."
                      + (" Includes signing and configured delivery." if request.get("delivery_target") else ""),
            "evidence": "Durable Job state, exit code, cleanup, revision and artifact identity when applicable."}


def authorize_request(policy, principal, request, *, execute=False, request_key=None, require_operation=False):
    fields = {"project", "profile", "expected_sha", "binding"}
    if execute:
        fields.update(("execution_id", "context_id"))
        if isinstance(request, dict) and request.get("profile") in QA_PROFILES:
            fields.add("qa_plan_sha256")
            if "qa_signer_sha256" in request or type(policy) is SupervisedWorkspacePolicy:
                fields.add("qa_signer_sha256")
    if isinstance(request, dict) and "operation_sha256" in request:
        fields.add("operation_sha256")
    if isinstance(request, dict) and "codex_task" in request:
        fields.add("codex_task")
    if isinstance(request, dict) and "changes" in request:
        fields.add("changes")
    if isinstance(request, dict) and "delivery_target" in request:
        fields.add("delivery_target")
    if (not isinstance(request, dict)
            or set(request) != fields
            or any(not isinstance(value, str) for key, value in request.items()
                   if key not in {"changes", "delivery_target", "codex_task"})
            or not PROJECT.fullmatch(request["project"])
            or not SHA.fullmatch(request["expected_sha"])
            or not re.fullmatch(r"[0-9a-f]{64}", request["binding"])):
        raise ValueError("INVALID_WORKSPACE_REQUEST")
    profile_for(request["profile"])
    project = request["project"]
    if request["profile"] == CODEX_PROFILE:
        from .codex_provider import validate_task
        if (not execute or type(policy) is not SupervisedWorkspacePolicy
                or "codex_task" not in request or "changes" in request or "delivery_target" in request):
            raise ValueError("INVALID_CODEX_TASK")
        validate_task(request["codex_task"])
    elif "codex_task" in request:
        raise ValueError("INVALID_CODEX_TASK")
    if "delivery_target" in request:
        target = request["delivery_target"]
        if (not execute or type(policy) is not SupervisedWorkspacePolicy
                or request["profile"] not in QA_PROFILES or "changes" in request
                or not isinstance(target, dict)
                or set(target) != {"project", "head", "pr", "repository_id", "binding_sha256"}
                or target["project"] != project or target["head"] != request["expected_sha"]
                or type(target["pr"]) is not int or not 0 < target["pr"] <= 2147483647
                or type(target["repository_id"]) is not int
                or target["repository_id"] != policy.initial_entries.get(project, {}).get("repository_id")
                or not isinstance(target["binding_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", target["binding_sha256"])):
            raise ValueError("QA_DELIVERY_TARGET_INVALID")
        if require_operation:
            policy.require(principal, "workspace_delivery", project)
    if "changes" in request:
        policy.require(principal, "workspace_change", project)
        if normalize_changes(request["changes"]) != request["changes"]:
            raise ValueError("INVALID_WORKSPACE_CHANGES")
    if execute:
        if (not re.fullmatch(r"[0-9a-f]{64}", request["execution_id"])
                or request["context_id"] != request["execution_id"]):
            raise ValueError("INVALID_EXECUTION_BINDING")
        if "context_id" in request and not re.fullmatch(r"[0-9a-f]{64}", request["context_id"]):
            raise ValueError("INVALID_EXECUTION_CONTEXT")
        if request["profile"] in QA_PROFILES and (not re.fullmatch(r"[0-9a-f]{64}", request["qa_plan_sha256"])
                or "context_id" not in request):
            raise ValueError("INVALID_QA_PLAN")
        if "qa_signer_sha256" in request and not re.fullmatch(r"[0-9a-f]{64}", request["qa_signer_sha256"]):
            raise ValueError("INVALID_QA_SIGNER")
        policy.require(principal, "workspace_execute", project)
    for op in ("workspace_prepare", "workspace_materialize", request["profile"]):
        policy.require(principal, op, project)
    direct = execute and type(policy) is SupervisedWorkspacePolicy and request["profile"] != CODEX_PROFILE
    if "operation_sha256" in request:
        if not direct or not re.fullmatch(r"[0-9a-f]{64}", request["operation_sha256"]):
            raise PermissionError("INVALID_OPERATION_BINDING")
        if request_key is not None and direct_operation(policy, principal, request, request_key)["operation_sha256"] != request["operation_sha256"]:
            raise PermissionError("OPERATION_CHANGED")
    elif direct and require_operation:
        raise PermissionError("OPERATION_APPROVAL_REQUIRED")


def browser_route(jobs, principal, project, expected_sha, task, request_key, *, authorize):
    """Advisory route, not a lease across Browser/GitHub operations."""
    from .worker import exclusive_worker, WorkerBusy
    from .codex_provider import require_checkout, validate_task
    validate_task(task)
    if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_key):
        raise ValueError("INVALID_REQUEST_KEY")
    blocked = {"executor": "blocked", "handoff_verified": False}
    try:
        with exclusive_worker(jobs):
            authorize()
            runtime = local_runtime(jobs.probe.root, jobs.policy)
            jobs.policy.require(principal, "submit", workspace_resource(jobs.policy))
            entry, root = project_checkout(runtime, jobs.policy, principal, project, expected_sha)
            binding = binding_digest(entry, root)
            with jobs.transaction() as conn:
                if conn.execute("SELECT 1 FROM jobs WHERE state IN ('QUEUED','RUNNING') LIMIT 1").fetchone():
                    return {**blocked, "reason": "ACTIVE_JOB"}
                if conn.execute("SELECT 1 FROM fixture_effects WHERE resolved_at IS NULL LIMIT 1").fetchone():
                    return {**blocked, "reason": "RECONCILIATION_REQUIRED"}
                if conn.execute("SELECT 1 FROM jobs WHERE principal=? AND resource=? AND request_key=?",
                                (principal, workspace_resource(jobs.policy), request_key)).fetchone():
                    return {**blocked, "reason": "EXISTING_REQUEST_RECONCILE"}
                observed = require_checkout(root, expected_sha, task["branch"])
                current_entry, current_root = project_checkout(runtime, jobs.policy, principal, project, expected_sha)
                if binding_digest(current_entry, current_root) != binding:
                    return {**blocked, "reason": "WORKSPACE_BINDING_CHANGED"}
                authorize()
            return {"executor": "browser", "reason": "DIRECT_ROUTE_OBSERVED",
                    "checkout": observed, "handoff_verified": True, "lease_held": False}
    except WorkerBusy:
        return {**blocked, "reason": "ACTIVE_WORKER"}
    except (OSError, ValueError, TypeError):
        return {**blocked, "reason": "HANDOFF_UNVERIFIED"}


def workspace_git_status(jobs, principal, project, expected_sha, *, authorize=lambda: None):
    """Observe the checkout and a bounded history while holding the worker fence."""
    from .worker import exclusive_worker
    from .codex_provider import checkout_state
    from .methodology import git
    with exclusive_worker(jobs):
        authorize()
        runtime = local_runtime(jobs.probe.root, jobs.policy)
        jobs.policy.require(principal, "workspace_git_read", project)
        entry, root = project_checkout(runtime, jobs.policy, principal, project, expected_sha)
        binding = binding_digest(entry, root)
        with jobs.transaction() as conn:
            if conn.execute("SELECT 1 FROM jobs WHERE state IN ('QUEUED','RUNNING') LIMIT 1").fetchone():
                raise ValueError("ACTIVE_JOB")
            if conn.execute("SELECT 1 FROM fixture_effects WHERE resolved_at IS NULL LIMIT 1").fetchone():
                raise ValueError("RECONCILIATION_REQUIRED")
            before = checkout_state(root)
            # Batch mode reports a missing object on stdout with exit status zero;
            # process failures must remain errors, not be mistaken for absence.
            object_info = git(root, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                              input_data=(expected_sha + "\n").encode("ascii")).decode("ascii").strip()
            if object_info == expected_sha + " missing":
                present = False
            elif object_info == expected_sha + " commit":
                present = True
            elif re.fullmatch(re.escape(expected_sha) + r" (?:tree|blob|tag)", object_info):
                present = False
            else:
                raise ValueError("WORKSPACE_GIT_OBJECT_INVALID")
            history = git(root, "log", "--format=%H", "-n", "20", before["head"]).decode("ascii").splitlines()
            if any(not SHA.fullmatch(item) for item in history):
                raise ValueError("WORKSPACE_GIT_HISTORY_INVALID")
            if checkout_state(root) != before:
                raise ValueError("WORKSPACE_CHECKOUT_CHANGED")
            current_entry, current_root = project_checkout(runtime, jobs.policy, principal, project, expected_sha)
            if binding_digest(current_entry, current_root) != binding:
                raise PermissionError("WORKSPACE_BINDING_CHANGED")
            jobs.policy.require(principal, "workspace_git_read", project)
            authorize()
            return {**before, "requested_sha": expected_sha, "sha_present": present,
                    "history": history, "repository_id": entry["repository_id"]}


def _run_git_network(*args, **kwargs):
    return subprocess.run(*args, **kwargs)


def workspace_git_fetch(jobs, principal, project, expected_sha, *, authorize=lambda: None):
    """Fetch origin once under the worker fence; retain uncertain effects for reconciliation."""
    from .worker import exclusive_worker
    from .codex_provider import checkout_state
    from .methodology import git
    from .core import now
    with exclusive_worker(jobs):
        authorize()
        runtime = local_runtime(jobs.probe.root, jobs.policy)
        jobs.policy.require(principal, "workspace_git_fetch", project)
        entry, root = project_checkout(runtime, jobs.policy, principal, project, expected_sha)
        binding = binding_digest(entry, root)
        before = checkout_state(root)
        def present():
            value = git(root, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                        input_data=(expected_sha + "\n").encode("ascii")).decode("ascii").strip()
            if value == expected_sha + " commit":
                return True
            if value == expected_sha + " missing" or re.fullmatch(re.escape(expected_sha) + r" (?:tree|blob|tag)", value):
                return False
            raise ValueError("WORKSPACE_GIT_OBJECT_INVALID")
        # Resolve Git URL rewrites before allowing the named remote to be contacted.
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1")
        resolved_result = _run_git_network(["git", "-C", str(root), "remote", "get-url", "--all", "origin"],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, env=env, timeout=5, check=True)
        resolved = resolved_result.stdout.decode("utf-8").splitlines()
        repository = entry["repository"]
        allowed = {("https://github.com/" + repository).casefold(),
                   ("https://github.com/" + repository + ".git").casefold(),
                   ("git@github.com:" + repository).casefold(),
                   ("git@github.com:" + repository + ".git").casefold()}
        if len(resolved) != 1 or resolved[0].casefold() not in allowed:
            raise ValueError("WORKSPACE_ORIGIN_INVALID")
        already_present = present()
        effect_id, token = uuid.uuid4().hex, uuid.uuid4().hex
        with jobs.transaction() as conn:
            if conn.execute("SELECT 1 FROM jobs WHERE state IN ('QUEUED','RUNNING') LIMIT 1").fetchone():
                raise ValueError("ACTIVE_JOB")
            if conn.execute("SELECT 1 FROM fixture_effects WHERE resolved_at IS NULL LIMIT 1").fetchone():
                raise ValueError("RECONCILIATION_REQUIRED")
            authorize()
            jobs.policy.require(principal, "workspace_git_fetch", project)
            if binding_digest(*project_checkout(runtime, jobs.policy, principal, project, expected_sha)) != binding:
                raise PermissionError("WORKSPACE_BINDING_CHANGED")
            if conn.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 10000:
                raise ValueError("JOB_STORAGE_LIMIT")
            stamp = now()
            conn.execute("INSERT INTO jobs(id,principal,resource,workflow,request_key,state,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                         (effect_id, principal, workspace_resource(jobs.policy), "workspace_git_fetch", effect_id, "RUNNING", stamp, stamp))
            jobs.event(conn, effect_id, "RUNNING")
            conn.execute("INSERT INTO fixture_effects(job_id,token,context_id) VALUES(?,?,?)", (effect_id, token, binding))
        # Never replay after an interruption or error: the durable effect remains pending.
        result = _run_git_network(["git", "-C", str(root), "-c", "core.fsmonitor=false", "-c", "remote.origin.uploadpack=git-upload-pack",
                                 "fetch", "--no-tags", "--no-write-fetch-head", "--no-recurse-submodules",
                                 "--no-auto-maintenance", "--no-write-commit-graph", "origin",
                                 "+refs/heads/*:refs/remotes/origin/*"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=env, timeout=120, check=False)
        if result.returncode:
            raise ValueError("WORKSPACE_FETCH_UNCERTAIN")
        after_present = present()
        if checkout_state(root) != before:
            raise ValueError("WORKSPACE_CHECKOUT_CHANGED")
        if binding_digest(*project_checkout(runtime, jobs.policy, principal, project, expected_sha)) != binding:
            raise PermissionError("WORKSPACE_BINDING_CHANGED")
        jobs.policy.require(principal, "workspace_git_fetch", project)
        authorize()
        with jobs.transaction() as conn:
            conn.execute("UPDATE fixture_effects SET resolved_at=? WHERE job_id=? AND token=? AND resolved_at IS NULL", (now(), effect_id, token))
            jobs.transition(conn, effect_id, "RUNNING", "SUCCEEDED")
        return {**before, "requested_sha": expected_sha, "sha_present_before": already_present,
                "sha_present": after_present, "repository_id": entry["repository_id"]}


def submit_workspace(jobs, principal, project, expected_sha, profile, request_key, *, authorize=lambda: None, backend=None, changes=None, delivery_target=None, codex_task=None, preview=False, operation_sha256=None):
    if (profile == CODEX_PROFILE) != (codex_task is not None):
        raise ValueError("INVALID_CODEX_TASK")
    runtime = local_runtime(jobs.probe.root, jobs.policy)
    jobs.policy.require(principal, "submit", workspace_resource(jobs.policy))
    jobs.policy.require(principal, "workspace_materialize", project)
    execution_id = None
    if backend is not None:
        jobs.policy.require(principal, "workspace_execute", project)
        jobs.policy.require(principal, profile, project)
        if type(jobs.policy) is SupervisedWorkspacePolicy and jobs.policy.backend is not backend:
            raise PermissionError("DENIED")
        from .execution import WorkspaceWSL
        if type(backend) is not WorkspaceWSL:
            raise ValueError("DIRECT_WSL_BACKEND_REQUIRED")
        execution_id, context_id = backend.binding(profile, project)
    else:
        context_id = None
    args = (runtime, jobs.policy, principal, project, expected_sha, profile)
    _, entry, root = _binding(*args)
    request = {"project": project, "profile": profile, "expected_sha": expected_sha,
               "binding": binding_digest(entry, root)}
    if codex_task is not None:
        request["codex_task"] = codex_task
    if changes is not None:
        jobs.policy.require(principal, "workspace_change", project)
        request["changes"] = normalize_changes(changes)
    execute = execution_id is not None
    if execute:
        request["execution_id"] = execution_id
        request["context_id"] = context_id
        if profile in QA_PROFILES:
            if backend is None:
                raise ValueError("QA_BACKEND_REQUIRED")
            request["qa_plan_sha256"] = backend.plan_digest(profile, project)
            signer = backend.qa_signers.get(backend.route(profile, project))
            if signer is not None:
                request["qa_signer_sha256"] = signer.digest
    if delivery_target is not None:
        jobs.policy.require(principal, "workspace_delivery", project)
        request["delivery_target"] = delivery_target
    authorize_request(jobs.policy, principal, request, execute=execute)
    # Admission checks the mapping and immutable commit before queueing.
    prepare_workspace(*args)
    local_runtime(jobs.probe.root, jobs.policy)
    _, current_entry, current_root = _binding(*args)
    if binding_digest(current_entry, current_root) != request["binding"]:
        raise PermissionError("WORKSPACE_BINDING_CHANGED")
    authorize()
    direct = execute and type(jobs.policy) is SupervisedWorkspacePolicy and profile != CODEX_PROFILE
    if direct:
        operation = direct_operation(jobs.policy, principal, request, request_key)
        if preview:
            return operation
        if operation_sha256 != operation["operation_sha256"]:
            raise PermissionError("OPERATION_APPROVAL_REQUIRED")
        request["operation_sha256"] = operation_sha256
    elif preview or operation_sha256 is not None:
        raise ValueError("OPERATION_PREVIEW_UNAVAILABLE")
    return jobs.submit(principal, workspace_resource(jobs.policy), "workspace_execute" if execute else "workspace_prepare",
                       request_key, workspace=request)


def require_workspace_job(jobs, principal, job_id, *, allow_execute=False):
    """Revalidate ownership and the frozen mapping before HTTP disclosure."""
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise PermissionError("DENIED")
    runtime = local_runtime(jobs.probe.root, jobs.policy)
    with jobs.transaction() as conn:
        row = conn.execute(
            "SELECT jobs.principal, jobs.resource, jobs.workflow, workspace_inputs.request "
            "FROM jobs JOIN workspace_inputs ON jobs.id=workspace_inputs.job_id "
            "WHERE jobs.id=?", (job_id,)).fetchone()
        allowed = {"workspace_prepare", "workspace_execute"} if allow_execute else {"workspace_prepare"}
        if (not row or row["principal"] != principal or row["workflow"] not in allowed
                or row["resource"] != workspace_resource(jobs.policy)):
            raise PermissionError("DENIED")
        request = json.loads(row["request"])
    jobs.policy.require(principal, "read", row["resource"])
    execute = row["workflow"] == "workspace_execute"
    if execute and "context_id" not in request:
        raise PermissionError("DENIED")
    authorize_request(jobs.policy, principal, request, execute=execute)
    _, entry, root = _binding(runtime, jobs.policy, principal, request["project"],
                              request["expected_sha"], request["profile"])
    if binding_digest(entry, root) != request["binding"]:
        raise PermissionError("DENIED")
    return request


def workspace_changes(jobs, principal, job_id, *, allow_execute=False):
    request = require_workspace_job(jobs, principal, job_id, allow_execute=allow_execute)
    evidence = jobs.evidence(principal, job_id)
    if ("changes" not in request or evidence["state"] not in {"SUCCEEDED", "FAILED"}
            or not isinstance(evidence["result"], dict)):
        raise ValueError("WORKSPACE_CHANGES_UNAVAILABLE")
    result = describe_changes(local_runtime(jobs.probe.root, jobs.policy), jobs.policy, principal,
                              request, evidence["result"])
    if require_workspace_job(jobs, principal, job_id, allow_execute=allow_execute) != request:
        raise PermissionError("DENIED")
    return result


def verified_qa_build_input(jobs, principal, job_id, *, expected_project, expected_sha):
    """Local finalizer input only: unfinalized bytes of an authorized successful build."""
    from .workspace_profiles import apk_path, read_apk_bytes
    request = require_workspace_job(jobs, principal, job_id, allow_execute=True)
    if (request["project"] != expected_project or request["expected_sha"] != expected_sha
            or request["profile"] not in QA_PROFILES or "qa_plan_sha256" not in request):
        raise PermissionError("DENIED")
    evidence = jobs.evidence(principal, job_id)
    result = evidence.get("result") or {}
    execution = result.get("execution") or {}
    if (evidence["state"] != "SUCCEEDED" or result.get("operation") != "execute"
            or result.get("head") != expected_sha or result.get("workspace_materialized") is not True
            or execution.get("cleanup_verified") is not True or execution.get("exit_code") != 0
            or execution.get("execution_id") != request.get("execution_id")
            or execution.get("workspace_sha256") != result.get("workspace_sha256")
            or execution.get("qa_plan_sha256") != request["qa_plan_sha256"]
            or execution.get("artifact_stage") != "unfinalized"
            or execution.get("qa_delivery_ready") is not False
            or any(effect["job_id"] == job_id for effect in jobs.pending_effects())):
        raise ValueError("QA_BUILD_EVIDENCE_UNAVAILABLE")
    path = apk_path(jobs.probe.root, job_id)
    info = private_file(path)
    raw = read_apk_bytes(path, (info.st_dev, info.st_ino))
    identity = artifact_identity("apk", "app-qa-unfinalized.apk", raw)
    if identity != execution.get("artifact"):
        raise ValueError("APK_ARTIFACT_IDENTITY_MISMATCH")
    if (require_workspace_job(jobs, principal, job_id, allow_execute=True) != request
            or jobs.evidence(principal, job_id) != evidence
            or any(effect["job_id"] == job_id for effect in jobs.pending_effects())):
        raise PermissionError("DENIED")
    return raw, identity


def workspace_context(jobs, principal, project, expected_sha, profile, paths, *, include_dirty=False):
    runtime = local_runtime(jobs.probe.root, jobs.policy)
    return read_workspace_context(runtime, jobs.policy, principal, project,
                                  expected_sha, profile, paths, include_dirty=include_dirty)




_WORKSPACE_ERROR_CODE = frozenset(["DENIED","EXECUTION_BINDING_CHANGED","EXECUTION_EVIDENCE_INVALID","INVALID_WORKSPACE_CHANGE","INVALID_WORKSPACE_CHANGES","INVALID_WORKSPACE_CONTEXT","INVALID_WORKSPACE_PROFILE","INVALID_WORKSPACE_REQUEST","LOCKFILE_UNAVAILABLE","PRIVATE_WORKSPACE_PATH","PROFILE_UNAVAILABLE","UNSUPPORTED_PROJECT_LAYOUT","UNSUPPORTED_WORKSPACE_PATH","WORKSPACE_BINDING_CHANGED","WORKSPACE_CHANGES_UNAVAILABLE","WORKSPACE_CHANGE_CONFLICT","WORKSPACE_CHANGE_LIMIT","WORKSPACE_CHANGE_NOOP","WORKSPACE_CHANGE_NOT_TEXT","WORKSPACE_CONTEXT_CHANGED","WORKSPACE_CONTEXT_HEAD_CHANGED","WORKSPACE_CONTEXT_LIMIT","WORKSPACE_CONTEXT_NOT_REGULAR","WORKSPACE_CONTEXT_NOT_TEXT","WORKSPACE_CONTEXT_UNAVAILABLE","WORKSPACE_DIFF_LIMIT","WORKSPACE_DIFF_LIMIT_OR_IDENTITY","WORKSPACE_GRANTS_UNAVAILABLE","WORKSPACE_INTEGRITY","WORKSPACE_LIMIT","WORKSPACE_MUST_BE_SEPARATE","WORKSPACE_PATH_COLLISION","WORKSPACE_TREE_UNAVAILABLE"])


def workspace_error_code(exc, fallback):
    # Only known fixed literals, never arbitrary exception text.
    value = exc.args[0] if len(exc.args) == 1 else None
    return value if type(value) is str and value in _WORKSPACE_ERROR_CODE else fallback


def run_workspace(jobs, row, *, executor=None):
    request = row["workspace"]
    result = {"operation": "prepare", "profile": request["profile"],
              "head": request["expected_sha"], "execution_available": False}
    if "operation_sha256" in request:
        result["operation_sha256"] = request["operation_sha256"]
    dispatched = False
    try:
        runtime = local_runtime(jobs.probe.root, jobs.policy)
        execute = row["workflow"] == "workspace_execute"
        authorize_request(jobs.policy, row["principal"], request, execute=execute,
                          request_key=row.get("request_key"), require_operation=True)
        if execute and executor is None:
            return "BLOCKED", {**result, "reason": "EXECUTION_BACKEND_UNAVAILABLE"}
        if request["profile"] == CODEX_PROFILE:
            from .codex_provider import require_checkout
            args = (runtime, jobs.policy, row["principal"], request["project"],
                    request["expected_sha"], request["profile"])
            snapshot = prepare_workspace(*args)
            _, entry, root = _binding(*args)
            if binding_digest(entry, root) != request["binding"]:
                raise PermissionError("WORKSPACE_BINDING_CHANGED")
            require_checkout(root, request["expected_sha"], request["codex_task"]["branch"])
            authorize_request(jobs.policy, row["principal"], request, execute=True)
            dispatched = True
            execution = executor(root, row, snapshot)
            verified = (execution.get("cleanup_verified") is True
                        and execution.get("effects_reconciled", True) is True
                        and execution.get("checkout_verified", True) is True
                        and execution.get("execution_id") == request["execution_id"])
            state = ("SUCCEEDED" if verified and execution.get("exit_code") == 0
                     and execution.get("executor") == "codex" else "BLOCKED")
            return state, {**result, **snapshot, "operation": "codex",
                           "execution_available": execution.get("started") is True,
                           "issue": request["codex_task"]["issue"], "pr": request["codex_task"]["pr"],
                           "reason": execution.get("reason"), "execution": execution}
        snapshot = materialize_workspace(runtime, jobs.policy, row["principal"], request["project"],
                                         request["expected_sha"], request["profile"],
                                         jobs.probe.root, row["id"], expected_binding=request["binding"], changes=request.get("changes"))
        local_runtime(jobs.probe.root, jobs.policy)
        if not execute:
            return "SUCCEEDED", {**result, **snapshot}
        authorize_request(jobs.policy, row["principal"], request, execute=True,
                          request_key=row.get("request_key"), require_operation=True)
        _, entry, root = _binding(runtime, jobs.policy, row["principal"], request["project"],
                                  request["expected_sha"], request["profile"])
        if binding_digest(entry, root) != request["binding"]:
            raise PermissionError("WORKSPACE_BINDING_CHANGED")
        # Only the registered direct backend.
        dispatched = True
        execution = executor(jobs.probe.root / ("workspace-" + row["id"]), row, snapshot)
        if "context_id" in request and (execution.get("cleanup_verified") is not True
                or execution.get("execution_id") != request.get("execution_id")):
            return "BLOCKED", {**result, **snapshot, "operation": "execute",
                               "reason": "CLEANUP_OR_EXECUTION_UNVERIFIED", "execution": execution}
        if type(execution.get("exit_code")) is not int:
            raise ValueError("EXECUTION_EVIDENCE_INVALID")
        return ("SUCCEEDED" if execution["exit_code"] == 0 else "FAILED",
                {**result, **snapshot, "operation": "execute", "execution_available": True,
                 "reason": None, "execution": execution})
    except (PermissionError, ValueError, FileExistsError, FileNotFoundError) as exc:
        if not dispatched and row.get("effect_context") is not None:
            result["execution"] = {"cleanup_verified": True, "execution_id": request["execution_id"],
                                   "started": False}
        return "BLOCKED", {**result, "reason": "WORKSPACE_PREFLIGHT_BLOCKED",
                           "error_code": workspace_error_code(exc, "WORKSPACE_PREFLIGHT_BLOCKED")}
    except (OSError, RuntimeError) as exc:
        if not dispatched and row.get("effect_context") is not None:
            result["execution"] = {"cleanup_verified": True, "execution_id": request["execution_id"],
                                   "started": False}
        return "FAILED", {**result, "reason": "WORKSPACE_PREPARATION_FAILED",
                          "error_code": workspace_error_code(exc, "WORKSPACE_PREPARATION_FAILED")}
