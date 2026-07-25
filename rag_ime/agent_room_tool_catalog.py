from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .agent_room_capabilities import ROOM_PUBLIC_TOOLS, room_runtime_registry


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
    effective: Sequence[Mapping[str, object]],
) -> RoomToolCatalogPlan:
    """Merge Room protocol Tools with the Session's normal Agent Tool surface.

    Room roles and task templates describe responsibility and handoff behavior;
    they are not a second Tool ACL. The Session policy remains the Tool owner,
    while the Room manifest adds Dispatch fencing, revocation, and result receipts.
    """

    available_by_name = _by_name(available)
    user_names = set(_by_name(user_authorized))
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
    complete_surface = (*room_names, *product_names)

    return RoomToolCatalogPlan(
        runtime_registry=runtime_registry,
        user_authorized=(*room_names, *(name for name in product_names if name in user_names)),
        template_allowed=complete_surface,
        role_allowed=complete_surface,
        profile_allowed=complete_surface,
        state_allowed=complete_surface,
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
    projections = _runtime_projections(value.get("runtimeProjections"), name)
    if projections:
        entry["runtimeProjections"] = projections
    return entry


def _runtime_projections(value: object, tool_name: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"product Tool {tool_name} runtimeProjections must be an array")
    projections: list[dict[str, str]] = []
    seen_names: set[str] = set()
    seen_operations: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(
                f"product Tool {tool_name} runtimeProjections entries must be objects"
            )
        name = _required(item.get("name"), f"{tool_name}.runtimeProjections.name")
        operation = _required(
            item.get("operation"),
            f"{tool_name}.runtimeProjections.operation",
        )
        if name in seen_names or operation in seen_operations:
            raise ValueError(
                f"product Tool {tool_name} runtimeProjections must be unique"
            )
        seen_names.add(name)
        seen_operations.add(operation)
        projections.append({"name": name, "operation": operation})
    return projections


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be an array")
    result = [str(item).strip() for item in value if str(item).strip()]
    if not result:
        raise ValueError(f"{field} must not be empty")
    return result


def _required(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text
