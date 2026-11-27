"""Central trusted Drive delivery; no project code, public sharing or MCP bytes.

The private binding and OAuth credential must be enrolled by the local owner.
No generic Drive access, arbitrary destination URL or permission mutation.
"""
import hashlib
import json
import logging
import re
from urllib.parse import urlsplit

import httpx

from .github_operational import _private_bytes, _unique_object

SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
MIME = "application/vnd.android.package-archive"
FIELDS = "id,name,mimeType,size,sha256Checksum,parents,trashed,ownedByMe,driveId,appProperties"
ID = re.compile(r"[A-Za-z0-9_-]{1,200}")
SHA = re.compile(r"[0-9a-f]{64}")
MAX_APK = 256 * 1024 * 1024


class DriveDeliveryError(RuntimeError):
    """Fixed sanitized category, not an upstream payload or credential."""


def drive_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("DRIVE_ID_INVALID")
    return value


class DrivePublisher:
    def __init__(self, credential_path, folder_id, owner_permission_id, *, transport=None, check_access=lambda: None):
        self.check_access = check_access
        self.folder = drive_id(folder_id)
        self.owner = drive_id(owner_permission_id)
        self.credential_path = credential_path
        self._credential = _private_bytes(credential_path, 16384)
        config = json.loads(self._credential, object_pairs_hook=_unique_object)
        if (not isinstance(config, dict)
                or set(config) != {"client_id", "client_secret", "refresh_token", "scope"}
                or config["scope"] != SCOPE
                or not all(isinstance(v, str) and 0 < len(v) <= 4096 for v in config.values())):
            raise ValueError("DRIVE_CREDENTIAL_INVALID")
        self.config = config
        # Binding change invalidates an in-flight request; do not record secret material.
        self.binding = hashlib.sha256(json.dumps({"folder": self.folder, "owner": self.owner,
            "client_id": config["client_id"], "scope": SCOPE}, sort_keys=True).encode()).hexdigest()
        # Request URLs can include bearer-like resumable upload session IDs.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        self.http = httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                                 timeout=httpx.Timeout(90, connect=15))
        self._token = None

    def close(self):
        self.http.close()

    def _check(self):
        self.check_access()
        if _private_bytes(self.credential_path, 16384) != self._credential:
            raise PermissionError("DRIVE_CREDENTIAL_CHANGED")

    def _request(self, method, url, *, expected=(200,), headers=None, limit=1048576,
                 auth=True, **kwargs):
        self._check()
        headers = dict(headers or {})
        if auth:
            if self._token is None:
                self._refresh()
            headers["Authorization"] = "Bearer " + self._token
        try:
            with self.http.stream(method, url, headers=headers, **kwargs) as response:
                if response.status_code not in expected:
                    raise DriveDeliveryError("DRIVE_HTTP_" + str(response.status_code))
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise DriveDeliveryError("DRIVE_RESPONSE_LIMIT")
                self._check()
                return response.status_code, dict(response.headers), bytes(body)
        except httpx.HTTPError:
            raise DriveDeliveryError("DRIVE_TRANSPORT_UNCERTAIN") from None

    def _json(self, method, url, **kwargs):
        _, _, body = self._request(method, url, **kwargs)
        try:
            obj = json.loads(body, object_pairs_hook=_unique_object)
            if not isinstance(obj, dict):
                raise ValueError()
            return obj
        except (ValueError, UnicodeError):
            raise DriveDeliveryError("DRIVE_RESPONSE_INVALID") from None

    def _refresh(self):
        data = self._json("POST", TOKEN, auth=False, data={
            "client_id": self.config["client_id"], "client_secret": self.config["client_secret"],
            "refresh_token": self.config["refresh_token"], "grant_type": "refresh_token"})
        token = data.get("access_token")
        if (not isinstance(token, str) or not 0 < len(token) <= 8192
                or any(ord(c) <= 32 or ord(c) >= 127 for c in token)
                or data.get("token_type", "").lower() != "bearer"
                or ("scope" in data and data["scope"] != SCOPE)):
            raise DriveDeliveryError("DRIVE_TOKEN_INVALID")
        self._token = token

    def _file(self, file_id, fields=FIELDS):
        return self._json("GET", API + "/files/" + drive_id(file_id),
                          params={"fields": fields})

    def _private(self, file_id):
        # MVP: owner-only My Drive, not shared drives or link/domain sharing.
        obj = self._json("GET", API + "/files/" + drive_id(file_id) + "/permissions",
                         params={"fields": "nextPageToken,permissions(id,type,role,deleted)",
                                 "pageSize": 100})
        entries = obj.get("permissions")
        if (obj.get("nextPageToken") or not isinstance(entries, list) or len(entries) != 1
                or entries[0].get("id") != self.owner or entries[0].get("type") != "user"
                or entries[0].get("role") != "owner" or entries[0].get("deleted", False)):
            raise PermissionError("DRIVE_NOT_OWNER_PRIVATE")

    def require_folder(self):
        obj = self._file(self.folder, "id,mimeType,trashed,ownedByMe,driveId,capabilities(canAddChildren)")
        if (obj.get("id") != self.folder or obj.get("mimeType") != "application/vnd.google-apps.folder"
                or obj.get("trashed") is not False or obj.get("ownedByMe") is not True
                or obj.get("driveId") or obj.get("capabilities", {}).get("canAddChildren") is not True):
            raise PermissionError("DRIVE_FOLDER_UNAVAILABLE")
        self._private(self.folder)

    def reserve(self):
        self.require_folder()
        obj = self._json("GET", API + "/files/generateIds",
                         params={"count": 1, "space": "drive", "type": "files"})
        ids = obj.get("ids")
        if not isinstance(ids, list) or len(ids) != 1:
            raise DriveDeliveryError("DRIVE_ID_UNAVAILABLE")
        return drive_id(ids[0])

    def upload(self, file_id, raw, properties):
        self.require_folder()
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_APK:
            raise ValueError("DRIVE_APK_INVALID")
        file_id = drive_id(file_id)
        name = "qa-" + properties["job_id"] + ".apk"
        _, headers, _ = self._request("POST", UPLOAD,
            params={"uploadType": "resumable", "fields": "id"},
            headers={"X-Upload-Content-Type": MIME, "X-Upload-Content-Length": str(len(raw))},
            json={"id": file_id, "name": name, "mimeType": MIME,
                  "parents": [self.folder], "appProperties": properties})
        location = headers.get("location", "")
        u = urlsplit(location)
        # Only the documented upload origin/path; never forward OAuth to another host.
        if (u.scheme != "https" or u.netloc != "www.googleapis.com"
                or u.path != "/upload/drive/v3/files" or not u.query or u.fragment):
            raise DriveDeliveryError("DRIVE_SESSION_INVALID")
        self.require_folder()
        self._request("PUT", location, expected=(200, 201), auth=False,
                      headers={"Content-Type": MIME, "Content-Length": str(len(raw)),
                               "Content-Range": f"bytes 0-{len(raw)-1}/{len(raw)}"},
                      content=raw)

    def verify(self, file_id, artifact, properties):
        self.require_folder()
        file_id = drive_id(file_id)
        obj = self._file(file_id)
        if (obj.get("id") != file_id or obj.get("parents") != [self.folder]
                or obj.get("name") != "qa-" + properties["job_id"] + ".apk"
                or obj.get("mimeType") != MIME or obj.get("trashed") is not False
                or obj.get("ownedByMe") is not True or obj.get("driveId")
                or obj.get("appProperties") != properties
                or obj.get("size") != str(artifact["size"])
                or (obj.get("sha256Checksum") is not None
                    and obj["sha256Checksum"] != artifact["sha256"])):
            raise DriveDeliveryError("DRIVE_FILE_IDENTITY_MISMATCH")
        self._private(file_id)
        _, _, raw = self._request("GET", API + "/files/" + file_id,
                                  params={"alt": "media"}, limit=artifact["size"])
        if len(raw) != artifact["size"] or hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
            raise DriveDeliveryError("DRIVE_BYTES_MISMATCH")
        if self._file(file_id) != obj:
            raise DriveDeliveryError("DRIVE_FILE_CHANGED")
        self.require_folder()
        self._private(file_id)
        return {"file_id": file_id, "sha256": artifact["sha256"], "size": artifact["size"],
                "url": "https://drive.google.com/file/d/" + file_id + "/view"}
