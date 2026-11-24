import json
import unittest
from unittest.mock import Mock, patch
from project_os_bridge.isolated import validate_in_container, SCRIPT, CHECKS

IMAGE="python@sha256:"+"a"*64

class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.repo=Mock()
        self.repo.snapshot.return_value={"revision":"expected","text":"after\n"}

    def invoke(self):
        return validate_in_container(self.repo,"local","expected",IMAGE,token="b"*32)

    def info(self,**kwargs):
        security={"rootless":True,"seccompEnabled":True,**kwargs}
        return Mock(returncode=0,stdout=json.dumps({"host":{"security":security,"cgroupVersion":"v2"}}).encode())

    def test_revision_conflict(self):
        self.repo.snapshot.return_value={"revision":"other"}
        with patch("project_os_bridge.isolated.subprocess.run") as run:
            self.assertEqual(self.invoke()["reason"],"REVISION_CONFLICT")
            run.assert_not_called()

    def test_no_root_execution(self):
        with patch("project_os_bridge.isolated.os.getuid",return_value=0), patch("project_os_bridge.isolated.subprocess.run") as run:
            self.assertEqual(self.invoke()["reason"],"ROOTLESS_REQUIRED")
            run.assert_not_called()

    def test_no_unpinned_image(self):
        for image in ("python:latest","--evil@sha256:"+"a"*64):
            with self.assertRaises(ValueError):
                validate_in_container(self.repo,"local","expected",image,token="b"*32)

    def test_validation_command_and_exact_bytes(self):
        compile(SCRIPT,"<fixture>","exec")
        self.assertIn("== b'after\\n'",SCRIPT)
        with patch("project_os_bridge.isolated.os.getuid",return_value=1000), patch("project_os_bridge.isolated.subprocess.run") as run:
            run.side_effect=[self.info(),Mock(returncode=0),Mock(returncode=1),Mock(returncode=0,stdout=b"")]
            result=self.invoke()
        self.assertEqual(result["status"],"SUCCEEDED")
        self.assertEqual(result["checks"],CHECKS)
        self.assertTrue(result["cleanup_verified"])
        args=run.call_args_list[1].args[0]
        for flag in ("--pull=never","--network=none","--read-only","--read-only-tmpfs=false","--cap-drop=ALL","--http-proxy=false","--image-volume=ignore","--pid=private","--ipc=private","--cgroupns=private"):
            self.assertIn(flag,args)

    def test_preflight_denies_without_seccomp(self):
        with patch("project_os_bridge.isolated.os.getuid",return_value=1000), patch("project_os_bridge.isolated.subprocess.run",return_value=self.info(seccompEnabled=False)) as run:
            self.assertEqual(self.invoke()["reason"],"SECURITY_PREFLIGHT_FAILED")
            self.assertEqual(run.call_count,1)

    def test_cleanup_is_required(self):
        with patch("project_os_bridge.isolated.os.getuid",return_value=1000), patch("project_os_bridge.isolated.subprocess.run") as run:
            run.side_effect=[self.info(),Mock(returncode=0),Mock(returncode=0),Mock(returncode=0,stdout=b"")]
            self.assertEqual(self.invoke()["reason"],"CLEANUP_UNVERIFIED")

    def test_negative_probe_failure(self):
        with patch("project_os_bridge.isolated.os.getuid",return_value=1000), patch("project_os_bridge.isolated.subprocess.run") as run:
            run.side_effect=[self.info(),Mock(returncode=14),Mock(returncode=1),Mock(returncode=0,stdout=b"")]
            result=self.invoke()
            self.assertEqual(result["status"],"FAILED")
            self.assertEqual(result["checks"],[])

    def test_run_timeout_requires_reconciliation(self):
        import subprocess
        with patch("project_os_bridge.isolated.os.getuid",return_value=1000), patch("project_os_bridge.isolated.subprocess.run") as run:
            run.side_effect=[self.info(),subprocess.TimeoutExpired("podman",30)]
            result=self.invoke()
        self.assertEqual(result["reason"],"CLEANUP_UNVERIFIED")
        self.assertFalse(result["container_absent"])
        self.assertEqual(run.call_count,2)
