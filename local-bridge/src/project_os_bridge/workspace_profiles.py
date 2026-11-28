"""Closed registered profile descriptors for direct local execution."""
import re
import os
import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType

from .workos_auth import private_file


@dataclass(frozen=True)
class Profile:
    required: tuple[str, ...]
    argv: tuple[str, ...]
    artifact_kind: str | None = None


FLUTTER = ("pubspec.yaml", "pubspec.lock")
EXPO = ("package.json", "package-lock.json")
PROFILES = MappingProxyType({
    "flutter-analyze": Profile(FLUTTER, ("flutter", "analyze", "--no-pub")),
    "flutter-test": Profile(FLUTTER, ("flutter", "test", "--no-pub")),
    "flutter-apk-debug": Profile(
        FLUTTER + ("android/app/src/main/AndroidManifest.xml",),
        ("flutter", "build", "apk", "--debug", "--no-pub"), "apk"),
    "expo-typecheck": Profile(EXPO, ("npm", "run", "typecheck")),
    "expo-test": Profile(EXPO, ("npm", "run", "test")),
    # Native generation and Gradle/toolchain setup use installed local tools.
    # APK build command runs from the generated android/ directory, never ADB.
    # Managed Expo projects need not have an android/ directory in Git.
    "expo-apk-debug": Profile(EXPO, ("./gradlew", "--offline", ":app:assembleDebug"), "apk"),
    "flutter-apk-qa": Profile(FLUTTER + ("android/app/src/main/AndroidManifest.xml",),
        ("flutter", "build", "apk", "--release", "--no-pub",
         "--target-platform", "android-arm64,android-x64"), "apk"),
    "expo-apk-qa": Profile(EXPO, ("./gradlew", "--offline", ":app:assembleRelease",
        ":app:lintVitalRelease", "-PreactNativeArchitectures=arm64-v8a,x86_64",
        "--no-daemon", "--max-workers=2"), "apk"),
})
QA_PROFILES = frozenset({"flutter-apk-qa", "expo-apk-qa"})


@dataclass(frozen=True)
class QAPlan:
    argv: tuple[str, ...]
    native: str
    output: str
    env: tuple[tuple[str, str], ...]

    def digest(self):
        return hashlib.sha256(json.dumps([self.argv, self.native, self.output, self.env],
            separators=(",", ":")).encode()).hexdigest()


def qa_plan(profile, data):
    """Local reviewed public configuration; no caller shell or signing material."""
    if profile not in QA_PROFILES or not isinstance(data, dict):
        raise ValueError("INVALID_QA_PLAN")
    def pairs(values, pattern):
        if (not isinstance(values, dict) or len(values) > 32
                or any(not isinstance(k, str) or not re.fullmatch(pattern, k)
                       or not isinstance(v, str) or len(v) > 2048
                       or any(ord(ch) < 32 or ord(ch) == 127 for ch in v)
                       for k, v in values.items())):
            raise ValueError("INVALID_QA_PUBLIC_CONFIG")
        return tuple(sorted(values.items()))
    argv = PROFILES[profile].argv
    if profile == "flutter-apk-qa":
        if not set(data) <= {"dart_defines", "build_number"}:
            raise ValueError("INVALID_QA_PLAN")
        number = data.get("build_number")
        if number is not None:
            if type(number) is not int or not 1 <= number <= 2100000000:
                raise ValueError("INVALID_QA_VERSION")
            argv += ("--build-number=" + str(number),)
        argv += tuple("--dart-define=" + k + "=" + v for k, v in
                      pairs(data.get("dart_defines", {}), r"[A-Za-z_][A-Za-z0-9_]{0,79}"))
        return QAPlan(argv, "native", "build/app/outputs/flutter-apk/app-release.apk", ())
    if not set(data) <= {"native", "public_env"}:
        raise ValueError("INVALID_QA_PLAN")
    native = data.get("native", "native")
    if native not in ("native", "managed-expo", "managed-script"):
        raise ValueError("INVALID_QA_NATIVE")
    env = pairs(data.get("public_env", {}), r"EXPO_PUBLIC_[A-Za-z0-9_]{1,64}")
    return QAPlan(argv, native, "android/app/build/outputs/apk/release/app-release.apk", env)


def profile_for(name):
    if not isinstance(name, str) or name not in PROFILES:
        raise ValueError("INVALID_WORKSPACE_PROFILE")
    return PROFILES[name]


def execution_route(profile, project=None):
    profile_for(profile)
    if project is None:
        return profile  # Existing dedicated CI candidate only.
    if not isinstance(project, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", project):
        raise ValueError("INVALID_WORKSPACE_PROJECT")
    return project + ":" + profile


def artifact_identity(kind, name, data):
    """Identity of observed bytes; not a package/signature attestation."""
    import hashlib
    if kind not in {"zip", "apk"} or not isinstance(data, bytes):
        raise ValueError("INVALID_ARTIFACT")
    return {"kind": kind, "artifact": name, "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data)}


MAX_APK = 256 * 1024 * 1024


def apk_path(state, job_id):
    return state / ("apk-" + job_id + ".apk")


def read_apk_bytes(path, original):
    info = private_file(path)
    if (info.st_dev, info.st_ino) != original or not 0 < info.st_size <= MAX_APK:
        raise ValueError("APK_IDENTITY_INVALID")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != original or opened.st_size != info.st_size:
            raise ValueError("APK_IDENTITY_INVALID")
        raw = stream.read(MAX_APK + 1)
        after = os.fstat(stream.fileno())
        current = private_file(path)
        def observed(st):
            return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns
        if len(raw) != info.st_size or observed(info) != observed(after) or observed(after) != observed(current):
            raise ValueError("APK_IDENTITY_INVALID")
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return raw


def read_apk(path, original, *, name="app-debug.apk"):
    return artifact_identity("apk", name, read_apk_bytes(path, original))
