from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from collections.abc import Callable, Mapping
from pathlib import PurePosixPath

from .contracts.json_schema import validate_contract


_COMPILER_VERSION = "collaboration-profile-compiler-v1"
_CAPABILITIES = {"rag", "memory", "planning", "review", "control", "delegation"}
_MANIFEST_FIELDS = {
    "schemaVersion", "profileId", "version", "displayName", "summary",
    "collaborationRoleRefs", "capabilityRequests", "requiredGateIds",
    "promptGuidance", "trustTier",
}
_SAFE_FILE_SUFFIXES = {".md", ".txt", ".json"}
_EXECUTABLE_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".py", ".sh", ".command", ".exe", ".dylib", ".so"}
_MAX_FILES = 32
_MAX_TOTAL_BYTES = 256 * 1024


class CollaborationProfileStore:
    """Persist signed declarative profiles behind an ordered activation pipeline."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        trusted_signers: Mapping[str, bytes],
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.conn = conn
        self._trusted_signers = {
            _required_text(signer_id, "signer_id"): bytes(key)
            for signer_id, key in trusted_signers.items()
        }
        self._clock = clock or (lambda: int(time.time() * 1000))

    def inspect(self, bundle: Mapping[str, object]) -> dict[str, object]:
        if set(bundle) != {"manifest", "files", "signature"}:
            raise ValueError("profile bundle must contain only manifest, files, and signature")
        manifest = _object(bundle.get("manifest"), "manifest")
        files = _safe_files(bundle.get("files"))
        signature = _object(bundle.get("signature"), "signature")
        if set(signature) != {"signerId", "value"}:
            raise ValueError("profile signature shape is invalid")
        profile_id = _required_text(manifest.get("profileId"), "profileId")
        profile_version = _required_text(manifest.get("version"), "version")
        content_hash = _content_hash({"manifest": manifest, "files": files})
        signer_id = _required_text(signature.get("signerId"), "signerId")
        signature_value = _required_text(signature.get("value"), "signature.value")
        existing = self.conn.execute(
            "SELECT candidate_id, pipeline_stage FROM collaboration_profile_candidates WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if existing is not None:
            return _candidate_projection(str(existing[0]), profile_id, profile_version, content_hash, str(existing[1]))
        candidate_id = f"profile-candidate:{secrets.token_hex(12)}"
        now = self._clock()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO collaboration_profile_candidates(
                    candidate_id, profile_id, profile_version, content_hash,
                    manifest_json, files_json, signer_id, signature,
                    pipeline_stage, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'inspected', ?, ?)
                """,
                (
                    candidate_id, profile_id, profile_version, content_hash,
                    _canonical_json(manifest), _canonical_json(files), signer_id,
                    signature_value, now, now,
                ),
            )
        return _candidate_projection(candidate_id, profile_id, profile_version, content_hash, "inspected")

    def validate(self, candidate_id: object) -> dict[str, object]:
        candidate = self._candidate(candidate_id, expected_stage="inspected")
        manifest = _json_object(candidate[4])
        _validate_manifest_strict(manifest)
        signer_id = str(candidate[6])
        signing_key = self._trusted_signers.get(signer_id)
        if signing_key is None:
            raise ValueError("profile signer is not trusted by this local installation")
        expected = _signature_for(str(candidate[3]), signing_key)
        if not hmac.compare_digest(str(candidate[7]), expected):
            raise ValueError("profile signature does not match canonical content")
        self._advance(str(candidate[0]), "validated")
        return _candidate_projection(str(candidate[0]), str(candidate[1]), str(candidate[2]), str(candidate[3]), "validated")

    def compile(
        self,
        candidate_id: object,
        *,
        baseline_capabilities: tuple[str, ...],
        binding_revision: object,
    ) -> dict[str, object]:
        candidate = self._candidate(candidate_id, expected_stage="validated")
        manifest = _json_object(candidate[4])
        baseline = _normalized_capabilities(baseline_capabilities)
        requested = _normalized_capabilities(tuple(manifest["capabilityRequests"]))
        effective = tuple(sorted(set(baseline) & set(requested)))
        rejected = tuple(sorted(set(requested) - set(effective)))
        revision = _required_text(binding_revision, "binding_revision")
        receipt_material = _canonical_json({
            "contentHash": candidate[3],
            "bindingRevision": revision,
            "baselineCapabilities": list(baseline),
        })
        receipt_id = f"profile-compile:{hashlib.sha256(receipt_material.encode()).hexdigest()[:24]}"
        created_at_ms = self._clock()
        payload: dict[str, object] = {
            "schemaVersion": "rag-ime.collaboration-profile-compile-receipt.v1",
            "receiptId": receipt_id,
            "contentHash": str(candidate[3]),
            "compilerVersion": _COMPILER_VERSION,
            "bindingRevision": revision,
            "baselineCapabilities": list(baseline),
            "requestedCapabilities": list(requested),
            "effectiveCapabilities": list(effective),
            "rejectedCapabilities": list(rejected),
            "createdAtMs": created_at_ms,
        }
        validate_contract(payload, "collaboration-profile-compile-receipt.v1.json")
        if not set(effective).issubset(baseline):
            raise RuntimeError("compiled profile attempted to expand its capability baseline")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO collaboration_profile_compile_receipts(
                    receipt_id, content_hash, compiler_version, binding_revision,
                    baseline_capabilities_json, requested_capabilities_json,
                    effective_capabilities_json, rejected_capabilities_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id, candidate[3], _COMPILER_VERSION, revision,
                    _canonical_json(list(baseline)), _canonical_json(list(requested)),
                    _canonical_json(list(effective)), _canonical_json(list(rejected)), created_at_ms,
                ),
            )
            self.conn.execute(
                "UPDATE collaboration_profile_candidates SET pipeline_stage = 'compiled', compile_receipt_id = ?, updated_at_ms = ? WHERE candidate_id = ?",
                (receipt_id, created_at_ms, candidate[0]),
            )
        return payload

    def dry_run(self, candidate_id: object) -> dict[str, object]:
        candidate = self._candidate(candidate_id, expected_stage="compiled")
        receipt = self._compile_receipt(str(candidate[8]))
        baseline = set(_json_array(receipt[4]))
        effective = set(_json_array(receipt[6]))
        if not effective.issubset(baseline):
            raise RuntimeError("dry-run detected capability elevation")
        self._advance(str(candidate[0]), "dry_run")
        return {
            **_candidate_projection(str(candidate[0]), str(candidate[1]), str(candidate[2]), str(candidate[3]), "dry_run"),
            "removedCapabilities": sorted(baseline - effective),
            "canActivate": True,
        }

    def stage(self, candidate_id: object) -> dict[str, object]:
        candidate = self._candidate(candidate_id, expected_stage="dry_run")
        conflict = self.conn.execute(
            "SELECT content_hash FROM collaboration_profile_versions WHERE profile_id = ? AND profile_version = ?",
            (candidate[1], candidate[2]),
        ).fetchone()
        if conflict is not None and str(conflict[0]) != str(candidate[3]):
            raise ValueError("same profile version already exists; content-addressed versions cannot be overwritten")
        now = self._clock()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO collaboration_profile_versions(
                    content_hash, profile_id, profile_version, manifest_json, files_json,
                    signer_id, signature, compile_receipt_id, staged_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (candidate[3], candidate[1], candidate[2], candidate[4], candidate[5], candidate[6], candidate[7], candidate[8], now),
            )
            self.conn.execute(
                "UPDATE collaboration_profile_candidates SET pipeline_stage = 'staged', updated_at_ms = ? WHERE candidate_id = ?",
                (now, candidate[0]),
            )
        return _candidate_projection(str(candidate[0]), str(candidate[1]), str(candidate[2]), str(candidate[3]), "staged")

    def activate(
        self,
        *,
        profile_id: object,
        content_hash: object,
        expected_pointer_revision: int,
        _fail_after_pointer: bool = False,
    ) -> dict[str, object]:
        normalized_id = _required_text(profile_id, "profile_id")
        normalized_hash = _required_hash(content_hash)
        version = self._version(normalized_hash)
        if str(version[1]) != normalized_id:
            raise ValueError("profile content hash belongs to another profile")
        if version[8] is not None:
            raise ValueError("revoked profile version cannot be activated")
        now = self._clock()
        with self.conn:
            pointer = self._pointer(normalized_id)
            current_revision = int(pointer[3]) if pointer else 0
            if current_revision != int(expected_pointer_revision):
                raise ValueError("profile active pointer revision changed")
            previous_active = str(pointer[1]) if pointer and pointer[1] is not None else None
            next_revision = current_revision + 1
            self.conn.execute(
                """
                INSERT INTO collaboration_profile_active_pointers(
                    profile_id, active_content_hash, previous_content_hash, pointer_revision, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    active_content_hash = excluded.active_content_hash,
                    previous_content_hash = excluded.previous_content_hash,
                    pointer_revision = excluded.pointer_revision,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (normalized_id, normalized_hash, previous_active, next_revision, now),
            )
            if _fail_after_pointer:
                raise RuntimeError("simulated activation crash")
            receipt_id = self._activation_receipt(
                profile_id=normalized_id, action="activate", from_hash=previous_active,
                to_hash=normalized_hash, pointer_revision=next_revision, now=now,
            )
        return _pointer_payload(normalized_id, normalized_hash, previous_active, next_revision, receipt_id)

    def rollback(self, *, profile_id: object, expected_pointer_revision: int) -> dict[str, object]:
        normalized_id = _required_text(profile_id, "profile_id")
        now = self._clock()
        with self.conn:
            pointer = self._pointer(normalized_id)
            if pointer is None or pointer[2] is None:
                raise ValueError("profile rollback target is unavailable")
            if int(pointer[3]) != int(expected_pointer_revision):
                raise ValueError("profile active pointer revision changed")
            active_hash = str(pointer[1]) if pointer[1] is not None else None
            target_hash = str(pointer[2])
            target = self._version(target_hash)
            if target[8] is not None:
                raise ValueError("revoked profile version cannot be restored")
            next_revision = int(pointer[3]) + 1
            self.conn.execute(
                "UPDATE collaboration_profile_active_pointers SET active_content_hash = ?, previous_content_hash = ?, pointer_revision = ?, updated_at_ms = ? WHERE profile_id = ?",
                (target_hash, active_hash, next_revision, now, normalized_id),
            )
            receipt_id = self._activation_receipt(
                profile_id=normalized_id, action="rollback", from_hash=active_hash,
                to_hash=target_hash, pointer_revision=next_revision, now=now,
            )
        return _pointer_payload(normalized_id, target_hash, active_hash, next_revision, receipt_id)

    def revoke(
        self,
        *,
        content_hash: object,
        reason: object,
        expected_pointer_revision: int,
    ) -> dict[str, object]:
        normalized_hash = _required_hash(content_hash)
        version = self._version(normalized_hash)
        profile_id = str(version[1])
        reason_text = _required_text(reason, "reason")
        now = self._clock()
        with self.conn:
            pointer = self._pointer(profile_id)
            current_revision = int(pointer[3]) if pointer else 0
            if current_revision != int(expected_pointer_revision):
                raise ValueError("profile active pointer revision changed")
            self.conn.execute(
                "UPDATE collaboration_profile_versions SET revoked_at_ms = ?, revoke_reason = ? WHERE content_hash = ?",
                (now, reason_text, normalized_hash),
            )
            next_revision = current_revision
            receipt_id = ""
            if pointer is not None and pointer[1] == normalized_hash:
                next_revision += 1
                self.conn.execute(
                    "UPDATE collaboration_profile_active_pointers SET active_content_hash = NULL, previous_content_hash = ?, pointer_revision = ?, updated_at_ms = ? WHERE profile_id = ?",
                    (normalized_hash, next_revision, now, profile_id),
                )
                receipt_id = self._activation_receipt(
                    profile_id=profile_id, action="revoke", from_hash=normalized_hash,
                    to_hash=None, pointer_revision=next_revision, now=now,
                )
        return {
            "profileId": profile_id, "contentHash": normalized_hash, "revoked": True,
            "pointerRevision": next_revision, "receiptId": receipt_id,
        }

    def active_ref(self, profile_id: object) -> dict[str, object] | None:
        normalized_id = _required_text(profile_id, "profile_id")
        pointer = self._pointer(normalized_id)
        if pointer is None or pointer[1] is None:
            return None
        version = self._version(str(pointer[1]))
        if version[8] is not None:
            return None
        receipt = self._compile_receipt(str(version[7]))
        return {
            "profileId": normalized_id,
            "version": str(version[2]),
            "contentHash": str(version[0]),
            "pointerRevision": int(pointer[3]),
            "compileReceiptId": str(version[7]),
            "bindingRevision": str(receipt[3]),
        }

    def inspect_profile(self, profile_id: object) -> dict[str, object]:
        normalized_id = _required_text(profile_id, "profile_id")
        pointer = self._pointer(normalized_id)
        rows = self.conn.execute(
            """
            SELECT content_hash, profile_version, manifest_json, compile_receipt_id,
                   revoked_at_ms, revoke_reason, staged_at_ms
            FROM collaboration_profile_versions WHERE profile_id = ?
            ORDER BY staged_at_ms DESC, profile_version DESC
            """,
            (normalized_id,),
        ).fetchall()
        return {
            "schemaVersion": "rag-ime.collaboration-profile-inspection.v1",
            "profileId": normalized_id,
            "active": self.active_ref(normalized_id),
            "pointerRevision": int(pointer[3]) if pointer else 0,
            "versions": [
                {
                    "contentHash": str(row[0]), "version": str(row[1]),
                    "manifest": _json_object(row[2]), "compileReceiptId": str(row[3]),
                    "revoked": row[4] is not None, "revokeReason": str(row[5]),
                    "stagedAtMs": int(row[6]),
                }
                for row in rows
            ],
        }

    def _candidate(self, candidate_id: object, *, expected_stage: str) -> tuple[object, ...]:
        normalized_id = _required_text(candidate_id, "candidate_id")
        row = self.conn.execute(
            """
            SELECT candidate_id, profile_id, profile_version, content_hash,
                   manifest_json, files_json, signer_id, signature,
                   compile_receipt_id, pipeline_stage
            FROM collaboration_profile_candidates WHERE candidate_id = ?
            """,
            (normalized_id,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown profile candidate")
        if str(row[9]) != expected_stage:
            raise ValueError(f"profile pipeline requires {expected_stage} before this operation")
        return tuple(row)

    def _advance(self, candidate_id: str, stage: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE collaboration_profile_candidates SET pipeline_stage = ?, updated_at_ms = ? WHERE candidate_id = ?",
                (stage, self._clock(), candidate_id),
            )

    def _compile_receipt(self, receipt_id: str) -> tuple[object, ...]:
        row = self.conn.execute(
            """
            SELECT receipt_id, content_hash, compiler_version, binding_revision,
                   baseline_capabilities_json, requested_capabilities_json,
                   effective_capabilities_json, rejected_capabilities_json, created_at_ms
            FROM collaboration_profile_compile_receipts WHERE receipt_id = ?
            """,
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("profile compile receipt is missing")
        return tuple(row)

    def _version(self, content_hash: str) -> tuple[object, ...]:
        row = self.conn.execute(
            """
            SELECT content_hash, profile_id, profile_version, manifest_json, files_json,
                   signer_id, signature, compile_receipt_id, revoked_at_ms, revoke_reason
            FROM collaboration_profile_versions WHERE content_hash = ?
            """,
            (content_hash,),
        ).fetchone()
        if row is None:
            raise ValueError("profile version is not staged")
        return tuple(row)

    def _pointer(self, profile_id: str) -> tuple[object, ...] | None:
        row = self.conn.execute(
            "SELECT profile_id, active_content_hash, previous_content_hash, pointer_revision, updated_at_ms FROM collaboration_profile_active_pointers WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        return tuple(row) if row is not None else None

    def _activation_receipt(
        self,
        *,
        profile_id: str,
        action: str,
        from_hash: str | None,
        to_hash: str | None,
        pointer_revision: int,
        now: int,
    ) -> str:
        receipt_id = f"profile-{action}:{secrets.token_hex(12)}"
        self.conn.execute(
            """
            INSERT INTO collaboration_profile_activation_receipts(
                receipt_id, profile_id, action, from_content_hash, to_content_hash,
                pointer_revision, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (receipt_id, profile_id, action, from_hash, to_hash, pointer_revision, now),
        )
        return receipt_id


def sign_profile_bundle(
    *,
    manifest: Mapping[str, object],
    files: Mapping[str, str],
    signer_id: str,
    signing_key: bytes,
) -> dict[str, object]:
    safe_files = _safe_files(files)
    material = {"manifest": dict(manifest), "files": safe_files}
    content_hash = _content_hash(material)
    return {
        **material,
        "signature": {
            "signerId": _required_text(signer_id, "signer_id"),
            "value": _signature_for(content_hash, bytes(signing_key)),
        },
    }


def _validate_manifest_strict(manifest: Mapping[str, object]) -> None:
    if set(manifest) != _MANIFEST_FIELDS:
        missing = sorted(_MANIFEST_FIELDS - set(manifest))
        extra = sorted(set(manifest) - _MANIFEST_FIELDS)
        raise ValueError(f"profile manifest fields are not strict: missing={missing}, extra={extra}")
    validate_contract(dict(manifest), "collaboration-profile.v1.json")
    profile_id = _required_text(manifest["profileId"], "profileId")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", profile_id) is None:
        raise ValueError("profileId is invalid")
    version = _required_text(manifest["version"], "version")
    if re.fullmatch(r"[1-9][0-9]{0,5}", version) is None:
        raise ValueError("profile version is invalid")
    _bounded_unique_strings(manifest["collaborationRoleRefs"], "collaborationRoleRefs", 1, 16)
    _bounded_unique_strings(manifest["capabilityRequests"], "capabilityRequests", 1, 8)
    _normalized_capabilities(tuple(manifest["capabilityRequests"]))
    _bounded_unique_strings(manifest["requiredGateIds"], "requiredGateIds", 1, 16)
    _bounded_unique_strings(manifest["promptGuidance"], "promptGuidance", 1, 12)
    if manifest["trustTier"] not in {"builtin", "signed", "local-untrusted"}:
        raise ValueError("profile trustTier is invalid")


def _safe_files(value: object) -> dict[str, str]:
    files = _object(value, "files")
    if len(files) > _MAX_FILES:
        raise ValueError("profile package contains too many files")
    result: dict[str, str] = {}
    total = 0
    for raw_path, raw_content in files.items():
        path = str(raw_path)
        if "\\" in path or path.startswith("/") or path.startswith("."):
            raise ValueError("unsafe profile package path")
        normalized = PurePosixPath(path)
        if (
            not path
            or str(normalized) != path
            or any(part in {"", ".", ".."} for part in normalized.parts)
        ):
            raise ValueError("unsafe profile package path")
        suffix = normalized.suffix.lower()
        if suffix in _EXECUTABLE_SUFFIXES:
            raise ValueError("executable profile package files are forbidden")
        if suffix not in _SAFE_FILE_SUFFIXES:
            raise ValueError("unsafe profile package file type")
        if not isinstance(raw_content, str):
            raise ValueError("profile package files must contain text")
        total += len(raw_content.encode("utf-8"))
        if total > _MAX_TOTAL_BYTES:
            raise ValueError("profile package exceeds its byte limit")
        result[path] = raw_content
    return {key: result[key] for key in sorted(result)}


def _bounded_unique_strings(value: object, field: str, minimum: int, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} length is invalid")
    normalized = tuple(_required_text(item, field) for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must be unique")
    return normalized


def _normalized_capabilities(values: tuple[object, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted({_required_text(value, "capability") for value in values}))
    unsupported = set(normalized) - _CAPABILITIES
    if unsupported:
        raise ValueError(f"unsupported profile capabilities: {sorted(unsupported)}")
    return normalized


def _candidate_projection(candidate_id: str, profile_id: str, version: str, content_hash: str, stage: str) -> dict[str, object]:
    return {
        "candidateId": candidate_id, "profileId": profile_id, "version": version,
        "contentHash": content_hash, "stage": stage,
    }


def _pointer_payload(profile_id: str, active_hash: str | None, previous_hash: str | None, revision: int, receipt_id: str) -> dict[str, object]:
    return {
        "profileId": profile_id, "activeContentHash": active_hash,
        "previousContentHash": previous_hash, "pointerRevision": revision,
        "receiptId": receipt_id,
    }


def _content_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _signature_for(content_hash: str, key: bytes) -> str:
    return "hmac-sha256:" + hmac.new(key, content_hash.encode("ascii"), hashlib.sha256).hexdigest()


def _required_hash(value: object) -> str:
    normalized = _required_text(value, "content_hash")
    if re.fullmatch(r"sha256:[a-f0-9]{64}", normalized) is None:
        raise ValueError("profile content hash is invalid")
    return normalized


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return {str(key): item for key, item in value.items()}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _json_object(value: object) -> dict[str, object]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise RuntimeError("stored profile JSON is not an object")
    return parsed


def _json_array(value: object) -> list[object]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise RuntimeError("stored profile JSON is not an array")
    return parsed
