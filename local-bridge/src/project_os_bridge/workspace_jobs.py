"""Durable preparation jobs for the dedicated disposable workspace profile.

Not registered by the authenticated service. No executable runner is enabled.
"""
import os
import re

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


def authorize_request(policy, principal, request):
    if (not isinstance(request, dict)
            or set(request) != {"project", "profile", "expected_sha", "binding"}
            or any(not isinstance(value, str) for value in request.values())
            or not PROJECT.fullmatch(request["project"])
            or not SHA.fullmatch(request["expected_sha"])
            or not re.fullmatch(r"[0-9a-f]{64}", request["binding"])):
        raise ValueError("INVALID_WORKSPACE_REQUEST")
    profile_for(request["profile"])
    project = request["project"]
    for op in ("workspace_prepare", "workspace_materialize", request["profile"]):
        policy.require(principal, op, project)


def submit_workspace(jobs, principal, project, expected_sha, profile, request_key):
    runtime = local_runtime(jobs.probe.root)
    jobs.policy.require(principal, "submit", "disposable")
    jobs.policy.require(principal, "workspace_materialize", project)
    args = (runtime, jobs.policy, principal, project, expected_sha, profile)
    _, entry, root = _binding(*args)
    request = {"project": project, "profile": profile, "expected_sha": expected_sha,
               "binding": binding_digest(entry, root)}
    authorize_request(jobs.policy, principal, request)
    # Admission checks the mapping and immutable commit before queueing.
    prepare_workspace(*args)
    return jobs.submit(principal, "disposable", "workspace_prepare", request_key, workspace=request)


def run_workspace(jobs, row):
    request = row["workspace"]
    result = {"operation": "prepare", "profile": request["profile"],
              "head": request["expected_sha"], "execution_available": False}
    try:
        runtime = local_runtime(jobs.probe.root)
        authorize_request(jobs.policy, row["principal"], request)
        snapshot = materialize_workspace(runtime, jobs.policy, row["principal"], request["project"],
                                         request["expected_sha"], request["profile"],
                                         jobs.probe.root, row["id"], expected_binding=request["binding"])
        local_runtime(jobs.probe.root)
        return "SUCCEEDED", {**result, **snapshot}
    except (PermissionError, ValueError, FileExistsError, FileNotFoundError):
        return "BLOCKED", {**result, "reason": "WORKSPACE_PREFLIGHT_BLOCKED"}
    except (OSError, RuntimeError):
        return "FAILED", {**result, "reason": "WORKSPACE_PREPARATION_FAILED"}
