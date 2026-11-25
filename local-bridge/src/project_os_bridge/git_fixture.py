"""Bridge-created Git fixture only; no adopted repository, remote or caller path."""
import fcntl
import hashlib
import os
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

from .core import Policy

FILE = "fixture.txt"
MAX_PATCH = 65536
SHA = re.compile(r"[0-9a-f]{40}")


class GitFixture:
    def __init__(self, root: Path, policy: Policy):
        self.root = root
        self.policy = policy
        self.repo = root / "repo"
        self.worktree = root / "worktree"
        self._check_root()

    def _check_root(self):
        if not self.root.is_absolute() or self.root.resolve(strict=True) != self.root:
            raise PermissionError("Canonical private root required")
        st = self.root.stat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise PermissionError("Private root required")

    @contextmanager
    def _lock(self):
        self._check_root()
        fd = os.open(self.root / "git-fixture.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_mode & 0o077:
                raise PermissionError("Unsafe lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _git(self, directory, *args, data=None):
        # Never inherit credential helpers, aliases, hooks, global/system config or caller environment.
        env = {"PATH":"/usr/bin:/bin","HOME":str(self.root),"GIT_CONFIG_NOSYSTEM":"1",
               "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0",
               "GIT_CONFIG_COUNT":"0","LC_ALL":"C"}
        result = subprocess.run(["/usr/bin/git","-c","core.hooksPath=/dev/null",
                                 "-c","core.fsmonitor=false","-c","credential.helper=",
                                 "-c","core.autocrlf=false","-C",str(directory),*args],
                                input=data,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                env=env,timeout=15,check=False)
        if result.returncode:
            raise RuntimeError("GIT_OPERATION_FAILED")
        if len(result.stdout)>262144:
            raise ValueError("GIT_OUTPUT_LIMIT")
        return result.stdout

    def _directory(self, path):
        if path.is_symlink() or not path.is_dir() or path.resolve(strict=True)!=path:
            raise PermissionError("Unsafe fixture checkout")

    def initialize(self, principal):
        self.policy.require(principal,"git_prepare","disposable")
        with self._lock():
            # Refuse any existing target rather than adopt an unknown repository.
            if os.path.lexists(self.repo) or os.path.lexists(self.worktree):
                raise FileExistsError("Fixture already initialized")
            self.repo.mkdir(mode=0o700)
            self._git(self.repo,"init","--template=","--object-format=sha1","-b","fixture")
            (self.repo / FILE).write_text("before\n",encoding="utf-8")
            self._git(self.repo,"add","--",FILE)
            self._git(self.repo,"-c","user.name=Project OS Fixture","-c","user.email=fixture@example.invalid",
                      "commit","--no-gpg-sign","-m","initial disposable fixture")
            return self._git(self.repo,"rev-parse","HEAD").decode().strip()

    def prepare(self, principal, expected_sha):
        self.policy.require(principal,"git_prepare","disposable")
        if not isinstance(expected_sha,str) or not SHA.fullmatch(expected_sha):
            raise ValueError("Full fixture SHA required")
        with self._lock():
            self._directory(self.repo)
            if self._git(self.repo,"rev-parse","HEAD").decode().strip()!=expected_sha:
                raise ValueError("HEAD_CONFLICT")
            if os.path.lexists(self.worktree):
                raise FileExistsError("Worktree already exists")
            self._git(self.repo,"worktree","add","--detach",str(self.worktree),expected_sha)
            return self._snapshot()

    def _snapshot(self):
        self._directory(self.worktree)
        head=self._git(self.worktree,"rev-parse","HEAD").decode().strip()
        # Only the fixed tracked file is accepted; reject untracked/unstaged changes.
        if self._git(self.worktree,"ls-files","-z") != b"fixture.txt\0":
            raise PermissionError("Unexpected tracked paths")
        if self._git(self.worktree,"ls-files","--others","--exclude-standard","-z"):
            raise PermissionError("Unexpected untracked paths")
        if self._git(self.worktree,"diff","--no-ext-diff","--no-textconv","--",FILE):
            raise ValueError("UNSTAGED_CHANGES")
        fd=os.open(self.worktree / FILE,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,"rb") as f:
            st=os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=os.getuid():
                raise PermissionError("Unsafe fixture file")
            data=f.read(MAX_PATCH+1)
        if len(data)>MAX_PATCH or b"\0" in data:
            raise ValueError("Invalid fixture data")
        text=data.decode("utf-8")
        return {"head":head,"revision":hashlib.sha256(data).hexdigest(),"text":text}

    def snapshot(self, principal):
        self.policy.require(principal,"git_read","disposable")
        with self._lock():
            return self._snapshot()

    def apply_patch(self, principal, expected_sha, expected_revision, patch):
        self.policy.require(principal,"git_patch","disposable")
        if not isinstance(patch,str) or len(patch.encode("utf-8"))>MAX_PATCH or "\0" in patch:
            raise ValueError("Invalid patch")
        # Deliberately narrow grammar: one normal text diff, no modes, renames,
        # binary data, extra files or arbitrary paths. Git validates hunk syntax.
        lines=patch.splitlines()
        if len(lines)<4 or lines[:3]!=["diff --git a/fixture.txt b/fixture.txt","--- a/fixture.txt","+++ b/fixture.txt"]:
            raise ValueError("Only fixed fixture patch allowed")
        if not lines[3].startswith("@@ ") or any(not l.startswith((" ","+","-","@@ ","\\ No newline at end of file")) for l in lines[3:]):
            raise ValueError("Unexpected patch metadata")
        if any(l.startswith(("--- ","+++ ")) for l in lines[3:]):
            raise ValueError("Additional file headers denied")
        data=patch.encode("utf-8")
        with self._lock():
            before=self._snapshot()
            if before["head"]!=expected_sha or before["revision"]!=expected_revision:
                raise ValueError("REVISION_CONFLICT")
            if not re.fullmatch(rb"\d+\t\d+\tfixture\.txt\0",self._git(self.worktree,"apply","--numstat","-z","-",data=data)):
                raise ValueError("Unexpected patch paths")
            self._git(self.worktree,"apply","--check","--index","-",data=data)
            self._git(self.worktree,"apply","--index","-",data=data)
            return self._snapshot()

    def diff(self, principal):
        self.policy.require(principal,"git_read","disposable")
        with self._lock():
            snapshot=self._snapshot()
            return {**snapshot,"diff":self._git(self.worktree,"diff","--cached","--no-ext-diff","--no-textconv","--",FILE).decode("utf-8")}
