"""Local-only candidate validation and synthetic APK backend; no service or MCP registration.

An image binding is supplied by trusted local test/operator code, never a tool
argument. No production image is approved or installed by this module.
"""
import os
import subprocess
from types import MappingProxyType

from .isolated import IMAGE, ALPINE_BASELINE, ALPINE_FIXTURE_ONLY, container_name, container_absent
from .podman_context import SAFE_PATH, PodmanContext
from .workspace_profiles import profile_for, artifact_identity, execution_route, QA_PROFILES, qa_plan
from .workos_auth import private_directory, private_file

VALIDATION = MappingProxyType({
    "flutter-analyze": ("pubspec.lock", "flutter pub get --offline"),
    "flutter-test": ("pubspec.lock", "flutter pub get --offline"),
    "expo-typecheck": ("package-lock.json", "npm ci --offline --ignore-scripts --no-audit --no-fund"),
    "expo-test": ("package-lock.json", "npm ci --offline --ignore-scripts --no-audit --no-fund"),
    "flutter-apk-debug": ("pubspec.lock", "flutter pub get --offline"),
    "expo-apk-debug": ("package-lock.json", "npm ci --offline --ignore-scripts --no-audit --no-fund"),
    "flutter-apk-qa": ("pubspec.lock", "flutter pub get --offline"),
    "expo-apk-qa": ("package-lock.json", "npm ci --offline --no-audit --no-fund"),
})

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


class WorkspacePodman:
    def __init__(self, context, images, *, qa_plans=None):
        if not isinstance(images, dict) or not images:
            raise ValueError("Explicit local candidate bindings required")
        if not all(isinstance(key, str) for key in images):
            raise ValueError("Invalid validation route")
        scoped = {":" in key for key in images}
        if len(scoped) != 1:
            raise ValueError("Mixed execution binding scopes")
        self.project_scoped = scoped.pop()
        for key, image in images.items():
            if self.project_scoped:
                project, profile = key.split(":", 1)
                if execution_route(profile, project) != key:
                    raise ValueError("Invalid validation route")
            else:
                profile = key
            if (profile not in VALIDATION or not isinstance(image, str) or not IMAGE.fullmatch(image)
                    or image.rsplit("@", 1)[-1] in {ALPINE_BASELINE, ALPINE_FIXTURE_ONLY}):
                raise ValueError("Invalid validation image binding")
        contexts = ({profile: context for profile in images}
                    if isinstance(context, PodmanContext) else context)
        if (not isinstance(contexts, dict) or set(contexts) != set(images)
                or any(not isinstance(item, PodmanContext) for item in contexts.values())):
            raise ValueError("Explicit context per profile required")
        identities, pins = {}, {}
        for profile, item in contexts.items():
            identity = item.identity()
            if identity in pins and pins[identity] != images[profile]:
                raise ValueError("One pinned image per context required")
            identities[profile] = identity
            pins[identity] = images[profile]
        required = {key for key in images if key.rsplit(":", 1)[-1] in QA_PROFILES}
        qa_plans = {} if qa_plans is None else qa_plans
        if (not isinstance(qa_plans, dict) or set(qa_plans) != required
                or (required and not self.project_scoped)):
            raise ValueError("Explicit project QA plans required")
        self.qa_plans = MappingProxyType({
            key: qa_plan(key.rsplit(":", 1)[-1], value) for key, value in qa_plans.items()})
        self.contexts = MappingProxyType(dict(contexts))
        self.images = MappingProxyType(dict(images))
        self.context_ids = MappingProxyType(identities)

    def identities(self):
        checked = set()
        for profile, context in self.contexts.items():
            identity = self.context_ids[profile]
            if identity not in checked:
                if context.identity(identity) != identity:
                    raise PermissionError("EXECUTION_CONTEXT_CHANGED")
                checked.add(identity)
        return dict(self.context_ids)

    def identity(self):
        identities = set(self.identities().values())
        if len(identities) != 1:
            raise ValueError("Select a registered profile context")
        return next(iter(identities))

    def route(self, profile, project=None):
        if self.project_scoped and project is None:
            raise PermissionError("PROJECT_BINDING_REQUIRED")
        key = execution_route(profile, project if self.project_scoped else None)
        if key not in self.images:
            raise PermissionError("PROFILE_UNAVAILABLE")
        return key

    def binding(self, profile, project=None):
        key = self.route(profile, project)
        image, context = self.images[key], self.contexts[key]
        identity = self.context_ids[key]
        if context.identity(identity) != identity:
            raise PermissionError("EXECUTION_CONTEXT_CHANGED")
        context.require_import(identity, image)
        return image.rsplit("@", 1)[-1], identity

    def plan_digest(self, profile, project=None):
        plan = self.qa_plans.get(self.route(profile, project))
        return plan.digest() if plan is not None else None

    def execute(self, workspace, row, snapshot):
        request = row["workspace"]
        profile = request["profile"]
        key = self.route(profile, request["project"])
        image_id, identity = self.binding(profile, request["project"])
        context = self.contexts[key]
        plan = self.qa_plans.get(key)
        if (request.get("qa_plan_sha256") != (plan.digest() if plan else None)
                or request.get("context_id") != identity or row.get("effect_context") != identity
                or request["image_id"] != image_id or snapshot["head"] != request["expected_sha"]
                or snapshot.get("workspace_materialized") is not True):
            raise PermissionError("EXECUTION_BINDING_CHANGED")
        token = row["effect_token"]
        name = container_name(token)
        private_directory(workspace)
        if not SAFE_PATH.fullmatch(str(workspace)):
            raise PermissionError("WORKSPACE_MOUNT_UNAVAILABLE")
        context.host(identity)
        if not container_absent(context, identity, token):
            return {"image_id": image_id, "cleanup_verified": False}
        lock, install = VALIDATION[profile]
        # APK candidates use the same container and effect ledger. Only the
        # fixed, precreated job output file is writable on the host.
        descriptor = profile_for(profile)
        apk = descriptor.artifact_kind == "apk"
        setup = "set -eu; cmp /source/" + lock + " " + lock + "; "
        output_args = []
        if apk:
            output = apk_path(workspace.parent, row["id"])
            with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                   0o600), "wb") as stream:
                info = os.fstat(stream.fileno())
                original = (info.st_dev, info.st_ino)
            output_args = ["--volume", f"{output}:/output.apk:rw",
                           "--ulimit=fsize=536870912:536870912",
                           "--env=EXPO_OFFLINE=1", "--env=EXPO_NO_TELEMETRY=1"]
            setup += 'test ! -e /fixture/build; test ! -e /fixture/android; '
            if plan is None:
                setup += ('test "$ANDROID_USER_HOME" = /home/smoke/.android; '
                          'test -s "$ANDROID_USER_HOME/debug.keystore"; '
                          'test ! -L "$ANDROID_USER_HOME/debug.keystore"; ')
        setup += ("cp -a /source/. /fixture/; " + install +
                  "; cmp /source/" + lock + " " + lock + "; ")
        argv = descriptor.argv
        if plan is not None:
            output_args += ["--env=EXPO_NO_DOTENV=1",
                            *("--env=" + key + "=" + value for key, value in plan.env)]
            if plan.native == "managed-script":
                setup += 'test ! -e android; npm run prebuild -- --platform android --no-install; '
            elif plan.native == "managed-expo":
                setup += 'test ! -e android; ./node_modules/.bin/expo prebuild --platform android --no-install; '
            setup += 'test -d android; cmp /source/' + lock + ' ' + lock + '; '
            setup += 'apk="$1"; shift; '
            setup += ('(cd android; "$@"); ' if profile == "expo-apk-qa" else '"$@"; ')
            setup += ('cmp /source/' + lock + ' ' + lock + '; '
                      'test -f "$apk"; test ! -L "$apk"; cat "$apk" > /output.apk')
            argv = (plan.output, *plan.argv)
        elif apk:
            setup += ('"$@"; apk=build/app/outputs/flutter-apk/app-debug.apk; '
                      if profile == "flutter-apk-debug" else
                      'cd android; "$@"; apk=app/build/outputs/apk/debug/app-debug.apk; ')
            setup += ('test -f "$apk"; test ! -L "$apk"; '
                      '/opt/android-sdk/build-tools/36.0.0/apksigner verify "$apk"; '
                      '/opt/android-sdk/build-tools/36.0.0/aapt dump badging "$apk" > /dev/null; '
                      'cat "$apk" > /output.apk')
        else:
            setup += 'exec "$@"'
        args = ["run", "--rm", "--name", name, "--label", "io.project-os.fixture=" + token,
                "--pull=never", "--network=none", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--http-proxy=false", "--image-volume=ignore",
                "--pid=private", "--ipc=private", "--cgroupns=private", "--uts=private",
                "--pids-limit=512", "--memory=5g", "--cpus=2", "--userns=keep-id",
                "--passwd=false", "--user", f"{os.getuid()}:{os.getgid()}",
                "--volume", f"{workspace}:/source:ro", *output_args, "--workdir", "/fixture",
                "--entrypoint", "/bin/sh", self.images[key], "-c", setup, "profile", *argv]
        try:
            result = context.run(identity, *args, timeout=900, capture=False)
            # No automatic retry or cleanup on uncertain launch/timeout.
            if not container_absent(context, identity, token):
                return {"image_id": image_id, "cleanup_verified": False}
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            return {"image_id": image_id, "cleanup_verified": False}
        evidence = {"image_id": image_id, "exit_code": result.returncode,
                    "cleanup_verified": True, "workspace_sha256": snapshot["workspace_sha256"]}
        if apk and result.returncode == 0:
            try:
                evidence["artifact"] = read_apk(output, original,
                    name="app-qa-unfinalized.apk" if plan is not None else "app-debug.apk")
                if plan is not None:
                    evidence.update(qa_plan_sha256=plan.digest(), artifact_stage="unfinalized",
                                    qa_delivery_ready=False)
            except (OSError, ValueError):
                evidence.update(exit_code=125, artifact_error="APK_IDENTITY_INVALID")
        return evidence
