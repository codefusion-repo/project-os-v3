"""Single-repository, local opt-in and sanitized LB-06 audit."""
import json
import os
import re
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from .core import Policy
from .github import GitHubReader
from .github_context import GitHubContext, PROJECT
from .security import Audit
from .workos_auth import private_directory, private_file

FLAG = "allow-github-context"
PROJECT_CONFIG = ".project-os/config.json"
CONFIG_DIR = "github-context-gh"
AUDIT_NAME = "github-context-audit.jsonl"
MAX_BINDING = 64 * 1024
MAX_AUDIT = 1024 * 1024
OUTCOMES = frozenset({"admitted", "complete", "partial", "denied", "failed"})


def _private_bytes(path, limit):
    private_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        Audit._validate_info(info)
        if info.st_size > limit:
            raise ValueError("Invalid GitHub context binding")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        current = private_file(path)
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) or len(data) > limit:
            raise ValueError("GitHub context binding changed")
        return data
    finally:
        os.close(fd)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate binding key")
        result[key] = value
    return result


class GitHubContextAudit:
    """Local bounded sidecar; no payloads, paths or identities."""

    def __init__(self, root):
        private_directory(root)
        self.root = root
        self.lock = threading.Lock()

    def record(self, outcome):
        if outcome not in OUTCOMES:
            raise ValueError("Invalid audit outcome")
        data = (json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                            "event": "github_context", "outcome": outcome}) + "\n").encode()
        with self.lock:
            private_directory(self.root)
            fd, size = Audit._open(self.root / AUDIT_NAME, create=True)
            try:
                if size + len(data) > MAX_AUDIT:
                    raise OSError("GitHub context audit capacity reached")
                Audit._append(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)


def load_operational_provider(verifier, *, supervised, project_config=None):
    """Register only from explicit private binding with no active opt-in.

    Startup never grants repository access. The local operator may enable the
    separate marker only after the existing gates. Credential provenance and
    host gates are independent prerequisites, not established by this loader.
    """
    state = verifier.state_dir
    private_directory(state)
    flag = state / FLAG
    if os.path.lexists(flag):
        raise PermissionError("Revoke GitHub context before startup")
    if project_config is None:
        return None
    if supervised is not True:
        raise PermissionError("Supervised non-fixture HTTPS required")
    path = Path(project_config)
    if not path.is_absolute() or path.name != "config.json" or path.parent.name != ".project-os":
        raise ValueError("Canonical project configuration required")
    private_directory(path.parent)
    # Never read a tracked project configuration. Explicit local locator only.
    env = {"PATH": "/usr/bin:/bin", "HOME": str(state.parent), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"}
    def git(*args):
        return subprocess.run(["git", "-C", str(path.parent.parent), *args], env=env,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=5, check=False)
    try:
        tracked = git("ls-files", "--", ".project-os/")
        ignored = git("check-ignore", "--", PROJECT_CONFIG)
    except subprocess.TimeoutExpired:
        raise PermissionError("Project configuration exclusion could not be verified") from None
    if tracked.returncode != 0 or tracked.stdout or ignored.returncode != 0:
        raise PermissionError("Project configuration must be excluded from Git")
    def read_binding():
        data = json.loads(_private_bytes(path, MAX_BINDING), object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 2:
            raise ValueError("Invalid project configuration")
        config = data.get("github_context")
        if not isinstance(config, dict) or set(config) != {"project", "repository", "repository_id"}:
            raise ValueError("Invalid GitHub context binding")
        project, repo, repo_id = (config[key] for key in ("project", "repository", "repository_id"))
        repositories = data.get("repositories")
        if (not isinstance(repositories, list) or not all(isinstance(v, str) for v in repositories)
                or not isinstance(repo, str) or repo.casefold() not in {v.casefold() for v in repositories}
                or not isinstance(project, str) or not PROJECT.fullmatch(project)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
                or any(part in {".", ".."} for part in repo.split("/"))
                or type(repo_id) is not int or not 0 < repo_id <= 2**63 - 1):
            raise ValueError("Invalid GitHub context binding")
        return project, repo, repo_id

    project, repo, repo_id = read_binding()
    actor = verifier.subject
    config_dir = state.parent / CONFIG_DIR
    private_directory(config_dir)
    initial_dir = config_dir.stat()

    def authorize(principal, requested_project, repository):
        if (principal, requested_project, repository) != (actor, project, repo):
            return False
        try:
            private_directory(config_dir)
            current_dir = config_dir.stat()
            return (verifier.enabled() and (current_dir.st_dev, current_dir.st_ino) ==
                    (initial_dir.st_dev, initial_dir.st_ino)
                    and _private_bytes(flag, 0) == b""
                    and read_binding() == (project, repo, repo_id))
        except (OSError, ValueError):
            return False

    reader = GitHubReader(Policy([(actor, "github_read", project)]), {project: repo},
                          config_dir, repository_ids={project: repo_id})
    return GitHubContext(reader, authorize, audit=GitHubContextAudit(state))
