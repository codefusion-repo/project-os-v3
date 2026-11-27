"""Durable preparation jobs for the dedicated disposable workspace profile.

Not registered by the authenticated service. A trusted internal CI caller may
supply a fixed executor for a single disposable execution job.
"""
import os
import re
import json

from .github_context import PROJECT
from .github_operational import _private_bytes, _unique_object, registry_entries
from .core import Policy
from .methodology import SHA
from .workspace_preflight import (_binding, binding_digest, materialize_workspace,
                                  prepare_workspace, normalize_changes, describe_changes, read_workspace_context)
from .workspace_profiles import PROFILES, profile_for, execution_route, QA_PROFILES, artifact_identity
from .workos_auth import private_directory, private_file

MARKER = "local-workspace-mode"
RUNTIME = "workspace-runtime.json"


SUPERVISED_GRANTS = "workspace-grants.json"
SUPERVISED_EXECUTION = "workspace-execution.json"
PREPARATION_OPS = frozenset({"workspace_prepare", "workspace_materialize",
                             "workspace_change", "workspace_context", "workspace_dirty_context", *PROFILES})
WORKSPACE_OPS = PREPARATION_OPS | {"workspace_execute"}


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
                    if any(execution_route(profile, alias) in self.backend.images
                           for profile in PROFILES if profile in ops):
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
                  and (operation != "workspace_execute" or self.execution_available(resource))):
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
    """Register only operator-enrolled exact profile/context/image bindings.

    This loader validates identity and local admission, not image review or host
    certification. The local operator must complete those gates before creating
    the private configuration. No acquisition, import or grant is performed here.
    """
    from pathlib import Path
    from .podman_context import PodmanContext
    from .workspace_podman import WorkspacePodman
    if type(policy) is not SupervisedWorkspacePolicy:
        return None
    path = policy.root / SUPERVISED_EXECUTION
    if not os.path.lexists(path):
        return None
    raw = _private_bytes(path, 65536)
    data = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or not data or not set(data) <= set(policy.initial):
        raise ValueError("Invalid workspace execution bindings")
    contexts, images, expected, plans = {}, {}, {}, {}
    for project, profiles in data.items():
        if not isinstance(profiles, dict) or not profiles or not set(profiles) <= set(PROFILES):
            raise ValueError("Invalid workspace execution profiles")
        for profile, entry in profiles.items():
            fields = {"context", "context_id", "image"} | ({"qa"} if profile in QA_PROFILES else set())
            if (not isinstance(entry, dict) or set(entry) != fields
                    or not all(isinstance(entry[key], str) for key in ("context", "context_id", "image"))
                    or not re.fullmatch(r"[0-9a-f]{64}", entry["context_id"])
                    or not {"workspace_prepare", "workspace_materialize", "workspace_execute", profile}
                           <= policy.initial[project]):
                raise ValueError("Invalid workspace execution binding")
            key = execution_route(profile, project)
            context = PodmanContext(Path(entry["context"]))
            if context.identity(entry["context_id"]) != entry["context_id"]:
                raise PermissionError("WORKSPACE_CONTEXT_CHANGED")
            contexts[key], images[key], expected[key] = context, entry["image"], entry["context_id"]
            if profile in QA_PROFILES:
                plans[key] = entry["qa"]
    backend = WorkspacePodman(contexts, images, qa_plans=plans)
    for key, identity in expected.items():
        project, profile = key.split(":", 1)
        if backend.binding(profile, project)[1] != identity:
            raise PermissionError("WORKSPACE_CONTEXT_CHANGED")
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


def authorize_request(policy, principal, request, *, execute=False):
    fields = {"project", "profile", "expected_sha", "binding"}
    if execute:
        fields.add("image_id")
        if isinstance(request, dict) and "context_id" in request:
            fields.add("context_id")
        if isinstance(request, dict) and request.get("profile") in QA_PROFILES:
            fields.add("qa_plan_sha256")
    if isinstance(request, dict) and "changes" in request:
        fields.add("changes")
    if (not isinstance(request, dict)
            or set(request) != fields
            or any(not isinstance(value, str) for key, value in request.items() if key != "changes")
            or not PROJECT.fullmatch(request["project"])
            or not SHA.fullmatch(request["expected_sha"])
            or not re.fullmatch(r"[0-9a-f]{64}", request["binding"])):
        raise ValueError("INVALID_WORKSPACE_REQUEST")
    profile_for(request["profile"])
    project = request["project"]
    if "changes" in request:
        policy.require(principal, "workspace_change", project)
        if normalize_changes(request["changes"]) != request["changes"]:
            raise ValueError("INVALID_WORKSPACE_CHANGES")
    if execute:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", request["image_id"]):
            raise ValueError("INVALID_EXECUTION_IMAGE")
        if "context_id" in request and not re.fullmatch(r"[0-9a-f]{64}", request["context_id"]):
            raise ValueError("INVALID_EXECUTION_CONTEXT")
        if request["profile"] in QA_PROFILES and (not re.fullmatch(r"[0-9a-f]{64}", request["qa_plan_sha256"])
                or "context_id" not in request):
            raise ValueError("INVALID_QA_PLAN")
        policy.require(principal, "workspace_execute", project)
    for op in ("workspace_prepare", "workspace_materialize", request["profile"]):
        policy.require(principal, op, project)


def submit_workspace(jobs, principal, project, expected_sha, profile, request_key, *, image_id=None,
                     authorize=lambda: None, backend=None, changes=None):
    runtime = local_runtime(jobs.probe.root, jobs.policy)
    jobs.policy.require(principal, "submit", workspace_resource(jobs.policy))
    jobs.policy.require(principal, "workspace_materialize", project)
    if backend is not None:
        if image_id is not None:
            raise ValueError("Use backend-selected image only")
        jobs.policy.require(principal, "workspace_execute", project)
        jobs.policy.require(principal, profile, project)
        if type(jobs.policy) is SupervisedWorkspacePolicy and jobs.policy.backend is not backend:
            raise PermissionError("DENIED")
        image_id, context_id = backend.binding(profile, project)
    else:
        context_id = None
    args = (runtime, jobs.policy, principal, project, expected_sha, profile)
    _, entry, root = _binding(*args)
    request = {"project": project, "profile": profile, "expected_sha": expected_sha,
               "binding": binding_digest(entry, root)}
    if changes is not None:
        jobs.policy.require(principal, "workspace_change", project)
        request["changes"] = normalize_changes(changes)
    execute = image_id is not None
    if execute:
        request["image_id"] = image_id
        if context_id is not None:
            request["context_id"] = context_id
        if profile in QA_PROFILES:
            if backend is None:
                raise ValueError("QA_BACKEND_REQUIRED")
            request["qa_plan_sha256"] = backend.plan_digest(profile, project)
    authorize_request(jobs.policy, principal, request, execute=execute)
    # Admission checks the mapping and immutable commit before queueing.
    prepare_workspace(*args)
    local_runtime(jobs.probe.root, jobs.policy)
    _, current_entry, current_root = _binding(*args)
    if binding_digest(current_entry, current_root) != request["binding"]:
        raise PermissionError("WORKSPACE_BINDING_CHANGED")
    authorize()
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
    from .workspace_podman import apk_path, read_apk_bytes
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
            or execution.get("image_id") != request.get("image_id")
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


def run_workspace(jobs, row, *, executor=None):
    request = row["workspace"]
    result = {"operation": "prepare", "profile": request["profile"],
              "head": request["expected_sha"], "execution_available": False}
    try:
        runtime = local_runtime(jobs.probe.root, jobs.policy)
        execute = row["workflow"] == "workspace_execute"
        authorize_request(jobs.policy, row["principal"], request, execute=execute)
        if execute and executor is None:
            return "BLOCKED", {**result, "reason": "EXECUTION_BACKEND_UNAVAILABLE"}
        snapshot = materialize_workspace(runtime, jobs.policy, row["principal"], request["project"],
                                         request["expected_sha"], request["profile"],
                                         jobs.probe.root, row["id"], expected_binding=request["binding"], changes=request.get("changes"))
        local_runtime(jobs.probe.root, jobs.policy)
        if not execute:
            return "SUCCEEDED", {**result, **snapshot}
        authorize_request(jobs.policy, row["principal"], request, execute=True)
        _, entry, root = _binding(runtime, jobs.policy, row["principal"], request["project"],
                                  request["expected_sha"], request["profile"])
        if binding_digest(entry, root) != request["binding"]:
            raise PermissionError("WORKSPACE_BINDING_CHANGED")
        # Only the registered backend (or the pre-existing disposable CI test executor).
        execution = executor(jobs.probe.root / ("workspace-" + row["id"]), row, snapshot)
        if "context_id" in request and (execution.get("cleanup_verified") is not True
                or execution.get("image_id") != request["image_id"]):
            return "BLOCKED", {**result, **snapshot, "operation": "execute",
                               "reason": "CLEANUP_OR_EXECUTION_UNVERIFIED"}
        if type(execution.get("exit_code")) is not int:
            raise ValueError("EXECUTION_EVIDENCE_INVALID")
        return ("SUCCEEDED" if execution["exit_code"] == 0 else "FAILED",
                {**result, **snapshot, "operation": "execute", "execution_available": True,
                 "reason": None, "execution": execution})
    except (PermissionError, ValueError, FileExistsError, FileNotFoundError):
        return "BLOCKED", {**result, "reason": "WORKSPACE_PREFLIGHT_BLOCKED"}
    except (OSError, RuntimeError):
        return "FAILED", {**result, "reason": "WORKSPACE_PREPARATION_FAILED"}
