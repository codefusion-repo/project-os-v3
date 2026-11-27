"""Local trusted Android QA finalization, not an MCP command or build fallback.

Only a reviewed local caller may supply the SDK paths and expected package.
Project code stays in the existing isolated builder. No publisher credentials
or signing material are passed to that builder.
"""
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from pathlib import Path

from .github_operational import _private_bytes, _unique_object
from .worker import exclusive_worker
from .workos_auth import private_directory, private_file
from .workspace_jobs import verified_qa_build_input
from .workspace_podman import read_apk_bytes
from .workspace_profiles import artifact_identity

PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
CERT = re.compile(r"[0-9a-f]{64}")
ALIAS = "project-os-qa"
ABIS = frozenset({"arm64-v8a", "x86_64"})


def _directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    private_directory(path)
    return path


def _sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path, data):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600), "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _read_json(path):
    return json.loads(_private_bytes(path, 16384), object_pairs_hook=_unique_object)


def _apk_bytes(path):
    info = private_file(path)
    return read_apk_bytes(path, (info.st_dev, info.st_ino))


def _adopt(stage, destination):
    # All callers hold the existing exclusive worker lock.
    if os.path.lexists(destination):
        raise FileExistsError("QA_IDENTITY_EXISTS")
    for path in stage.iterdir():
        private_file(path)
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    _sync(stage)
    stage.rename(destination)
    _sync(destination.parent)


def _tool(path):
    """Explicit trusted installation, never a path from project/build data."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("QA_TOOLCHAIN_UNAVAILABLE")
    resolved = path.resolve(strict=True)
    for component in (resolved, *resolved.parents):
        info = component.stat()
        if info.st_uid not in {0, os.getuid()} or info.st_mode & 0o022:
            raise PermissionError("QA_TOOLCHAIN_UNAVAILABLE")
    if not stat.S_ISREG(resolved.stat().st_mode) or not os.access(resolved, os.X_OK):
        raise ValueError("QA_TOOLCHAIN_UNAVAILABLE")
    return resolved


class AndroidQATools:
    """Approved local JDK/Android SDK utilities only; no repo commands or shell."""

    def __init__(self, java_home, build_tools):
        self.keytool = _tool(Path(java_home) / "bin/keytool")
        self.java_home = Path(java_home).resolve(strict=True)
        self.java = _tool(self.java_home / "bin/java")
        self.aapt = _tool(Path(build_tools) / "aapt")
        self.apksigner = _tool(Path(build_tools) / "apksigner")
        self.zipalign = _tool(Path(build_tools) / "zipalign")

    def _run(self, executable, args, work, password=None):
        private_directory(work)
        # Never inherit project variables, Java options, or credentials.
        env = {"PATH": str(self.java_home / "bin") + ":/usr/bin:/bin",
               "JAVA_HOME": str(self.java_home), "HOME": str(work),
               "TMPDIR": str(work), "LC_ALL": "C"}
        if password is not None:
            env["QA_STORE_PASSWORD"] = password
        try:
            result = subprocess.run([str(executable), *map(str, args)], cwd=work, env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=180, check=False,
                                    umask=0o077)
        except (OSError, subprocess.SubprocessError):
            raise ValueError("QA_TOOL_FAILED") from None
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            raise ValueError("QA_TOOL_FAILED")
        return result.stdout.decode("utf-8", "strict")

    def generate(self, directory, password):
        self._run(self.keytool, ["-genkeypair", "-noprompt", "-storetype", "PKCS12",
            "-keystore", directory / "qa.p12", "-alias", ALIAS, "-keyalg", "RSA",
            "-keysize", "3072", "-validity", "10000", "-dname", "CN=Project OS QA",
            "-storepass:env", "QA_STORE_PASSWORD"], directory, password)

    def certificate(self, directory, password, work):
        self._run(self.keytool, ["-exportcert", "-storetype", "PKCS12", "-keystore",
            directory / "qa.p12", "-alias", ALIAS, "-storepass:env", "QA_STORE_PASSWORD",
            "-file", work / "observed.der"], work, password)
        raw = _private_bytes(work / "observed.der", 16384)
        (work / "observed.der").unlink()
        if not raw:
            raise ValueError("QA_CERTIFICATE_UNAVAILABLE")
        return hashlib.sha256(raw).hexdigest()

    def inspect(self, apk, work):
        out = self._run(self.aapt, ["dump", "badging", apk], work)
        packages = re.findall(r"^package: name='([^']+)' versionCode='([0-9]+)'", out, re.M)
        native = re.findall(r"^native-code:\s*(.*)$", out, re.M)
        if len(packages) != 1 or len(native) != 1:
            raise ValueError("QA_APK_METADATA_INVALID")
        abis = re.findall(r"'([^']+)'", native[0])
        package, version = packages[0]
        if not PACKAGE.fullmatch(package) or not 1 <= int(version) <= 2100000000:
            raise ValueError("QA_APK_METADATA_INVALID")
        return {"package": package, "version_code": int(version), "abis": sorted(set(abis)),
                "debuggable": bool(re.search(r"^application-debuggable(?:\s|$)", out, re.M))}

    def sign(self, source, destination, directory, password, work):
        aligned = work / "aligned.apk"
        self._run(self.zipalign, ["-P", "16", "-f", "4", source, aligned], work)
        self._run(self.apksigner, ["sign", "--ks", directory / "qa.p12", "--ks-type",
            "PKCS12", "--ks-key-alias", ALIAS, "--ks-pass", "env:QA_STORE_PASSWORD",
            "--key-pass", "env:QA_STORE_PASSWORD", "--out", destination, aligned],
            work, password)
        aligned.unlink()

    def verify(self, apk, work):
        self._run(self.zipalign, ["-c", "-P", "16", "4", apk], work)
        out = self._run(self.apksigner, ["verify", "--verbose", "--print-certs", apk], work)
        digests = re.findall(r"^Signer #([0-9]+) certificate SHA-256 digest: ([0-9a-fA-F]{64})$", out, re.M)
        if len(digests) != 1 or digests[0][0] != "1":
            raise ValueError("QA_APK_SIGNER_INVALID")
        return digests[0][1].lower()


def _key(project_root, package, tools):
    directory = project_root / "identity"
    if not os.path.lexists(directory):
        if any((project_root / "artifacts").iterdir()):
            raise ValueError("QA_IDENTITY_UNAVAILABLE")
        with tempfile.TemporaryDirectory(prefix=".key-", dir=project_root) as tmp:
            stage = Path(tmp)
            # Create an entire identity atomically; incomplete identities are
            # never adopted. Once present, missing components fail, not rotate.
            password = secrets.token_hex(32)
            _write(stage / "password", password.encode("ascii"))
            tools.generate(stage, password)
            private_file(stage / "qa.p12")
            cert = tools.certificate(stage, password, stage)
            if not CERT.fullmatch(cert):
                raise ValueError("QA_CERTIFICATE_UNAVAILABLE")
            _write(stage / "identity.json", json.dumps({"package": package,
                "certificate_sha256": cert}, sort_keys=True).encode())
            _adopt(stage, directory)
    private_directory(directory)
    private_file(directory / "qa.p12")
    password = _private_bytes(directory / "password", 64).decode("ascii")
    identity = _read_json(directory / "identity.json")
    if (not re.fullmatch(r"[0-9a-f]{64}", password) or identity.get("package") != package
            or not CERT.fullmatch(identity.get("certificate_sha256", ""))):
        raise ValueError("QA_IDENTITY_INVALID")
    return directory, password, identity["certificate_sha256"]


def _check_metadata(meta, package, minimum):
    if (meta.get("package") != package or type(meta.get("version_code")) is not int
            or not minimum <= meta["version_code"] <= 2100000000
            or set(meta.get("abis", [])) != ABIS or meta.get("debuggable") is not False):
        raise ValueError("QA_APK_METADATA_INVALID")


def finalize_qa_build(jobs, principal, job_id, *, expected_project, expected_sha,
                      expected_package, tools, minimum_version=1):
    """Idempotent private local finalization. No network or PR mutation.

    Local orchestration supplies the reviewed SDK and QA package binding.
    The existing worker lock also excludes another finalizer.
    """
    if (not isinstance(expected_package, str) or not PACKAGE.fullmatch(expected_package)
            or type(minimum_version) is not int or not 1 <= minimum_version <= 2100000000):
        raise ValueError("QA_PACKAGE_BINDING_INVALID")
    with exclusive_worker(jobs):
        return _finalize_locked(jobs, principal, job_id, expected_project=expected_project,
            expected_sha=expected_sha, expected_package=expected_package, tools=tools,
            minimum_version=minimum_version)


def _finalize_locked(jobs, principal, job_id, *, expected_project, expected_sha,
                     expected_package, tools, minimum_version=1):
    """Internal only: the caller owns the existing exclusive worker lock."""
    if jobs.pending_effects():
        raise PermissionError("QA_EFFECTS_PENDING")
    def input_bytes():
        return verified_qa_build_input(jobs, principal, job_id,
            expected_project=expected_project, expected_sha=expected_sha)
    raw, source = input_bytes()
    build = jobs.evidence(principal, job_id)["result"]
    repository_id = build.get("repository_id")
    if type(repository_id) is not int or repository_id <= 0:
        raise ValueError("QA_REPOSITORY_IDENTITY_INVALID")
    project_root = _directory(_directory(jobs.probe.root / "qa-signing") / str(repository_id))
    artifacts = _directory(project_root / "artifacts")
    dest = artifacts / job_id
    base = {"job_id": job_id, "repository_id": repository_id, "head": expected_sha,
            "workspace_sha256": build["workspace_sha256"], "source": source,
            "qa_plan_sha256": build["execution"]["qa_plan_sha256"]}
    if build.get("changes_sha256") is not None:
        base["changes_sha256"] = build["changes_sha256"]
    with tempfile.TemporaryDirectory(prefix=".finalize-", dir=project_root) as tmp:
        work = Path(tmp)
        if os.path.lexists(dest):
            private_directory(dest)
            receipt = _read_json(dest / "receipt.json")
            for key, value in base.items():
                if receipt.get(key) != value:
                    raise ValueError("QA_RECEIPT_IDENTITY_MISMATCH")
            # Replay does not generate a key if the existing identity was lost.
            if not os.path.lexists(project_root / "identity"):
                raise ValueError("QA_IDENTITY_UNAVAILABLE")
            directory, password, cert = _key(project_root, expected_package, tools)
            apk = dest / "app-qa.apk"
            _check_metadata(receipt.get("metadata", {}), expected_package, minimum_version)
            if (tools.certificate(directory, password, work) != cert
                    or tools.verify(apk, work) != cert
                    or tools.inspect(apk, work) != receipt["metadata"]
                    or receipt.get("certificate_sha256") != cert
                    or receipt.get("artifact") != artifact_identity("apk", "app-qa.apk", _apk_bytes(apk))
                    or input_bytes()[1] != source):
                raise ValueError("QA_RECEIPT_IDENTITY_MISMATCH")
            return receipt
        _write(work / "input.apk", raw)
        # Do not create a key for an invalid APK.
        metadata = tools.inspect(work / "input.apk", work)
        for old in artifacts.iterdir():
            if not re.fullmatch(r"[0-9a-f]{32}", old.name):
                raise ValueError("QA_HISTORY_INVALID")
            private_directory(old)
            record = _read_json(old / "receipt.json")
            if record.get("repository_id") != repository_id or record.get("job_id") != old.name:
                raise ValueError("QA_HISTORY_INVALID")
            _check_metadata(record.get("metadata", {}), expected_package, 1)
            minimum_version = max(minimum_version, record["metadata"]["version_code"])
        _check_metadata(metadata, expected_package, minimum_version)
        directory, password, cert = _key(project_root, expected_package, tools)
        for old in artifacts.iterdir():
            if _read_json(old / "receipt.json").get("certificate_sha256") != cert:
                raise ValueError("QA_CERTIFICATE_CHANGED")
        if tools.certificate(directory, password, work) != cert:
            raise ValueError("QA_CERTIFICATE_CHANGED")
        stage = _directory(work / "output")
        apk = stage / "app-qa.apk"
        tools.sign(work / "input.apk", apk, directory, password, work)
        if tools.verify(apk, work) != cert or tools.inspect(apk, work) != metadata:
            raise ValueError("QA_APK_SIGNER_INVALID")
        identity = artifact_identity("apk", "app-qa.apk", _apk_bytes(apk))
        if input_bytes()[1] != source or jobs.pending_effects():
            raise PermissionError("QA_BUILD_IDENTITY_CHANGED")
        receipt = {**base, "metadata": metadata, "certificate_sha256": cert,
                   "artifact": identity, "signature_verified": True, "published": False}
        _write(stage / "receipt.json", json.dumps(receipt, sort_keys=True).encode())
        _adopt(stage, dest)
        return receipt


class QASignerBinding:
    """Operator-reviewed local signing recipe, frozen with the execution binding."""
    def __init__(self, config):
        if (not isinstance(config, dict)
                or set(config) != {"package", "java_home", "build_tools"}
                or not all(isinstance(value, str) for value in config.values())
                or not PACKAGE.fullmatch(config["package"])):
            raise ValueError("QA_SIGNER_BINDING_INVALID")
        self.package = config["package"]
        self.tools = AndroidQATools(config["java_home"], config["build_tools"])
        self.digest = hashlib.sha256(json.dumps(config, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()

    def finalize_locked(self, jobs, principal, job_id, request):
        from .workspace_jobs import require_workspace_job
        if (request.get("qa_signer_sha256") != self.digest
                or require_workspace_job(jobs, principal, job_id, allow_execute=True) != request):
            raise PermissionError("QA_SIGNER_BINDING_CHANGED")
        return _finalize_locked(jobs, principal, job_id, expected_project=request["project"],
            expected_sha=request["expected_sha"], expected_package=self.package, tools=self.tools)


def finalize_pending_locked(jobs, backend, *, enabled):
    """Resume only successful builds with a frozen signer, before the next build.

    The atomic receipt makes a crash after signing but before recording safe.
    Failed attempts are recorded and not retried automatically.
    """
    if not backend.qa_signers:
        return
    with jobs.transaction() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT jobs.id,jobs.principal,jobs.result,workspace_inputs.request "
            "FROM jobs JOIN workspace_inputs ON jobs.id=workspace_inputs.job_id "
            "WHERE jobs.workflow='workspace_execute' AND jobs.state='SUCCEEDED' "
            "AND json_extract(workspace_inputs.request,'$.qa_signer_sha256') IS NOT NULL "
            "AND json_extract(jobs.result,'$.qa_finalization') IS NULL "
            "ORDER BY jobs.created,jobs.id")]
    for row in rows:
        if not enabled() or jobs.pending_effects():
            return
        request = json.loads(row["request"])
        result = json.loads(row["result"])
        try:
            signer = backend.qa_signers[backend.route(request["profile"], request["project"])]
            if (backend.plan_digest(request["profile"], request["project"]) != request["qa_plan_sha256"]
                    or signer.digest != request["qa_signer_sha256"]):
                raise PermissionError("QA_SIGNER_BINDING_CHANGED")
            receipt = signer.finalize_locked(jobs, row["principal"], row["id"], request)
            outcome = {"state": "SUCCEEDED", "receipt": receipt}
        except PermissionError:
            outcome = {"state": "BLOCKED", "reason": "QA_FINALIZATION_DENIED"}
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            outcome = {"state": "FAILED", "reason": "QA_FINALIZATION_FAILED"}
        result["qa_finalization"] = outcome
        with jobs.transaction() as conn:
            changed = conn.execute("UPDATE jobs SET result=? WHERE id=? AND state='SUCCEEDED' AND result=?",
                (json.dumps(result, sort_keys=True), row["id"], row["result"]))
            if changed.rowcount != 1:
                raise RuntimeError("QA_FINALIZATION_RECORD_CONFLICT")
