"""Internal LB-07 project/profile preflight; no executable backend is registered."""
from pathlib import Path
from types import MappingProxyType
import re

from .github_context import PROJECT
from .github_operational import registry_entries, read_project_binding
from .methodology import checkout, commit, git, SHA

# Fixed candidate commands for a future reviewed offline Flutter profile.
# Never pass these to a host subprocess. The current fixture image is NOT eligible.
FLUTTER_PROFILES = MappingProxyType({
    "flutter-analyze": ("flutter", "analyze", "--no-pub"),
    "flutter-test": ("flutter", "test", "--no-pub"),
    "flutter-apk-debug": ("flutter", "build", "apk", "--debug", "--no-pub"),
})


def prepare_flutter(runtime, policy, principal, project, expected_sha, profile):
    """Check the exact locally available revision and mapping without materializing code.

    The runtime locator and policy are supplied by trusted local code, not a tool
    caller. A read-only GitHub grant is not a preparation or execution grant.
    No fetch, checkout mutation, source content read or execution is performed.
    """
    if (not isinstance(project, str) or not PROJECT.fullmatch(project)
            or not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha)
            or not isinstance(profile, str) or profile not in FLUTTER_PROFILES):
        raise ValueError("INVALID_WORKSPACE_REQUEST")

    def authorize():
        policy.require(principal, "workspace_prepare", project)
        policy.require(principal, profile, project)

    def mapping():
        entry = registry_entries(runtime).get(project)
        if entry is None:
            raise PermissionError("DENIED")
        config = Path(entry["config"])
        expected = (project, entry["repository"], entry["repository_id"])
        if read_project_binding(config) != expected:
            raise PermissionError("DENIED")
        return entry, config.parent.parent

    authorize()
    entry, root = mapping()
    checkout(root, entry["repository"])
    sha = commit(root, expected_sha)
    tree = git(root, "rev-parse", "--verify", sha + "^{tree}").decode("ascii").strip()
    if not SHA.fullmatch(tree):
        raise ValueError("WORKSPACE_TREE_UNAVAILABLE")
    required = ["pubspec.yaml", "pubspec.lock"]
    if profile == "flutter-apk-debug":
        required.append("android/app/src/main/AndroidManifest.xml")
    # Fixed paths only, inspect modes and object identities; do not open blobs.
    entries = git(root, "ls-tree", "-z", sha, "--", *required)
    observed = {}
    for item in entries.split(b"\0"):
        if not item:
            continue
        match = re.fullmatch(rb"100(?:644|755) blob ([0-9a-f]{40})\t(.+)", item)
        if match is None:
            raise ValueError("UNSUPPORTED_PROJECT_LAYOUT")
        path = match.group(2).decode("utf-8")
        if path not in required or path in observed:
            raise ValueError("UNSUPPORTED_PROJECT_LAYOUT")
        observed[path] = match.group(1).decode("ascii")
    if set(observed) != set(required):
        raise ValueError("UNSUPPORTED_PROJECT_LAYOUT")
    authorize()
    if mapping() != (entry, root):
        raise PermissionError("DENIED")
    checkout(root, entry["repository"])
    return {"project": project, "repository_id": entry["repository_id"],
            "head": sha, "tree": tree, "profile": profile,
            "layout_checked": True, "workspace_materialized": False,
            "execution_available": False,
            "reason": "REVIEWED_FLUTTER_BACKEND_REQUIRED"}
