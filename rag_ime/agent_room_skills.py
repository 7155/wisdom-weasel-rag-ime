from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


_POLICY_ROOT_KEYS = frozenset(
    {"schemaVersion", "policyId", "version", "hashRule", "skills"}
)
_POLICY_ENTRY_KEYS = frozenset({"skillId", "stages", "risk", "nextCandidates"})
_LOAD_REASONS = frozenset({"stage_required", "model_selected", "compaction_restore"})
_MODEL_SKILL_CATALOG_KEYS = (
    "name",
    "when",
    "notFor",
    "input",
    "output",
    "does",
)


class RoomSkillPolicyConflict(RuntimeError):
    """A policy or receipt reused an immutable identity with different content."""


class RoomSkillEpochRevoked(RuntimeError):
    """A Skill load or recovery belongs to a revoked capability epoch."""


class SkillCatalogRevisionMismatch(RuntimeError):
    """The live native Pi Skill catalog no longer matches the pinned receipt."""


class SkillContentRevisionMismatch(RuntimeError):
    """The native Skill body no longer matches the pinned load receipt."""


class RoomSkillPolicy:
    """Governance references around Pi native Skills, not a second Skill loader."""

    def __init__(self, policy_path: str | Path, skills_root: str | Path) -> None:
        self.policy_path = Path(policy_path)
        self.skills_root = Path(skills_root)
        raw = json.loads(self.policy_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Room Skill policy must be an object")
        if set(raw) != _POLICY_ROOT_KEYS:
            raise ValueError("Room Skill policy contains unsupported root fields")
        validate_contract(raw, "room-skill-policy.v1.json")

        entries = raw.get("skills")
        if not isinstance(entries, list) or not entries:
            raise ValueError("Room Skill policy requires skills[]")
        normalized: list[dict[str, object]] = []
        seen: set[str] = set()
        for index, value in enumerate(entries):
            if not isinstance(value, Mapping) or set(value) != _POLICY_ENTRY_KEYS:
                raise ValueError(f"Room Skill policy skills[{index}] has unsupported fields")
            skill_id = _required_text(value.get("skillId"), f"skills[{index}].skillId")
            if skill_id in seen:
                raise ValueError(f"duplicate Room Skill policy entry: {skill_id}")
            stages = _string_list(value.get("stages"), f"skills[{index}].stages", allow_empty=False)
            next_candidates = _string_list(
                value.get("nextCandidates"),
                f"skills[{index}].nextCandidates",
                allow_empty=True,
            )
            risk = _required_text(value.get("risk"), f"skills[{index}].risk")
            if risk not in {"low", "medium", "high"}:
                raise ValueError(f"unsupported Room Skill risk: {risk}")
            if not self.skill_path(skill_id).is_file():
                raise ValueError(f"Room Skill source does not exist: {skill_id}")
            seen.add(skill_id)
            normalized.append(
                {
                    "skillId": skill_id,
                    "stages": stages,
                    "risk": risk,
                    "nextCandidates": next_candidates,
                }
            )

        for entry in normalized:
            for candidate in entry["nextCandidates"]:  # type: ignore[union-attr]
                if candidate not in seen:
                    raise ValueError(f"unknown next Room Skill candidate: {candidate}")

        self.policy_id = _required_text(raw.get("policyId"), "policyId")
        self.version = _positive_int(raw.get("version"), "version")
        self.hash_rule = _required_text(raw.get("hashRule"), "hashRule")
        self._entries = tuple(normalized)
        self._by_id = {str(entry["skillId"]): entry for entry in normalized}

    @property
    def skill_ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    def skill_path(self, skill_id: str) -> Path:
        skill_id = _required_text(skill_id, "skillId")
        if "/" in skill_id or "\\" in skill_id or skill_id in {".", ".."}:
            raise ValueError("skillId must be an exact native Skill name")
        return self.skills_root / skill_id / "SKILL.md"

    def skill_hash(self, skill_id: str) -> str:
        if skill_id not in self._by_id:
            raise ValueError(f"Skill is not governed by Room policy: {skill_id}")
        content = self.skill_path(skill_id).read_text(encoding="utf-8")
        body = _native_skill_body(content)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def skill_body(self, skill_id: str) -> str:
        if skill_id not in self._by_id:
            raise ValueError(f"Skill is not governed by Room policy: {skill_id}")
        return _native_skill_body(self.skill_path(skill_id).read_text(encoding="utf-8"))

    def catalog(self) -> list[dict[str, object]]:
        """Expose only progressive-disclosure metadata, never Skill bodies."""

        return [self._catalog_entry(skill_id) for skill_id in self.skill_ids]

    def load_exact(self, skill_id: str) -> dict[str, object]:
        """Load exactly one governed native Skill; fuzzy names are rejected."""

        skill_id = _required_text(skill_id, "skillId")
        if skill_id not in self._by_id:
            raise ValueError(f"Skill is not governed by Room policy: {skill_id}")
        return {
            **self._catalog_entry(skill_id),
            "body": self.skill_body(skill_id),
            "contentRevision": self.skill_hash(skill_id),
        }

    def _catalog_entry(self, skill_id: str) -> dict[str, object]:
        metadata = _native_skill_metadata(
            self.skill_path(skill_id).read_text(encoding="utf-8")
        )
        if metadata["name"] != skill_id:
            raise ValueError(f"native Skill name differs from policy: {skill_id}")
        # Provider-facing discovery is deliberately smaller than governance.
        # Stage/risk/continuation metadata stays in the policy and receipts so
        # it cannot silently become model authority or bloat every turn.
        return {key: metadata[key] for key in _MODEL_SKILL_CATALOG_KEYS}

    def select_stage(self, stage: str) -> dict[str, object]:
        """Select only explicit stages; semantic matching remains Pi's native job."""

        stage = _required_text(stage, "stage")
        matches = [
            entry
            for entry in self._entries
            if stage in entry["stages"]  # type: ignore[operator]
        ]
        if not matches:
            result: dict[str, object] = {
                "schemaVersion": "wisdom-weasel.room-skill-selection.v1",
                "stage": stage,
                "selection": "none",
                "skillId": None,
                "candidateSkillIds": [],
                "risk": None,
            }
        elif len(matches) == 1:
            entry = matches[0]
            result = {
                "schemaVersion": "wisdom-weasel.room-skill-selection.v1",
                "selection": "required",
                "stage": stage,
                "skillId": entry["skillId"],
                "candidateSkillIds": [],
                "risk": entry["risk"],
            }
        else:
            result = {
                "schemaVersion": "wisdom-weasel.room-skill-selection.v1",
                "selection": "suggested",
                "stage": stage,
                "skillId": None,
                "candidateSkillIds": [entry["skillId"] for entry in matches],
                "risk": None,
            }
        validate_contract(result, "room-skill-selection.v1.json")
        return result

    def next_candidates(self, skill_id: str) -> list[str]:
        entry = self._by_id.get(_required_text(skill_id, "skillId"))
        if entry is None:
            raise ValueError(f"Skill is not governed by Room policy: {skill_id}")
        return list(entry["nextCandidates"])  # type: ignore[arg-type]


class RoomSkillPolicyStore:
    """Durable pins for loads performed by Pi's existing native skill_load Tool."""

    def __init__(self, db_path: str | Path, policy: RoomSkillPolicy) -> None:
        self.db_path = Path(db_path)
        self.policy = policy

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def next_candidates(self, skill_id: str) -> list[str]:
        # This is deliberately a pure read. Candidates never imply Dispatch creation.
        return self.policy.next_candidates(skill_id)

    def active_for_session(self, session_id: str) -> dict[str, object] | None:
        return self._latest_for_session(session_id, state="active")

    def latest_for_session(self, session_id: str) -> dict[str, object] | None:
        """Return the newest receipt for audit, including an already revoked pin."""

        return self._latest_for_session(session_id)

    def _latest_for_session(
        self, session_id: str, *, state: str | None = None
    ) -> dict[str, object] | None:
        where = "session_id = ?"
        params: tuple[object, ...] = (_required_text(session_id, "sessionId"),)
        if state is not None:
            where += " AND state = ?"
            params += (state,)
        with self._connect() as conn:
            row = conn.execute(
                f"""SELECT * FROM room_v2_skill_load_receipts
                    WHERE {where}
                    ORDER BY created_at_ms DESC, receipt_id DESC LIMIT 1""",
                params,
            ).fetchone()
        return _receipt_payload(row) if row is not None else None

    def pin_skill(
        self,
        *,
        receipt_id: str,
        root_id: str,
        task_id: str,
        dispatch_id: str,
        session_id: str,
        skill_id: str,
        skill_hash: str,
        catalog_revision: str,
        load_reason: str,
        capability_epoch: int,
        idempotency_key: str,
        created_at_ms: int,
        source_receipt_id: str = "",
    ) -> tuple[dict[str, object], bool]:
        receipt_id = _required_text(receipt_id, "receiptId")
        root_id = _required_text(root_id, "rootId")
        task_id = _required_text(task_id, "taskId")
        dispatch_id = _required_text(dispatch_id, "dispatchId")
        session_id = _required_text(session_id, "sessionId")
        skill_id = _required_text(skill_id, "explicit skillId")
        skill_hash = _required_hash(skill_hash, "skillHash")
        catalog_revision = _required_hash(catalog_revision, "catalogRevision")
        load_reason = _required_text(load_reason, "loadReason")
        if load_reason not in _LOAD_REASONS:
            raise ValueError("unsupported Room Skill loadReason")
        capability_epoch = _non_negative_int(capability_epoch, "capabilityEpoch")
        idempotency_key = _required_text(idempotency_key, "idempotencyKey")
        created_at_ms = _non_negative_int(created_at_ms, "createdAtMs")
        source_receipt_id = str(source_receipt_id or "").strip()
        current_hash = self.policy.skill_hash(skill_id)
        if skill_hash != current_hash:
            raise SkillContentRevisionMismatch(
                f"native Skill load hash no longer matches source: {skill_id}"
            )
        identity = {
            "receiptId": receipt_id,
            "rootId": root_id,
            "taskId": task_id,
            "dispatchId": dispatch_id,
            "sessionId": session_id,
            "skillId": skill_id,
            "skillHash": skill_hash,
            "hashRule": self.policy.hash_rule,
            "catalogRevision": catalog_revision,
            "policyId": self.policy.policy_id,
            "policyVersion": self.policy.version,
            "loadReason": load_reason,
            "capabilityEpoch": capability_epoch,
            "idempotencyKey": idempotency_key,
            "sourceReceiptId": source_receipt_id,
            "createdAtMs": created_at_ms,
        }
        identity_hash = _sha256_json(identity)

        with self._connect(immediate=True) as conn:
            epoch_row = conn.execute(
                "SELECT capability_epoch FROM room_v2_skill_capability_epochs WHERE root_id = ?",
                (root_id,),
            ).fetchone()
            if epoch_row is None:
                conn.execute(
                    """
                    INSERT INTO room_v2_skill_capability_epochs(root_id, capability_epoch, updated_at_ms)
                    VALUES (?, ?, ?)
                    """,
                    (root_id, capability_epoch, created_at_ms),
                )
                current_epoch = capability_epoch
            else:
                current_epoch = int(epoch_row[0])
            if capability_epoch != current_epoch:
                raise RoomSkillEpochRevoked(
                    f"capability epoch {capability_epoch} does not match {current_epoch}"
                )
            rows = conn.execute(
                """
                SELECT * FROM room_v2_skill_load_receipts
                WHERE receipt_id = ? OR (root_id = ? AND idempotency_key = ?)
                """,
                (receipt_id, root_id, idempotency_key),
            ).fetchall()
            if len(rows) > 1:
                raise RoomSkillPolicyConflict("Skill receipt identifiers resolve to different records")
            if rows:
                if str(rows[0]["identity_hash"]) != identity_hash:
                    raise RoomSkillPolicyConflict(
                        "Skill receipt identity was reused with different immutable content"
                    )
                return _receipt_payload(rows[0]), False
            conn.execute(
                """
                INSERT INTO room_v2_skill_load_receipts(
                    receipt_id, root_id, task_id, dispatch_id, session_id,
                    skill_id, skill_hash, hash_rule, catalog_revision,
                    policy_id, policy_version, load_reason, capability_epoch,
                    idempotency_key, state, source_receipt_id, identity_hash,
                    created_at_ms, revoked_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL)
                """,
                (
                    receipt_id,
                    root_id,
                    task_id,
                    dispatch_id,
                    session_id,
                    skill_id,
                    skill_hash,
                    self.policy.hash_rule,
                    catalog_revision,
                    self.policy.policy_id,
                    self.policy.version,
                    load_reason,
                    capability_epoch,
                    idempotency_key,
                    source_receipt_id,
                    identity_hash,
                    created_at_ms,
                ),
            )
            row = conn.execute(
                "SELECT * FROM room_v2_skill_load_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - protected by transaction
                raise RuntimeError("Skill load receipt did not persist")
            payload = _receipt_payload(row)
            validate_contract(payload, "room-skill-load-receipt.v1.json")
            return payload, True

    def restore_for_compaction(
        self,
        receipt_id: str,
        *,
        expected_capability_epoch: int,
        catalog_revision: str,
        allow_immediately_revoked: bool = False,
    ) -> dict[str, object]:
        receipt_id = _required_text(receipt_id, "receiptId")
        expected_capability_epoch = _non_negative_int(
            expected_capability_epoch,
            "expectedCapabilityEpoch",
        )
        catalog_revision = _required_hash(catalog_revision, "catalogRevision")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_skill_load_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown Room Skill load receipt: {receipt_id}")
            current_epoch = self._current_epoch(conn, str(row["root_id"]))
            newer_receipt_exists = conn.execute(
                """SELECT 1 FROM room_v2_skill_load_receipts
                   WHERE root_id = ? AND capability_epoch > ? LIMIT 1""",
                (str(row["root_id"]), expected_capability_epoch),
            ).fetchone() is not None
        receipt = _receipt_payload(row)
        receipt_epoch = int(receipt["capabilityEpoch"])
        active_epoch = (
            receipt["state"] == "active"
            and receipt_epoch == expected_capability_epoch
            and current_epoch == expected_capability_epoch
        )
        sealed_epoch = (
            allow_immediately_revoked
            and receipt["state"] == "revoked"
            and receipt_epoch == expected_capability_epoch
            and current_epoch == expected_capability_epoch + 1
            and not newer_receipt_exists
        )
        if not (active_epoch or sealed_epoch):
            raise RoomSkillEpochRevoked("Room Skill load receipt belongs to a revoked epoch")
        if receipt["catalogRevision"] != catalog_revision:
            raise SkillCatalogRevisionMismatch("native Pi Skill catalog revision changed")
        if (
            receipt["policyId"] != self.policy.policy_id
            or receipt["policyVersion"] != self.policy.version
        ):
            raise RoomSkillPolicyConflict("Room Skill policy revision changed")
        current_hash = self.policy.skill_hash(str(receipt["skillId"]))
        if receipt["skillHash"] != current_hash:
            raise SkillContentRevisionMismatch("native Skill body revision changed")
        recovery = {
            "schemaVersion": "wisdom-weasel.room-skill-recovery.v1",
            "restoredFromReceiptId": receipt["receiptId"],
            "skillId": receipt["skillId"],
            "skillHash": receipt["skillHash"],
            "hashRule": receipt["hashRule"],
            "catalogRevision": receipt["catalogRevision"],
            "policyId": receipt["policyId"],
            "policyVersion": receipt["policyVersion"],
            "capabilityEpoch": receipt["capabilityEpoch"],
        }
        validate_contract(recovery, "room-skill-recovery.v1.json")
        return recovery

    def revoke_before_epoch(
        self,
        root_id: str,
        *,
        new_capability_epoch: int,
        revoked_at_ms: int,
    ) -> int:
        root_id = _required_text(root_id, "rootId")
        new_capability_epoch = _non_negative_int(new_capability_epoch, "newCapabilityEpoch")
        revoked_at_ms = _non_negative_int(revoked_at_ms, "revokedAtMs")
        with self._connect(immediate=True) as conn:
            current = self._current_epoch(conn, root_id)
            if new_capability_epoch < current:
                raise ValueError("newCapabilityEpoch must advance monotonically")
            if new_capability_epoch == current:
                # Parallel Dispatches in one Root share a capability epoch.
                # Each Session revokes its own runtime binding, while this
                # Root-scoped Skill fence is an idempotent set operation.
                return 0
            conn.execute(
                """
                INSERT INTO room_v2_skill_capability_epochs(root_id, capability_epoch, updated_at_ms)
                VALUES (?, ?, ?)
                ON CONFLICT(root_id) DO UPDATE SET
                    capability_epoch = excluded.capability_epoch,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (root_id, new_capability_epoch, revoked_at_ms),
            )
            cursor = conn.execute(
                """
                UPDATE room_v2_skill_load_receipts
                SET state = 'revoked', revoked_at_ms = ?
                WHERE root_id = ? AND capability_epoch < ? AND state = 'active'
                """,
                (revoked_at_ms, root_id, new_capability_epoch),
            )
            return int(cursor.rowcount)

    @staticmethod
    def _current_epoch(conn: sqlite3.Connection, root_id: str) -> int:
        row = conn.execute(
            "SELECT capability_epoch FROM room_v2_skill_capability_epochs WHERE root_id = ?",
            (root_id,),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _receipt_payload(row: sqlite3.Row) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "wisdom-weasel.room-skill-load-receipt.v1",
        "receiptId": str(row["receipt_id"]),
        "rootId": str(row["root_id"]),
        "taskId": str(row["task_id"]),
        "dispatchId": str(row["dispatch_id"]),
        "sessionId": str(row["session_id"]),
        "skillId": str(row["skill_id"]),
        "skillHash": str(row["skill_hash"]),
        "hashRule": str(row["hash_rule"]),
        "catalogRevision": str(row["catalog_revision"]),
        "policyId": str(row["policy_id"]),
        "policyVersion": int(row["policy_version"]),
        "loadReason": str(row["load_reason"]),
        "capabilityEpoch": int(row["capability_epoch"]),
        "idempotencyKey": str(row["idempotency_key"]),
        "state": str(row["state"]),
        "sourceReceiptId": str(row["source_receipt_id"]),
        "createdAtMs": int(row["created_at_ms"]),
        "revokedAtMs": int(row["revoked_at_ms"]) if row["revoked_at_ms"] is not None else None,
    }
    validate_contract(payload, "room-skill-load-receipt.v1.json")
    return payload


def _native_skill_body(content: str) -> str:
    if not content.startswith("---"):
        raise ValueError("native Skill source is missing YAML frontmatter")
    lines = content.splitlines(keepends=True)
    closing = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        raise ValueError("native Skill source has unclosed YAML frontmatter")
    return "".join(lines[closing + 1 :]).strip()


def _native_skill_metadata(content: str) -> dict[str, object]:
    """Parse the exact six-field model catalog from native Skill frontmatter."""

    if not content.startswith("---"):
        raise ValueError("native Skill source is missing YAML frontmatter")
    lines = content.splitlines()
    try:
        closing = lines[1:].index("---") + 1
    except ValueError as exc:
        raise ValueError("native Skill source has unclosed YAML frontmatter") from exc
    scalar: dict[str, str] = {}
    arrays: dict[str, list[str]] = {"when": [], "notFor": []}
    current_array = ""
    for line in lines[1:closing]:
        list_match = re.fullmatch(r"\s+-\s+(.+)", line)
        if list_match and current_array:
            arrays[current_array].append(list_match.group(1).strip())
            continue
        field_match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*):(?:\s*(.*))?", line)
        if not field_match:
            raise ValueError("native Skill frontmatter uses unsupported YAML")
        key, value = field_match.groups()
        current_array = key if key in arrays and not value else ""
        if value:
            scalar[key] = value.strip()
    if any(not scalar.get(key) for key in ("name", "input", "output", "does")):
        raise ValueError("native Skill catalog metadata is incomplete")
    if not arrays["when"] or not arrays["notFor"]:
        raise ValueError("native Skill requires non-empty when and notFor metadata")
    return {
        "name": scalar["name"],
        "when": arrays["when"],
        "notFor": arrays["notFor"],
        "input": scalar["input"],
        "output": scalar["output"],
        "does": scalar["does"],
    }


def _string_list(value: object, field: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{field} must be a {'possibly empty' if allow_empty else 'non-empty'} string array")
    result = [_required_text(item, field) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{field} contains duplicates")
    return result


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_hash(value: object, field: str) -> str:
    text = _required_text(value, field)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _non_negative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: object, field: str) -> int:
    result = _non_negative_int(value, field)
    if result < 1:
        raise ValueError(f"{field} must be at least 1")
    return result


def _sha256_json(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
