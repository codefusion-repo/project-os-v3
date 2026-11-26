"""Closed, internal profile descriptors; no runtime backend is enabled."""
from dataclasses import dataclass
from types import MappingProxyType


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
    "expo-test": Profile(EXPO, ("npm", "run", "test", "--", "--runInBand")),
    # Native generation and Gradle/toolchain setup belong to the future backend.
    # APK build command runs from the generated android/ directory, never ADB.
    # Managed Expo projects need not have an android/ directory in Git.
    "expo-apk-debug": Profile(EXPO, ("./gradlew", "--offline", ":app:assembleDebug"), "apk"),
})


def profile_for(name):
    if not isinstance(name, str) or name not in PROFILES:
        raise ValueError("INVALID_WORKSPACE_PROFILE")
    return PROFILES[name]


def artifact_identity(kind, name, data):
    """Identity of observed bytes; not a package/signature attestation."""
    import hashlib
    if kind not in {"zip", "apk"} or not isinstance(data, bytes):
        raise ValueError("INVALID_ARTIFACT")
    return {"kind": kind, "artifact": name, "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data)}
