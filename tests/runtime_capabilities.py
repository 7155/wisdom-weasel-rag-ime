from __future__ import annotations

import errno
import os
import socket
import subprocess
import unittest
from functools import lru_cache


@lru_cache(maxsize=1)
def loopback_bind_available() -> tuple[bool, str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EPERM}:
            return False, f"sandbox denies loopback bind: {error}"
        raise
    finally:
        sock.close()
    return True, ""


def requires_loopback_bind(test):
    available, reason = loopback_bind_available()
    return unittest.skipUnless(available, reason)(test)


@lru_cache(maxsize=1)
def process_identity_available() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(os.getpid())],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EPERM}:
            return False, f"sandbox denies process identity inspection: {error}"
        raise
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or f"ps exited {result.returncode}"
        return False, f"process identity inspection is unavailable: {detail}"
    return True, ""


def requires_process_identity(test):
    available, reason = process_identity_available()
    return unittest.skipUnless(available, reason)(test)


@lru_cache(maxsize=1)
def metal_available() -> tuple[bool, str]:
    try:
        import mlx.core as mx  # type: ignore[import-not-found]

        mx.eval(mx.array([1]))
    except (ImportError, ModuleNotFoundError) as error:
        return False, f"MLX is unavailable: {error}"
    except RuntimeError as error:
        message = str(error).lower()
        if "metal" in message or "gpu" in message or "device" in message:
            return False, f"Metal is unavailable: {error}"
        raise
    return True, ""


def requires_metal(test):
    available, reason = metal_available()
    return unittest.skipUnless(available, reason)(test)
