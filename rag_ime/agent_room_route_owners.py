from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoomRouteOwner:
    route_id: str
    entrypoint: str
    legacy_owner: str
    room_binding_owner: str
    enforcement: str


ROOM_ROUTE_OWNER_CENSUS = (
    RoomRouteOwner("room.message.mention", "_post_room_message_once", "room_router", "kernel", "reject_legacy"),
    RoomRouteOwner("intercom.send", "send_room_intercom", "intercom", "kernel", "reject_legacy"),
    RoomRouteOwner("intercom.ask", "send_room_intercom", "intercom", "kernel", "reject_legacy"),
    RoomRouteOwner("intercom.reply", "send_room_intercom", "intercom", "kernel", "reject_legacy"),
    RoomRouteOwner("intercom.delivery", "_deliver_room_intercom", "intercom", "kernel", "reject_legacy"),
    RoomRouteOwner("work_item.assign", "assign_room_work", "work_item", "kernel", "reject_legacy"),
    RoomRouteOwner("work_item.submit", "submit_room_work", "work_item", "kernel", "reject_legacy"),
    RoomRouteOwner("work_item.accept", "accept_room_work", "work_item", "kernel", "reject_legacy"),
    RoomRouteOwner("work_item.return", "return_room_work", "work_item", "kernel", "reject_legacy"),
    RoomRouteOwner("work_item.block", "block_room_work", "work_item", "kernel", "reject_legacy"),
    RoomRouteOwner("work_item.escalate", "escalate_room_work", "work_item", "kernel", "reject_legacy"),
    RoomRouteOwner("wake.dispatch", "_dispatch_scheduled_wake", "wake_scheduler", "kernel", "reject_legacy"),
    RoomRouteOwner("tool.room_state", "execute_room_capability_tool", "reject", "kernel", "canonical_only"),
    RoomRouteOwner("tool.room_post", "execute_room_capability_tool", "reject", "kernel", "canonical_only"),
    RoomRouteOwner("tool.room_commit", "execute_room_capability_tool", "reject", "kernel", "canonical_only"),
)


def room_route_owner(route_id: str, *, has_room_binding: bool) -> str:
    for route in ROOM_ROUTE_OWNER_CENSUS:
        if route.route_id == route_id:
            return route.room_binding_owner if has_room_binding else route.legacy_owner
    raise KeyError(route_id)


def validate_room_route_owner_census(service_type: type[object]) -> None:
    route_ids = [route.route_id for route in ROOM_ROUTE_OWNER_CENSUS]
    if len(route_ids) != len(set(route_ids)):
        raise RuntimeError("Room route owner census contains duplicate route ids")
    for route in ROOM_ROUTE_OWNER_CENSUS:
        if route.room_binding_owner != "kernel":
            raise RuntimeError(f"RoomBinding route has a non-Kernel owner: {route.route_id}")
        if not callable(getattr(service_type, route.entrypoint, None)):
            raise RuntimeError(f"Room route entrypoint is missing: {route.entrypoint}")
