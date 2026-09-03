from __future__ import annotations

from collections.abc import Mapping

from .agent_execution_policy import (
    FULL_TRUST_EXECUTION_MODE,
    PER_ACTION_EXECUTION_MODE,
    READ_ONLY_EXECUTION_MODE,
    SUPPORTED_EXECUTION_MODES,
    WORKSPACE_MANAGED_EXECUTION_MODE,
)
from .contracts.json_schema import validate_contract


ROOM_PERMISSION_POLICY_SCHEMA_VERSION = "rag-ime.room-permission-policy.v1"
ROOM_PERMISSION_LAYERS = ("room", "partner", "toolAgent")
INHERIT_EXECUTION_MODE = "inherit"
LOWER_LAYER_EXECUTION_MODES = frozenset((*SUPPORTED_EXECUTION_MODES, INHERIT_EXECUTION_MODE))

# The existing execution modes form a conservative authority ordering for
# parent-to-child projection.  A child may retain the parent's mode or choose a
# lower mode, but never acquire a stronger mode than its parent.
_EXECUTION_MODE_RANK = {
    READ_ONLY_EXECUTION_MODE: 0,
    PER_ACTION_EXECUTION_MODE: 1,
    WORKSPACE_MANAGED_EXECUTION_MODE: 2,
    FULL_TRUST_EXECUTION_MODE: 3,
}


def default_room_permission_policy(room_kind: object = "collaboration") -> dict[str, object]:
    kind = str(room_kind or "collaboration").strip().lower()
    room_mode = (
        FULL_TRUST_EXECUTION_MODE
        if kind == "collaboration"
        else PER_ACTION_EXECUTION_MODE
    )
    return _policy(room_mode, INHERIT_EXECUTION_MODE, INHERIT_EXECUTION_MODE)


def normalize_room_permission_policy(
    value: object = None,
    *,
    room_kind: object = "collaboration",
    current: object = None,
    legacy_execution_mode: object = None,
    allow_partial: bool = False,
) -> dict[str, object]:
    """Normalize and validate the server-owned Room permission projection.

    ``current`` may be a Room projection or an already-normalized policy. A
    legacy top-level ``executionMode`` is accepted only as an input migration;
    all returned values use the versioned nested policy shape.
    """

    baseline = _policy_from_value(current) if current is not None else None
    if baseline is None:
        baseline = default_room_permission_policy(room_kind)

    if value is None:
        if legacy_execution_mode is not None:
            room_mode = _normalize_mode(
                legacy_execution_mode,
                allow_inherit=False,
                default=baseline["room"]["executionMode"],
            )
            candidate = _policy(
                room_mode,
                baseline["partner"]["executionMode"],
                baseline["toolAgent"]["executionMode"],
            )
        else:
            candidate = baseline
    elif isinstance(value, Mapping):
        raw_schema_version = value.get("schemaVersion")
        if raw_schema_version != ROOM_PERMISSION_POLICY_SCHEMA_VERSION:
            raise ValueError(
                "permissionPolicy.schemaVersion must be "
                f"{ROOM_PERMISSION_POLICY_SCHEMA_VERSION}"
            )
        candidate_layers: dict[str, str] = {
            layer: baseline[layer]["executionMode"]
            for layer in ROOM_PERMISSION_LAYERS
        }
        unknown = set(value) - (
            set(ROOM_PERMISSION_LAYERS) | {"schemaVersion"}
        )
        if unknown:
            raise ValueError(
                "permissionPolicy contains unsupported layers: "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        for layer in ROOM_PERMISSION_LAYERS:
            if layer not in value:
                if not allow_partial:
                    raise ValueError(f"permissionPolicy.{layer} is required")
                continue
            raw_layer = value[layer]
            if not isinstance(raw_layer, Mapping):
                raise ValueError(f"permissionPolicy.{layer} must be an object")
            if set(raw_layer) != {"executionMode"}:
                unknown_layer = set(raw_layer) - {"executionMode"}
                raise ValueError(
                    f"permissionPolicy.{layer} contains unsupported fields: "
                    + ", ".join(sorted(str(item) for item in unknown_layer))
                )
            candidate_layers[layer] = _normalize_mode(
                raw_layer.get("executionMode"),
                allow_inherit=layer != "room",
                default=candidate_layers[layer],
            )
        candidate = _policy(
            candidate_layers["room"],
            candidate_layers["partner"],
            candidate_layers["toolAgent"],
        )
    else:
        raise ValueError("permissionPolicy must be an object")

    if value is not None and legacy_execution_mode is not None:
        legacy_mode = _normalize_mode(
            legacy_execution_mode,
            allow_inherit=False,
            default=candidate["room"]["executionMode"],
        )
        if legacy_mode != candidate["room"]["executionMode"]:
            raise ValueError(
                "executionMode must match permissionPolicy.room.executionMode"
            )

    _validate_policy_authority(candidate, room_kind=room_kind)
    # Keep this projection tied to the canonical wire contract, not an ad hoc
    # participant or Session-shaped mapping.
    validate_contract(candidate, "room-permission-policy.v1.json")
    return candidate


def resolve_room_permission_policy(
    policy: Mapping[str, object],
) -> dict[str, object]:
    """Resolve lower-layer ``inherit`` values without changing the stored form."""

    normalized = normalize_room_permission_policy(policy)
    room_mode = normalized["room"]["executionMode"]
    partner_configured = normalized["partner"]["executionMode"]
    partner_mode = room_mode if partner_configured == INHERIT_EXECUTION_MODE else partner_configured
    tool_agent_configured = normalized["toolAgent"]["executionMode"]
    tool_agent_mode = (
        partner_mode
        if tool_agent_configured == INHERIT_EXECUTION_MODE
        else tool_agent_configured
    )
    return _policy(room_mode, partner_mode, tool_agent_mode)


def effective_room_permission_mode(
    policy: Mapping[str, object],
    layer: str,
) -> str:
    if layer not in ROOM_PERMISSION_LAYERS:
        raise ValueError(f"unsupported permissionPolicy layer: {layer}")
    return resolve_room_permission_policy(policy)[layer]["executionMode"]


def room_permission_policy_from_row(row: Mapping[str, object]) -> dict[str, object]:
    return normalize_room_permission_policy(
        {
            "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
            "room": {"executionMode": _lookup(row, "execution_mode")},
            "partner": {
                "executionMode": _lookup(
                    row,
                    "partner_execution_mode",
                    INHERIT_EXECUTION_MODE,
                )
            },
            "toolAgent": {
                "executionMode": _lookup(
                    row,
                    "tool_agent_execution_mode",
                    INHERIT_EXECUTION_MODE,
                )
            },
        },
        room_kind=_lookup(row, "room_kind", "collaboration"),
    )

def _lookup(row: Mapping[str, object], key: str, default: object = None) -> object:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default



def room_permission_policy_columns(
    policy: Mapping[str, object],
) -> dict[str, str]:
    normalized = normalize_room_permission_policy(policy)
    return {
        "execution_mode": normalized["room"]["executionMode"],
        "partner_execution_mode": normalized["partner"]["executionMode"],
        "tool_agent_execution_mode": normalized["toolAgent"]["executionMode"],
    }


def _policy(
    room_mode: str,
    partner_mode: str,
    tool_agent_mode: str,
) -> dict[str, object]:
    return {
        "schemaVersion": ROOM_PERMISSION_POLICY_SCHEMA_VERSION,
        "room": {"executionMode": room_mode},
        "partner": {"executionMode": partner_mode},
        "toolAgent": {"executionMode": tool_agent_mode},
    }
def _policy_from_value(value: object) -> dict[str, object] | None:

    if not isinstance(value, Mapping):
        return None
    candidate = value.get("permissionPolicy")
    if isinstance(candidate, Mapping):
        return _policy_from_value(candidate)
    if all(layer in value for layer in ROOM_PERMISSION_LAYERS):
        try:
            return normalize_room_permission_policy(
                value,
                room_kind="collaboration",
            )
        except ValueError:
            return None
    return None


def _normalize_mode(value: object, *, allow_inherit: bool, default: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        normalized = default
    allowed = LOWER_LAYER_EXECUTION_MODES if allow_inherit else SUPPORTED_EXECUTION_MODES
    if normalized not in allowed:
        raise ValueError("unsupported Room permission execution mode")
    return normalized


def _validate_policy_authority(policy: Mapping[str, Mapping[str, str]], *, room_kind: object) -> None:
    room_mode = policy["room"]["executionMode"]
    if (
        str(room_kind or "collaboration").strip().lower() == "roleplay"
        and _EXECUTION_MODE_RANK[room_mode]
        > _EXECUTION_MODE_RANK[PER_ACTION_EXECUTION_MODE]
    ):
        raise ValueError("roleplay Rooms cannot elevate Room execution mode")
    room_rank = _EXECUTION_MODE_RANK[room_mode]
    partner_mode = policy["partner"]["executionMode"]
    if partner_mode != INHERIT_EXECUTION_MODE and _EXECUTION_MODE_RANK[partner_mode] > room_rank:
        raise ValueError("Room partner permission cannot widen Room authority")
    effective_partner = room_mode if partner_mode == INHERIT_EXECUTION_MODE else partner_mode
    tool_agent_mode = policy["toolAgent"]["executionMode"]
    if tool_agent_mode != INHERIT_EXECUTION_MODE and _EXECUTION_MODE_RANK[tool_agent_mode] > _EXECUTION_MODE_RANK[effective_partner]:
        raise ValueError("Room Tool-Agent permission cannot widen partner authority")
