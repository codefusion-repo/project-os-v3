"""Fixed-resource disposable probe; not a general repository authorization system."""
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

MARKER = "project-os-bridge-probe-v1"


class Probe:
    def __init__(self, state_dir: Path):
        if not state_dir.is_absolute():
            raise ValueError("State directory must be absolute")
        self.root = state_dir
        self._check_directory()
        self.db = self.root / "probe.sqlite3"
        if self.db.is_symlink():
            raise PermissionError("State database must not be a symlink")
        if not self.db.exists():
            try:
                fd = os.open(self.db, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        self._check_file(self.db)
        with closing(self._connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY CHECK(id=1), marker TEXT NOT NULL)")
    
    def _check_directory(self):
        if self.root.resolve(strict=True) != self.root:
            raise PermissionError("State directory must be canonical and not traverse symlinks")
        st = self.root.stat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise PermissionError("State directory must be private and owned by service user")

    @staticmethod
    def _check_file(path):
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_nlink != 1:
            raise PermissionError("State file must be a private regular file owned by service user")

    def _connect(self):
        self._check_directory()
        self._check_file(self.db)
        return sqlite3.connect(self.db, timeout=5)

    def write_enabled(self):
        flag = self.root / "allow-probe-write"
        try:
            self._check_file(flag)
            return True
        except (FileNotFoundError, PermissionError):
            return False

    def read(self):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT marker FROM probe WHERE id=1").fetchone()
        return {"present": row is not None, "marker": row[0] if row else None}

    def write(self):
        if not self.write_enabled():
            return {"status": "BLOCKED", "reason": "LOCAL_WRITE_DISABLED"}
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self.write_enabled():
                return {"status": "BLOCKED", "reason": "LOCAL_WRITE_DISABLED"}
            cursor = conn.execute("INSERT OR IGNORE INTO probe VALUES (1, ?)", (MARKER,))
            return {"status": "SUCCEEDED", "created": cursor.rowcount == 1, "marker": MARKER}
