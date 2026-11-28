"""Real Android signing tools, synthetic APK, existing Jobs/worker.

No private project, device, production credential or application compilation.
Only the application build output is simulated; Android packaging, key generation,
alignment, signing, inspection and verification use the installed SDK/JDK.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import zipfile
from unittest.mock import patch

from project_os_bridge.android_qa import QASignerBinding, verified_qa_delivery_input, verify_qa_artifact_zip
from project_os_bridge.core import Jobs, Policy
from project_os_bridge.worker import run_pending
from project_os_bridge.workspace_jobs import submit_workspace
from project_os_bridge.execution import WorkspaceWSL
from test_workspace_preflight import WorkspacePreflightTests


def command(*args):
    subprocess.run(list(map(str, args)), stdin=subprocess.DEVNULL,
                   timeout=180, check=True, umask=0o077)


def copy_fixture_tools(source, destination):
    # copytree preserves source modes. Remove group/other write permission
    # only on the new fixture copy, not the runner's installed SDK/JDK.
    shutil.copytree(source.resolve(strict=True), destination)
    for path in (destination, *destination.rglob("*")):
        info = path.lstat()
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError("QA_CI_TOOL_COPY_UNSUPPORTED")
        path.chmod(stat.S_IMODE(info.st_mode) & ~0o022)


def main():
    # The workflow creates a new owner-private directory directly under /
    # in the disposable VM. CI 46065127256 showed /opt is mode 0777;
    # using a private child under it does not satisfy the ancestry check.
    # Preserve the production admission policy unchanged.
    sdk = Path(os.environ["ANDROID_HOME"])
    ndk = Path(os.environ["ANDROID_NDK_HOME"]) / "toolchains/llvm/prebuilt/linux-x86_64/bin"
    fixture = WorkspacePreflightTests()
    fixture.setUp()
    try:
        with tempfile.TemporaryDirectory(prefix="signing-", dir="/project-os-qa-ci") as tmp:
            root = Path(tmp).resolve()
            java = root / "java"
            tools = root / "build-tools"
            copy_fixture_tools(Path(os.environ["JAVA_HOME_17_X64"]), java)
            copy_fixture_tools(sdk / "build-tools/36.0.0", tools)
            for executable in (java / "bin/keytool", java / "bin/java",
                               tools / "aapt", tools / "apksigner", tools / "zipalign"):
                for component in (executable, *executable.parents):
                    info = component.stat()
                    if info.st_uid not in {0, os.getuid()} or info.st_mode & 0o022:
                        print("QA_CI_TOOL_ADMISSION", component.name,
                              "mode=" + oct(stat.S_IMODE(info.st_mode)),
                              "trusted_owner=" + str(info.st_uid in {0, os.getuid()}),
                              flush=True)
                        raise PermissionError("QA_CI_TOOLCHAIN_UNAVAILABLE")
            manifest = root / "AndroidManifest.xml"
            source = root / "fixture.c"
            source.write_text("int project_os_fixture(void) { return 42; }\n")
            libs = {}
            for abi, target in (("arm64-v8a", "aarch64-linux-android24-clang"),
                                ("x86_64", "x86_64-linux-android24-clang")):
                lib = root / (abi + ".so")
                command(ndk / target, "-shared", "-fPIC", "-Wl,-z,max-page-size=16384",
                        source, "-o", lib)
                libs[abi] = lib.read_bytes()

            def apk(version):
                manifest.write_text(
                    '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
                    'package="example.demo.qa" android:versionCode="' + str(version) +
                    '" android:versionName="1.0"><uses-sdk android:minSdkVersion="24" '
                    'android:targetSdkVersion="35"/><application android:hasCode="false" '
                    'android:debuggable="false" android:extractNativeLibs="false" '
                    'android:label="Project OS QA fixture"/></manifest>')
                path = root / ("input-" + str(version) + ".apk")
                command(tools / "aapt2", "link", "--manifest", manifest,
                        "-I", sdk / "platforms/android-35/android.jar", "-o", path)
                with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_STORED) as archive:
                    for abi, data in libs.items():
                        archive.writestr("lib/" + abi + "/libfixture.so", data)
                return path.read_bytes()

            jobs = fixture.workspace_queue()
            policy = Policy([*jobs.policy.grants, ("operator", "workspace_execute", "demo")])
            jobs = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
            route = "demo:expo-apk-qa"
            signer = QASignerBinding({"package": "example.demo.qa", "java_home": str(java),
                                      "build_tools": str(tools)})
            backend = WorkspaceWSL({route: {"PATH": "/usr/bin:/bin"}}, qa_plans={route: {}},
                                   qa_signers={route: signer})

            def finalize(version):
                data = apk(version)
                job = submit_workspace(jobs, "operator", "demo", fixture.sha,
                                       "expo-apk-qa", "signing-" + str(version), backend=backend)
                def build_command(argv, cwd, env, deadline):
                    if ":app:assembleRelease" in argv:
                        path = cwd / "app/build/outputs/apk/release/app-release.apk"
                        path.parent.mkdir(parents=True)
                        path.write_bytes(data)
                    return 0, True
                with patch("project_os_bridge.execution._command", side_effect=build_command):
                    run_pending(jobs, workspace_backend=backend)
                result = jobs.evidence("operator", job)["result"]["qa_finalization"]
                assert result["state"] == "SUCCEEDED", result
                raw, receipt = verified_qa_delivery_input(jobs, "operator", job,
                    expected_project="demo", expected_sha=fixture.sha, expected_repository_id=123)
                assert receipt["artifact"]["sha256"] == hashlib.sha256(raw).hexdigest()
                assert receipt["metadata"]["version_code"] == version
                assert receipt["metadata"]["abis"] == ["arm64-v8a", "x86_64"]
                assert receipt["signature_verified"] and not receipt["published"]
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
                    zipped.writestr("app-qa.apk", raw)
                identity = verify_qa_artifact_zip(archive.getvalue(), receipt)
                assert identity["sha256"] == hashlib.sha256(archive.getvalue()).hexdigest()
                return job, receipt

            first, one = finalize(41)
            second, two = finalize(42)
            assert one["certificate_sha256"] == two["certificate_sha256"]
            reopened = Jobs(jobs.probe.root, policy, workflows=("workspace_execute",))
            run_pending(reopened, workspace_backend=backend)
            assert verified_qa_delivery_input(reopened, "operator", first,
                expected_project="demo", expected_sha=fixture.sha, expected_repository_id=123)[1] == one
            try:
                verified_qa_delivery_input(reopened, "operator", second,
                    expected_project="demo", expected_sha=fixture.sha, expected_repository_id=124)
            except (ValueError, PermissionError):
                pass
            else:
                raise AssertionError("CROSS_REPOSITORY_DELIVERY")
            target = jobs.probe.root / "qa-signing" / "123" / "artifacts" / second / "app-qa.apk"
            with target.open("ab") as output:
                output.write(b"tampered")
            try:
                verified_qa_delivery_input(reopened, "operator", second,
                    expected_project="demo", expected_sha=fixture.sha, expected_repository_id=123)
            except ValueError:
                pass
            else:
                raise AssertionError("TAMPERED_DELIVERY")
            assert not reopened.pending_effects()
            print("QA_REAL_SIGNING_PASS", json.dumps({"certificate_sha256": one["certificate_sha256"],
                  "first": one["artifact"], "second": two["artifact"],
                  "versions": [41, 42], "device_qa": False, "published": False}))
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
