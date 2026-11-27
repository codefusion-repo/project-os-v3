import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from project_os_bridge.core import Jobs, Policy
from project_os_bridge.drive_delivery import DrivePublisher, DriveDeliveryError, SCOPE, MIME
from project_os_bridge.qa_drive_job import deliver_qa


class DriveDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.credential = self.root / "credential.json"
        self.credential.touch(mode=0o600)
        self.credential.write_text(json.dumps({"client_id": "fixture", "client_secret": "fixture",
            "refresh_token": "fixture", "scope": SCOPE}))
        self.raw = b"synthetic apk"
        self.artifact = {"kind": "apk", "artifact": "app-qa.apk",
                         "sha256": hashlib.sha256(self.raw).hexdigest(), "size": len(self.raw)}
        self.props = {"job_id": "a" * 32}
        self.shared = False
        self.tampered = False
        self.uploads = 0

    def handler(self, req):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fixture", "token_type": "Bearer", "scope": SCOPE})
        if req.url.path.endswith("/permissions"):
            perms = [{"id": "owner", "type": "user", "role": "owner"}]
            if self.shared:
                perms.append({"id": "any", "type": "anyone", "role": "reader"})
            return httpx.Response(200, json={"permissions": perms})
        if req.url.path.endswith("/generateIds"):
            return httpx.Response(200, json={"ids": ["remote"]})
        if req.url.path.endswith("/folder"):
            return httpx.Response(200, json={"id": "folder", "mimeType": "application/vnd.google-apps.folder",
                "trashed": False, "ownedByMe": True, "capabilities": {"canAddChildren": True}})
        if req.method == "POST":
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=fixture"})
        if req.method == "PUT":
            self.uploads += 1
            self.assertEqual(req.content, self.raw)
            self.assertNotIn("authorization", req.headers)
            return httpx.Response(200, json={"id": "remote"})
        if req.url.params.get("alt") == "media":
            return httpx.Response(200, content=b"x" * len(self.raw) if self.tampered else self.raw)
        return httpx.Response(200, json={"id": "remote", "name": "qa-" + self.props["job_id"] + ".apk",
            "mimeType": MIME, "parents": ["folder"], "trashed": False, "ownedByMe": True,
            "appProperties": self.props, "size": str(len(self.raw)), "sha256Checksum": self.artifact["sha256"]})

    def publisher(self):
        p = DrivePublisher(self.credential, "folder", "owner", transport=httpx.MockTransport(self.handler))
        self.addCleanup(p.close)
        return p

    def test_upload_and_readback(self):
        p = self.publisher()
        self.assertEqual(p.reserve(), "remote")
        p.upload("remote", self.raw, self.props)
        self.assertEqual(p.verify("remote", self.artifact, self.props)["sha256"], self.artifact["sha256"])
        self.assertEqual(self.uploads, 1)
        self.tampered = True
        with self.assertRaises(DriveDeliveryError):
            p.verify("remote", self.artifact, self.props)

    def test_shared_folder_denied(self):
        self.shared = True
        with self.assertRaises(PermissionError):
            self.publisher().reserve()
        self.assertEqual(self.uploads, 0)

    def test_durable_uncertain_and_reconcile(self):
        policy = Policy([("operator", "submit", "disposable"), ("operator", "read", "disposable"),
                         ("operator", "workspace_delivery", "demo")])
        jobs = Jobs(self.root, policy)
        job = jobs.submit("operator", "disposable", "probe_check", "qa-fixture")
        jobs.claim()
        jobs.finish(job, "SUCCEEDED", {})
        receipt = {"artifact": self.artifact, "workspace_sha256": "c" * 64}
        pub = Mock()
        pub.binding = "d" * 64
        pub.reserve.return_value = "remote"
        pub.upload.side_effect = DriveDeliveryError("uncertain")
        pub.verify.return_value = {"file_id": "remote", "sha256": self.artifact["sha256"],
            "size": self.artifact["size"], "url": "https://drive.google.com/file/d/remote/view"}
        args = dict(project="demo", head="a" * 40, repository_id=123, pr=1,
                    publisher=pub, check_target=Mock())
        with patch("project_os_bridge.qa_drive_job._verified_qa_delivery_locked",
                   return_value=(self.raw, receipt)):
            with self.assertRaises(DriveDeliveryError):
                deliver_qa(jobs, "operator", job, **args)
            self.assertEqual(jobs.evidence("operator", job)["result"]["qa_delivery"]["state"], "UNCERTAIN")
            reopened = Jobs(self.root, policy)
            result = deliver_qa(reopened, "operator", job, **args, reconcile_only=True)
            self.assertEqual(result["state"], "SUCCEEDED")
            deliver_qa(reopened, "operator", job, **args)
        pub.reserve.assert_called_once()
        pub.upload.assert_called_once()

    def test_reserved_id_can_resume_before_any_upload(self):
        policy = Policy([("operator", "submit", "disposable"), ("operator", "read", "disposable"),
                         ("operator", "workspace_delivery", "demo")])
        jobs = Jobs(self.root, policy)
        job = jobs.submit("operator", "disposable", "qa-reserved")
        jobs.claim()
        jobs.finish(job, "SUCCEEDED", {})
        receipt = {"artifact": self.artifact, "workspace_sha256": "c" * 64}
        pub = Mock()
        pub.binding = "d" * 64
        pub.reserve.return_value = "remote"
        pub.verify.return_value = {"file_id": "remote", "sha256": self.artifact["sha256"],
            "size": self.artifact["size"], "url": "https://drive.google.com/file/d/remote/view"}
        guard = Mock(side_effect=[None, None, PermissionError("interrupted before create")])
        args = dict(project="demo", head="a" * 40, repository_id=123, pr=1,
                    publisher=pub, check_target=guard)
        with patch("project_os_bridge.qa_drive_job._verified_qa_delivery_locked",
                   return_value=(self.raw, receipt)):
            with self.assertRaises(PermissionError):
                deliver_qa(jobs, "operator", job, **args)
            self.assertEqual(jobs.evidence("operator", job)["result"]["qa_delivery"]["state"], "RESERVED")
            pub.upload.assert_not_called()
            guard.side_effect = None
            result = deliver_qa(Jobs(self.root, policy), "operator", job, **args, reconcile_only=True)
            self.assertEqual(result["state"], "SUCCEEDED")
        pub.reserve.assert_called_once()
        pub.upload.assert_called_once()
