"""Fixed two-child HTTPS supervisor; no remote control or shell."""
import argparse
import fcntl
import json
import os
import re
import signal
import ssl
import subprocess
import sys
import threading
import time
import stat
from pathlib import Path

from .workos_auth import load_config, private_directory, private_file
from .authenticated import tls_options
from .isolated import IMAGE
from .service_setup import checked_path
from .readiness import read_metadata, verify_metadata


def read_private(path, limit):
    if private_file(path).st_size > limit:
        raise ValueError("Private configuration too large")
    return path.read_text(encoding="utf-8")


def commands(root):
    checked_path(root)
    private_directory(root)
    verifier = load_config(root / "oauth.json", root / "state")
    service = root / "service"
    private_directory(service)
    config = json.loads(read_private(service / "runtime.json", 4096))
    if not isinstance(config, dict) or set(config) != {"tunnel", "tunnel_id", "image"}:
        raise ValueError("Invalid service configuration")
    tunnel = checked_path(Path(config["tunnel"]))
    info = tunnel.stat()
    if not tunnel.is_file() or info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022 or not os.access(tunnel, os.X_OK):
        raise PermissionError("Trusted executable required")
    if config["tunnel_id"] != verifier.resource.rsplit("/", 1)[-1]:
        raise ValueError("Tunnel identity mismatch")
    image = config["image"]
    if image is not None:
        if not isinstance(image, str) or not IMAGE.fullmatch(image):
            raise ValueError("Invalid fixture image")
        if read_private(root / "state" / "fixture-image", 1024) != image + "\n":
            raise PermissionError("Fixture binding mismatch")
    key = read_private(service / "runtime-key", 4096)
    if not re.fullmatch(r"[!-~]{16,4096}", key):
        raise ValueError("Invalid runtime key")
    if read_private(service / "tunnel.yaml", 16) != "{}\n":
        raise ValueError("Unexpected tunnel configuration")
    ca, cert, cert_key = (service / name for name in ("ca.pem","server.pem","server-key.pem"))
    private_file(ca)
    tls_options(cert, cert_key)
    # Trust only this private CA for the readiness probe.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(ca))
    env = {"PATH":"/usr/bin:/bin", "HOME":str(Path.home()), "LC_ALL":"C",
           "XDG_RUNTIME_DIR":f"/run/user/{os.getuid()}"}
    bridge = [sys.executable, "-I", "-m", "project_os_bridge.authenticated",
              "--config",str(root/"oauth.json"),"--state-dir",str(root/"state"),
              "--port","8765","--tls-cert",str(cert),"--tls-key",str(cert_key),
              "--supervised-ca",str(ca)]
    if image:
        bridge += ["--fixture-image", image]
    tunnel_cmd = [str(tunnel),"run","--config",str(service/"tunnel.yaml"),
                  "--mcp.server-url","https://127.0.0.1:8765/mcp",
                  "--ca-bundle",str(ca),"--mcp.oauth-trusted-origin",verifier.issuer]
    tunnel_env = dict(env, CONTROL_PLANE_TUNNEL_ID=config["tunnel_id"], CONTROL_PLANE_API_KEY=key)
    return bridge, tunnel_cmd, env, tunnel_env, context, verifier


def stop_child(child, timeout):
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)
        raise RuntimeError("Forced child termination; inspect local state")


def supervise(bridge_cmd, tunnel_cmd, env, tunnel_env, context, verifier, stop):
    bridge = tunnel = None
    # Check the port before starting the child; never reuse an existing listener.
    import socket
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1",8765))
    try:
        if stop.is_set():
            return
        bridge = subprocess.Popen(bridge_cmd, env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic()+30
        while not stop.is_set():
            if bridge.poll() is not None or time.monotonic()>=deadline:
                raise RuntimeError("Local TLS readiness failed")
            try:
                metadata = read_metadata(context)
                verify_metadata(metadata, verifier)
                break
            except (OSError, ValueError):
                stop.wait(0.25)
        if stop.is_set():
            return
        if bridge.poll() is not None:
            raise RuntimeError("Bridge exited before tunnel launch")
        tunnel = subprocess.Popen(tunnel_cmd,env=tunnel_env,stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        print("HTTPS_BRIDGE_READY; TUNNEL_STARTED (remote readiness unverified)",flush=True)
        while not stop.wait(0.5):
            if bridge.poll() is not None or tunnel.poll() is not None:
                raise RuntimeError("Child exited; both services stopping")
    finally:
        try:
            stop_child(tunnel,10)
        finally:
            stop_child(bridge,90)


def run(root):
    if os.getuid() == 0:
        raise PermissionError("Unprivileged account required")
    checked_path(root)
    private_directory(root / "service")
    fd = os.open(root/"service"/"supervisor.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise PermissionError("Unsafe supervisor lock")
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        bridge_cmd, tunnel_cmd, env, tunnel_env, context, verifier = commands(root)
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_:stop.set())
        supervise(bridge_cmd, tunnel_cmd, env, tunnel_env, context, verifier, stop)
    finally:
        os.close(fd)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    args=parser.parse_args()
    os.umask(0o077)
    try:
        run(args.root)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        print("SUPERVISOR_BLOCKED_OR_FAILED; inspect local configuration",file=sys.stderr)
        raise SystemExit(1)


if __name__=="__main__":
    main()
