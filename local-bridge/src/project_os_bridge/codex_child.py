"""Short-lived Linux process owner for one trusted Codex CLI invocation.

A subreaper adopts orphan descendants even if they create a new session.
The parent control pipe closes on shutdown or parent death. No shell, daemon,
global process matching, or changes to the host's isolation policy.
"""
import ctypes
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


def own(control, status, argv):
    if not argv:
        raise ValueError("Missing executable")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "Subreaper unavailable")
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    # Child cannot inherit the lifecycle descriptors. Only this owner holds them.
    os.set_inheritable(control, False)
    os.set_inheritable(status, False)
    if select.select([control], [], [], 0)[0]:
        os.write(status, b"1")
        return 130
    try:
        child = subprocess.Popen(argv, close_fds=True)
    except OSError:
        os.write(status, b"1")  # no child was launched
        return 127
    # The provider's JSONL/stdin streams belong to Codex, not this owner.
    os.close(0)
    os.close(1)
    code = None
    deadline = None
    children_file = Path(f"/proc/self/task/{os.getpid()}/children")
    while True:
        try:
            while True:
                pid, result = os.waitpid(-1, os.WNOHANG)
                if not pid:
                    break
                if pid == child.pid:
                    child.returncode = os.waitstatus_to_exitcode(result)
                    code = child.returncode
        except ChildProcessError:
            # ECHILD after reaping is the evidence that all adopted children
            # are gone; a snapshot of a process group alone is not sufficient.
            os.write(status, b"1")
            return 125 if code is None else (code if code >= 0 else 128 - code)
        if not stopping and select.select([control], [], [], 0.05)[0]:
            stopping = True
        if code is not None or stopping:
            now = time.monotonic()
            if deadline is None:
                deadline = now + 8
            if now >= deadline:
                return 125  # no clean marker; retain the durable effect fence
            sig = signal.SIGTERM if now < deadline - 5 else signal.SIGKILL
            # Only direct children of this private owner, not other Codex
            # sessions. A child cannot be PID-reused until we reap it.
            for raw in children_file.read_text().split():
                try:
                    os.kill(int(raw), sig)
                except ProcessLookupError:
                    pass
            time.sleep(0.05)


def main():
    try:
        control, status = map(int, sys.argv[1:3])
        code = own(control, status, sys.argv[3:])
    except (OSError, ValueError, RuntimeError):
        code = 125
    raise SystemExit(code)


if __name__ == "__main__":
    main()
