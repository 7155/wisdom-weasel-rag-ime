from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .agent_definitions import (
    CollaborationProfileManifest,
    collaboration_profile,
)
from .agent_room_kernel import RoomKernelFenceError
from .collaboration_profile_store import CollaborationProfileStore


class RoomCollaborationProfilePins:
    """Freeze one immutable collaboration profile for a Root lifetime."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def resolve(
        self,
        root: Mapping[str, object],
        *,
        pinned_at_ms: int,
    ) -> tuple[CollaborationProfileManifest, dict[str, object]]:
        root_id = _required_text(root, "rootId")
        requested = str(
            root.get("activeProfileRef") or "standard-room"
        ).strip()
        parsed = urlparse(requested)
        expected_hash = ""
        if parsed.scheme:
            if (
                parsed.scheme != "rag-ime-definition"
                or parsed.netloc != "collaboration-profile"
            ):
                raise RoomKernelFenceError(
                    "Root activeProfileRef is not a CollaborationProfile ref"
                )
            profile_id = unquote(parsed.path.lstrip("/"))
            expected_hash = str(
                parse_qs(parsed.query).get("contentHash", [""])[0]
            )
        else:
            profile_id = requested
        if not profile_id:
            raise RoomKernelFenceError(
                "Root CollaborationProfile id is empty"
            )

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM room_v2_root_profile_pins WHERE root_id=?",
                (root_id,),
            ).fetchone()
            if existing is not None:
                if profile_id != str(existing["profile_id"]):
                    raise RoomKernelFenceError(
                        "Root CollaborationProfile pin cannot hot-swap"
                    )
                manifest = _manifest(
                    json.loads(str(existing["manifest_json"]))
                )
                return manifest, _pin_payload(existing)

            store = CollaborationProfileStore(conn, trusted_signers={})
            active = store.active_manifest(profile_id)
            if active is None:
                if profile_id != "standard-room":
                    raise RoomKernelFenceError(
                        "requested CollaborationProfile has no active version"
                    )
                manifest = collaboration_profile("standard-room", "1")
                bundle_hash = _content_hash(manifest.to_payload())
                pointer_revision = 0
                guard_epoch = 0
                compile_receipt_id = "builtin:standard-room@1"
            else:
                manifest = _manifest(active["manifest"])
                bundle_hash = str(active["contentHash"])
                pointer_revision = int(active["pointerRevision"])
                guard_epoch = int(active["guardEpoch"])
                compile_receipt_id = str(active["compileReceiptId"])
            definition_hash = _content_hash(manifest.to_payload())
            if expected_hash and expected_hash not in {
                bundle_hash,
                definition_hash,
            }:
                raise RoomKernelFenceError(
                    "Root CollaborationProfile ref does not match active content"
                )
            conn.execute(
                """INSERT INTO room_v2_root_profile_pins(
                   root_id,profile_id,profile_version,bundle_content_hash,
                   definition_content_hash,pointer_revision,guard_epoch,
                   compile_receipt_id,manifest_json,pinned_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    root_id,
                    manifest.profile_id,
                    manifest.version,
                    bundle_hash,
                    definition_hash,
                    pointer_revision,
                    guard_epoch,
                    compile_receipt_id,
                    json.dumps(
                        manifest.to_payload(),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    int(pinned_at_ms),
                ),
            )
            row = conn.execute(
                "SELECT * FROM room_v2_root_profile_pins WHERE root_id=?",
                (root_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - protected by transaction
                raise RuntimeError("CollaborationProfile pin did not persist")
            return manifest, _pin_payload(row)


def _manifest(value: object) -> CollaborationProfileManifest:
    if not isinstance(value, Mapping):
        raise RoomKernelFenceError(
            "pinned CollaborationProfile manifest is invalid"
        )
    return CollaborationProfileManifest(
        profile_id=_required_text(value, "profileId"),
        version=_required_text(value, "version"),
        display_name=_required_text(value, "displayName"),
        summary=_required_text(value, "summary"),
        collaboration_role_refs=tuple(
            str(item)
            for item in value.get("collaborationRoleRefs") or ()
        ),
        capability_requests=tuple(
            str(item)
            for item in value.get("capabilityRequests") or ()
        ),
        required_gate_ids=tuple(
            str(item)
            for item in value.get("requiredGateIds") or ()
        ),
        prompt_guidance=tuple(
            str(item)
            for item in value.get("promptGuidance") or ()
        ),
        trust_tier=str(value.get("trustTier") or "signed"),
    )


def _pin_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "rootId": str(row["root_id"]),
        "profileId": str(row["profile_id"]),
        "version": str(row["profile_version"]),
        "bundleContentHash": str(row["bundle_content_hash"]),
        "definitionContentHash": str(row["definition_content_hash"]),
        "pointerRevision": int(row["pointer_revision"]),
        "guardEpoch": int(row["guard_epoch"]),
        "compileReceiptId": str(row["compile_receipt_id"]),
        "pinnedAtMs": int(row["pinned_at_ms"]),
    }


def _content_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value
