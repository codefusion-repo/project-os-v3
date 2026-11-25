"""Produce candidate hashes from the exact downloaded wheels and their metadata.

Run in a clean Linux x86_64 CPython 3.12 environment. Output is review evidence,
not an automatic update of the committed lock.
"""
import hashlib
import re
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def generate(pins, wheels):
    expected = {}
    for line in pins.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9.!+_-]+", line):
            raise ValueError("Expected exact version pin")
        name, version = line.split("==")
        name = normalize(name)
        if name in expected:
            raise ValueError("Duplicate pin")
        expected[name] = version
    actual = {}
    for wheel in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(wheel) as z:
            metadata = [n for n in z.namelist() if n.count("/")==1 and n.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("Invalid wheel metadata")
            with z.open(metadata[0]) as stream:
                msg = BytesParser().parsebytes(stream.read(1024 * 1024 + 1))
        name, version = normalize(msg["Name"]), msg["Version"]
        if expected.get(name) != version or name in actual:
            raise ValueError("Unexpected or duplicate wheel")
        with wheel.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        actual[name] = f"{name}=={version} --hash=sha256:{digest}"
    if actual.keys() != expected.keys():
        raise ValueError("Incomplete wheel set")
    return "\n".join(actual[name] for name in sorted(actual)) + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: lock_wheels.py PINS WHEEL_DIRECTORY")
    print(generate(Path(sys.argv[1]), Path(sys.argv[2])), end="")
