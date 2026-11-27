"""Internal workspace preparation from an authorized, locally available Git revision."""
from pathlib import Path
import hashlib
import json
import os
import re

from .github_context import PROJECT
from .github_operational import registry_entries, read_project_binding
from .methodology import checkout, commit, git, SHA
from .workspace_profiles import PROFILES, profile_for
from .workos_auth import private_directory

MAX_FILES = 2048
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024

# Transitional internal alias: the earlier slice has not been released.
FLUTTER_PROFILES = {name: profile.argv for name, profile in PROFILES.items()
                    if name.startswith("flutter-")}


def _binding(runtime, policy, principal, project, expected_sha, profile):
    descriptor = profile_for(profile)
    if (not isinstance(project, str) or not PROJECT.fullmatch(project)
            or not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha)):
        raise ValueError("INVALID_WORKSPACE_REQUEST")
    policy.require(principal, "workspace_prepare", project)
    policy.require(principal, profile, project)
    entry = registry_entries(runtime).get(project)
    if entry is None:
        raise PermissionError("DENIED")
    config = Path(entry["config"])
    if read_project_binding(config) != (project, entry["repository"], entry["repository_id"]):
        raise PermissionError("DENIED")
    root = config.parent.parent
    checkout(root, entry["repository"])
    return descriptor, entry, root


def binding_digest(entry, root):
    info = root.stat()
    return hashlib.sha256(json.dumps([entry, info.st_dev, info.st_ino], sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _entries(raw):
    for item in raw.split(b"\0"):
        if not item:
            continue
        match = re.fullmatch(rb"100(644|755) blob ([0-9a-f]{40})\t([^\0]+)", item)
        if match is None:
            raise ValueError("UNSUPPORTED_PROJECT_LAYOUT")
        yield match.group(3).decode("utf-8"), match.group(1).decode(), match.group(2).decode()


def prepare_workspace(runtime, policy, principal, project, expected_sha, profile):
    args = (runtime, policy, principal, project, expected_sha, profile)
    descriptor, entry, root = _binding(*args)
    sha = commit(root, expected_sha)
    tree = git(root, "rev-parse", "--verify", sha + "^{tree}").decode("ascii").strip()
    if not SHA.fullmatch(tree):
        raise ValueError("WORKSPACE_TREE_UNAVAILABLE")
    required = descriptor.required
    observed = [path for path, _, _ in _entries(git(root, "ls-tree", "-z", sha, "--", *required))]
    if len(observed) != len(required) or set(observed) != set(required):
        raise ValueError("UNSUPPORTED_PROJECT_LAYOUT")
    if _binding(*args) != (descriptor, entry, root):
        raise PermissionError("DENIED")
    return {"project": project, "repository_id": entry["repository_id"],
            "head": sha, "tree": tree, "profile": profile,
            "layout_checked": True, "workspace_materialized": False,
            "execution_available": False, "reason": "REVIEWED_PROFILE_BACKEND_REQUIRED"}


def prepare_flutter(runtime, policy, principal, project, expected_sha, profile):
    if profile not in FLUTTER_PROFILES:
        raise ValueError("INVALID_WORKSPACE_PROFILE")
    return prepare_workspace(runtime, policy, principal, project, expected_sha, profile)


def _safe_path(path):
    parts = path.split("/")
    if (len(path.encode("utf-8")) > 512 or len(parts) > 32
            or any(not part or part in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.@+ -]+", part)
                   or part.endswith((".", " ")) for part in parts)):
        raise ValueError("UNSUPPORTED_WORKSPACE_PATH")
    for part in parts:
        name = part.casefold()
        if (name in {".git", ".project-os", ".ssh", ".aws", ".gnupg", ".npmrc",
                     ".git-credentials", "credentials.json", "key.properties", "local.properties"}
                or name.startswith(".env") or name.endswith((".pem", ".key", ".p12", ".pfx",
                                                            ".jks", ".keystore", ".dump", ".sql.gz"))
                or "service-account" in name or "service_account" in name):
            raise PermissionError("PRIVATE_WORKSPACE_PATH")
    return parts


def normalize_changes(changes):
    """Bounded text edits; exact old-byte digest or explicit absence."""
    if not isinstance(changes, list) or not 1 <= len(changes) <= 16:
        raise ValueError("INVALID_WORKSPACE_CHANGES")
    seen = set()
    for item in changes:
        if not isinstance(item, dict) or set(item) != {"path", "before", "text"}:
            raise ValueError("INVALID_WORKSPACE_CHANGE")
        path, before, text = item["path"], item["before"], item["text"]
        if (not isinstance(path, str) or path.casefold() in seen
                or (before is not None and (not isinstance(before, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", before)))
                or (text is not None and (not isinstance(text, str) or "\x00" in text))
                or (before is None and text is None)):
            raise ValueError("INVALID_WORKSPACE_CHANGE")
        _safe_path(path)
        seen.add(path.casefold())
        if text is not None:
            text.encode("utf-8")
    ordered = sorted(changes, key=lambda item: item["path"])
    if len(json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode()) > 32768:
        raise ValueError("WORKSPACE_CHANGE_LIMIT")
    return ordered


def changes_digest(changes):
    return hashlib.sha256(json.dumps(normalize_changes(changes), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _blob_data(root, blob, size):
    data = git(root, "cat-file", "blob", blob)
    if len(data) != size or hashlib.sha1(b"blob " + str(size).encode() + b"\0" + data).hexdigest() != blob:
        raise ValueError("WORKSPACE_INTEGRITY")
    return data


def _plan(entries):
    total, names, directories = 0, set(), {}
    for path, (mode, blob, size, data) in entries.items():
        parts = _safe_path(path)
        folded = path.casefold()
        if folded in names or folded in directories:
            raise ValueError("WORKSPACE_PATH_COLLISION")
        for index in range(1, len(parts)):
            directory = "/".join(parts[:index])
            key = directory.casefold()
            if key in names or (key in directories and directories[key] != directory):
                raise ValueError("WORKSPACE_PATH_COLLISION")
            directories[key] = directory
        names.add(folded)
        total += size
        if not 0 <= size <= MAX_FILE or total > MAX_TOTAL:
            raise ValueError("WORKSPACE_LIMIT")
    if not entries or len(entries) > MAX_FILES:
        raise ValueError("WORKSPACE_LIMIT")
    return total


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def materialize_workspace(runtime, policy, principal, project, expected_sha, profile,
                          private_parent, job_id, *, expected_binding=None, changes=None):
    """Internal local-only materialization; caller holds the existing worker lock.

    The parent and job id are trusted local locators, not MCP inputs. No checkout,
    hooks, archive filters, submodules or symlinks. Partial output stays private
    and cannot be reused; this function does not dispatch any project command.
    """
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("INVALID_JOB_ID")
    private_directory(private_parent)
    args = (runtime, policy, principal, project, expected_sha, profile)
    policy.require(principal, "workspace_materialize", project)
    if changes is not None:
        policy.require(principal, "workspace_change", project)
        changes = normalize_changes(changes)
    descriptor, entry, root = _binding(*args)
    binding = binding_digest(entry, root)
    if expected_binding is not None and expected_binding != binding:
        raise PermissionError("WORKSPACE_BINDING_CHANGED")
    if private_parent == root or root in private_parent.parents or private_parent in root.parents:
        raise PermissionError("WORKSPACE_MUST_BE_SEPARATE")
    result = prepare_workspace(*args)
    if (_binding(*args) != (descriptor, entry, root)
            or binding_digest(entry, root) != binding):
        raise PermissionError("DENIED")
    # Validate metadata and limits for every file before reading any blobs.
    raw = git(root, "ls-tree", "-r", "-z", result["tree"])
    if len(raw) > MAX_FILES * 640:
        raise ValueError("WORKSPACE_LIMIT")
    entries = list(_entries(raw))
    if not entries or len(entries) > MAX_FILES:
        raise ValueError("WORKSPACE_LIMIT")
    planned = {}
    for path, mode, blob in entries:
        if path in planned:
            raise ValueError("WORKSPACE_PATH_COLLISION")
        planned[path] = (mode, blob, int(git(root, "cat-file", "-s", blob)), None)
    _plan(planned)
    edits = []
    if changes is not None:
        for change in changes:
            path, before, text = change["path"], change["before"], change["text"]
            original = planned.get(path)
            if (original is None) != (before is None):
                raise ValueError("WORKSPACE_CHANGE_CONFLICT")
            mode = "644"
            if original is not None:
                mode, blob, size, _ = original
                old = _blob_data(root, blob, size)
                old.decode("utf-8")
                if hashlib.sha256(old).hexdigest() != before:
                    raise ValueError("WORKSPACE_CHANGE_CONFLICT")
            if text is None:
                del planned[path]
                after = None
            else:
                data = text.encode("utf-8")
                after = hashlib.sha256(data).hexdigest()
                if after == before:
                    raise ValueError("WORKSPACE_CHANGE_NOOP")
                planned[path] = (mode, None, len(data), data)
            edits.append({"path": path, "before": before, "after": after})
        if not set(descriptor.required) <= planned.keys():
            raise ValueError("UNSUPPORTED_PROJECT_LAYOUT")
    total = _plan(planned)
    policy.require(principal, "workspace_materialize", project)
    if (_binding(*args) != (descriptor, entry, root)
            or binding_digest(entry, root) != binding):
        raise PermissionError("DENIED")
    target = private_parent / ("workspace-" + job_id)
    stage = private_parent / ("pending-workspace-" + job_id)
    if os.path.lexists(target):
        raise FileExistsError("Workspace already exists")
    stage.mkdir(mode=0o700)
    manifest = []
    for path, (mode, blob, size, data) in sorted(planned.items()):
        if data is None:
            data = _blob_data(root, blob, size)
        dest = stage.joinpath(*_safe_path(path))
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o700 if mode == "755" else 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        manifest.append([path, mode, hashlib.sha256(data).hexdigest(), size])
    policy.require(principal, "workspace_materialize", project)
    if (_binding(*args) != (descriptor, entry, root)
            or binding_digest(entry, root) != binding):
        raise PermissionError("DENIED")
    if changes is not None:
        policy.require(principal, "workspace_change", project)
    # Only complete snapshots are adopted at the final job-owned name.
    # Existing worker exclusivity protects this private parent.
    for directory, _, _ in os.walk(stage, topdown=False):
        _sync_directory(directory)
    if os.path.lexists(target):
        raise FileExistsError("Workspace already exists")
    os.rename(stage, target)
    _sync_directory(private_parent)
    if changes is not None:
        result.update(changes_sha256=changes_digest(changes), changes=edits)
    result.update(workspace_materialized=True, files=len(manifest), bytes=total,
                  workspace_sha256=hashlib.sha256(json.dumps(manifest, separators=(",", ":"),
                                                           ensure_ascii=True).encode()).hexdigest())
    return result
