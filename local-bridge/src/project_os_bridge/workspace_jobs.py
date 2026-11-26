"""Durable preparation jobs for the dedicated disposable workspace profile.

Not registered by the authenticated service. A trusted internal CI caller may
supply a fixed executor for a single disposable execution job.
"""
import os
import re
import json

from .github_context import PROJECT
from .methodology import SHA
from .workspace_preflight import _binding, binding_digest, materialize_workspace, prepare_workspace
from .workspace_profiles import profile_for
from .workos_auth import private_directory, private_file

MARKER = "local-workspace-mode"
RUNTIME = "workspace-runtime.json"


def local_runtime(root):
    private_directory(root)
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
    if (not isinstance(request, dict)
            or set(request) != fields
            or any(not isinstance(value, str) for value in request.values())
            or not PROJECT.fullmatch(request["project"])
            or not SHA.fullmatch(request["expected_sha"])
            or not re.fullmatch(r"[0-9a-f]{64}", request["binding"])):
        raise ValueError("INVALID_WORKSPACE_REQUEST")
    profile_for(request["profile"])
    project = request["project"]
    if execute:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", request["image_id"]):
            raise ValueError("INVALID_EXECUTION_IMAGE")
        policy.require(principal, "workspace_execute", project)
    for op in ("workspace_prepare", "workspace_materialize", request["profile"]):
        policy.require(principal, op, project)


def submit_workspace(jobs, principal, project, expected_sha, profile, request_key, *, image_id=None,
                     authorize=lambda: None):
    runtime = local_runtime(jobs.probe.root)
    jobs.policy.require(principal, "submit", "disposable")
    jobs.policy.require(principal, "workspace_materialize", project)
    args = (runtime, jobs.policy, principal, project, expected_sha, profile)
    _, entry, root = _binding(*args)
    request = {"project": project, "profile": profile, "expected_sha": expected_sha,
               "binding": binding_digest(entry, root)}
    execute = image_id is not None
    if execute:
        request["image_id"] = image_id
    authorize_request(jobs.policy, principal, request, execute=execute)
    # Admission checks the mapping and immutable commit before queueing.
    prepare_workspace(*args)
    local_runtime(jobs.probe.root)
    _, current_entry, current_root = _binding(*args)
    if binding_digest(current_entry, current_root) != request["binding"]:
        raise PermissionError("WORKSPACE_BINDING_CHANGED")
    authorize()
    return jobs.submit(principal, "disposable", "workspace_execute" if execute else "workspace_prepare",
                       request_key, workspace=request)


def require_workspace_job(jobs, principal, job_id):
    """Revalidate ownership and the frozen mapping before HTTP disclosure."""
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise PermissionError("DENIED")
    runtime = local_runtime(jobs.probe.root)
    with jobs.transaction() as conn:
        row = conn.execute(
            "SELECT jobs.principal, jobs.workflow, workspace_inputs.request "
            "FROM jobs JOIN workspace_inputs ON jobs.id=workspace_inputs.job_id "
            "WHERE jobs.id=?", (job_id,)).fetchone()
        if not row or row["principal"] != principal or row["workflow"] != "workspace_prepare":
            raise PermissionError("DENIED")
        request = json.loads(row["request"])
    authorize_request(jobs.policy, principal, request)
    _, entry, root = _binding(runtime, jobs.policy, principal, request["project"],
                              request["expected_sha"], request["profile"])
    if binding_digest(entry, root) != request["binding"]:
        raise PermissionError("DENIED")


def run_workspace(jobs, row, *, executor=None):
    request = row["workspace"]
    result = {"operation": "prepare", "profile": request["profile"],
              "head": request["expected_sha"], "execution_available": False}
    try:
        runtime = local_runtime(jobs.probe.root)
        execute = row["workflow"] == "workspace_execute"
        authorize_request(jobs.policy, row["principal"], request, execute=execute)
        if execute and executor is None:
            return "BLOCKED", {**result, "reason": "EXECUTION_BACKEND_UNAVAILABLE"}
        snapshot = materialize_workspace(runtime, jobs.policy, row["principal"], request["project"],
                                         request["expected_sha"], request["profile"],
                                         jobs.probe.root, row["id"], expected_binding=request["binding"])
        local_runtime(jobs.probe.root)
        if not execute:
            return "SUCCEEDED", {**result, **snapshot}
        authorize_request(jobs.policy, row["principal"], request, execute=True)
        _, entry, root = _binding(runtime, jobs.policy, row["principal"], request["project"],
                                  request["expected_sha"], request["profile"])
        if binding_digest(entry, root) != request["binding"]:
            raise PermissionError("WORKSPACE_BINDING_CHANGED")
        # Trusted internal caller only; production service supplies no executor.
        execution = executor(jobs.probe.root / ("workspace-" + row["id"]), row, snapshot)
        if type(execution.get("exit_code")) is not int:
            raise ValueError("EXECUTION_EVIDENCE_INVALID")
        return ("SUCCEEDED" if execution["exit_code"] == 0 else "FAILED",
                {**result, **snapshot, "operation": "execute", "execution_available": True,
                 "reason": None, "execution": execution})
    except (PermissionError, ValueError, FileExistsError, FileNotFoundError):
        return "BLOCKED", {**result, "reason": "WORKSPACE_PREFLIGHT_BLOCKED"}
    except (OSError, RuntimeError):
        return "FAILED", {**result, "reason": "WORKSPACE_PREPARATION_FAILED"}
