"""Explicit, local-only Podman storage and rootless runtime for disposable OCI."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from .workos_auth import private_directory, private_file

CONTEXT_ID = re.compile(r"[0-9a-f]{64}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./-]+")
PODMAN = "/usr/bin/podman"
RUNROOT_MAX_BYTES = 50  # Podman 4.9.3 storage path limit.
FIXTURE_TAG = "localhost/project-os-alpine-ci:candidate"
RPM_HOME_FILES = {Path(".rpmdb") / name for name in ("rpmdb.sqlite", "rpmdb.sqlite-shm", "rpmdb.sqlite-wal")}
DIRECTORIES = ("home", "runtime", "graph", "runroot", "libpod", "volumes", "networks", "tmp", "hooks",
               "config", "data", "cache")


class ContextError(PermissionError):
    """A fixed diagnostic safe for local CLI and disposable CI output."""


def file_identity(path):
    info = path.stat()
    return [info.st_dev, info.st_ino]


class PodmanContext:
    """One prepared store. Identity includes the state DB and rootless namespace."""

    def __init__(self, root):
        if os.getuid() == 0 or not SAFE_PATH.fullmatch(str(root)):
            raise ContextError("Canonical private rootless Podman context required")
        if len(os.fsencode(root / "runroot")) > RUNROOT_MAX_BYTES:
            raise ContextError("Podman runroot would exceed 50 bytes; choose a shorter private context path")
        self.root = root

    def configuration(self):
        root = self.root
        return {
            "containers.conf": b'[engine]\ndatabase_backend = "sqlite"\n',
            "storage.conf": (f'[storage]\ndriver = "overlay"\nrunroot = "{root}/runroot"\n'
                             f'graphroot = "{root}/graph"\nrootless_storage_path = "{root}/graph"\n'
                             '[storage.options]\nadditionalimagestores = []\n').encode(),
            "auth.json": b'{"auths":{}}\n',
        }

    def check_layout(self):
        root = self.root
        private_directory(root)
        for name in DIRECTORIES:
            private_directory(root / name)
        for name, content in self.configuration().items():
            path = root / name
            if private_file(path).st_size != len(content) or path.read_bytes() != content:
                raise ContextError("Podman context configuration changed")
        if any((root / "hooks").iterdir()):
            raise ContextError("Podman context hooks must be empty")
        home = root / "home"
        for parent, dirs, files in os.walk(home, followlinks=False):
            for name in dirs:
                info = (Path(parent) / name).lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                    raise ContextError("Unsafe directory in Podman context HOME")
            # Some hosts run RPM package probes during Podman info, even on Ubuntu.
            # This HOME starts empty. Permit the specific runtime DB, never auth/config files.
            for name in files:
                path = Path(parent) / name
                info = path.lstat()
                if (path.relative_to(home) not in RPM_HOME_FILES or not stat.S_ISREG(info.st_mode)
                        or info.st_uid != os.getuid() or info.st_mode & 0o022 or info.st_nlink != 1):
                    raise ContextError("Unexpected file in Podman context HOME")
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            mount = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), line.split()[4])
            if Path(mount).is_relative_to(root):
                raise ContextError("Unexpected mount inside Podman context")
        # Avoid auto-injected host mounts before the fixed child can inspect its mount table.
        for directory in (Path("/usr/share/containers"), Path("/etc/containers"), root / "config/containers"):
            path = directory / "mounts.conf"
            if os.path.lexists(path):
                info = path.stat()
                if (not stat.S_ISREG(info.st_mode) or info.st_size > 65536 or any(
                        line.strip() and not line.lstrip().startswith("#") for line in path.read_text().splitlines())):
                    raise ContextError("Podman automatic host mounts are not allowed")

    def _run(self, *args, timeout=10, capture=False):
        root = self.root
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": str(root / "home"),
               "XDG_RUNTIME_DIR": str(root / "runtime"), "XDG_CONFIG_HOME": str(root / "config"),
               "XDG_DATA_HOME": str(root / "data"), "XDG_CACHE_HOME": str(root / "cache"),
               "TMPDIR": str(root / "tmp"), "REGISTRY_AUTH_FILE": str(root / "auth.json"),
               "CONTAINERS_CONF": str(root / "containers.conf"),
               "CONTAINERS_STORAGE_CONF": str(root / "storage.conf"),
               "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{os.getuid()}/bus"}
        flags = ("--remote=false", "--root", root / "graph", "--runroot", root / "runroot",
                 "--tmpdir", root / "libpod", "--volumepath", root / "volumes",
                 "--network-config-dir", root / "networks", "--hooks-dir", root / "hooks",
                 "--storage-driver=overlay", "--events-backend=file")
        return subprocess.run([PODMAN, *flags, *args], env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.PIPE if args[:1] == ("info",) else subprocess.DEVNULL,
                              timeout=timeout, check=False)

    def _host(self):
        info = self._run("info", "--format", "json", capture=True)
        if info.returncode:
            lines = (info.stderr or b"").decode("utf-8", "replace").splitlines()
            error = next((line.removeprefix("Error: ") for line in reversed(lines)
                          if line.startswith("Error: ")), "no error detail")
            # Podman receives a closed environment and an empty registry auth file.
            # Keep the first error bounded, and redact paths, URLs and opaque IDs.
            error = error.replace(str(self.root), "[context]")
            error = re.sub(r"(?:https?://|/)[^\s\"']+", "[path]", error)
            error = re.sub(r"[A-Za-z0-9_-]{24,}", "[redacted]", error)
            error = re.sub(r"[^ A-Za-z0-9:.,_()\[\]=-]", "?", error)[:160]
            raise ContextError(f"Podman info exit {info.returncode}: {error}")
        if len(info.stdout) > 262144:
            raise ContextError("Podman info exceeds bound")
        data = json.loads(info.stdout)
        host, store = data["host"], data["store"]
        paths = {"graphRoot": "graph", "runRoot": "runroot", "volumePath": "volumes",
                 "imageCopyTmpDir": "tmp", "configFile": "storage.conf"}
        for key, value in paths.items():
            if store.get(key) != str(self.root / value):
                raise ContextError(f"Unexpected Podman storage path field: {key}")
        if (store.get("graphDriverName") != "overlay" or store.get("transientStore") is not False
                or any("additional" in k.lower() for k in (store.get("graphOptions") or {}))
                or not host["security"].get("rootless") is True
                or not host["security"].get("seccompEnabled") is True
                or host.get("cgroupVersion") != "v2" or host.get("databaseBackend") != "sqlite"):
            raise ContextError("Unexpected Podman storage or security configuration")
        return host

    def _identity(self):
        self.check_layout()
        root = self.root
        db = root / "graph/db.sql"
        # Podman SQLite creates a 0644 file inside the owner-private graphroot.
        info = db.lstat()
        if (db.resolve(strict=True) != db or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022 or info.st_nlink != 1):
            raise ContextError("Unknown Podman state database")
        pause = root / "runtime/libpod/tmp/pause.pid"
        if pause.resolve(strict=True) != pause or not 0 < private_file(pause).st_size <= 32:
            raise ContextError("Rootless Podman pause identity unavailable")
        pid = pause.read_text().strip()
        if not re.fullmatch(r"[1-9][0-9]*", pid):
            raise ContextError("Rootless Podman pause identity unavailable")
        ns = Path("/proc") / pid / "ns"
        values = ["podman-context-v1", os.getuid(), str(root), Path("/proc/sys/kernel/random/boot_id").read_text()]
        values += [file_identity(p) for p in (root, *(root / name for name in DIRECTORIES), db, pause,
                                             ns / "user", ns / "mnt")]
        return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()

    def identity(self, expected=None):
        private_directory(self.root)
        path = self.root / "identity"
        if private_file(path).st_size != 65:
            raise ContextError("Unknown Podman context")
        identity = path.read_text().strip()
        if (not CONTEXT_ID.fullmatch(identity) or (expected is not None and identity != expected)
                or identity != self._identity()):
            raise ContextError("Podman context identity differs")
        return identity

    def host(self, expected):
        self.identity(expected)
        result = self._host()
        self.identity(expected)
        return result

    def run(self, expected, *args, timeout=10, capture=False):
        self.identity(expected)
        result = self._run(*args, timeout=timeout, capture=capture)
        self.identity(expected)
        return result

    def prepare(self):
        if self.root.resolve() != self.root:
            raise ValueError("Canonical Podman context path required")
        self.root.mkdir(mode=0o700)
        for name in DIRECTORIES:
            (self.root / name).mkdir(mode=0o700)
        for name, content in self.configuration().items():
            with (self.root / name).open("xb") as file:
                file.write(content)
        self.check_layout()
        self._host()
        try:
            identity = self._identity()
        except (FileNotFoundError, PermissionError) as exc:
            if isinstance(exc, ContextError):
                raise
            db = self.root / "graph/db.sql"
            pause = self.root / "runtime/libpod/tmp/pause.pid"
            part = "state DB" if not db.is_file() else "pause file" if not pause.is_file() else "pause namespace"
            raise ContextError(f"Podman {part} unavailable during prepare ({type(exc).__name__})") from None
        with (self.root / "identity").open("x") as file:
            file.write(identity + "\n")
        return identity

    def check_image(self, identity, image, digest=None):
        result = self.run(identity, "image", "inspect", "--format", "{{.Digest}}", image, capture=True)
        if result.returncode or result.stdout.strip() != (digest or image.rsplit("@", 1)[-1]).encode():
            raise ContextError("Exact digest absent from the Podman context")

    def require_import(self, identity, image):
        self.identity(identity)
        pin = self.root / "image"
        if private_file(pin).st_size != len(image) + 1 or pin.read_text() != image + "\n":
            raise ContextError("Fixture image was not imported into this context")
        self.check_image(identity, image)

    def import_layout(self, layout, digest):
        if not DIGEST.fullmatch(digest) or not SAFE_PATH.fullmatch(str(layout)):
            raise ValueError("Canonical OCI layout and locked digest required")
        private_directory(layout.parent)
        if layout.resolve(strict=True) != layout or not layout.is_dir():
            raise ValueError("Canonical OCI layout required")
        index = layout / "index.json"
        if index.stat().st_size > 65536:
            raise ValueError("OCI index too large")
        manifests = json.loads(index.read_bytes())["manifests"]
        if len(manifests) != 1 or manifests[0]["digest"] != digest:
            raise ValueError("Unexpected OCI layout digest")
        identity = self.identity()
        pin = self.root / "image"
        image = FIXTURE_TAG.split(":", 1)[0] + "@" + digest
        with (self.root / "identity").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.host(identity)
            if not os.path.lexists(pin):
                loaded = self.run(identity, "pull", "--quiet", f"oci:{layout}:candidate", timeout=120, capture=True)
                image_id = loaded.stdout.strip().decode("ascii")
                if loaded.returncode or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", image_id):
                    raise ValueError("OCI layout import failed")
                self.check_image(identity, image_id, digest)
                if self.run(identity, "tag", image_id, FIXTURE_TAG).returncode:
                    raise ValueError("OCI image tag failed")
                self.check_image(identity, image)
                with pin.open("x") as file:
                    file.write(image + "\n")
                    file.flush()
                    os.fsync(file.fileno())
            self.require_import(identity, image)
        return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("prepare")
    acquire = sub.add_parser("import-layout")
    acquire.add_argument("layout", type=Path)
    acquire.add_argument("digest")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        context = PodmanContext(args.context)
        if args.operation == "prepare":
            context.prepare()
            print("Private Podman context prepared")
        else:
            print(context.import_layout(args.layout, args.digest))
    except ContextError as exc:
        parser.exit(1, f"PODMAN_CONTEXT_BLOCKED: {exc}\n")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"PODMAN_CONTEXT_BLOCKED during {args.operation} ({type(exc).__name__})\n")


if __name__ == "__main__":
    main()
