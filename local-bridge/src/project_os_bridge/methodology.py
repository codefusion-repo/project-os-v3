"""Read selected versioned documents from the installed canonical kit."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from .github_context import SENSITIVE
from .github_operational import _private_bytes, _unique_object

CANONICAL = "codefusion-repo/project-os-v3"
SHA = re.compile(r"[0-9a-f]{40}")
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WORKFLOW = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)*")
MAX_DOCUMENT = 64 * 1024
MAX_RESPONSE = 384 * 1024


def git(root, *args):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_NO_REPLACE_OBJECTS": "1",
           "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        result = subprocess.run(["git", "-C", str(root), "-c", "core.fsmonitor=false", *args],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=env, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("METHODOLOGY_UNAVAILABLE") from None
    if result.returncode:
        raise ValueError("METHODOLOGY_UNAVAILABLE")
    return result.stdout


def checkout(root, repository):
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise ValueError("METHODOLOGY_UNAVAILABLE")
    if git(root, "rev-parse", "--show-toplevel").decode().strip() != str(root):
        raise ValueError("METHODOLOGY_UNAVAILABLE")
    origin = git(root, "config", "--local", "--get", "remote.origin.url").decode().strip()
    allowed = {"https://github.com/" + repository, "https://github.com/" + repository + ".git",
               "git@github.com:" + repository, "git@github.com:" + repository + ".git"}
    if origin.casefold() not in {item.casefold() for item in allowed}:
        raise ValueError("METHODOLOGY_UNAVAILABLE")


def commit(root, revision):
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError("METHODOLOGY_UNAVAILABLE")
    if git(root, "rev-parse", "--verify", revision + "^{commit}").decode().strip() != revision:
        raise ValueError("METHODOLOGY_UNAVAILABLE")
    return revision


def document(root, repository, revision, path):
    entry = git(root, "ls-tree", "-z", revision, "--", path)
    match = re.fullmatch(rb"100(?:644|755) blob ([0-9a-f]{40})\t" + re.escape(path.encode()) + rb"\x00", entry)
    if match is None:
        raise ValueError("METHODOLOGY_DOCUMENT_UNAVAILABLE")
    blob = match.group(1).decode()
    size = int(git(root, "cat-file", "-s", blob))
    if not 0 <= size <= MAX_DOCUMENT:
        raise ValueError("METHODOLOGY_LIMIT")
    raw = git(root, "cat-file", "blob", blob)
    if len(raw) != size or hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest() != blob:
        raise ValueError("METHODOLOGY_INTEGRITY")
    return {"repository": repository, "revision": revision, "path": path,
            "blob_sha": blob, "content": raw.decode("utf-8")}


def selection(workflow, skills, templates):
    if (not isinstance(workflow, str) or len(workflow) > 80 or not WORKFLOW.fullmatch(workflow)
            or type(skills) is not list or type(templates) is not list
            or len(skills) > 12 or len(templates) > 14
            or any(not isinstance(n, str) or len(n) > 80 or not NAME.fullmatch(n)
                   for n in skills + templates)):
        raise ValueError("INVALID_METHODOLOGY_SELECTION")
    return ["PROJECT_OS.md", "workflows/" + workflow + ".md",
            *["skills/" + name + "/SKILL.md"
              for name in dict.fromkeys(["repo-context", "github-traceability", *skills])],
            *["templates/" + name + ".md" for name in dict.fromkeys(templates)],
            "adapters/browser-chat.md"]


def build_context(kit, installed, project_root, repository, workflow, skills, templates):
    paths = selection(workflow, skills, templates)
    checkout(kit, CANONICAL)
    installed = commit(kit, installed)
    if repository.casefold() == CANONICAL:
        version = installed
        agents = document(kit, CANONICAL, installed, "AGENTS.md")
    else:
        checkout(project_root, repository)
        head = commit(project_root, git(project_root, "rev-parse", "--verify", "HEAD").decode().strip())
        agents = document(project_root, repository, head, "AGENTS.md")
        if SENSITIVE.search(agents["content"]):
            raise ValueError("METHODOLOGY_DOCUMENT_UNAVAILABLE")
        markers = re.findall(r"(?im)^\s*(?:<!--\s*)?Project-OS-Version\s*:\s*(.*?)\s*$", agents["content"])
        refs = [marker.removesuffix("-->").strip().lower() for marker in markers]
        if (not refs or any(not SHA.fullmatch(ref) for ref in refs)
                or len(set(refs)) != 1 or CANONICAL not in agents["content"].lower()):
            raise ValueError("METHODOLOGY_VERSION_UNAVAILABLE")
        version = commit(kit, refs[0])
        git(kit, "merge-base", "--is-ancestor", version, installed)
    documents = [agents] + [document(kit, CANONICAL, version, path) for path in paths]
    result = {"complete": True, "methodology_revision": version,
              "installed_revision": installed, "documents": documents,
              "provenance": "local_reviewed_installation_git_objects"}
    if len(json.dumps(result, ensure_ascii=True).encode("ascii")) > MAX_RESPONSE:
        raise ValueError("METHODOLOGY_LIMIT")
    return result


def installed_context(project_config, repository, workflow, skills, templates):
    venv = Path(sys.prefix)
    if venv.name != ".venv" or venv.parent.name != "local-bridge":
        raise ValueError("METHODOLOGY_UNAVAILABLE")
    receipt = json.loads(_private_bytes(venv / ".project-os-bridge-install.json", 1024),
                         object_pairs_hook=_unique_object)
    if (not isinstance(receipt, dict) or set(receipt) != {"sha", "wheel_sha256"}
            or not isinstance(receipt["wheel_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", receipt["wheel_sha256"])):
        raise ValueError("METHODOLOGY_UNAVAILABLE")
    return build_context(venv.parents[1], receipt["sha"], project_config.parent.parent,
                         repository, workflow, skills, templates)
