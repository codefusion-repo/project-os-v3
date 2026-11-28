"""Shared bounded, authenticated GitHub CLI GET transport (stdlib only)."""
import json
import os
import re
import subprocess
import threading


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate GitHub JSON key")
        result[key] = value
    return result


def _http_result(raw, exit_code, *, strict=False):
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
    def error(category):
        result = {"complete": False, "error": category}
        if strict:
            result["http_status"] = code
        return result

    if code == 429 or (code == 403 and (
            b"0" in headers.get(b"x-ratelimit-remaining", [])
            or bool(headers.get(b"retry-after")))):
        return error("GH_RATE_LIMIT")
    if code == 403:
        try:
            payload = json.loads(body)
            message = payload.get("message", "") if isinstance(payload, dict) else ""
            if isinstance(message, str) and "secondary rate limit" in message.lower():
                return error("GH_RATE_LIMIT")
        except (ValueError, UnicodeError):
            pass
    if code != 200:
        return error("GH_AUTH_REQUIRED" if strict and code == 401 else "GH_HTTP_ERROR")
    if exit_code:
        return error("GH_FAILED_OR_TIMEOUT")
    if strict and b"link" in headers:
        return error("GH_INCOMPLETE_RESPONSE")
    try:
        return {"complete": True, "data": json.loads(body, object_pairs_hook=_unique if strict else None)}
    except (ValueError, UnicodeError):
        return {"complete": False, "error": "GH_UNAVAILABLE_OR_INVALID_JSON"}



def gh_request(config_dir, endpoint, *, strict=False):
    # Same dedicated CLI profile for both context reads and canonical maintenance.
    # Never inherit personal tokens, proxy/debug settings or Git configuration.
    try:
        if not config_dir.is_absolute() or config_dir.resolve(strict=True) != config_dir:
            raise ValueError("Dedicated canonical gh config required")
        info = config_dir.stat()
        if not config_dir.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError("Private gh config required")
    except (OSError, ValueError):
        return {"complete": False, "error": "GH_CONFIG_UNAVAILABLE"}
    env = {"PATH": "/usr/bin:/bin", "HOME": str(config_dir),
           "GH_CONFIG_DIR": str(config_dir), "GH_PROMPT_DISABLED": "1",
           "GH_HOST": "github.com", "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
    limit = 2 * 1024 * 1024 if strict else 1_048_576
    argv = ["gh", "api", "--hostname", "github.com", "--method", "GET", "--include"]
    if strict:
        argv += ["-H", "Accept: application/vnd.github+json",
                 "-H", "X-GitHub-Api-Version: 2022-11-28"]
    try:
        with subprocess.Popen([*argv, endpoint], env=env, cwd=config_dir,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as proc:
            timer = threading.Timer(15, proc.kill)
            timer.start()
            try:
                raw = proc.stdout.read(limit + 1)
                if len(raw) > limit:
                    proc.kill()
                    return {"complete": False, "error": "RESPONSE_LIMIT"}
                exit_code = proc.wait()
            finally:
                timer.cancel()
        return _http_result(raw, exit_code, strict=strict)
    except (OSError, ValueError):
        return {"complete": False, "error": "GH_UNAVAILABLE_OR_INVALID_JSON"}
