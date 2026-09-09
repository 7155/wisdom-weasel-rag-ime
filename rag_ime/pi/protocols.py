"""Validate the sole supported Pi Host wire protocol; no executor selection."""

from __future__ import annotations

PI_HOST_PROTOCOL_VERSION = "2"

__all__ = ["PI_HOST_PROTOCOL_VERSION", "PiRuntimeProtocolError", "normalize_protocol_version"]


class PiRuntimeProtocolError(ValueError):
    """An explicit configuration requests an unsupported execution protocol."""


def normalize_protocol_version(value: object) -> str:
    version = str(value or "").strip()
    if version == "1":
        raise PiRuntimeProtocolError(
            "Pi runtime protocol 1 is retired; rebuild the managed Pi Host with protocol 2"
        )
    if version != PI_HOST_PROTOCOL_VERSION:
        raise PiRuntimeProtocolError(
            "unsupported Pi runtime protocol version: " + (version or "<empty>")
        )
    return version
