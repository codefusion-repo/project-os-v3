"""Reject activation of a runtime with unfinished local installation."""
import os
from pathlib import Path


def require_no_installation(executable: Path):
    # Do not resolve the interpreter symlink: the stable venv path is the
    # identity used in the prepared unit.
    venv = executable.parent.parent
    if venv.name != ".venv" or venv.parent.name != "local-bridge":
        return
    guard = venv.parent / ".venv-install.guard"
    if os.path.lexists(guard / "active.json"):
        raise RuntimeError("Unresolved runtime installation")
    if os.path.lexists(guard) and (guard.is_symlink() or not guard.is_dir()):
        raise RuntimeError("Unsafe runtime installation guard")
