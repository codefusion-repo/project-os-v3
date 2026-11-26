import json
import os
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_os_bridge.service_setup import prepare_service, generate_tls, write_new
from project_os_bridge.supervised import commands, stop_child


class ServiceSetupTests(unittest.TestCase):
    def test_tls_chain_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            generate_tls(root)
            from project_os_bridge.authenticated import tls_options
            tls_options(root/"server.pem",root/"server-key.pem")
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(cafile=str(root/"ca.pem"))
            before=(root/"ca.pem").read_bytes()
            with self.assertRaises(FileExistsError):
                generate_tls(root)
            self.assertEqual((root/"ca.pem").read_bytes(),before)

    @unittest.skipIf(os.getuid()==0,"Requires unprivileged user")
    def test_prepare_preserves_state_and_separates_key(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            state=root/"state"
            state.mkdir(mode=0o700)
            config={"issuer":"https://fixture.authkit.app","resource":"https://api.openai.com/v1/mcp/tunnel_fixture","subject":"user_fixture"}
            write_new(root/"oauth.json",json.dumps(config).encode())
            write_new(state/"allow-authenticated-probe",b"")
            marker=state/"allow-authenticated-probe"
            key="synthetic-test-runtime-key"
            tunnel=root/"tunnel-client"
            write_new(tunnel,b"#!/bin/sh\nexit 0\n")
            tunnel.chmod(0o700)
            with patch("project_os_bridge.service_setup.os.path.lexists",return_value=False), patch.object(sys,"base_prefix","/synthetic-base"):
                service=prepare_service(root,tunnel,key)
            self.assertTrue(marker.exists())
            self.assertEqual(json.loads((root/"oauth.json").read_text()),config)
            bridge,cmd,env,tenv,context,_=commands(root)
            self.assertNotIn(key," ".join(bridge+cmd))
            self.assertNotIn("CONTROL_PLANE_API_KEY",env)
            self.assertEqual(tenv["CONTROL_PLANE_API_KEY"],key)
            self.assertNotIn("HARPOON_ALLOW_PLAINTEXT_HTTP",tenv)
            self.assertIn("https://127.0.0.1:8765/mcp",cmd)
            self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertEqual((service/"runtime-key").stat().st_mode&0o777,0o600)
            self.assertNotIn("--project-config", bridge)
            project = root / "project" / ".project-os"
            project.mkdir(parents=True, mode=0o700)
            locator = project / "config.json"
            write_new(locator, b"{}")
            runtime_path = service / "runtime.json"
            runtime = json.loads(runtime_path.read_text())
            runtime_path.write_text(json.dumps({**runtime, "project_config": str(locator)}))
            bridge, cmd, env, tenv, context, _ = commands(root)
            self.assertEqual(bridge[bridge.index("--project-config") + 1], str(locator))
            self.assertNotIn(str(locator), cmd)
            self.assertNotIn(key, " ".join(bridge + cmd))
            runtime_path.write_text(json.dumps({**runtime, "project_config": "relative/config.json"}))
            with self.assertRaises(ValueError):
                commands(root)
            runtime_path.write_text(json.dumps(runtime))
            with self.assertRaises(FileExistsError):
                with patch("project_os_bridge.service_setup.os.path.lexists",return_value=False), patch.object(sys,"base_prefix","/synthetic-base"):
                    prepare_service(root,tunnel,key)
            (service/"runtime-key").chmod(0o644)
            with self.assertRaises(PermissionError):
                commands(root)

    def test_stop_child(self):
        import subprocess
        child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])
        try:
            stop_child(child,5)
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()

    @unittest.skipIf(os.getuid()==0,"Requires unprivileged user")
    def test_supervisor_checks_existing_binding_before_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            state = root / "state"
            state.mkdir(mode=0o700)
            config = {"issuer": "https://fixture.authkit.app", "subject": "user_fixture",
                      "resource": "https://api.openai.com/v1/mcp/tunnel_fixture"}
            write_new(root / "oauth.json", json.dumps(config).encode())
            tunnel = root / "tunnel-client"
            write_new(tunnel, b"#!/bin/sh\nexit 0\n")
            tunnel.chmod(0o700)
            image, authorized = "example/python@sha256:" + "a" * 64, "1" * 64
            write_new(state / "fixture-image", (image + "\n").encode())
            write_new(state / "fixture-context", (authorized + "\n").encode())
            context = Path("/unused-test-context")
            with patch("project_os_bridge.service_setup.os.path.lexists", return_value=False), \
                    patch.object(sys, "base_prefix", "/synthetic-base"), \
                    patch("project_os_bridge.service_setup.PodmanContext") as prepare_context:
                prepare_service(root, tunnel, "synthetic-test-runtime-key", image, podman_context=context)
            prepare_context.assert_called_once_with(context)
            prepare_context.return_value.identity.assert_called_once_with(authorized)
            with patch("project_os_bridge.supervised.PodmanContext") as verify_context:
                verify_context.return_value.identity.side_effect = PermissionError("context replaced")
                with self.assertRaisesRegex(PermissionError, "context replaced"):
                    commands(root)
            verify_context.assert_called_once_with(context)
            verify_context.return_value.identity.assert_called_once_with(authorized)
