"""Local-only disposable revision/package profile. Never runs repository code."""
import hashlib
import io
import json
import os
import re
import zipfile

from .core import Jobs, Policy
from .git_fixture import GitFixture, SHA, FILE
from .workos_auth import private_directory, private_file
from .worker import run_pending

MARKER = "local-package-mode"
PRINCIPAL = "local-package"
OPERATIONS = ("submit", "read", "cancel", "git_prepare", "git_read", "fixture_package")
ARTIFACT = "fixture.zip"


def require_package(root):
    private_directory(root)
    if (private_file(root / MARKER).st_size != 0
            or any(os.path.lexists(root / name) for name in
                   ("allow-authenticated-probe", "local-fixture-mode", "fixture-image", "fixture-context"))):
        raise PermissionError("Dedicated package fixture state required")
    private_directory(root / "source")


def package_jobs(root, *, initialize=False):
    private_directory(root)
    policy = Policy((PRINCIPAL, op, "disposable") for op in OPERATIONS)
    if initialize:
        if any(root.iterdir()):
            raise PermissionError("Use a new empty private directory")
        fd = os.open(root / MARKER, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        source = root / "source"
        source.mkdir(mode=0o700)
        sha = GitFixture(source, policy).initialize(PRINCIPAL)
    else:
        sha = None
    require_package(root)
    if not initialize:
        private_file(root / "jobs.sqlite3")
        private_file(root / "probe.sqlite3")
    return Jobs(root, policy, workflows=("fixture_package",)), sha


def package_bytes(data):
    # Fixed stdlib builder; fixture bytes are data, never imported or executed.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as archive:
        entry = zipfile.ZipInfo(FILE, date_time=(1980, 1, 1, 0, 0, 0))
        entry.create_system = 3
        entry.external_attr = 0o100644 << 16
        archive.writestr(entry, data)
    return buf.getvalue()


def run_package(jobs, row):
    principal, sha, job_id = row["principal"], row["expected_sha"], row["id"]
    root = jobs.probe.root
    result = {"profile": "fixture-package", "head": sha, "steps": []}
    try:
        require_package(root)
        if principal != PRINCIPAL or row["resource"] != "disposable":
            raise PermissionError("DENIED")
        for operation in ("fixture_package", "git_prepare", "git_read"):
            jobs.policy.require(principal, operation, "disposable")
        repo = GitFixture(root / "source", jobs.policy, job_id=job_id)
        snapshot = repo.prepare(principal, sha)
        if snapshot["head"] != sha or repo.diff(principal)["diff"]:
            raise ValueError("REVISION_CONFLICT")
        data = snapshot["text"].encode("utf-8")
        if hashlib.sha256(data).hexdigest() != snapshot["revision"]:
            raise ValueError("REVISION_CONFLICT")
        result["revision"] = snapshot["revision"]
        result["steps"].append({"step": "prepare", "head": sha, "revision": snapshot["revision"]})
        # No source evaluation, dependency acquisition, subprocess or host fallback.
        passed = bool(data.strip())
        result["steps"].append({"step": "validate", "check": "nonempty_utf8",
                                "exit_code": 0 if passed else 1})
        if not passed:
            return "FAILED", result
        require_package(root)
        jobs.policy.require(principal, "fixture_package", "disposable")
        raw = package_bytes(data)
        folder = root / ("package-" + job_id)
        folder.mkdir(mode=0o700)
        artifact = folder / ARTIFACT
        fd = os.open(artifact, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        for directory in (folder, root):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        if private_file(artifact).st_size != len(raw) or artifact.read_bytes() != raw:
            raise RuntimeError("PACKAGE_VERIFICATION_FAILED")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if archive.namelist() != [FILE] or archive.read(FILE) != data:
                raise RuntimeError("PACKAGE_VERIFICATION_FAILED")
        result["steps"].append({"step": "build", "exit_code": 0, "artifact": ARTIFACT,
                                "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
        return "SUCCEEDED", result
    except (PermissionError, ValueError, FileExistsError):
        result["error"] = "PACKAGE_PREFLIGHT_BLOCKED"
        return "BLOCKED", result
    except (OSError, RuntimeError):
        result["error"] = "PACKAGE_FAILED"
        return "FAILED", result


def package_cli(args, parser):
    if args.image is not None or args.podman_context is not None:
        parser.error("Package fixture does not use a container image")
    if args.initialize:
        if args.expected_sha is not None:
            parser.error("Initialization does not accept a SHA")
        _, sha = package_jobs(args.state_dir, initialize=True)
        print(json.dumps({"profile": "fixture-package", "head": sha}))
        return
    if args.evidence_job_id is not None:
        if args.expected_sha is not None or not re.fullmatch(r"[0-9a-f]{32}", args.evidence_job_id):
            parser.error("Evidence requires a job ID and no SHA")
        jobs, _ = package_jobs(args.state_dir)
        print(json.dumps(jobs.evidence(PRINCIPAL, args.evidence_job_id), indent=2))
        return
    if not args.expected_sha or not SHA.fullmatch(args.expected_sha):
        parser.error("Exact full fixture SHA required")
    jobs, _ = package_jobs(args.state_dir)
    job = jobs.submit(PRINCIPAL, "disposable", "fixture_package", args.request_key,
                      expected_sha=args.expected_sha)
    run_pending(jobs)
    evidence = jobs.evidence(PRINCIPAL, job)
    print(json.dumps(evidence, indent=2))
    raise SystemExit(0 if evidence["state"] == "SUCCEEDED" else 1)
