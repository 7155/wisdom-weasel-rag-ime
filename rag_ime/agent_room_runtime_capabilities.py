from __future__ import annotations

from collections.abc import Mapping, Sequence

from .agent_room_capabilities import (
    RoomCapabilityManifestStore,
)
from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from .agent_room_skills import RoomSkillPolicyStore


class RoomRuntimeCapabilityService:
    """Compile, bind, and revoke one Dispatch-scoped capability manifest."""

    def __init__(
        self,
        *,
        kernel: RoomKernelStore,
        capabilities: RoomCapabilityManifestStore,
        skill_receipts: RoomSkillPolicyStore,
    ) -> None:
        self.kernel = kernel
        self.capabilities = capabilities
        self.skill_receipts = skill_receipts

    def bind(
        self,
        *,
        room_binding: Mapping[str, object],
        participant_binding: Mapping[str, object],
        prompt_compile_receipt: Mapping[str, object],
        manifest_id: str,
        dispatch_id: str,
        user_authorized: Sequence[str],
        template_allowed: Sequence[str],
        role_allowed: Sequence[str],
        profile_allowed: Sequence[str],
        state_allowed: Sequence[str],
        runtime_registry: Mapping[str, Mapping[str, object]],
        created_at_ms: int,
        runtime_state: str = "active",
    ) -> dict[str, object]:
        session_id = str(participant_binding.get("sessionId") or "")
        dispatch = self.kernel.dispatch(dispatch_id)
        root = self.kernel.root(str(dispatch["rootId"]))
        if (
            dispatch.get("targetSessionId") != session_id
            or dispatch.get("rootId") != room_binding.get("rootId")
            or dispatch.get("taskId") != room_binding.get("taskId")
            or int(dispatch.get("generation", -1))
            != int(room_binding.get("generation", -2))
            or int(dispatch.get("capabilityEpoch", -1))
            != int(participant_binding.get("capabilityEpoch", -2))
            or root.get("roomId") != room_binding.get("roomId")
        ):
            raise RoomKernelFenceError(
                "Capability binding does not match the canonical Dispatch"
            )
        compiled_ref = participant_binding.get("compiledRuntimeProfileRef")
        if not isinstance(compiled_ref, Mapping):
            raise ValueError("compiledRuntimeProfileRef is required")
        compiled = self.capabilities.compile_manifest(
            manifest_id=manifest_id,
            room_binding=room_binding,
            participant_binding=participant_binding,
            dispatch_id=str(dispatch["dispatchId"]),
            runtime_registry=runtime_registry,
            user_authorized=user_authorized,
            template_allowed=template_allowed,
            role_allowed=role_allowed,
            profile_allowed=profile_allowed,
            state_allowed=state_allowed,
            created_at_ms=created_at_ms,
        )
        if compiled is None:
            raise RoomKernelFenceError(
                "Capability Manifest requires canonical bindings"
            )
        manifest, created = compiled
        binding, binding_created = self.capabilities.bind_runtime(
            session_id=session_id,
            manifest_id=str(manifest["manifestId"]),
            manifest_hash=str(manifest["manifestHash"]),
            prompt_compile_receipt=prompt_compile_receipt,
            compiled_runtime_profile_ref=compiled_ref,
            room_binding=room_binding,
            participant_binding=participant_binding,
            surface_manifest_hashes={
                name: str(manifest["manifestHash"])
                for name in ("prompt", "runtime", "gateway", "ui")
            },
            created_at_ms=created_at_ms,
            state=runtime_state,
        )
        return {
            "manifest": manifest,
            "binding": binding,
            "created": created,
            "bindingCreated": binding_created,
        }

    def revoke(self, session_id: str, now_ms: int) -> None:
        binding = self.capabilities.runtime_binding(session_id)
        if binding is None:
            return
        next_epoch = int(binding["capabilityEpoch"]) + 1
        manifest_id = str(binding["manifestId"])
        if not manifest_id.startswith("capability-manifest:"):
            raise RoomKernelFenceError(
                "Room capability binding has no Dispatch lineage"
            )
        dispatch = self.kernel.dispatch(
            manifest_id.removeprefix("capability-manifest:")
        )
        self.skill_receipts.revoke_before_epoch(
            str(dispatch["rootId"]),
            new_capability_epoch=next_epoch,
            revoked_at_ms=now_ms,
        )
        self.capabilities.revoke_runtime(
            session_id,
            capability_epoch=next_epoch,
            now_ms=now_ms,
        )
