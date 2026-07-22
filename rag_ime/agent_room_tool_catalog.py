from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .agent_room_capabilities import ROOM_PUBLIC_TOOLS, room_runtime_registry
from .agent_tool_ids import tool_capability


@dataclass(frozen=True)
class RoomToolCatalogPlan:
    """One Dispatch-scoped Tool registry plus its independent authorization gates."""

    runtime_registry: dict[str, dict[str, object]]
    user_authorized: tuple[str, ...]
    template_allowed: tuple[str, ...]
    role_allowed: tuple[str, ...]
    profile_allowed: tuple[str, ...]
    state_allowed: tuple[str, ...]


def compose_room_tool_catalog(
    *,
    available: Sequence[Mapping[str, object]],
    user_authorized: Sequence[Mapping[str, object]],
    template_allowed: Sequence[Mapping[str, object]],
    effective: Sequence[Mapping[str, object]],
    template_capabilities: Sequence[str],
    role_capabilities: Sequence[str],
    profile_capabilities: Sequence[str],
) -> RoomToolCatalogPlan:
    """Merge Room protocol Tools with normal Agent Tools without widening policy.

    ``available`` describes backend capability. The other inputs are separately
    derived from the user's Session policy, the Agent template Tool profile, and
    their intersection. Collaboration role/Profile capabilities remain distinct
    gates so the manifest can explain why a Tool is unavailable to this Dispatch.
    """

    available_by_name = _by_name(available)
    user_names = set(_by_name(user_authorized))
    template_names = set(_by_name(template_allowed))
    effective_by_name = _by_name(effective)
    room_registry = room_runtime_registry()
    collisions = set(room_registry) & set(available_by_name)
    if collisions:
        raise ValueError(
            "product Tool catalog collides with Room protocol Tools: "
            + ",".join(sorted(collisions))
        )

    runtime_registry = dict(room_registry)
    for name in sorted(available_by_name):
        source = effective_by_name.get(name) or available_by_name[name]
        runtime_registry[name] = _registry_entry(source)

    room_names = tuple(ROOM_PUBLIC_TOOLS)
    product_names = tuple(sorted(available_by_name))
    template_caps = _capabilities(template_capabilities)
    role_caps = _capabilities(role_capabilities)
    profile_caps = _capabilities(profile_capabilities)

    def allowed_by_capability(capabilities: set[str]) -> tuple[str, ...]:
        return (
            *room_names,
            *(
                name
                for name in product_names
                if tool_capability(name) in capabilities
            ),
        )

    return RoomToolCatalogPlan(
        runtime_registry=runtime_registry,
        user_authorized=(*room_names, *(name for name in product_names if name in user_names)),
        template_allowed=(
            *room_names,
            *(
                name
                for name in product_names
                if name in template_names
                and tool_capability(name) in template_caps
            ),
        ),
        role_allowed=allowed_by_capability(role_caps),
        profile_allowed=allowed_by_capability(profile_caps),
        state_allowed=(*room_names, *product_names),
    )


def _by_name(values: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for value in values:
        name = str(value.get("name") or "").strip()
        if not name:
            raise ValueError("product Tool manifest requires a name")
        if name in result:
            raise ValueError(f"duplicate product Tool manifest: {name}")
        result[name] = value
    return result


def _registry_entry(value: Mapping[str, object]) -> dict[str, object]:
    name = str(value.get("name") or "").strip()
    schema = value.get("parameters")
    if not isinstance(schema, Mapping):
        raise ValueError(f"product Tool {name} requires a Provider parameter schema")
    entry: dict[str, object] = {
        "catalogKind": "product-tool",
        "description": _required(value.get("description"), f"{name}.description"),
        "when": _strings(value.get("when"), f"{name}.when"),
        "notFor": _strings(value.get("notFor"), f"{name}.notFor"),
        "input": _required(value.get("input"), f"{name}.input"),
        "output": _required(value.get("output"), f"{name}.output"),
        "does": _required(value.get("does"), f"{name}.does"),
        "risk": _required(value.get("risk") or "R0", f"{name}.risk"),
        "operation": f"product.{name}",
        "inputSchema": dict(schema),
    }
    return entry


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be an array")
    result = [str(item).strip() for item in value if str(item).strip()]
    if not result:
        raise ValueError(f"{field} must not be empty")
    return result


def _capabilities(values: Sequence[str]) -> set[str]:
    return {str(value).strip() for value in values if str(value).strip()}


def _required(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text
