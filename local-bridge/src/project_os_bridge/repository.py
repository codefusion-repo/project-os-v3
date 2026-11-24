"""Local disposable fixture operations, not a general checkout sandbox."""
import hashlib
import os
import re
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile
from contextlib import contextmanager
import fcntl

from .core import Policy


class FixtureRepository:
    """A fixed text resource in a dedicated private directory. No Git hooks or shell."""
    def __init__(self, root: Path, policy: Policy):
        if not root.is_absolute() or root.resolve(strict=True) != root:
            raise ValueError("Canonical fixture root required")
        self.root = root
        self.policy = policy
        self.path = root / "fixture.txt"
        self.check_root()

    def check_root(self):
        st = self.root.stat()
        if self.root.resolve(strict=True) != self.root or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise PermissionError("Private fixture directory required")

    @contextmanager
    def lock(self):
        self.check_root()
        fd = os.open(self.root / "fixture.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_mode & 0o077:
                raise PermissionError("Unsafe lock")
            fcntl.flock(fd,fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def read_fixed(self):
        fd = os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,"rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_mode & 0o077:
                raise PermissionError("Unsafe fixture")
            data = f.read(65537)
        if len(data)>65536:
            raise ValueError("Fixture exceeds limit")
        return data

    def read(self, principal):
        self.policy.require(principal,"fixture_read","disposable")
        with self.lock():
            data = self.read_fixed()
            return {"text":data.decode("utf-8"),"revision":hashlib.sha256(data).hexdigest()}

    def replace(self,principal,expected_revision,text):
        self.policy.require(principal,"fixture_write","disposable")
        if not re.fullmatch(r"[0-9a-f]{64}",expected_revision):
            raise ValueError("Expected digest required")
        data = text.encode("utf-8")
        if len(data)>65536 or "\x00" in text:
            raise ValueError("Invalid fixture content")
        with self.lock():
            old = self.read_fixed()
            if hashlib.sha256(old).hexdigest()!=expected_revision:
                raise ValueError("REVISION_CONFLICT")
            tmp = None
            try:
                with NamedTemporaryFile(dir=self.root,delete=False) as f:
                    tmp = Path(f.name)
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp,self.path)
                directory = os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if tmp is not None and tmp.exists():
                    tmp.unlink()
            return {"revision":hashlib.sha256(data).hexdigest()}
