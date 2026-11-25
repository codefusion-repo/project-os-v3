"""Verify the pinned bootstrap wheel before executing its Python code."""
import hashlib
import re
import sys
import zipfile
from pathlib import Path


def verify(wheel, lock):
    expected = lock.read_text(encoding="utf-8").strip().split()
    if (len(expected) != 2 or expected[0] != "pip==26.3"
            or not re.fullmatch(r"--hash=sha256:[0-9a-f]{64}", expected[1])):
        raise ValueError("Invalid bootstrap lock")
    if wheel.name != "pip-26.3-py3-none-any.whl" or wheel.stat().st_size > 5_000_000:
        raise ValueError("Invalid bootstrap wheel identity or size")
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != expected[1].split(":", 1)[1]:
        raise ValueError("Bootstrap wheel hash mismatch")
    with zipfile.ZipFile(wheel) as archive:
        entries = archive.namelist()
        names = set(entries)
        if len(entries) != len(names):
            raise ValueError("Duplicate wheel member")
        if "pip/_vendor/pkg_resources/__init__.py" not in names:
            raise ValueError("Unexpected setuptools vendoring layout")
        # The cited advisories affect package_index, sdist/MANIFEST.in and
        # legacy wheel install in setuptools, not the retained pkg_resources.
        # This is component evidence, NOT a scanner exception or risk acceptance.
        if any(n.startswith(("pip/_vendor/setuptools/", "setuptools/"))
               or n in {"pip/_vendor/setuptools.py", "setuptools.py"}
               or (n.startswith("pip/_vendor/pkg_resources/") and
                   n.rsplit("/", 1)[-1] in {"package_index.py", "sdist.py", "manifest.py", "wheel.py"})
               for n in names):
            raise ValueError("Unexpected setuptools implementation in bootstrap wheel")
        if "pip/_vendor/vendor.txt" not in names:
            raise ValueError("Missing vendor inventory")
        retained = sorted(n for n in names if n.startswith("pip/_vendor/pkg_resources/") and not n.endswith("/"))
        if set(retained) != {"pip/_vendor/pkg_resources/LICENSE", "pip/_vendor/pkg_resources/__init__.py"}:
            raise ValueError("Unexpected retained setuptools files")
    return retained


if __name__ == "__main__":
    for name in verify(Path(sys.argv[1]), Path(sys.argv[2])):
        print("BOOTSTRAP_RETAINED_COMPONENT", name)
    print("BOOTSTRAP_WHEEL_VERIFIED")
