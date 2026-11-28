"""Fixed disposable validation, not a sandbox for arbitrary repository code."""
from .repository import FixtureRepository


def validate_fixture(repo: FixtureRepository, principal, expected_revision):
    repo.policy.require(principal,"fixture_validate","disposable")
    snapshot=repo.read(principal)
    if snapshot["revision"]!=expected_revision:
        return {"status":"BLOCKED","reason":"REVISION_CONFLICT"}
    # Trusted internal code only, no subprocess and no evaluation of fixture text.
    valid=bool(snapshot["text"].strip())
    return {"status":"SUCCEEDED" if valid else "FAILED",
            "revision":snapshot["revision"],"check":"nonempty_utf8","passed":valid}



# Direct trusted execution in the existing local Linux/WSL account. The
# operator must observe the physical host budget before and during heavy jobs.
# This is not a sandbox and does not claim to measure Windows free space.
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from types import MappingProxyType

from .workspace_profiles import (PROFILES, QA_PROFILES, profile_for, execution_route,
                                 qa_plan, apk_path, read_apk, MAX_APK)
from .workos_auth import private_directory

_TOOLCHAIN = frozenset({"PATH", "JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT",
                        "ANDROID_USER_HOME", "GRADLE_USER_HOME", "PUB_CACHE",
                        "FLUTTER_ROOT", "npm_config_cache"})


def _environment(config):
    if (not isinstance(config, dict) or "PATH" not in config
            or not set(config) <= _TOOLCHAIN):
        raise ValueError("INVALID_LOCAL_TOOLCHAIN")
    for name, value in config.items():
        if (not isinstance(value, str) or not value or len(value) > 4096
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("INVALID_LOCAL_TOOLCHAIN")
        paths = value.split(os.pathsep) if name == "PATH" else [value]
        if any(not Path(path).is_absolute() for path in paths):
            raise ValueError("INVALID_LOCAL_TOOLCHAIN")
    # Reuse the operator's installed tools/caches, not its inherited tokens.
    import pwd
    return {"HOME": pwd.getpwuid(os.getuid()).pw_dir, "LANG": "C.UTF-8",
            "CI": "true", "EXPO_NO_TELEMETRY": "1", "EXPO_NO_DOTENV": "1",
            "EXPO_OFFLINE": "1", **config}


def _group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _command(argv, cwd, env, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return 124, True
    executable = (cwd / argv[0] if argv[0].startswith("./")
                  else shutil.which(argv[0], path=env["PATH"]))
    if executable is None:
        return 127, True
    process = subprocess.Popen([str(executable), *argv[1:]], cwd=cwd, env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True,
                               umask=0o077)
    timed_out = False
    try:
        code = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        timed_out = True
        code = 124
    if timed_out or _group_exists(process.pid):
        # Only signal the process group launched for this command.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if _group_exists(process.pid):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return 124, False
        # A command leaving children behind is not a successful build.
        if not timed_out and code == 0:
            code = 125
    return code, not _group_exists(process.pid)


def _lock_digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("LOCKFILE_UNAVAILABLE")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _adopt_apk(workspace, source, job_id, name):
    source = workspace / source
    if source.is_symlink() or not source.resolve(strict=True).is_relative_to(workspace.resolve(strict=True)):
        raise ValueError("APK_IDENTITY_INVALID")
    import stat
    output = apk_path(workspace.parent, job_id)
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as inp:
        info = os.fstat(inp.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_APK:
            raise ValueError("APK_IDENTITY_INVALID")
        data = inp.read(MAX_APK + 1)
        after = os.fstat(inp.fileno())
        if len(data) != info.st_size or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("APK_IDENTITY_INVALID")
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                           0o600), "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
        info = os.fstat(out.fileno())
    return read_apk(output, (info.st_dev, info.st_ino), name=name)


class WorkspaceWSL:
    """Registered direct profiles, using the existing Jobs effect fence."""

    def __init__(self, toolchains, *, qa_plans=None, qa_signers=None):
        if not isinstance(toolchains, dict) or not toolchains:
            raise ValueError("EXPLICIT_LOCAL_BINDINGS_REQUIRED")
        self.toolchains = {}
        for route, config in toolchains.items():
            project, profile = route.split(":", 1)
            if execution_route(profile, project) != route:
                raise ValueError("INVALID_LOCAL_ROUTE")
            self.toolchains[route] = MappingProxyType(_environment(config))
        required = {route for route in toolchains if route.split(":", 1)[1] in QA_PROFILES}
        qa_plans = {} if qa_plans is None else qa_plans
        qa_signers = {} if qa_signers is None else qa_signers
        if set(qa_plans) != required or not set(qa_signers) <= required:
            raise ValueError("INVALID_QA_BINDINGS")
        self.qa_plans = MappingProxyType({route: qa_plan(route.split(":", 1)[1], data)
                                          for route, data in qa_plans.items()})
        self.qa_signers = MappingProxyType(dict(qa_signers))
        self.toolchains = MappingProxyType(self.toolchains)
        self.routes = frozenset(self.toolchains)
        self._identities = MappingProxyType({
            route: hashlib.sha256(json.dumps(["wsl-direct-v1", route, dict(env)],
                              sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            for route, env in self.toolchains.items()})

    def route(self, profile, project=None):
        key = execution_route(profile, project)
        if key not in self.routes:
            raise PermissionError("PROFILE_UNAVAILABLE")
        return key

    def identities(self):
        return dict(self._identities)

    def binding(self, profile, project=None):
        identity = self._identities[self.route(profile, project)]
        return identity, identity

    def plan_digest(self, profile, project=None):
        plan = self.qa_plans.get(self.route(profile, project))
        return plan.digest() if plan is not None else None

    def execute(self, workspace, row, snapshot):
        request = row["workspace"]
        profile = request["profile"]
        key = self.route(profile, request["project"])
        identity, context = self.binding(profile, request["project"])
        plan = self.qa_plans.get(key)
        signer = self.qa_signers.get(key)
        if (request.get("execution_id") != identity or request.get("context_id") != context
                or row.get("effect_context") != context
                or request.get("qa_plan_sha256") != (plan.digest() if plan else None)
                or request.get("qa_signer_sha256") != (signer.digest if signer else None)
                or snapshot["head"] != request["expected_sha"]
                or snapshot.get("workspace_materialized") is not True):
            raise PermissionError("EXECUTION_BINDING_CHANGED")
        private_directory(workspace)
        env = dict(self.toolchains[key])
        if plan is not None:
            env.update(plan.env)
        flutter = profile.startswith("flutter-")
        lock = workspace / ("pubspec.lock" if flutter else "package-lock.json")
        before = _lock_digest(lock)
        descriptor = profile_for(profile)
        install = (("flutter", "pub", "get", "--offline") if flutter else
                   ("npm", "ci", "--offline", "--no-audit", "--no-fund"))
        if not flutter and profile != "expo-apk-qa":
            install += ("--ignore-scripts",)
        steps = [(install, workspace)]
        if plan is not None and plan.native == "managed-script":
            steps.append((("npm", "run", "prebuild", "--", "--platform", "android",
                           "--no-install"), workspace))
        elif plan is not None and plan.native == "managed-expo":
            steps.append((("./node_modules/.bin/expo", "prebuild", "--platform",
                           "android", "--no-install"), workspace))
        argv = plan.argv if plan is not None else descriptor.argv
        build_dir = workspace / "android" if profile.startswith("expo-apk-") else workspace
        if profile == "expo-apk-debug":
            argv += ("--no-daemon",)
        steps.append((argv, build_dir))
        result = {"execution_id": identity, "execution_environment": "wsl-direct",
                  "workspace_sha256": snapshot["workspace_sha256"],
                  "lock_sha256": before, "cleanup_verified": True}
        deadline = time.monotonic() + 900
        for index, (command, cwd) in enumerate(steps):
            if index == 1 and plan is not None and plan.native.startswith("managed-") and (workspace / "android").exists():
                return {**result, "exit_code": 125, "reason": "MANAGED_LAYOUT_CHANGED"}
            if not cwd.is_dir():
                return {**result, "exit_code": 125, "reason": "PROFILE_LAYOUT_UNAVAILABLE"}
            try:
                code, clean = _command(command, cwd, env, deadline)
            except OSError:
                return {**result, "cleanup_verified": False, "reason": "EXECUTION_UNCERTAIN"}
            if not clean:
                return {**result, "cleanup_verified": False}
            try:
                unchanged = _lock_digest(lock) == before
            except (OSError, ValueError):
                unchanged = False
            if not unchanged:
                return {**result, "exit_code": 125, "reason": "LOCKFILE_CHANGED"}
            if code != 0:
                return {**result, "exit_code": code}
        result["exit_code"] = 0
        if descriptor.artifact_kind == "apk":
            source = (plan.output if plan is not None else
                      "build/app/outputs/flutter-apk/app-debug.apk" if flutter else
                      "android/app/build/outputs/apk/debug/app-debug.apk")
            try:
                result["artifact"] = _adopt_apk(workspace, source, row["id"],
                    "app-qa-unfinalized.apk" if plan is not None else "app-debug.apk")
                if plan is not None:
                    result.update(qa_plan_sha256=plan.digest(), artifact_stage="unfinalized",
                                  qa_delivery_ready=False)
            except (OSError, ValueError):
                result.update(exit_code=125, artifact_error="APK_IDENTITY_INVALID")
        return result
