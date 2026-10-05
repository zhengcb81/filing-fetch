"""P5-FF test support: adapt legacy ``CompletedProcess`` stubs to the bounded
transport's ``(stdout_bytes, stderr_bytes, returncode)`` tuple return.

Real children of the shared bounded layer exchange *bytes*; tests keep writing
the familiar ``subprocess.CompletedProcess(stdout=str, stderr=str)`` shapes and
``_bounded_response()`` translates them. ``side_effect`` list patterns map a
list of stubs to a list of tuples 1:1.
"""

from __future__ import annotations

import subprocess


def bounded_response(stub):
    """One CompletedProcess stub -> (stdout, stderr, returncode)."""
    if isinstance(stub, subprocess.CompletedProcess):
        stdout = stub.stdout or ""
        stderr = stub.stderr or ""
        if isinstance(stdout, str):
            stdout = stdout.encode("utf-8")
        if isinstance(stderr, str):
            stderr = stderr.encode("utf-8")
        return (stdout, stderr, stub.returncode)
    if isinstance(stub, tuple) and len(stub) == 3:
        return stub
    raise TypeError(f"unsupported bounded stub: {stub!r}")


def bounded_side_effect(stubs):
    """List of stubs -> sequence the bounded mock returns one per call."""
    return [bounded_response(s) for s in stubs]
