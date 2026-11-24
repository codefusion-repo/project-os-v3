"""Require byte-identical wheels from independently prepared source trees."""
import hashlib
from pathlib import Path
import sys


def identity(directory):
    files = list(directory.iterdir())
    if len(files) != 1 or files[0].suffix != ".whl" or not files[0].is_file() or files[0].is_symlink():
        raise ValueError("Expected exactly one regular wheel")
    with files[0].open("rb") as stream:
        return files[0].name, hashlib.file_digest(stream, "sha256").hexdigest()


def compare(first, second):
    if first.resolve() == second.resolve():
        raise ValueError("Independent build directories required")
    a, b = identity(first), identity(second)
    if a != b:
        raise ValueError("Project wheel identity mismatch")
    return a


if __name__ == "__main__":
    print("PROJECT_WHEEL_REPRODUCIBLE", *compare(Path(sys.argv[1]), Path(sys.argv[2])))
