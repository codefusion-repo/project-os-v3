"""Local-only read provider. Do not expose until trusted caller identity is verified."""
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from concurrent.futures import ThreadPoolExecutor

from .core import Policy


class GitHubReadError(RuntimeError):
    """Fixed upstream error category; no raw response text."""


def _http_result(raw, exit_code):
    """Classify bounded gh --include output without returning headers."""
    head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep:
        head, sep, body = raw.partition(b"\n\n")
    lines = head.splitlines()
    status = re.fullmatch(rb"HTTP/\d(?:\.\d)? ([1-5]\d\d)(?: [^\r\n]*)?", lines[0]) if lines else None
    if not sep or status is None:
        return {"complete": False, "error": "GH_FAILED_OR_TIMEOUT" if exit_code else "INVALID_RESPONSE"}
    code = int(status[1])
    headers = {}
    for line in lines[1:]:
        key, colon, value = line.partition(b":")
        if not colon:
            return {"complete": False, "error": "INVALID_RESPONSE"}
        headers.setdefault(key.lower(), []).append(value.strip())
    if code == 429 or (code == 403 and (
            b"0" in headers.get(b"x-ratelimit-remaining", [])
            or bool(headers.get(b"retry-after")))):
        return {"complete": False, "error": "GH_RATE_LIMIT"}
    if code == 403:
        try:
            error = json.loads(body)
            message = error.get("message", "") if isinstance(error, dict) else ""
            if isinstance(message, str) and "secondary rate limit" in message.lower():
                return {"complete": False, "error": "GH_RATE_LIMIT"}
        except (ValueError, UnicodeError):
            pass
    if code != 200:
        return {"complete": False, "error": "GH_HTTP_ERROR"}
    if exit_code:
        return {"complete": False, "error": "GH_FAILED_OR_TIMEOUT"}
    try:
        return {"complete": True, "data": json.loads(body)}
    except (ValueError, UnicodeError):
        return {"complete": False, "error": "GH_UNAVAILABLE_OR_INVALID_JSON"}


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
        # Explicit GET, no caller-defined endpoint, no inherited tokens or Git config.
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.config_dir),
               "GH_CONFIG_DIR": str(self.config_dir), "GH_PROMPT_DISABLED": "1",
               "GH_HOST": "github.com", "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
        try:
            # Bound memory and disk: stream at most one MiB plus one byte;
            # timeout is enforced by a separate watchdog around the pipe read.
            import threading
            with subprocess.Popen(["gh","api","--hostname","github.com","--method","GET","--include",endpoint],
                                  env=env,cwd=self.config_dir,stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE,stderr=subprocess.DEVNULL) as proc:
                timer = threading.Timer(15, proc.kill)
                timer.start()
                try:
                    raw = proc.stdout.read(1_048_577)
                    if len(raw) > 1_048_576:
                        proc.kill()
                        return {"complete":False,"error":"RESPONSE_LIMIT"}
                    exit_code = proc.wait()
                finally:
                    timer.cancel()
            return _http_result(raw, exit_code)
        except (OSError, ValueError):
            return {"complete":False,"error":"GH_UNAVAILABLE_OR_INVALID_JSON"}

    def issue_context(self, principal, project, number, *, check_access=None):
        repo = self._repo(principal, project)
        if type(number) is not int or not 1 <= number <= 2_147_483_647:
            raise ValueError("Invalid issue number")
        def authorized_request(endpoint):
            self._repo(principal, project)
            if check_access is not None:
                check_access()
            result = self._request(endpoint)
            if check_access is not None:
                check_access()
            return result

        def verify_identity():
            expected = self.repository_ids.get(project)
            if expected is None:
                return
            result = authorized_request(f"repos/{repo}")
            if result.get("complete") is not True:
                raise GitHubReadError(result.get("error", "INVALID_RESPONSE"))
            data = result.get("data")
            if (not isinstance(data, dict) or type(data.get("id")) is not int
                    or data["id"] != expected or not isinstance(data.get("full_name"), str)
                    or not data["full_name"].isascii() or data["full_name"].lower() != repo.lower()):
                raise GitHubReadError("RESOURCE_MISMATCH")

        def checked_request(endpoint):
            # REST issue routes are name-based, not an atomic ID snapshot.
            verify_identity()
            result = authorized_request(endpoint)
            if result.get("error") == "GH_RATE_LIMIT":
                raise GitHubReadError("GH_RATE_LIMIT")
            verify_identity()
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
            results = [self.issue_context(principal, project, n, check_access=check_access) for n in unique]
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda n: self.issue_context(principal,project,n, check_access=check_access),unique))
        self._repo(principal, project)
        return {"complete":all(x["complete"] for x in results),
                "issues":dict(zip(unique,results))}
