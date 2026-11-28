"""Local-only read provider. Do not expose until trusted caller identity is verified."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from concurrent.futures import ThreadPoolExecutor

from .core import Policy
from .github_transport import _http_result, gh_request


class GitHubReadError(RuntimeError):
    """Fixed upstream error category; no raw response text."""


class GitHubReader:
    def __init__(self, policy: Policy, repositories: dict, config_dir: Path, *, repository_ids=None):
        self.policy = policy
        self.repositories = MappingProxyType(dict(repositories))
        self.config_dir = config_dir
        ids = dict(repository_ids or {})
        if repository_ids is not None and (set(ids) != set(repositories) or any(type(v) is not int or not 0 < v <= 2**63 - 1 for v in ids.values())):
            raise ValueError("Invalid repository identity binding")
        self.repository_ids = MappingProxyType(ids)
        if not config_dir.is_absolute() or config_dir.resolve(strict=True) != config_dir:
            raise ValueError("Dedicated canonical gh config required")
        st = config_dir.stat()
        if not config_dir.is_dir() or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise PermissionError("Private gh config required")

    def _repo(self, principal, project):
        self.policy.require(principal, "github_read", project)
        repo = self.repositories.get(project, "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or any(
            part in {".",".."} for part in repo.split("/")
        ):
            raise ValueError("Unknown repository")
        return repo

    def authorized_repository(self, principal, project):
        """Resolve an exact locally configured repository after policy evaluation."""
        return self._repo(principal, project)

    def _request(self, endpoint):
        return gh_request(self.config_dir, endpoint)

    def issue_context(self, principal, project, number, *, check_access=None):
        repo = self._repo(principal, project)
        if type(number) is not int or not 1 <= number <= 2_147_483_647:
            raise ValueError("Invalid issue number")
        self._verify_identity(principal, project, check_access)
        return self._issue_context(principal, project, number, check_access)

    def _authorized_request(self, principal, project, endpoint, check_access):
        self._repo(principal, project)
        if check_access is not None:
            check_access()
        result = self._request(endpoint)
        if check_access is not None:
            check_access()
        return result

    def _verify_identity(self, principal, project, check_access):
        expected = self.repository_ids.get(project)
        if expected is None:
            return
        repo = self._repo(principal, project)
        result = self._authorized_request(principal, project, f"repos/{repo}", check_access)
        if result.get("complete") is not True:
            raise GitHubReadError(result.get("error", "INVALID_RESPONSE"))
        data = result.get("data")
        if (not isinstance(data, dict) or type(data.get("id")) is not int
                or data["id"] != expected or not isinstance(data.get("full_name"), str)
                or not data["full_name"].isascii() or data["full_name"].lower() != repo.lower()):
            raise GitHubReadError("RESOURCE_MISMATCH")

    def _issue_context(self, principal, project, number, check_access):
        repo = self._repo(principal, project)

        def checked_request(endpoint):
            result = self._authorized_request(principal, project, endpoint, check_access)
            if result.get("error") == "GH_RATE_LIMIT":
                raise GitHubReadError("GH_RATE_LIMIT")
            return result

        prefix = f"repos/{repo}/issues/{number}"
        issue = checked_request(prefix)
        comments = []
        complete = issue["complete"] and isinstance(issue.get("data"), dict)
        if issue["complete"] and not complete:
            issue = {"complete": False, "error": "INVALID_RESPONSE"}
        # Bounded pagination; never silently imply exhaustive results.
        error = None
        for page in range(1, 6):
            result = checked_request(f"{prefix}/comments?per_page=100&page={page}")
            if not result["complete"] or not isinstance(result.get("data"), list):
                complete = False
                error = result.get("error","INVALID_RESPONSE")
                break
            candidate = comments + result["data"]
            if len(json.dumps(candidate, ensure_ascii=True).encode("ascii")) > 1_048_576:
                complete = False
                error = "AGGREGATE_LIMIT"
                break
            comments = candidate
            if len(result["data"]) < 100:
                break
        else:
            complete = False
            error = "PAGE_LIMIT"
        self._repo(principal, project)
        return {"complete":complete,"issue":issue,"comments":comments,"comments_error":error,
                "retrieved_at":datetime.now(timezone.utc).isoformat(),
                "source":"github.com","untrusted_content":True}

    def batch_issues(self, principal, project, numbers, *, check_access=None):
        self._repo(principal, project)
        if not isinstance(numbers,(list,tuple)) or not 1 <= len(numbers) <= 5:
            raise ValueError("Batch must contain 1–5 issues")
        if any(type(n) is not int or not 1 <= n <= 2_147_483_647 for n in numbers):
            raise ValueError("Invalid issue number")
        unique = list(dict.fromkeys(numbers))
        # For the operational binding, stop the batch on the first identity or
        # rate-limit failure rather than queueing more upstream requests.
        if project in self.repository_ids:
            self._verify_identity(principal, project, check_access)
            results = [self._issue_context(principal, project, n, check_access) for n in unique]
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda n: self.issue_context(principal,project,n, check_access=check_access),unique))
        self._repo(principal, project)
        return {"complete":all(x["complete"] for x in results),
                "issues":dict(zip(unique,results))}
