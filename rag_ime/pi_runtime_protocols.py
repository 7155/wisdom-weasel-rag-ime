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


# protocol version -> (module, attribute). Resolved lazily so this module can
# be imported by either runtime without creating an import cycle.
PROTOCOL_MANAGERS: dict[str, tuple[str, str]] = {
    "1": ("rag_ime.pi_runtime", "PiRuntimeManager"),
    "2": ("rag_ime.pi_runtime_v2", "PiRuntimeHostManager"),
}

DEFAULT_PROTOCOL_VERSION = "1"


def normalize_protocol_version(value: object) -> str:
    """Unknown or empty versions fall back to v1, matching the prior branch.

    The replaced code was `if protocol_version == "2": ... else: v1`, so every
    value other than "2" already meant v1. Keeping that exact behaviour matters:
    a stricter check here would turn a mis-set config into a hard failure at
    runtime rather than the previous silent fallback.
    """

    version = str(value or "").strip()
    return version if version in PROTOCOL_MANAGERS else DEFAULT_PROTOCOL_VERSION


def resolve_protocol_manager(value: object) -> Any:
    """Return the runtime manager class registered for one protocol version."""

    module_name, attribute = PROTOCOL_MANAGERS[normalize_protocol_version(value)]
    return getattr(importlib.import_module(module_name), attribute)
