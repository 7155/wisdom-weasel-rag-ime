#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from rag_ime.agent_service import AgentService
from rag_ime.pi_runtime import PiRuntimeConfig


@contextmanager
def _temporary_environment(values: Mapping[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _wait_for(
    load: Callable[[], list[dict[str, object]]],
    predicate: Callable[[list[dict[str, object]]], bool],
    *,
    timeout: float = 15.0,
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    latest: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        latest = load()
        if predicate(latest):
            return latest
        time.sleep(0.025)
    raise RuntimeError(
        "Room composition did not reach its expected terminal state; "
        f"events={[item.get('eventType') for item in latest]}"
    )


def _turn_events(
    service: AgentService,
    room_id: str,
    room_turn_id: str,
) -> list[dict[str, object]]:
    return [
        event
        for event in service.rooms.list_events(room_id, after_sequence=0, limit=2000)
        if str(event.get("turnId") or "") == room_turn_id
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise a light Room composed from ordinary staged Pi Sessions"
    )
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--deterministic-test-gate", action="store_true", required=True)
    args = parser.parse_args()

    payload = args.payload.resolve()
    workspace_root = args.workspace_root.resolve()
    node = payload / "bin" / "node"
    entrypoint = payload / "runtime-host" / "cli.mjs"
    manifest_path = payload / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not node.is_file() or not entrypoint.is_file():
        raise SystemExit("staged Runtime Host payload is incomplete")

    with tempfile.TemporaryDirectory(prefix="pi-room-composition-") as state_root_text:
        state_root = Path(state_root_text)
        environment = {
            "NODE_ENV": "test",
            "RAG_IME_PI_DETERMINISTIC_ADAPTER": "room-v2",
            "RAG_IME_PI_DETERMINISTIC_SLOW": "1",
            "RAG_IME_APP_SUPPORT_DIR": str(state_root),
            "RAG_IME_WORKSPACE_ROOTS": str(workspace_root),
        }
        with _temporary_environment(environment):
            service = AgentService(
                db_path=state_root / "rag-ime.sqlite",
                runtime_config=PiRuntimeConfig(
                    enabled=True,
                    executable=entrypoint,
                    node_executable=str(node),
                    agent_dir=state_root / "Agent" / "config",
                    session_dir=state_root / "Agent" / "sessions",
                    logs_dir=state_root / "Agent" / "logs",
                    provider="rag-ime-deterministic",
                    model="room-v2-test",
                    provider_environment={
                        "NODE_ENV": "test",
                        "RAG_IME_PI_DETERMINISTIC_ADAPTER": "room-v2",
                        "RAG_IME_PI_DETERMINISTIC_SLOW": "1",
                    },
                    pi_version="0.80.7",
                    protocol_version="2",
                    max_sessions=8,
                ),
                project=str(workspace_root),
                wake_scheduler_enabled=False,
                background_job_execution_owner=False,
            )
            try:
                # Production personas keep their user-selected models. The
                # offline canary pins both participants to the staged test
                # Provider so no network model is involved in this proof.
                for role_id in (
                    "companion-present-v1",
                    "companion-firstlight-v1",
                ):
                    service.personas.set_runtime_defaults(
                        role_id,
                        "1",
                        model_profile="rag-ime-deterministic/room-v2-test",
                        thinking_level="off",
                    )
                room = service.create_room(
                    {
                        "title": "Staged Session Composition",
                        "routingPolicy": "manual_mentions",
                        "workspaceRoots": [str(workspace_root)],
                        "participants": [
                            {
                                "roleId": "companion-present-v1",
                                "roleVersion": "1",
                            },
                            {
                                "roleId": "companion-firstlight-v1",
                                "roleVersion": "1",
                            },
                        ],
                    }
                )["room"]
                room_id = str(room["id"])
                facilitator, partner = room["participants"]
                facilitator_session = service.sessions.get(
                    str(facilitator["sessionId"])
                )
                if facilitator_session.get("modelProfile") != (
                    "rag-ime-deterministic/room-v2-test"
                ):
                    raise RuntimeError(
                        "Room participant did not inherit the configured Pi model: "
                        f"{facilitator_session.get('modelProfile')}"
                    )

                started = service.post_room_message(
                    room_id,
                    {
                        "message": "Keep this Room turn active until the steering message.",
                        "clientMessageId": "room-composition-start",
                    },
                )
                root_id = str(started["roomTurnId"])
                if started.get("executionOwner") != "session":
                    raise RuntimeError("Room dispatch is not owned by ordinary Sessions")
                if len(started.get("dispatches") or []) != 1:
                    raise RuntimeError("Unaddressed Room input did not select exactly one lead")
                if str(started["participant"]["id"]) != str(facilitator["id"]):
                    raise RuntimeError("Unaddressed Room input did not select the facilitator")

                steered = service.steer_room_participant(
                    room_id,
                    {
                        "action": "steer_participant",
                        "rootId": root_id,
                        "participantId": str(facilitator["id"]),
                        "message": "Stop the original direction and acknowledge this steer.",
                        "clientActionId": "room-composition-steer",
                    },
                )
                if steered.get("delivery") != "steer":
                    raise RuntimeError("Room steer did not use native Session delivery")

                completed_events = _wait_for(
                    lambda: _turn_events(service, room_id, root_id),
                    lambda events: any(
                        event.get("eventType") == "turn_completed" for event in events
                    ),
                )
                event_types = [str(event.get("eventType") or "") for event in completed_events]
                first_user_index = event_types.index("user_message")
                route_index = event_types.index("route_decision")
                steer_index = next(
                    index
                    for index, event in enumerate(completed_events)
                    if event.get("eventType") == "user_message"
                    and isinstance(event.get("payload"), Mapping)
                    and event["payload"].get("delivery") == "steer"
                )
                terminal_index = event_types.index("turn_completed")
                if not first_user_index < route_index < steer_index < terminal_index:
                    raise RuntimeError(
                        "Room user, route, steer, and terminal events are out of order"
                    )
                terminal_events = [
                    event for event in completed_events if event.get("eventType") == "turn_completed"
                ]
                if len(terminal_events) != 1:
                    raise RuntimeError("Room turn produced more than one terminal event")

                service.runtime.stop()
                # Hold one synthetic parent binding while exercising the child
                # adapter directly. In production the same binding is owned by
                # the Facilitator's in-flight room_partner Tool call.
                partner_parent_root = "room-turn:partner-parent"
                partner_parent_session_turn = "turn:partner-parent"
                service._begin_room_turn(
                    str(facilitator["sessionId"]),
                    partner_parent_root,
                    str(room.get("activeTopicId") or ""),
                    dispatch_id="room-dispatch:partner-parent",
                )
                service._accept_room_turn(
                    str(facilitator["sessionId"]),
                    partner_parent_session_turn,
                    partner_parent_root,
                )
                child_result = service.execute_room_partner_tool(
                    str(facilitator["sessionId"]),
                    {
                        "op": "delegate",
                        "targetParticipantId": str(partner["id"]),
                        "task": "Return the exact marker ROOM-PARTNER-CHILD-OK.",
                        "expectedOutput": "One exact marker",
                        "acceptanceCriteria": [
                            "The result contains ROOM-PARTNER-CHILD-OK"
                        ],
                        "timeoutSeconds": 12,
                    },
                    tool_call_id="room-composition-partner-tool",
                )
                if child_result.get("status") != "completed":
                    raise RuntimeError(
                        f"Room Partner child did not complete: {child_result}"
                    )
                partner_events = _turn_events(
                    service,
                    room_id,
                    partner_parent_root,
                )
                child_terminals = [
                    event
                    for event in partner_events
                    if event.get("eventType") == "participant_activity"
                    and isinstance(event.get("payload"), Mapping)
                    and isinstance(event["payload"].get("data"), Mapping)
                    and event["payload"]["data"].get("activityKind") == "child"
                    and event["payload"]["data"].get("phase") == "completed"
                ]
                if len(child_terminals) != 1:
                    raise RuntimeError(
                        "Room Partner child did not produce one child terminal event"
                    )
                root_terminals = [
                    event
                    for event in partner_events
                    if event.get("eventType") == "turn_completed"
                ]
                if len(root_terminals) > 1:
                    raise RuntimeError(
                        "Room Partner child produced a second Root final"
                    )
                service._finish_room_turn(
                    str(facilitator["sessionId"]),
                    partner_parent_session_turn,
                    partner_parent_root,
                )

                # Reset the deterministic Provider's finite response queue so
                # the Stop proof begins with a genuinely active second turn.
                service.runtime.stop()
                partner_started = service.post_room_message(
                    room_id,
                    {
                        "message": f"@{partner['displayName']} Keep this turn active for Stop.",
                        "clientMessageId": "room-composition-stop-start",
                    },
                )
                partner_root_id = str(partner_started["roomTurnId"])
                if str(partner_started["participant"]["id"]) != str(partner["id"]):
                    raise RuntimeError("Explicit mention did not select the partner Session")
                stopped = service.abort_room_turn(
                    room_id,
                    {
                        "roomTurnId": partner_root_id,
                        "clientRequestId": "room-composition-stop",
                    },
                )
                if stopped.get("status") != "terminated":
                    raise RuntimeError(f"Room Stop did not terminate: {stopped}")
                stopped_events = _wait_for(
                    lambda: _turn_events(service, room_id, partner_root_id),
                    lambda events: any(
                        event.get("eventType") == "turn_completed"
                        and isinstance(event.get("payload"), Mapping)
                        and event["payload"].get("status") == "aborted"
                        for event in events
                    ),
                )
                stopped_terminals = [
                    event for event in stopped_events if event.get("eventType") == "turn_completed"
                ]
                if len(stopped_terminals) != 1:
                    raise RuntimeError("Stopped Room turn produced an invalid terminal count")

                print(
                    json.dumps(
                        {
                            "schemaVersion": "rag-ime.pi-room-composition-e2e.v1",
                            "status": "passed_not_installed",
                            "productionEnabled": False,
                            "runtimeVersion": manifest.get("runtimeVersion"),
                            "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
                            "sourceCommit": (manifest.get("source") or {}).get("commit"),
                            "executionOwner": started.get("executionOwner"),
                            "leadDispatchCount": len(started.get("dispatches") or []),
                            "leadSessionId": facilitator.get("sessionId"),
                            "partnerSessionId": partner.get("sessionId"),
                            "partnerChildStatus": child_result.get("status"),
                            "partnerChildTerminalCount": len(child_terminals),
                            "steerDelivery": steered.get("delivery"),
                            "steerOrderedBeforeTerminal": steer_index < terminal_index,
                            "stopStatus": stopped.get("status"),
                            "uniqueFinalPerTurn": True,
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            finally:
                service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
