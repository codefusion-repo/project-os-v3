"""Operator-only enrollment using the existing runtime and project configuration."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from .core import Policy
from .github import GitHubReader
from .github_context import PROJECT
from .github_operational import (
    CONFIG_DIR, FLAG, MAX_BINDING, _private_bytes, _unique_object,
    read_project_binding, read_runtime, validate_entries,
)
from .lifecycle import exclusive_lifecycle, prepared_unit, snapshot
from .maintenance_guard import require_no_installation
from .methodology import checkout
from .workos_auth import load_config, private_directory

PROFILE_MIGRATION = "profile-migration.json"
PROFILE_RESTORE = "profile-restore.json"


def repository_identity(root, repository):
    # Local operator selection only; the reader never inherits personal credentials.
    if (not isinstance(repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or any(part in {".", ".."} for part in repository.split("/"))):
        raise ValueError("Invalid repository")
    prepared_unit(root)
    require_no_installation(Path(sys.executable))
    private_directory(root / CONFIG_DIR)
    reader = GitHubReader(Policy([]), {}, root / CONFIG_DIR)
    result = reader._request("repos/" + repository)
    data = result.get("data")
    if (result.get("complete") is not True or not isinstance(data, dict)
            or type(data.get("id")) is not int or not 0 < data["id"] <= 2**63 - 1
            or not isinstance(data.get("full_name"), str)
            or data["full_name"].casefold() != repository.casefold()):
        raise PermissionError("Dedicated GitHub credential or repository identity unavailable")
    return data["id"]


def next_runtime(data, *, config=None, binding=None, revoke=None):
    """Pure plan: preserve unrelated settings; never silently replace an existing grant."""
    result = dict(data)
    migrate = "github_projects" not in result
    if migrate:
        if revoke is not None:
            raise ValueError("Multi-project profile not prepared")
        legacy = result.pop("project_config", None)
        if legacy is not None and legacy != str(config):
            raise PermissionError("Migrate the existing project first")
        entries = {}
    else:
        entries = dict(validate_entries(result["github_projects"]))
    if revoke is not None:
        if not isinstance(revoke, str) or not PROJECT.fullmatch(revoke):
            raise ValueError("Invalid project")
        entries.pop(revoke, None)
    else:
        project, repository, repository_id = binding
        entry = {"config": str(config), "repository": repository,
                 "repository_id": repository_id}
        if project in entries and entries[project] != entry:
            raise PermissionError("Revoke the previous binding before changing it")
        entries[project] = entry
    result["github_projects"] = validate_entries(entries)
    return result, migrate



def record_migration(root, before, binding, backup, receipt):
    """Persist legacy-profile evidence before the live profile can change."""
    if not os.path.lexists(backup):
        return
    private_directory(backup)
    transaction = json.loads(_private_bytes(backup / "transaction.json", 16384),
                             object_pairs_hook=_unique_object)
    if (transaction.get("phase") != "installed" or transaction.get("root") != str(root)
            or transaction.get("sha") != receipt.get("sha")
            or transaction.get("wheel") != receipt.get("wheel_sha256")
            or not isinstance(transaction.get("prior"), dict)
            or os.path.lexists(backup / PROFILE_RESTORE)):
        raise RuntimeError("Unreconciled maintenance backup")
    record = {"format": 1, "sha": transaction["sha"], "root": str(root),
              "before": before, "binding": list(binding)}
    path = backup / PROFILE_MIGRATION
    if os.path.lexists(path):
        if json.loads(_private_bytes(path, 128 * 1024), object_pairs_hook=_unique_object) != record:
            raise RuntimeError("Previous profile migration evidence differs")
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=backup, prefix=".profile-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((json.dumps(record, sort_keys=True) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        if os.path.lexists(path):
            raise RuntimeError("Migration evidence appeared")
        os.replace(temporary, path)
        fd = os.open(backup, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def update_runtime(root, *, config=None, revoke=None):
    if (config is None) == (revoke is None):
        raise ValueError("Choose exactly one enrollment operation")
    unit = prepared_unit(root)
    with exclusive_lifecycle():
        require_no_installation(Path(sys.executable))
        before = snapshot(unit)
        if (not before["linked"] or before["pending_job"]
                or before["active"] not in {"active", "inactive"}):
            raise RuntimeError("Stable prepared service required")
        runtime = root / "service" / "runtime.json"
        original = _private_bytes(runtime, MAX_BINDING)
        data = read_runtime(runtime)
        if json.loads(original, object_pairs_hook=_unique_object) != data:
            raise RuntimeError("Service configuration changed")
        if "github_projects" not in data:
            if (before["active"] != "inactive" or before["enabled"]
                    or os.path.lexists(root / "state" / FLAG)):
                raise RuntimeError("First profile migration requires the stopped disabled unit and revoked GitHub opt-in")
        binding = None
        if config is not None:
            binding = read_project_binding(config)
            checkout(config.parent.parent, binding[1])
            load_config(root / "oauth.json", root / "state")
            if repository_identity(root, binding[1]) != binding[2]:
                raise PermissionError("Repository identity changed")
        updated, migrated = next_runtime(data, config=config, binding=binding, revoke=revoke)
        payload = (json.dumps(updated, indent=2) + "\n").encode()
        if len(payload) > MAX_BINDING:
            raise ValueError("Service configuration capacity reached")
        if updated == data:
            return False, False
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=runtime.parent, prefix=".runtime-", delete=False) as stream:
                temp = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if (_private_bytes(runtime, MAX_BINDING) != original or snapshot(unit) != before
                    or (config is not None and read_project_binding(config) != binding)):
                raise RuntimeError("Configuration or lifecycle changed; no grant written")
            if migrated:
                venv = Path(sys.prefix)
                backup = venv.parent / ".venv-install.rollback"
                if os.path.lexists(backup):
                    receipt = json.loads(_private_bytes(venv / ".project-os-bridge-install.json", 1024),
                                         object_pairs_hook=_unique_object)
                    record_migration(root, data, binding, backup, receipt)
                if _private_bytes(runtime, MAX_BINDING) != original:
                    raise RuntimeError("Configuration changed after migration evidence")
            os.replace(temp, runtime)
            fd = os.open(runtime.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        return True, migrated
