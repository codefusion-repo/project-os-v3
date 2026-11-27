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
from .workspace_profiles import PROFILES, profile_for
from .workos_auth import private_directory, private_file

MARKER = "local-workspace-mode"
RUNTIME = "workspace-runtime.json"


SUPERVISED_GRANTS = "workspace-grants.json"
PREPARATION_OPS = frozenset({"workspace_prepare", "workspace_materialize",
                             "workspace_change", "workspace_context", *PROFILES})


class SupervisedWorkspacePolicy(Policy):
    """Explicit private preparation grants; live revocation, no execution grant."""
    def __init__(self, verifier, base_grants):
        super().__init__(base_grants)
        self.verifier = verifier
        self.root = verifier.state_dir
        self.runtime = self.root.parent / "service" / "runtime.json"
        self.initial_entries = registry_entries(self.runtime)
        self.initial = self.current(startup=True)

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
                        or len(set(ops)) != len(ops) or not set(ops) <= PREPARATION_OPS):
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
        if resource == "workspace" or operation in PREPARATION_OPS or operation == "workspace_execute":
            if principal != self.verifier.subject or not self.verifier.enabled():
                raise PermissionError("DENIED")
            current = self.current()
            if resource == "workspace" and operation in {"submit", "read", "cancel"}:
                if any(ops & current.get(project, frozenset())
                       for project, ops in self.initial.items()):
                    return
            elif (operation in PREPARATION_OPS and operation in self.initial.get(resource, ())
                  and operation in current.get(resource, ())):
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
        policy.require(principal, "workspace_execute", project)
    for op in ("workspace_prepare", "workspace_materialize", request["profile"]):
        policy.require(principal, op, project)


def submit_workspace(jobs, principal, project, expected_sha, profile, request_key, *, image_id=None,
                     authorize=lambda: None, backend=None, changes=None):
    if backend is not None:
        if image_id is not None:
            raise ValueError("Use backend-selected image only")
        image_id, context_id = backend.binding(profile)
    else:
        context_id = None
    runtime = local_runtime(jobs.probe.root, jobs.policy)
    jobs.policy.require(principal, "submit", workspace_resource(jobs.policy))
    jobs.policy.require(principal, "workspace_materialize", project)
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


def workspace_context(jobs, principal, project, expected_sha, profile, paths):
    runtime = local_runtime(jobs.probe.root, jobs.policy)
    return read_workspace_context(runtime, jobs.policy, principal, project,
                                  expected_sha, profile, paths)


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
        # Trusted internal caller only; production service supplies no executor.
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
