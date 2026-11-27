"""One-time local OAuth enrollment, never a remote MCP handler.

Run from the reviewed installed interpreter as the existing service owner.
The Desktop client JSON is local input; no tokens, codes, or IDs are printed.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .drive_delivery import API, SCOPE, TOKEN, DrivePublisher, DriveDeliveryError, drive_id
from .github_operational import _private_bytes, _unique_object
from .maintenance import save, sync_dir
from .workos_auth import private_directory, private_file

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
FOLDER_MIME = "application/vnd.google-apps.folder"
FOLDER_NAME = "Project OS QA"
DIRECTORY = "drive-delivery"


def read_json(path):
    return json.loads(_private_bytes(path, 16384), object_pairs_hook=_unique_object)


def desktop_client(path):
    raw = read_json(path)
    installed = raw.get("installed") if isinstance(raw, dict) else None
    if not isinstance(installed, dict):
        raise ValueError("DRIVE_DESKTOP_CLIENT_REQUIRED")
    if (installed.get("token_uri") != TOKEN
            or installed.get("auth_uri") not in (AUTH, "https://accounts.google.com/o/oauth2/auth")):
        raise ValueError("DRIVE_OAUTH_ENDPOINT_INVALID")
    result = {key: installed.get(key) for key in ("client_id", "client_secret")}
    if not all(isinstance(v, str) and 0 < len(v) <= 4096 for v in result.values()):
        raise ValueError("DRIVE_DESKTOP_CLIENT_INVALID")
    return result


def authorization_url(client_id, redirect, state, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return AUTH + "?" + urlencode({"client_id": client_id, "redirect_uri": redirect,
        "response_type": "code", "scope": SCOPE, "access_type": "offline",
        "prompt": "consent", "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256"})


def callback_code(path, state):
    url = urlsplit(path)
    if url.path != "/callback" or url.netloc or url.scheme or url.fragment or len(path) > 8192:
        return None
    try:
        query = parse_qs(url.query, strict_parsing=True, max_num_fields=12)
    except ValueError:
        return None
    states = query.get("state", [])
    codes = query.get("code", [])
    if (len(states) != 1 or not secrets.compare_digest(states[0], state)
            or len(codes) != 1 or "error" in query or not 0 < len(codes[0]) <= 4096):
        return None
    return codes[0]


def authorize(client):
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            code = callback_code(self.path, state)
            message = b"Authorization received. Return to the terminal." if code else b"Invalid authorization callback."
            self.send_response(200 if code else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)
            if code:
                received.append(code)

    # Ephemeral loopback only; no LAN binding, tunnel, or OAuth out-of-band flow.
    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/callback"
        print("Open this one-time Google authorization URL in your local browser:")
        print(authorization_url(client["client_id"], redirect, state, verifier), flush=True)
        deadline = time.monotonic() + 300
        while not received and time.monotonic() < deadline:
            server.handle_request()
        if not received:
            raise DriveDeliveryError("DRIVE_AUTHORIZATION_TIMEOUT")

    with httpx.Client(trust_env=False, follow_redirects=False, timeout=30) as http:
        response = http.post(TOKEN, data={**client, "grant_type": "authorization_code",
            "code": received[0], "code_verifier": verifier, "redirect_uri": redirect})
        if response.status_code != 200:
            raise DriveDeliveryError("DRIVE_AUTHORIZATION_FAILED")
        data = response.json()
    if (not isinstance(data, dict) or data.get("scope") != SCOPE
            or not isinstance(data.get("refresh_token"), str)
            or not 0 < len(data["refresh_token"]) <= 4096):
        raise DriveDeliveryError("DRIVE_REFRESH_CREDENTIAL_MISSING")
    return {**client, "refresh_token": data["refresh_token"], "scope": SCOPE}


def enroll(root, client_path=None):
    if os.getuid() == 0:
        raise PermissionError("DRIVE_UNPRIVILEGED_OWNER_REQUIRED")
    private_directory(root)
    for parent in (root, *root.parents):
        if os.path.lexists(parent / ".git"):
            raise PermissionError("DRIVE_STATE_OUTSIDE_GIT_REQUIRED")
    state = root / "state"
    private_directory(state)
    private_file(root / "oauth.json")
    private_file(state / "jobs.sqlite3")
    private_file(root / "service" / "runtime.json")
    directory = state / DIRECTORY
    directory.mkdir(mode=0o700, exist_ok=True)
    private_directory(directory)
    sync_dir(state)
    fd = os.open(directory / "enroll.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        private_file(directory / "enroll.lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        credential = directory / "credentials.json"
        binding = directory / "binding.json"
        if not os.path.lexists(credential):
            if client_path is None or os.path.lexists(binding):
                raise ValueError("DRIVE_CLIENT_JSON_REQUIRED")
            save(credential, authorize(desktop_client(client_path)))
        # No implicit credential rotation; existing enrollment is reused.
        if os.path.lexists(binding):
            plan = read_json(binding)
            if (set(plan) != {"folder_id", "owner_permission_id", "state"}
                    or plan["state"] not in {"RESERVED", "READY"}):
                raise ValueError("DRIVE_ENROLLMENT_INVALID")
        else:
            p = DrivePublisher(credential, "pending", "pending")
            try:
                user = p._json("GET", API + "/about", params={"fields": "user(permissionId)"})
                ids = p._json("GET", API + "/files/generateIds",
                               params={"count": 1, "space": "drive", "type": "files"}).get("ids")
                if not isinstance(ids, list) or len(ids) != 1:
                    raise DriveDeliveryError("DRIVE_ID_UNAVAILABLE")
                plan = {"folder_id": drive_id(ids[0]),
                        "owner_permission_id": drive_id(user.get("user", {}).get("permissionId")),
                        "state": "RESERVED"}
            finally:
                p.close()
            save(binding, plan)
        p = DrivePublisher(credential, plan["folder_id"], plan["owner_permission_id"])
        try:
            user = p._json("GET", API + "/about", params={"fields": "user(permissionId)"})
            if user.get("user", {}).get("permissionId") != p.owner:
                raise PermissionError("DRIVE_OWNER_CHANGED")
            if plan["state"] == "RESERVED":
                # A pre-generated ID makes retry of the same create safe.
                # Do not allocate another ID after an ambiguous create.
                try:
                    p.require_folder()
                except DriveDeliveryError as exc:
                    if str(exc) != "DRIVE_HTTP_404":
                        raise
                    try:
                        p._json("POST", API + "/files", params={"fields": "id"},
                                json={"id": p.folder, "name": FOLDER_NAME, "mimeType": FOLDER_MIME})
                    except DriveDeliveryError as create_error:
                        if str(create_error) != "DRIVE_HTTP_409":
                            raise
                p.require_folder()
                save(binding, {**plan, "state": "READY"})
            else:
                p.require_folder()
        finally:
            p.close()
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--client-json", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if not sys.stdin.isatty():
        parser.exit(1, "DRIVE_LOCAL_INTERACTIVE_OWNER_REQUIRED\n")
    try:
        enroll(args.root, args.client_json)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, httpx.HTTPError, KeyboardInterrupt):
        parser.exit(1, "DRIVE_ENROLLMENT_BLOCKED; preserve local state and retry only the same enrollment\n")
    print("DRIVE_ENROLLMENT_READY; owner-private folder verified; no upload or grant activated.")


if __name__ == "__main__":
    main()
