"""Opt-in rootless Podman profile; no fallback to host execution."""
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from .git_fixture import GitFixture

IMAGE = re.compile(r"[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}")
SCRIPT = "from pathlib import Path; import sys; sys.exit(0 if Path('/fixture/fixture.txt').read_bytes() == b'after\\n' else 1)"


def validate_in_container(repo: GitFixture, principal, expected_revision, image):
    repo.policy.require(principal,"fixture_validate","disposable")
    if not isinstance(image,str) or not IMAGE.fullmatch(image):
        raise ValueError("Locally approved digest-pinned image required")
    snapshot=repo.snapshot(principal)
    if snapshot["revision"] != expected_revision:
        return {"status":"BLOCKED","reason":"REVISION_CONFLICT"}
    if os.getuid()==0:
        return {"status":"BLOCKED","reason":"ROOTLESS_REQUIRED"}
    env={"PATH":"/usr/bin:/bin","HOME":os.environ.get("HOME",""),
         "XDG_RUNTIME_DIR":f"/run/user/{os.getuid()}","LC_ALL":"C"}
    name="project-os-fixture-"+uuid.uuid4().hex
    try:
        info=subprocess.run(["/usr/bin/podman","info","--format","{{.Host.Security.Rootless}}"],
                            env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10)
        if info.returncode or info.stdout.strip()!=b"true":
            return {"status":"BLOCKED","reason":"ROOTLESS_UNAVAILABLE"}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/"fixture.txt").write_text(snapshot["text"],encoding="utf-8")
            # Export only fixed data, not Git metadata, state, home, sockets or credentials.
            args=["/usr/bin/podman","run","--rm","--name",name,"--pull=never",
                  "--network=none","--read-only","--cap-drop=ALL","--security-opt=no-new-privileges",
                  "--http-proxy=false","--image-volume=ignore",
                  "--pids-limit=64","--memory=128m","--cpus=1","--userns=keep-id",
                  "--volume",f"{path}:/fixture:ro","--entrypoint","python",image,"-I","-c",SCRIPT]
            try:
                result=subprocess.run(args,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL,timeout=30)
                return {"status":"SUCCEEDED" if result.returncode==0 else "FAILED",
                        "exit_code":result.returncode,"revision":expected_revision,"profile":"fixture-python"}
            finally:
                subprocess.run(["/usr/bin/podman","rm","-f","--ignore",name],env=env,
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    except (OSError,subprocess.TimeoutExpired):
        return {"status":"BLOCKED","reason":"ISOLATION_UNAVAILABLE_OR_TIMEOUT"}
