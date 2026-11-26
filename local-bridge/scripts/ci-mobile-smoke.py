"""CI-only mobile toolchain smoke: trusted synthetic Git source, durable prepare,
then offline container validation. No local execution backend or grants.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
import io
import stat
import tarfile

from project_os_bridge.core import Jobs, Policy
from project_os_bridge.workspace_jobs import MARKER, RUNTIME, submit_workspace
from project_os_bridge.workspace_profiles import PROFILES, artifact_identity
from project_os_bridge.worker import run_pending
from project_os_bridge.podman_context import PodmanContext
from project_os_bridge.workspace_podman import WorkspacePodman

FLUTTER_VERSION = "3.35.7"
FLUTTER_SHA256 = "146df531f9ac6a11a918013c1a70faafc053d4811c8cb69a413fd70748d51c3d"
NODE_VERSION = "22.16.0"
BASE = "docker.io/library/node@sha256:71bcbb3b215b3fa84b5b167585675072f4c270855e37a599803f1a58141a0716"
EXPO_VERSION = "54.0.37"
RN_VERSION = "0.81.5"

FLUTTER_FILES = {
    "pubspec.yaml": """name: synthetic_mobile
publish_to: none
environment:
  sdk: '>=3.9.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
dev_dependencies:
  flutter_test:
    sdk: flutter
""",
    "lib/main.dart": """import 'package:flutter/widgets.dart';
void main() => runApp(const Directionality(
  textDirection: TextDirection.ltr, child: Text('Bridge smoke')));
""",
    "test/widget_test.dart": """import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
void main() {
  testWidgets('renders synthetic label', (tester) async {
    await tester.pumpWidget(const Directionality(
      textDirection: TextDirection.ltr, child: Text('Bridge smoke')));
    expect(find.text('Bridge smoke'), findsOneWidget);
  });
}
""",
}
EXPO_FILES = {
    "package.json": json.dumps({
        "name": "synthetic-mobile", "version": "1.0.0", "private": True,
        "main": "index.tsx",
        "scripts": {"typecheck": "tsc --noEmit", "test": "node --test"},
        "dependencies": {"expo": EXPO_VERSION, "react": "19.1.0",
                         "react-native": RN_VERSION},
        "devDependencies": {"typescript": "5.9.2", "@types/react": "19.1.10"},
    }),
    "app.json": '{"expo":{"name":"Synthetic mobile","slug":"synthetic-mobile","version":"1.0.0","android":{"package":"com.example.synthetic_expo","versionCode":1}}}',
    "tsconfig.json": json.dumps({"compilerOptions": {"strict": True, "skipLibCheck": True,
        "jsx": "react-jsx", "moduleResolution": "bundler", "module": "ESNext",
        "target": "ES2022", "noEmit": True}, "include": ["index.tsx"]}),
    "index.tsx": """import { registerRootComponent } from 'expo';
import { Text } from 'react-native';
function App() { return <Text>Bridge smoke</Text>; }
registerRootComponent(App);
""",
    "value.cjs": "exports.label = () => 'Bridge smoke';\n",
    "value.test.cjs": """const { test } = require('node:test');
const assert = require('node:assert/strict');
const { label } = require('./value.cjs');
test('synthetic value', () => assert.equal(label(), 'Bridge smoke'));
""",
}

COMMON = """ARG BASE
FROM $BASE
ARG UID
ARG GID
ENV HOME=/home/smoke CI=1 FLUTTER_SUPPRESS_ANALYTICS=true EXPO_NO_TELEMETRY=1
RUN mkdir -p /home/smoke /fixture && chown "$UID:$GID" /home/smoke /fixture
WORKDIR /fixture
"""
FLUTTER_SETUP = """RUN apt-get update && apt-get install -y --no-install-recommends git curl xz-utils unzip libglu1-mesa libgtk-3-0 && rm -rf /var/lib/apt/lists/*
RUN curl --fail --show-error --silent --location --retry 2 https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.35.7-stable.tar.xz -o /tmp/flutter.tar.xz && echo '146df531f9ac6a11a918013c1a70faafc053d4811c8cb69a413fd70748d51c3d  /tmp/flutter.tar.xz' | sha256sum -c - && tar -xJf /tmp/flutter.tar.xz -C /opt && rm /tmp/flutter.tar.xz && chown -R "$UID:$GID" /opt/flutter
ENV PATH=/opt/flutter/bin:$PATH
COPY --chown=$UID:$GID seed/ /fixture/
USER $UID:$GID
RUN flutter --version && flutter config --no-analytics && flutter precache --linux && flutter pub get
"""
EXPO_SETUP = """COPY --chown=$UID:$GID seed/ /fixture/
USER $UID:$GID
RUN test "$(node --version)" = v22.16.0 && npm --version && npm install --package-lock-only --ignore-scripts --no-audit --no-fund && npm ci --ignore-scripts --no-audit --no-fund
"""

# CI-only candidate Android SDK. Official archive checksum:
# https://developer.android.com/studio#command-line-tools-only
ANDROID_SETUP = """USER root
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jdk-headless curl unzip && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ANDROID_HOME=/opt/android-sdk ANDROID_SDK_ROOT=/opt/android-sdk
# Numeric runner UID need not have an NSS account in the image. Android Gradle
# must resolve its synthetic debug signing location consistently with HOME.
ENV JAVA_TOOL_OPTIONS=-Duser.home=/home/smoke ANDROID_USER_HOME=/home/smoke/.android
ENV PATH=/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:$PATH
RUN mkdir -p /opt/android-sdk/cmdline-tools && curl --fail --show-error --silent --location --retry 2 https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip -o /tmp/android.zip && echo '4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583  /tmp/android.zip' | sha256sum -c - && unzip -q /tmp/android.zip -d /tmp/android-tools && mv /tmp/android-tools/cmdline-tools /opt/android-sdk/cmdline-tools/latest && rm /tmp/android.zip && chown -R "$UID:$GID" /opt/android-sdk
USER $UID:$GID
RUN yes | sdkmanager --licenses >/dev/null && sdkmanager 'platform-tools' 'platforms;android-35' 'platforms;android-36' 'build-tools;35.0.0' 'build-tools;36.0.0' 'ndk;27.0.12077973'
RUN test "$(id -u)" = "$UID" && test "$HOME" = /home/smoke && mkdir -p "$ANDROID_USER_HOME" && (java -XshowSettings:properties -version 2>&1 | grep -E '^[[:space:]]*user[.]home = /home/smoke$')
"""

FLUTTER_ANDROID_SETUP = """RUN flutter precache --android && flutter create --platforms=android --project-name=synthetic_mobile --org=com.example --no-pub /home/smoke/generated && cp -a /home/smoke/generated/android /fixture/android
RUN printf 'org.gradle.jvmargs=-Xmx2g -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8\\nandroid.useAndroidX=true\\norg.gradle.workers.max=2\\norg.gradle.daemon=false\\n' > android/gradle.properties
RUN flutter pub get && flutter build apk --debug --no-pub && test -s "$ANDROID_USER_HOME/debug.keystore" && test ! -L "$ANDROID_USER_HOME/debug.keystore" && echo CI_SYNTHETIC_DEBUG_SIGNING_HOME_PASS
"""

# The initial Expo reference uses npm, generated Android sources and Gradle.
# Never run expo run:android: that command also targets devices/Metro.
EXPO_ANDROID_SETUP = """RUN ./node_modules/.bin/expo prebuild --platform android --no-install && npm install --package-lock-only --ignore-scripts --no-audit --no-fund && npm ci --ignore-scripts --no-audit --no-fund
# A synthetic debug key stays inside this CI image, never the source archive.
RUN keytool -genkeypair -keystore "$ANDROID_USER_HOME/debug.keystore" -storetype JKS -storepass android -keypass android -alias androiddebugkey -dname 'CN=Android Debug,O=Android,C=US' -keyalg RSA -keysize 2048 -validity 3650
RUN test "$(grep -Fc "storeFile file('debug.keystore')" android/app/build.gradle)" = 1 && sed -i "s|storeFile file('debug.keystore')|storeFile file(System.getenv('ANDROID_USER_HOME') + '/debug.keystore')|" android/app/build.gradle && grep -F "storeFile file(System.getenv('ANDROID_USER_HOME') + '/debug.keystore')" android/app/build.gradle
RUN printf '\\norg.gradle.jvmargs=-Xmx2g -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8\\norg.gradle.workers.max=2\\norg.gradle.daemon=false\\n' >> android/gradle.properties
RUN cd android && ./gradlew :app:assembleDebug && test -s app/build/outputs/apk/debug/app-debug.apk && test -s "$ANDROID_USER_HOME/debug.keystore" && test ! -L "$ANDROID_USER_HOME/debug.keystore" && echo CI_SYNTHETIC_DEBUG_SIGNING_HOME_PASS
"""

ANDROID_EXPORT = """RUN tar --exclude=android/app/debug.keystore --exclude=android/app/.cxx --exclude=android/.cxx --exclude=android/local.properties --exclude=android/.gradle --exclude=android/.kotlin --exclude=android/app/build --exclude=android/build --exclude=android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java -cf /home/smoke/android-source.tar android && rm -rf /fixture/build /fixture/android /fixture/.dart_tool && mkdir -p /home/smoke/.gradle/init.d && printf 'gradle.startParameter.offline = true\\n' > /home/smoke/.gradle/init.d/ci-offline.gradle
"""

def command(argv, *, timeout=180, capture=False):
    return subprocess.run(argv, check=True, timeout=timeout,
                          stdout=subprocess.PIPE if capture else None,
                          stdin=subprocess.DEVNULL).stdout


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify_oci_conversion(source, image, manifest_bytes, config_bytes):
    """Check converted OCI config and ordered filesystem identity.

    Docker and OCI use different config encodings. Skopeo may change the
    config digest while preserving the execution settings and uncompressed
    layer identities. Never treat the two config digests as interchangeable.
    """
    if source["Id"] != image:
        raise RuntimeError("MOBILE_DOCKER_IMAGE_IDENTITY")
    manifest = json.loads(manifest_bytes)
    target = json.loads(config_bytes)
    digest = manifest["config"]["digest"]
    if (not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or digest != "sha256:" + sha256(config_bytes)
            or manifest["config"]["size"] != len(config_bytes)):
        raise RuntimeError("MOBILE_OCI_CONFIG_INTEGRITY")
    layers = source["RootFS"]["Layers"]
    if (source["RootFS"]["Type"] != "layers" or target["rootfs"]["type"] != "layers"
            or not layers or layers != target["rootfs"]["diff_ids"]
            or len(layers) != len(manifest["layers"])
            or source["Architecture"] != target["architecture"]
            or source["Os"] != target["os"]):
        raise RuntimeError("MOBILE_OCI_FILESYSTEM_IDENTITY")
    # Docker-only fields not defined by OCI (e.g. historical build metadata)
    # are not identity claims. Compare every execution-relevant OCI field.
    original, converted = source["Config"], target["config"]
    fields = {"User": "", "WorkingDir": "", "Env": [], "Entrypoint": [],
              "Cmd": [], "Volumes": {}, "ExposedPorts": {}, "Labels": {},
              "StopSignal": "", "ArgsEscaped": False}
    for name, empty in fields.items():
        def value(obj):
            v = obj.get(name)
            return empty if v is None else v
        if value(original) != value(converted):
            raise RuntimeError("MOBILE_OCI_EXECUTION_CONFIG_IDENTITY:" + name)
    return {"docker_config": image, "oci_config": digest,
            "rootfs_layers": len(layers), "filesystem_identity_verified": True,
            "execution_config_verified": True}


def write_files(folder, files):
    for name, data in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data)
        if name == "android/gradlew":
            path.chmod(0o700)


def git(root, *args):
    return command(["git", "-C", str(root), *args], capture=True).decode().strip()


def private_json(path, value):
    path.touch(mode=0o600, exist_ok=False)
    path.write_text(json.dumps(value))


def prepare(folder, files, lock, lock_bytes, profiles, *, image_id=None, executor=None, backend=None):
    source = folder / "source"
    source.mkdir(mode=0o700)
    write_files(source, {**files, ".gitignore": ".project-os/\n"})
    (source / lock).write_bytes(lock_bytes)
    git(source, "init", "-q")
    git(source, "config", "user.name", "Synthetic")
    git(source, "config", "user.email", "synthetic@example.invalid")
    git(source, "remote", "add", "origin", "https://github.com/example/synthetic.git")
    git(source, "add", ".")
    if image_id is not None:
        git(source, "add", "-f", "android")  # Only generated synthetic native source.
    git(source, "commit", "-qm", "synthetic mobile source")
    revision = git(source, "rev-parse", "HEAD")
    config_dir = source / ".project-os"
    config_dir.mkdir(mode=0o700)
    config = config_dir / "config.json"
    private_json(config, {"version": 2, "repositories": ["example/synthetic"],
                          "github_context": {"project": "synthetic", "repository": "example/synthetic",
                                             "repository_id": 1}})
    state = folder / "state"
    state.mkdir(mode=0o700)
    (state / MARKER).touch(mode=0o600)
    private_json(state / RUNTIME, {"tunnel": "fixture", "tunnel_id": "fixture", "image": None,
        "github_projects": {"synthetic": {"config": str(config), "repository": "example/synthetic",
                                         "repository_id": 1}}})
    principal = "ci-mobile"
    policy = Policy([(principal, "submit", "disposable"), (principal, "read", "disposable"),
                     *((principal, op, "synthetic") for op in
                       ("workspace_prepare", "workspace_materialize", "workspace_execute", *profiles))])
    workflow = "workspace_execute" if image_id is not None or backend is not None else "workspace_prepare"
    jobs = Jobs(state, policy, workflows=(workflow,))
    ids = {profile: submit_workspace(jobs, principal, "synthetic", revision, profile, profile,
                                     image_id=image_id, backend=backend) for profile in profiles}
    run_pending(jobs, workspace_executor=executor, workspace_backend=backend)
    jobs = Jobs(state, policy, workflows=(workflow,))
    evidence = {profile: jobs.evidence(principal, job) for profile, job in ids.items()}
    if image_id is None and backend is None and any(item["state"] != "SUCCEEDED" or item["result"]["head"] != revision
           or item["result"]["execution_available"] is not False for item in evidence.values()):
        raise RuntimeError("WORKSPACE_PREPARATION_FAILED")
    return state, ids, evidence


def container_args(image):
    return ["docker", "run", "--rm", "--pull=never", "--network", "none",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "512", "--memory", "5g", "--cpus", "2",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", "EXPO_OFFLINE=1", "--env", "EXPO_NO_TELEMETRY=1"]


def native_files(image):
    raw = command([*container_args(image), image, "cat", "/home/smoke/android-source.tar"],
                  capture=True)
    if not 0 < len(raw) <= 8 * 1024 * 1024:
        raise RuntimeError("NATIVE_SOURCE_LIMIT")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for item in archive:
            if item.isdir():
                continue
            if (not item.isfile() or not re.fullmatch(r"android/[A-Za-z0-9_./+@ -]+", item.name)
                    or any(part in {"", ".", ".."} for part in item.name.split("/"))
                    or item.name in files or item.size > 2 * 1024 * 1024):
                raise RuntimeError("INVALID_NATIVE_SOURCE")
            files[item.name] = archive.extractfile(item).read()
    if "android/app/src/main/AndroidManifest.xml" not in files:
        raise RuntimeError("NATIVE_MANIFEST_MISSING")
    return files


def apk_executor(image, output, profile):
    """CI-only registered APK operation. No local service registration."""
    if profile not in {"flutter-apk-debug", "expo-apk-debug"}:
        raise ValueError("UNEXPECTED_CI_PROFILE")
    flutter = profile == "flutter-apk-debug"
    lock = "pubspec.lock" if flutter else "package-lock.json"
    def execute(workspace, row, snapshot):
        request = row["workspace"]
        if request["profile"] != profile or request["image_id"] != image:
            raise PermissionError("UNEXPECTED_CI_PROFILE")
        name = "mobile-smoke-" + row["id"]
        artifacts = output / ("apk-" + row["id"])
        artifacts.mkdir(mode=0o700)
        # The image has no warmup build outputs or native tree. Offline Gradle
        # consumes only the pre-acquired toolchain/cache and prepared source.
        setup = ('set -eu; cmp /source/' + lock + ' /fixture/' + lock + '; '
                 'test ! -e /fixture/build; test ! -e /fixture/android; '
                 'test "$ANDROID_USER_HOME" = /home/smoke/.android; '
                 'test -s "$ANDROID_USER_HOME/debug.keystore"; '
                 'test ! -L "$ANDROID_USER_HOME/debug.keystore"; '
                 'cp -a /source/. /fixture/; ' +
                 ('flutter pub get --offline; ' if flutter else
                  'npm ci --offline --ignore-scripts --no-audit --no-fund; ') +
                 'cmp /source/' + lock + ' ' + lock + '; ' +
                 ('"$@"; apk=build/app/outputs/flutter-apk/app-debug.apk; ' if flutter else
                  'cd android; "$@"; apk=app/build/outputs/apk/debug/app-debug.apk; ') +
                 'test -f "$apk"; test ! -L "$apk"; '
                 '/opt/android-sdk/build-tools/36.0.0/apksigner verify --print-certs "$apk"; '
                 '/opt/android-sdk/build-tools/36.0.0/aapt dump badging "$apk" > /tmp/apk-badging; '
                 'head -n 1 /tmp/apk-badging; '
                 'cp "$apk" /output/app-debug.apk')
        argv = PROFILES[request["profile"]].argv
        args = [*container_args(image), "--name", name, "--mount",
                f"type=bind,src={workspace},dst=/source,readonly", "--mount",
                f"type=bind,src={artifacts},dst=/output", image, "/bin/sh", "-c",
                setup, "profile", *argv]
        try:
            proc = subprocess.run(args, stdin=subprocess.DEVNULL, timeout=900, check=False)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], timeout=30, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            code = 124
        # Confirm exact name absent. The VM and queue are single-use; never
        # retry interrupted work or reuse this execution state.
        names = command(["docker", "ps", "-a", "--filter", "name=^/" + name + "$",
                         "--format", "{{.Names}}"], capture=True)
        if names.strip():
            code = 125
        result = {"image_id": image, "argv": list(argv), "exit_code": code,
                  "cleanup_verified": not bool(names.strip()),
                  "workspace_sha256": snapshot["workspace_sha256"]}
        if code == 0:
            apk = artifacts / "app-debug.apk"
            info = apk.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or not 0 < info.st_size <= 256 * 1024 * 1024):
                raise RuntimeError("APK_IDENTITY_INVALID")
            raw = apk.read_bytes()
            if len(raw) != info.st_size:
                raise RuntimeError("APK_IDENTITY_INVALID")
            result["artifact"] = artifact_identity("apk", "app-debug.apk", raw)
            with apk.open("rb") as stream:
                os.fsync(stream.fileno())
        print("MOBILE_PROFILE_EXIT", request["profile"], code, flush=True)
        return result
    return execute


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux":
        raise RuntimeError("Disposable Linux CI only")
    os.umask(0o077)
    stack = os.environ["MOBILE_STACK"]
    apk = os.environ.get("MOBILE_APK") == "1"
    if stack not in {"flutter", "expo"} or os.getuid() == 0:
        raise RuntimeError("Invalid smoke profile or runner")
    checkout = Path.cwd()
    if git(checkout, "rev-parse", "HEAD") != os.environ["GITHUB_SHA"]:
        raise RuntimeError("CI revision mismatch")
    output = Path(os.environ["RUNNER_TEMP"]) / "mobile-smoke-evidence"
    output.mkdir(mode=0o700, exist_ok=False)
    record = {"scope": "trusted-synthetic-ci-only", "ci_sha": os.environ["GITHUB_SHA"],
              "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
              "stack": stack, "mode": "apk" if apk else "validation", "steps": []}
    evidence_file = output / "result.json"

    def save():
        evidence_file.write_text(json.dumps(record, indent=2) + "\n")

    save()
    try:
        with tempfile.TemporaryDirectory(prefix="mobile-ci-", dir=os.environ["RUNNER_TEMP"]) as tmp:
            folder = Path(tmp).resolve()
            context = folder / "context"
            seed = context / "seed"
            seed.mkdir(parents=True)
            files, lock, profiles, setup = (
                (FLUTTER_FILES, "pubspec.lock", ("flutter-analyze", "flutter-test"), FLUTTER_SETUP)
                if stack == "flutter" else
                (EXPO_FILES, "package-lock.json", ("expo-typecheck", "expo-test"), EXPO_SETUP))
            write_files(seed, files)
            if apk:
                setup += ANDROID_SETUP + (FLUTTER_ANDROID_SETUP if stack == "flutter" else EXPO_ANDROID_SETUP) + ANDROID_EXPORT
                profiles = (stack + "-apk-debug",)
            else:
                setup += ("RUN rm -rf /fixture/lib /fixture/test /fixture/.dart_tool /fixture/pubspec.yaml\n"
                          if stack == "flutter" else
                          "RUN rm -f /fixture/index.tsx /fixture/value.cjs /fixture/value.test.cjs /fixture/app.json /fixture/tsconfig.json /fixture/package.json\n")
            (context / "Dockerfile").write_text(COMMON + setup)
            # Acquisition is confined to a synthetic project in a fresh CI VM.
            # Resolve the public base once, then build and run by immutable identity.
            command(["docker", "pull", BASE], timeout=300)
            base = BASE
            record["base_image"] = base
            record["requested_toolchain"] = ({"flutter": FLUTTER_VERSION, "archive_sha256": FLUTTER_SHA256}
                if stack == "flutter" else {"node": NODE_VERSION, "expo": EXPO_VERSION, "react_native": RN_VERSION})
            save()
            iid = folder / "image-id"
            command(["docker", "build", "--iidfile", str(iid), "--build-arg", "BASE=" + base,
                     "--build-arg", f"UID={os.getuid()}", "--build-arg", f"GID={os.getgid()}",
                     str(context)], timeout=1800 if apk else 1000)
            image = iid.read_text().strip()
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
                raise RuntimeError("IMAGE_ID_UNAVAILABLE")
            record["image_id"] = image
            version = command([*container_args(image), image,
                *(["flutter", "--version", "--machine"] if stack == "flutter" else
                  ["node", "-e", "console.log(JSON.stringify({node:process.version,expo:require('expo/package.json').version,reactNative:require('react-native/package.json').version}))"])],
                capture=True)
            observed = json.loads(version)
            if stack == "flutter":
                if observed.get("frameworkVersion") != FLUTTER_VERSION:
                    raise RuntimeError("FLUTTER_VERSION_MISMATCH")
            elif observed != {"node": "v" + NODE_VERSION, "expo": EXPO_VERSION, "reactNative": RN_VERSION}:
                raise RuntimeError("EXPO_VERSION_MISMATCH")
            record["toolchain"] = observed
            lock_bytes = command([*container_args(image), image, "cat", "/fixture/" + lock], capture=True)
            if not 0 < len(lock_bytes) <= 2 * 1024 * 1024:
                raise RuntimeError("LOCKFILE_LIMIT")
            (output / lock).write_bytes(lock_bytes)
            record["lock_sha256"] = sha256(lock_bytes)
            if apk:
                files = {**files, **native_files(image)}
                if stack == "expo":
                    # Prebuild may update package.json. Commit the exact generated
                    # manifest that corresponds to the captured npm lockfile.
                    manifest = command([*container_args(image), image, "cat", "/fixture/package.json"], capture=True)
                    if not 0 < len(manifest) <= 65536:
                        raise RuntimeError("MANIFEST_LIMIT")
                    files["package.json"] = manifest
                record["android_sdk"] = command([*container_args(image), image, "sdkmanager", "--list_installed"],
                                                capture=True).decode("utf-8", "replace")[:16000]
                record["java"] = subprocess.run([*container_args(image), image, "java", "-version"],
                                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                stdin=subprocess.DEVNULL, timeout=30, check=True).stdout.decode("utf-8", "replace")[:4096]
                _, _, executed = prepare(folder, files, lock, lock_bytes, profiles, image_id=image,
                                         executor=apk_executor(image, output, profiles[0]))
                record["execution"] = executed
                save()
                result = executed[profiles[0]]
                if (result["state"] != "SUCCEEDED"
                        or result["result"]["execution"]["exit_code"] != 0
                        or result["result"]["execution"]["cleanup_verified"] is not True
                        or result["result"]["execution"]["artifact"]["kind"] != "apk"):
                    raise RuntimeError("APK_EXECUTION_FAILED")
                record["status"] = "success"
                save()
                return
            # Import the exact acquired candidate into a private rootless store,
            # not the Docker/default Podman store used for image acquisition.
            tag = "localhost/project-os-mobile-ci:validation"
            source = json.loads(command(["docker", "image", "inspect", image], capture=True))
            if len(source) != 1 or source[0].get("Id") != image:
                raise RuntimeError("MOBILE_DOCKER_IMAGE_IDENTITY")
            command(["docker", "tag", image, tag])
            layout = folder / "oci"
            command(["skopeo", "copy", "--format", "oci", "docker-daemon:" + tag,
                     "oci:" + str(layout) + ":candidate"], timeout=600)
            index = json.loads((layout / "index.json").read_bytes())
            manifests = index["manifests"]
            if len(manifests) != 1:
                raise RuntimeError("MOBILE_OCI_MANIFEST_COUNT")
            digest = manifests[0]["digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise RuntimeError("MOBILE_OCI_DIGEST")
            manifest = (layout / "blobs/sha256" / digest.split(":")[1]).read_bytes()
            if "sha256:" + sha256(manifest) != digest:
                raise RuntimeError("MOBILE_OCI_MANIFEST_INTEGRITY")
            config = json.loads(manifest)["config"]["digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", config):
                raise RuntimeError("MOBILE_OCI_CONFIG_DIGEST")
            record["oci_manifest"] = digest
            record["oci_config"] = config
            save()
            config_bytes = (layout / "blobs/sha256" / config.split(":")[1]).read_bytes()
            record["conversion"] = verify_oci_conversion(source[0], image, manifest, config_bytes)
            record["backend"] = "WorkspacePodman"
            save()
            # The short context path follows the existing Podman runroot limit.
            # Retain the private store until the disposable VM is destroyed.
            parent = Path(tempfile.mkdtemp(prefix="lbmob.", dir="/tmp")).resolve()
            ctx = PodmanContext(parent / "context")
            identity = ctx.prepare()
            imported = ctx.import_layout(layout, digest, kind="mobile-validation")
            host = ctx.host(identity)
            record["podman"] = {"rootless": host["security"]["rootless"],
                                "seccomp": host["security"]["seccompEnabled"],
                                "cgroup_version": host["cgroupVersion"],
                                "context_id": identity, "image": imported}
            save()
            backend = WorkspacePodman(ctx, {profile: imported for profile in profiles})
            state, ids, executed = prepare(folder, files, lock, lock_bytes, profiles, backend=backend)
            record["execution"] = executed
            save()
            # Reopen existing DB; confirm no unresolved effects or replay.
            principal = "ci-mobile"
            policy = Policy([(principal, "read", "disposable")])
            jobs = Jobs(state, policy, workflows=("workspace_execute",))
            if jobs.pending_effects():
                raise RuntimeError("MOBILE_PODMAN_RECONCILIATION_REQUIRED")
            for profile, item in executed.items():
                result = item.get("result") or {}
                execution = result.get("execution") or {}
                if (item["state"] != "SUCCEEDED" or execution.get("exit_code") != 0
                        or execution.get("cleanup_verified") is not True
                        or execution.get("image_id") != digest
                        or execution.get("workspace_sha256") != result.get("workspace_sha256")
                        or result.get("workspace_materialized") is not True
                        or jobs.evidence(principal, ids[profile]) != item):
                    raise RuntimeError("MOBILE_PODMAN_PROFILE_FAILED")
                record["steps"].append({"profile": profile, "job_id": ids[profile],
                    "workspace_sha256": result["workspace_sha256"],
                    "argv": list(PROFILES[profile].argv), "exit_code": execution["exit_code"]})
                print("MOBILE_PROFILE_EXIT", profile, execution["exit_code"], flush=True)
            record["pending_effects"] = 0
            record["status"] = "success"
            save()
    except Exception:
        record["status"] = "failed"
        save()
        raise


if __name__ == "__main__":
    main()
