"""Bounded single-instance HTTP admission and sanitized local audit."""
import json
import os
import stat
import threading
import time
from collections import deque
from datetime import datetime, timezone

from starlette.responses import JSONResponse

from .workos_auth import private_directory

MAX_AUDIT_BYTES = 4 * 1024 * 1024


class Audit:
    """Fixed-schema local security events; never store tokens, payloads or paths."""
    def __init__(self, root):
        private_directory(root)
        self.root=root
        self.path=root/"security-audit.jsonl"
        self.lock=threading.Lock()

    def record(self,status):
        if type(status) is not int or not 100 <= status <= 599:
            raise ValueError("Invalid HTTP status")
        data=(json.dumps({"at":datetime.now(timezone.utc).isoformat(),
                          "event":"mcp_http","status":status})+"\n").encode()
        with self.lock:
            private_directory(self.root)
            fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
            try:
                st=os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_nlink!=1 or st.st_mode&0o077:
                    raise PermissionError("Unsafe audit file")
                if st.st_size+len(data)>MAX_AUDIT_BYTES:
                    raise OSError("Audit capacity reached")
                if os.write(fd,data)!=len(data):
                    raise OSError("Incomplete audit")
            finally:
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
        async def audited_send(message):
            if message["type"]=="http.response.start":
                try:
                    self.audit.record(message["status"])
                except (OSError,ValueError):
                    # Do not claim an already performed side effect was undone.
                    pass
            await send(message)
        try:
            await self.app(scope,receive,audited_send)
        finally:
            with self.lock:
                self.active-=1
