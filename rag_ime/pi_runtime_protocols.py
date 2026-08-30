"""One owner for "which Pi protocol implementation serves this Root".

The choice used to live inside `PiRuntimeDriverFactory.create()` in
`pi_runtime`, as an `if config.protocol_version == "2":` guarding a
function-local import of `pi_runtime_v2`. That put v1 in charge of knowing v2
exists, so the two runtime modules pointed at each other: v2 imports helpers
from v1 at module level, and v1 reached back into v2 at call time. The
function-local import was hiding that, not resolving it.

The registry resolves implementations by name at call time, so this module
imports neither runtime at module level and adding a protocol is one entry
here instead of another branch inside a 3,000-line file.

This deliberately does not merge or move the runtime modules, and does not
touch Session ownership, event projection, abort behaviour or Provider
payloads: it only moves the selection decision.
"""

from __future__ import annotations

import importlib
from typing import Any


__all__ = [
    "PiRuntimeProtocolError",
    "normalize_protocol_version",
    "resolve_protocol_manager",
]


# protocol version -> (module, attribute). Resolved lazily so this module can
# be imported by either runtime without creating an import cycle.
PROTOCOL_MANAGERS: dict[str, tuple[str, str]] = {
    "1": ("rag_ime.pi_runtime", "PiRuntimeManager"),
    "2": ("rag_ime.pi_runtime_v2", "PiRuntimeHostManager"),
}

class PiRuntimeProtocolError(ValueError):
    """Raised when a runtime asks for a protocol without a registered owner."""


def normalize_protocol_version(value: object) -> str:
    """Return a registered protocol version, failing closed for unknown input.

    The old inline branch treated every value other than ``"2"`` as v1. That
    made a typo or stale manifest silently select the legacy runtime. Protocol
    ownership is now explicit: only registered versions may construct a
    manager, while callers that intentionally need the v1 compatibility path
    pass ``"1"``.
    """

    version = str(value or "").strip()
    if version not in PROTOCOL_MANAGERS:
        raise PiRuntimeProtocolError(
            "unsupported Pi runtime protocol version: "
            f"{version or '<empty>'}"
        )
    return version


def resolve_protocol_manager(value: object) -> Any:
    """Return the runtime manager class registered for one protocol version."""

    module_name, attribute = PROTOCOL_MANAGERS[normalize_protocol_version(value)]
    return getattr(importlib.import_module(module_name), attribute)
