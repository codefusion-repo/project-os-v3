"""Real negative containment control, only inside disposable hosted CI."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from project_os_bridge.core import Jobs, Policy, QueueLimitError
from project_os_bridge.isolated import container_absent, container_name
from project_os_bridge.podman_context import PodmanContext
from project_os_bridge.reconcile import reconcile
from project_os_bridge.worker import exclusive_worker, run_pending


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def checked(context, identity, *args):
    result = context.run(identity, *args, capture=True)
    require(result.returncode == 0, "Disposable Podman control failed")
    return result.stdout


def inspect_owned(context, identity, cid, token):
    values = json.loads(checked(context, identity, "container", "inspect", cid))
    require(isinstance(values, list) and len(values) == 1, "Unexpected inspect identity")
    item = values[0]
    require(item["Id"] == cid and item["Config"]["Labels"].get("io.project-os.fixture") == token
            and item["State"]["Running"] is False, "Container ownership or lifecycle mismatch")
    return item


def main():
    require(os.environ.get("GITHUB_ACTIONS") == "true" and os.getuid() != 0,
            "Disposable hosted CI only")
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    expected = (Path(__file__).parent / "alpine-fixture-only-manifest.sha256").read_text().strip()
    image = sys.argv[1]
    require(image == "localhost/project-os-alpine-ci@" + expected, "Unexpected locked candidate")
    context = PodmanContext(Path(sys.argv[2]))
    identity = context.identity()
    context.host(identity)
    context.require_import(identity, image)
    with tempfile.TemporaryDirectory(prefix="reconcile-control-", dir=runner) as folder:
        root = Path(folder).resolve()
        policy = Policy(("ci", op, "disposable") for op in ("submit", "read", "git_workflow"))
        jobs = Jobs(root, policy, workflows=("probe_check", "git_fixture_check"))
        first = jobs.submit("ci", "disposable", "git_fixture_check", "first")
        second = jobs.submit("ci", "disposable", "probe_check", "second")
        with exclusive_worker(jobs):
            row = jobs.claim(fixture_context=identity)
        require(row["id"] == first, "Wrong claimed job")
        token = row["effect_token"]
        name = container_name(token)
        require(container_absent(context, identity, token), "Unexpected preexisting container")
        cid = checked(context, identity, "create", "--name", name, "--label", "io.project-os.fixture=" + token,
                      "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL",
                      "--security-opt=no-new-privileges", "--entrypoint", "python",
                      image, "-I", "-B", "-c", "pass").decode("ascii").strip()
        require(re.fullmatch(r"[0-9a-f]{64}", cid) is not None, "Missing immutable container ID")
        try:
            inspect_owned(context, identity, cid, token)
            reopened = Jobs(root, policy, workflows=("probe_check", "git_fixture_check"))
            run_pending(reopened, fixture_image=image)
            require(reopened.get("ci", first)["state"] == "INTERRUPTED", "Interrupted state lost")
            require(reopened.get("ci", second)["state"] == "QUEUED", "Queue drained despite barrier")
            for renamed in (False, True):
                if renamed:
                    checked(context, identity, "rename", cid, name + "-renamed")
                    require(context.run(identity, "container", "exists", name).returncode == 1,
                            "Original name still exists")
                inspect_owned(context, identity, cid, token)
                try:
                    reconcile(reopened, first, context)
                except PermissionError:
                    pass
                else:
                    raise RuntimeError("Reconciled a still-existing owned container")
                require(len(reopened.pending_effects()) == 1 and reopened.claim() is None,
                        "Uncertain effect did not block claims")
            try:
                reopened.submit("ci", "disposable", "probe_check", "third")
            except QueueLimitError:
                pass
            else:
                raise RuntimeError("New submission admitted during barrier")
        finally:
            # CI cleanup only: the exact ID created above, verified again, never
            # a name, a running container, a wildcard, or a foreign resource.
            inspect_owned(context, identity, cid, token)
            checked(context, identity, "rm", cid)
        require(container_absent(context, identity, token), "Owned container absence not established")
        reconcile(reopened, first, context)
        require(not reopened.pending_effects(), "Barrier not cleared")
        require(reopened.get("ci", second)["state"] == "QUEUED", "Reconciliation dispatched work")
        run_pending(reopened)
        require(reopened.get("ci", second)["state"] == "SUCCEEDED", "Queue did not resume")
        require(reopened.get("ci", first)["state"] == "INTERRUPTED", "Uncertain job replayed")
        print("REAL_RECONCILIATION_NEGATIVE_PASS: name/label, rename, immutable-ID cleanup, restart, explicit absence, no replay")


if __name__ == "__main__":
    main()
