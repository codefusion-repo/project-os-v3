"""Candidate delivery boundary for real GitHub issue context; no startup wiring."""
import json
import re
import unicodedata
from datetime import datetime, timezone

from .github import GitHubReader

MAX_CONTEXT_BYTES = 512 * 1024
MAX_TEXT = 16_384
PROJECT = re.compile(r"[A-Za-z0-9_-]{1,80}")
# Defense in depth only: arbitrary prose can contain unknown secrets.
SENSITIVE = re.compile(
    r"-----BEGIN [^\n]{0,80}PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}|"
    r"sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b|"
    r"\bBearer\s+\S+|\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token)"
    r"\s*[:=]\s*\S+|https?://[^/\s@]+:[^/\s@]+@",
    re.IGNORECASE,
)
ERRORS = frozenset({
    "RESPONSE_LIMIT", "GH_FAILED_OR_TIMEOUT", "GH_UNAVAILABLE_OR_INVALID_JSON",
    "INVALID_RESPONSE", "AGGREGATE_LIMIT", "PAGE_LIMIT", "RESOURCE_MISMATCH",
})


def _size(value):
    # ASCII JSON accounts conservatively for escaped Unicode on the wire.
    return len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode("ascii"))


def _text(value):
    if value is None:
        return None, False
    if not isinstance(value, str):
        return None, True
    if len(value) > MAX_TEXT:
        return "[OMITTED: TEXT_LIMIT]", True
    clean = "".join(c for c in value if c in "\n\t" or unicodedata.category(c) not in {"Cc", "Cf", "Cs"})
    if SENSITIVE.search(clean):
        return "[REDACTED]", True
    return clean, clean != value


def _project_fields(data, fields):
    result, changed = {}, False
    for key in fields:
        if key not in data:
            continue
        value = data[key]
        if key in {"number", "id", "comments"}:
            if type(value) is int and 0 <= value <= 2**63 - 1:
                result[key] = value
            else:
                changed = True
        else:
            result[key], altered = _text(value)
            changed |= altered
    return result, changed


def _error(value):
    return value if isinstance(value, str) and value in ERRORS else "INVALID_RESPONSE"


def _resource_url(value, repository, suffix=""):
    # Compare only repository names case-insensitively (GitHub semantics).
    # No redirects, query strings, fragments, escaping or alternate hosts
    # are accepted as identity evidence. Never fetch these upstream URLs.
    prefix = "https://api.github.com/repos/"
    if not isinstance(value, str) or not value.isascii() or not value.startswith(prefix):
        return False
    path = value[len(prefix):]
    if suffix:
        if not path.endswith(suffix):
            return False
        path = path[:-len(suffix)]
    return path.lower() == repository.lower()


def _issue_error(data, repository, number):
    if not isinstance(data, dict):
        return "INVALID_RESPONSE"
    if (type(data.get("number")) is not int or data["number"] != number
            or not _resource_url(data.get("repository_url"), repository)
            or not _resource_url(data.get("url"), repository, f"/issues/{number}")):
        return "RESOURCE_MISMATCH"
    # Null is valid for an issue body, but absent is not.
    if (not isinstance(data.get("title"), str) or not data["title"].strip()
            or "body" not in data or not (data["body"] is None or isinstance(data["body"], str))
            or data.get("state") not in ("open", "closed")
            or type(data.get("comments")) is not int or not 0 <= data["comments"] <= 2**63 - 1):
        return "INVALID_RESPONSE"
    return None


def _comment_error(data, repository, number):
    if not isinstance(data, dict) or type(data.get("id")) is not int or not 0 < data["id"] <= 2**63 - 1:
        return "INVALID_RESPONSE"
    if (not _resource_url(data.get("issue_url"), repository, f"/issues/{number}")
            or not _resource_url(data.get("url"), repository, f"/issues/comments/{data['id']}")):
        return "RESOURCE_MISMATCH"
    if not isinstance(data.get("body"), str):
        return "INVALID_RESPONSE"
    return None


def _issue(repository, number, item):
    issue = item.get("issue", {})
    data = issue.get("data")
    complete = item.get("complete") is True
    issue_error = (_issue_error(data, repository, number) if issue.get("complete") is True
                   else _error(issue.get("error")))
    if issue_error is None:
        record, altered = _project_fields(
            data, ("number", "title", "body", "state", "comments", "created_at", "updated_at", "closed_at"))
        result = {"complete": not altered, "data": record}
        issue_valid = True
    else:
        record, altered = {}, False
        result = {"complete": False, "error": issue_error}
        issue_valid = False
        complete = False
    comments, seen = [], set()
    comment_error = item.get("comments_error")
    comment_error = _error(comment_error) if comment_error is not None else None
    if issue_valid:
        for raw in item.get("comments", []):
            error = _comment_error(raw, repository, number)
            if error == "RESOURCE_MISMATCH":
                # An inconsistent page invalidates the entire comment collection.
                comments.clear()
                comment_error = error
                complete = False
                break
            if error is not None or raw["id"] in seen:
                complete = False
                comment_error = "INVALID_RESPONSE"
                continue
            seen.add(raw["id"])
            comment, changed = _project_fields(raw, ("id", "body", "created_at", "updated_at"))
            comments.append(comment)
            altered |= changed
        if record["comments"] != len(comments):
            complete = False
            comment_error = comment_error or "COUNT_MISMATCH"
    retrieved_at, timestamp_changed = _text(item.get("retrieved_at"))
    if comment_error is not None:
        complete = False
    return {
        "complete": complete and not altered and not timestamp_changed,
        "issue": result, "comments": comments, "comments_error": comment_error,
        "content_filtered": altered, "retrieved_at": retrieved_at,
        "source": "github.com", "untrusted_content": True,
    }


class GitHubContext:
    """Reuse the real reader with a mandatory, trusted, current exact-repo grant.

    authorize(principal, project, repository) must return True only for a current
    local grant. It is supplied by trusted application code, never by tool input.
    No production configuration constructs this candidate yet.
    """

    def __init__(self, reader: GitHubReader, authorize):
        if type(reader) is not GitHubReader or not callable(authorize):
            raise ValueError("Real reader and explicit grant evaluator required")
        self.reader = reader
        self.authorize = authorize

    def require(self, principal, project):
        try:
            if not isinstance(project, str) or not PROJECT.fullmatch(project):
                raise PermissionError("DENIED")
            repo = self.reader.authorized_repository(principal, project)
            if self.authorize(principal, project, repo) is not True:
                raise PermissionError("DENIED")
            return repo
        except (OSError, ValueError, TypeError):
            raise PermissionError("DENIED") from None

    def read(self, principal, project, numbers, *, check_session=None):
        repo = self.require(principal, project)

        def check_access():
            if check_session is not None:
                check_session()
            if self.require(principal, project) != repo:
                raise PermissionError("DENIED")

        check_access()
        raw = self.reader.batch_issues(principal, project, numbers, check_access=check_access)
        check_access()
        response = {
            "complete": raw["complete"], "issues": {}, "omitted_issues": [],
            "error": None, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source": "github.com", "untrusted_content": True,
        }
        # Reserve space for all omission identifiers and error metadata.
        budget = MAX_CONTEXT_BYTES - 1024
        for number, item in raw["issues"].items():
            projected = _issue(repo, number, item)
            response["issues"][number] = projected
            if _size(response) > budget:
                del response["issues"][number]
                response["omitted_issues"].append(number)
                response["error"] = "BATCH_RESPONSE_LIMIT"
                response["complete"] = False
            elif not projected["complete"]:
                response["complete"] = False
        if _size(response) > MAX_CONTEXT_BYTES:
            raise RuntimeError("CONTEXT_RESPONSE_LIMIT")
        check_access()
        return response
