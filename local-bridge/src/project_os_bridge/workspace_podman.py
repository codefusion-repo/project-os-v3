"""Local-only candidate validation backend; no service or MCP registration.

An image binding is supplied by trusted local test/operator code, never a tool
argument. No production image is approved or installed by this module.
"""
import os
import subprocess
from types import MappingProxyType

from .isolated import IMAGE, ALPINE_BASELINE, ALPINE_FIXTURE_ONLY, container_name, container_absent
from .podman_context import SAFE_PATH, PodmanContext
from .workspace_profiles import profile_for
from .workos_auth import private_directory

VALIDATION = MappingProxyType({
    "flutter-analyze": ("pubspec.lock", "flutter pub get --offline"),
    "flutter-test": ("pubspec.lock", "flutter pub get --offline"),
    "expo-typecheck": ("package-lock.json", "npm ci --offline --ignore-scripts --no-audit --no-fund"),
    "expo-test": ("package-lock.json", "npm ci --offline --ignore-scripts --no-audit --no-fund"),
})


class WorkspacePodman:
    def __init__(self, context, images):
        if not isinstance(context, PodmanContext) or not isinstance(images, dict) or not images:
            raise ValueError("Explicit local candidate bindings required")
        if any(profile not in VALIDATION or not isinstance(image, str) or not IMAGE.fullmatch(image)
               or image.rsplit("@", 1)[-1] in {ALPINE_BASELINE, ALPINE_FIXTURE_ONLY}
               for profile, image in images.items()):
            raise ValueError("Invalid validation image binding")
        self.context = context
        self.images = MappingProxyType(dict(images))
        self.context_id = context.identity()

    def identity(self):
        return self.context.identity(self.context_id)

    def binding(self, profile):
        if profile not in self.images:
            raise PermissionError("PROFILE_UNAVAILABLE")
        image = self.images[profile]
        self.identity()
        self.context.require_import(self.context_id, image)
        return image.rsplit("@", 1)[-1], self.context_id

    def execute(self, workspace, row, snapshot):
        request = row["workspace"]
        profile = request["profile"]
        image_id, identity = self.binding(profile)
        if (request.get("context_id") != identity or row.get("effect_context") != identity
                or request["image_id"] != image_id or snapshot["head"] != request["expected_sha"]
                or snapshot.get("workspace_materialized") is not True):
            raise PermissionError("EXECUTION_BINDING_CHANGED")
        token = row["effect_token"]
        name = container_name(token)
        private_directory(workspace)
        if not SAFE_PATH.fullmatch(str(workspace)):
            raise PermissionError("WORKSPACE_MOUNT_UNAVAILABLE")
        self.context.host(identity)
        if not container_absent(self.context, identity, token):
            return {"image_id": image_id, "cleanup_verified": False}
        lock, install = VALIDATION[profile]
        # Image contract: reviewed offline toolchain/cache, /fixture writable
        # only in the disposable container layer. No writable host mount.
        setup = ("set -eu; cp -a /source/. /fixture/; " + install +
                 "; cmp /source/" + lock + " " + lock + '; exec "$@"')
        argv = profile_for(profile).argv
        args = ["run", "--rm", "--name", name, "--label", "io.project-os.fixture=" + token,
                "--pull=never", "--network=none", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--http-proxy=false", "--image-volume=ignore",
                "--pid=private", "--ipc=private", "--cgroupns=private", "--uts=private",
                "--pids-limit=512", "--memory=5g", "--cpus=2", "--userns=keep-id",
                "--passwd=false", "--user", f"{os.getuid()}:{os.getgid()}",
                "--volume", f"{workspace}:/source:ro", "--workdir", "/fixture",
                "--entrypoint", "/bin/sh", self.images[profile], "-c", setup, "profile", *argv]
        try:
            result = self.context.run(identity, *args, timeout=900, capture=False)
            # No automatic retry or cleanup on uncertain launch/timeout.
            if not container_absent(self.context, identity, token):
                return {"image_id": image_id, "cleanup_verified": False}
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            return {"image_id": image_id, "cleanup_verified": False}
        return {"image_id": image_id, "exit_code": result.returncode,
                "cleanup_verified": True, "workspace_sha256": snapshot["workspace_sha256"]}
