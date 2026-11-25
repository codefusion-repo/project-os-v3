"""Bounded single-instance HTTP admission and sanitized local audit."""
import json
import os
import stat
import threading
import time
from collections import deque
from datetime import datetime, timezone

from starlette.responses import JSONResponse

from .workos_auth import private_directory, AuthObservation, AuthOutcome, auth_outcome

MAX_AUDIT_BYTES = 4 * 1024 * 1024


AUTH_AUDIT_NAME = "oauth-audit.jsonl"


class Audit:
    """Bounded legacy HTTP audit plus local-only OAuth completion observations."""
    def __init__(self, root):
        private_directory(root)
        self.root=root
        self.path=root/"security-audit.jsonl"
        self.auth_path=root/AUTH_AUDIT_NAME
        self.lock=threading.Lock()

    @staticmethod
    def _open(path, *, create):
        flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        if create:
            flags |= os.O_CREAT
        fd = os.open(path, flags, 0o600)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_mode & 0o077:
                raise PermissionError("Unsafe audit file")
            return fd, st.st_size
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _append(fd, data):
        if os.write(fd, data) != len(data):
            raise OSError("Incomplete audit")

    def record(self,status, *, outcome=None):
        if type(status) is not int or not 100 <= status <= 599:
            raise ValueError("Invalid HTTP status")
        if outcome is not None and (not isinstance(outcome, AuthOutcome) or status < 200):
            raise ValueError("Invalid authentication outcome")
        at = datetime.now(timezone.utc).isoformat()
        event = {"at":at, "event":"mcp_http", "status":status}
        data = (json.dumps(event) + "\n").encode()
        auth_data = None
        if outcome is not None:
            auth_data = (json.dumps({**event, "auth_outcome":outcome.value}) + "\n").encode()
        with self.lock:
            private_directory(self.root)
            fd, size = self._open(self.path, create=True)
            auth_fd = None
            try:
                # Admission checks both private files and the shared budget,
                # even when no OAuth observation is to be written.
                try:
                    auth_fd, auth_size = self._open(self.auth_path, create=auth_data is not None)
                except FileNotFoundError:
                    if auth_data is not None:
                        raise
                    auth_size = 0
                if size + auth_size + len(data) > MAX_AUDIT_BYTES:
                    raise OSError("Audit capacity reached")
                # Always preserve the original HTTP completion first.
                self._append(fd, data)
                # Supplemental observation is best effort, like completion.
                # Never displace an HTTP record to make room for it.
                if auth_data is not None:
                    if size + auth_size + len(data) + len(auth_data) > MAX_AUDIT_BYTES:
                        raise OSError("OAuth audit capacity reached")
                    self._append(auth_fd, auth_data)
            finally:
                if auth_fd is not None:
                    os.close(auth_fd)
                os.close(fd)


class RequestGate:
    """Global in-memory sliding-window rate and concurrency cap (one process)."""
    def __init__(self,app,audit,limit=120):
        if type(limit) is not int or not 1<=limit<=120:
            raise ValueError("Invalid rate limit")
        self.app=app
        self.audit=audit
        self.limit=limit
        self.window=deque()
        self.active=0
        self.last_rejection=float("-inf")
        self.lock=threading.Lock()

    async def __call__(self,scope,receive,send):
        if scope["type"]!="http":
            await self.app(scope,receive,send)
            return
        now=time.monotonic()
        with self.lock:
            while self.window and self.window[0]<=now-60:
                self.window.popleft()
            allowed=len(self.window)<self.limit and self.active<8
            if allowed:
                self.window.append(now)
                self.active+=1
            record_rejection=not allowed and now-self.last_rejection>=60
            if record_rejection:
                self.last_rejection=now
        # Check audit availability before forwarding any admitted request.
        # A 503 here is fail-closed; audit saturation requires local maintenance.
        if not allowed:
            if record_rejection:
                try:
                    self.audit.record(429)
                except (OSError,ValueError):
                    pass
            await JSONResponse({"error":"rate_limited"},status_code=429,
                               headers={"Retry-After":"60"})(scope,receive,send)
            return
        try:
            # Verify audit availability before any downstream side effect.
            # Admission is itself an event, completion is recorded separately.
            self.audit.record(100)
        except (OSError,ValueError):
            with self.lock:
                self.active-=1
            await JSONResponse({"error":"audit_unavailable"},status_code=503)(scope,receive,send)
            return
        # Only fixed MCP requests carry authentication categories. The SDK
        # may authenticate before routing, including public metadata requests.
        # Default is missing bearer; a presented but unprocessed credential
        # is malformed/unsupported, never treated as verified.
        initial = AuthOutcome.TOKEN_MISSING
        if any(name.lower() == b"authorization" for name, _ in scope.get("headers", ())):
            initial = AuthOutcome.TOKEN_MALFORMED
        observation = AuthObservation(initial) if scope.get("path") == "/mcp" else None
        context = auth_outcome.set(observation)
        async def audited_send(message):
            if message["type"]=="http.response.start":
                try:
                    outcome = observation.outcome if observation is not None else None
                    if outcome is None or message["status"] < 200:
                        self.audit.record(message["status"])
                    else:
                        self.audit.record(message["status"], outcome=outcome)
                except (OSError,ValueError):
                    # Do not claim an already performed side effect was undone.
                    pass
            await send(message)
        try:
            await self.app(scope,receive,audited_send)
        finally:
            auth_outcome.reset(context)
            with self.lock:
                self.active-=1
