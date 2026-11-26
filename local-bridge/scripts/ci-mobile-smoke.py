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

from project_os_bridge.core import Jobs, Policy
from project_os_bridge.workspace_jobs import MARKER, RUNTIME, submit_workspace
from project_os_bridge.workspace_profiles import PROFILES
from project_os_bridge.worker import run_pending

FLUTTER_VERSION = "3.35.7"
FLUTTER_SHA256 = "146df531f9ac6a11a918013c1a70faafc053d4811c8cb69a413fd70748d51c3d"
NODE_VERSION = "22.16.0"
BASE = "docker.io/library/node:" + NODE_VERSION + "-bookworm"
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
    "app.json": '{"expo":{"name":"Synthetic mobile","slug":"synthetic-mobile","version":"1.0.0"}}',
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

def command(argv, *, timeout=180, capture=False):
    return subprocess.run(argv, check=True, timeout=timeout,
                          stdout=subprocess.PIPE if capture else None,
                          stdin=subprocess.DEVNULL).stdout


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_files(folder, files):
    for name, data in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)


def git(root, *args):
    return command(["git", "-C", str(root), *args], capture=True).decode().strip()


def private_json(path, value):
    path.touch(mode=0o600, exist_ok=False)
    path.write_text(json.dumps(value))


def prepare(folder, files, lock, lock_bytes, profiles):
    source = folder / "source"
    source.mkdir(mode=0o700)
    write_files(source, {**files, ".gitignore": ".project-os/\n"})
    (source / lock).write_bytes(lock_bytes)
    git(source, "init", "-q")
    git(source, "config", "user.name", "Synthetic")
    git(source, "config", "user.email", "synthetic@example.invalid")
    git(source, "remote", "add", "origin", "https://github.com/example/synthetic.git")
    git(source, "add", ".")
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
                       ("workspace_prepare", "workspace_materialize", *profiles))])
    jobs = Jobs(state, policy, workflows=("workspace_prepare",))
    ids = {profile: submit_workspace(jobs, principal, "synthetic", revision, profile, profile)
           for profile in profiles}
    run_pending(jobs)
    evidence = {profile: jobs.evidence(principal, job) for profile, job in ids.items()}
    if any(item["state"] != "SUCCEEDED" or item["result"]["head"] != revision
           or item["result"]["execution_available"] is not False for item in evidence.values()):
        raise RuntimeError("WORKSPACE_PREPARATION_FAILED")
    return state, ids, evidence


def container_args(image):
    return ["docker", "run", "--rm", "--pull=never", "--network", "none",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "512", "--memory", "5g", "--cpus", "2",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", "EXPO_OFFLINE=1", "--env", "EXPO_NO_TELEMETRY=1"]


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux":
        raise RuntimeError("Disposable Linux CI only")
    stack = os.environ["MOBILE_STACK"]
    if stack not in {"flutter", "expo"} or os.getuid() == 0:
        raise RuntimeError("Invalid smoke profile or runner")
    checkout = Path.cwd()
    if git(checkout, "rev-parse", "HEAD") != os.environ["GITHUB_SHA"]:
        raise RuntimeError("CI revision mismatch")
    output = Path(os.environ["RUNNER_TEMP"]) / "mobile-smoke-evidence"
    output.mkdir(mode=0o700, exist_ok=False)
    record = {"scope": "trusted-synthetic-ci-only", "ci_sha": os.environ["GITHUB_SHA"],
              "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
              "stack": stack, "steps": []}
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
            (context / "Dockerfile").write_text(COMMON + setup)
            # Acquisition is confined to a synthetic project in a fresh CI VM.
            # Resolve the public base once, then build and run by immutable identity.
            command(["docker", "pull", BASE], timeout=300)
            digests = json.loads(command(["docker", "image", "inspect", "--format",
                                          "{{json .RepoDigests}}", BASE], capture=True))
            base = next((value for value in digests if re.fullmatch(r"(?:docker\.io/library/)?node@sha256:[0-9a-f]{64}", value)), None)
            if base is None:
                raise RuntimeError("BASE_DIGEST_UNAVAILABLE")
            record["base_image"] = base
            record["requested_toolchain"] = ({"flutter": FLUTTER_VERSION, "archive_sha256": FLUTTER_SHA256}
                if stack == "flutter" else {"node": NODE_VERSION, "expo": EXPO_VERSION, "react_native": RN_VERSION})
            save()
            iid = folder / "image-id"
            command(["docker", "build", "--iidfile", str(iid), "--build-arg", "BASE=" + base,
                     "--build-arg", f"UID={os.getuid()}", "--build-arg", f"GID={os.getgid()}",
                     str(context)], timeout=1000)
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
            state, ids, prepared = prepare(folder, files, lock, lock_bytes, profiles)
            record["preparation"] = prepared
            save()
            # The same materialized revision feeds each fixed registered command.
            # No dependency download in this phase. The only host mount is the
            # private synthetic source, read-only; never a host SDK or socket.
            for profile in profiles:
                workspace = state / ("workspace-" + ids[profile])
                argv = PROFILES[profile].argv
                # Copy the checked-out bytes into the image's disposable writable
                # layer, preserving its pre-acquired cache and dependency closure.
                setup_cmd = ("set -eu; cmp /source/" + lock + " /fixture/" + lock +
                             "; cp -a /source/. /fixture/; " +
                             ("flutter pub get --offline; cmp /source/pubspec.lock pubspec.lock; "
                              if stack == "flutter" else "npm ci --offline --ignore-scripts --no-audit --no-fund; cmp /source/package-lock.json package-lock.json; ") +
                             'exec "$@"')
                name = "mobile-smoke-" + uuid.uuid4().hex
                args = [*container_args(image), "--name", name, "--mount",
                        f"type=bind,src={workspace},dst=/source,readonly", image,
                        "/bin/sh", "-c", setup_cmd, "profile", *argv]
                try:
                    proc = subprocess.run(args, stdin=subprocess.DEVNULL, timeout=300, check=False)
                    code = proc.returncode
                except subprocess.TimeoutExpired:
                    subprocess.run(["docker", "rm", "-f", name], timeout=30, check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    code = 124
                record["steps"].append({"profile": profile, "job_id": ids[profile],
                    "workspace_sha256": prepared[profile]["result"]["workspace_sha256"],
                    "argv": list(argv), "exit_code": code})
                save()
                print("MOBILE_PROFILE_EXIT", profile, code, flush=True)
                if code != 0:
                    raise RuntimeError("PROFILE_FAILED")
            record["status"] = "success"
            save()
    except Exception:
        record["status"] = "failed"
        save()
        raise


if __name__ == "__main__":
    main()
