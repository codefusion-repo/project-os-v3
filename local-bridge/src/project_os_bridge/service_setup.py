"""Local-only preparation of a disposable supervised HTTPS instance."""
import getpass
import json
import os
import re
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from ipaddress import ip_address

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

from .workos_auth import load_config, private_directory
from .isolated import IMAGE
from .podman_context import PodmanContext
from .vertical import bound_context

SAFE_PATH = re.compile(r"/[A-Za-z0-9_./-]+")


def checked_path(path):
    if not SAFE_PATH.fullmatch(str(path)) or path.resolve(strict=True) != path:
        raise ValueError("Canonical path without shell or systemd metacharacters required")
    return path


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def generate_tls(directory):
    """Create a one-leaf local CA; never persist its signing key."""
    private_directory(directory)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Project OS local CA")])
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Project OS loopback")])

    def cert(subject, issuer, public_key):
        return (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
                .public_key(public_key).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=90)))

    ca = (cert(ca_name, ca_name, ca_key.public_key())
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, None, None), critical=True)
          .sign(ca_key, hashes.SHA256()))
    leaf = (cert(name, ca_name, key.public_key())
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, None, None), critical=True)
            .sign(ca_key, hashes.SHA256()))
    for path, data in (("ca.pem", ca.public_bytes(serialization.Encoding.PEM)),
                       ("server.pem", leaf.public_bytes(serialization.Encoding.PEM)),
                       ("server-key.pem", key.private_bytes(serialization.Encoding.PEM,
                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))):
        write_new(directory / path, data)


def render_unit(root, python):
    return f"""[Unit]
Description=Project OS disposable authenticated bridge
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=3

[Service]
Type=simple
ExecStart={python} -I -m project_os_bridge.supervised --root {root}
UMask=0077
KillMode=mixed
TimeoutStopSec=120
Restart=no
Delegate=yes

[Install]
WantedBy=default.target
"""


def prepare_service(root, tunnel, runtime_key, image=None, *, podman_context=None):
    if os.getuid() == 0:
        raise PermissionError("Unprivileged account required")
    checked_path(root)
    private_directory(root)
    if any(os.path.lexists(p / ".git") for p in (root, *root.parents)):
        raise PermissionError("Instance must be outside Git")
    verifier = load_config(root / "oauth.json", root / "state")
    checked_path(tunnel)
    info = tunnel.stat()
    if not tunnel.is_file() or info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022 or not os.access(tunnel, os.X_OK):
        raise PermissionError("Trusted executable required")
    if not isinstance(runtime_key, str) or not re.fullmatch(r"[!-~]{16,4096}", runtime_key):
        raise ValueError("Invalid runtime key format")
    if image is not None and not IMAGE.fullmatch(image):
        raise ValueError("Locally approved digest required")
    if (image is None) != (podman_context is None):
        raise PermissionError("Fixture image and Podman context must be supplied together")
    if image is not None:
        PodmanContext(podman_context).identity(bound_context(root / "state", image))
    python = Path(sys.executable)
    if not SAFE_PATH.fullmatch(str(python)) or not python.is_absolute():
        raise ValueError("Unsupported Python path")
    if sys.prefix == sys.base_prefix:
        raise ValueError("Dedicated installed virtual environment required")
    service = root / "service"
    # Never replace existing credentials or certificates, even after failure.
    service.mkdir(mode=0o700)
    generate_tls(service)
    runtime = {"tunnel":str(tunnel), "tunnel_id":verifier.resource.rsplit("/",1)[-1], "image":image}
    if podman_context is not None:
        runtime["podman_context"] = str(podman_context)
    write_new(service / "runtime.json", json.dumps(runtime).encode())
    write_new(service / "tunnel.yaml", b"{}\n")
    unit = render_unit(root, python)
    write_new(service / "runtime-key", runtime_key.encode("ascii"))
    write_new(service / "project-os-bridge.service", unit.encode())
    return service


def interactive_prepare(root, allow_fixture=True):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError("Interactive local terminal required")
    if os.path.lexists(root / "service"):
        raise FileExistsError("Existing service preparation preserved")
    tunnel = Path(input("Verified tunnel-client executable (absolute path): ").strip())
    image = (input("Previously validated fixture image digest (blank disables fixture): ").strip() or None) if allow_fixture else None
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        key = getpass.getpass("Runtime API key (Read + Use only): ")
    context = Path(input("Prepared private Podman context (absolute path): ").strip()) if image else None
    prepare_service(root, tunnel, key, image, podman_context=context)
    print("Private service prepared; not linked, enabled, started or authorized.")
