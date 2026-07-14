from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


_MAX_LIFECYCLE_BYTES = 32 * 1024 * 1024
_MAX_RECORD_BYTES = 1024 * 1024
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
_MAX_INSPECTION_RECORDS = 500
_MAX_INSPECTION_BYTES = 256 * 1024
_MAX_INSPECTION_RECORD_BYTES = 32 * 1024
_OWNER_KINDS = frozenset({"subagent_run", "tool_run", "connector_run"})


class AgentArtifactStore:
    """Managed append-only artifacts plus atomic recovery snapshots."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        root: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.root = Path(root) if root is not None else self.db_path.parent / "agent-artifacts"
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_private_directory(self.root)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def ensure(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        artifact_kind: str = "lifecycle",
        media_type: str = "application/x-ndjson",
    ) -> dict[str, object]:
        owner = _owner(owner_kind, owner_id)
        kind = _bounded_identifier(artifact_kind, field="artifact kind")
        mime = _bounded_media_type(media_type)
        artifact_id = _artifact_id(owner[0], owner[1], kind)
        lifecycle_key, _ = self._storage_keys(owner[0], owner[1], kind)
        now = _now_ms()
        with self._lock:
            directory = self._resolve_storage(lifecycle_key).parent
            _ensure_private_directory(directory)
            lifecycle = self._resolve_storage(lifecycle_key)
            _ensure_private_file(lifecycle)
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO agent_artifacts(
                        id, owner_kind, owner_id, artifact_kind, media_type,
                        storage_key, append_only, byte_size, sha256,
                        record_count, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, 0, '', 0, ?, ?)
                    """,
                    (
                        artifact_id,
                        owner[0],
                        owner[1],
                        kind,
                        mime,
                        lifecycle_key,
                        now,
                        now,
                    ),
                )
            self._refresh_lifecycle_metadata(artifact_id, lifecycle)
        return self.reference(owner_kind=owner[0], owner_id=owner[1], artifact_kind=kind)

    def append_records(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        records: Sequence[Mapping[str, object]],
        artifact_kind: str = "lifecycle",
    ) -> dict[str, object]:
        reference = self.ensure(
            owner_kind=owner_kind,
            owner_id=owner_id,
            artifact_kind=artifact_kind,
        )
        artifact_id = str(reference["artifactId"])
        lifecycle_key, _ = self._storage_keys(owner_kind, owner_id, artifact_kind)
        lifecycle = self._resolve_storage(lifecycle_key)
        with self._lock:
            existing = {
                str(item.get("recordId") or "")
                for item in self.lifecycle_records(
                    owner_kind=owner_kind,
                    owner_id=owner_id,
                    artifact_kind=artifact_kind,
                )
            }
            encoded: list[bytes] = []
            seen = set(existing)
            for value in records:
                record = dict(value)
                record_id = str(record.get("recordId") or "").strip()
                if not record_id:
                    raise ValueError("artifact lifecycle record requires recordId")
                if record_id in seen:
                    continue
                record.setdefault("schemaVersion", "rag-ime.agent-artifact-record.v1")
                blob = (
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
                if len(blob) > _MAX_RECORD_BYTES:
                    raise ValueError("artifact lifecycle record is too large")
                encoded.append(blob)
                seen.add(record_id)
            if encoded:
                current_size = lifecycle.stat().st_size
                if current_size + sum(len(item) for item in encoded) > _MAX_LIFECYCLE_BYTES:
                    raise ValueError("artifact lifecycle exceeds the managed size limit")
                flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(lifecycle, flags)
                try:
                    with os.fdopen(descriptor, "ab", closefd=False) as handle:
                        for blob in encoded:
                            handle.write(blob)
                        handle.flush()
                        os.fsync(handle.fileno())
                finally:
                    os.close(descriptor)
                self._refresh_lifecycle_metadata(artifact_id, lifecycle)
        return self.reference(
            owner_kind=owner_kind,
            owner_id=owner_id,
            artifact_kind=artifact_kind,
        )

    def checkpoint(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        projection: Mapping[str, object] | None = None,
        runtime_checkpoint: Mapping[str, object] | None = None,
        supervision: Mapping[str, object] | None = None,
        artifact_kind: str = "lifecycle",
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        reference = self.ensure(
            owner_kind=owner_kind,
            owner_id=owner_id,
            artifact_kind=artifact_kind,
        )
        artifact_id = str(reference["artifactId"])
        _, snapshot_key = self._storage_keys(owner_kind, owner_id, artifact_kind)
        snapshot_path = self._resolve_storage(snapshot_key)
        now = int(updated_at_ms if updated_at_ms is not None else _now_ms())
        with self._lock:
            current = self._read_snapshot_path(snapshot_path) or {}
            revision = int(current.get("revision") or 0) + 1
            runtime_value = _merged_mapping(current.get("runtimeCheckpoint"), runtime_checkpoint)
            supervision_value = _merged_mapping(current.get("supervision"), supervision)
            payload = {
                "schemaVersion": "rag-ime.agent-run-snapshot.v1",
                "artifactId": artifact_id,
                "ownerKind": owner_kind,
                "ownerId": owner_id,
                "revision": revision,
                "projection": dict(
                    projection
                    if projection is not None
                    else _mapping_or_empty(current.get("projection"))
                ),
                "runtimeCheckpoint": runtime_value,
                "supervision": supervision_value,
                "updatedAtMs": now,
            }
            blob = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(blob) > _MAX_SNAPSHOT_BYTES:
                raise ValueError("agent run snapshot exceeds the managed size limit")
            _atomic_private_write(snapshot_path, blob)
            digest = hashlib.sha256(blob).hexdigest()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_artifact_snapshots(
                        artifact_id, revision, storage_key, byte_size, sha256, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(artifact_id) DO UPDATE SET
                        revision = excluded.revision,
                        storage_key = excluded.storage_key,
                        byte_size = excluded.byte_size,
                        sha256 = excluded.sha256,
                        updated_at_ms = excluded.updated_at_ms
                    """,
                    (artifact_id, revision, snapshot_key, len(blob), digest, now),
                )
        return self.reference(
            owner_kind=owner_kind,
            owner_id=owner_id,
            artifact_kind=artifact_kind,
        )

    def snapshot(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        artifact_kind: str = "lifecycle",
    ) -> dict[str, object] | None:
        _, snapshot_key = self._storage_keys(owner_kind, owner_id, artifact_kind)
        path = self._resolve_storage(snapshot_key)
        with self._lock:
            payload = self._read_snapshot_path(path)
            if payload is None:
                return None
            artifact_id = _artifact_id(owner_kind, owner_id, artifact_kind)
            blob = path.read_bytes()
            revision = int(payload.get("revision") or 1)
            digest = hashlib.sha256(blob).hexdigest()
            updated_at_ms = int(payload.get("updatedAtMs") or _now_ms())
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT revision, byte_size, sha256 FROM agent_artifact_snapshots WHERE artifact_id = ?",
                    (artifact_id,),
                ).fetchone()
                if row is None or (
                    int(row["revision"]) != revision
                    or int(row["byte_size"]) != len(blob)
                    or str(row["sha256"]) != digest
                ):
                    conn.execute(
                        """
                        INSERT INTO agent_artifact_snapshots(
                            artifact_id, revision, storage_key, byte_size, sha256, updated_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(artifact_id) DO UPDATE SET
                            revision = excluded.revision,
                            storage_key = excluded.storage_key,
                            byte_size = excluded.byte_size,
                            sha256 = excluded.sha256,
                            updated_at_ms = excluded.updated_at_ms
                        """,
                        (
                            artifact_id,
                            revision,
                            snapshot_key,
                            len(blob),
                            digest,
                            updated_at_ms,
                        ),
                    )
            return payload

    def lifecycle_records(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        artifact_kind: str = "lifecycle",
    ) -> list[dict[str, object]]:
        lifecycle_key, _ = self._storage_keys(owner_kind, owner_id, artifact_kind)
        return self._lifecycle_records_from_path(self._resolve_storage(lifecycle_key))

    def inspect(
        self,
        artifact_id: str,
        *,
        limit: int = 100,
    ) -> dict[str, object]:
        """Return a bounded public lifecycle view without exposing storage locators."""

        identifier = str(artifact_id or "").strip()
        if not identifier:
            raise ValueError("artifactId is required")
        bounded_limit = max(1, min(int(limit), _MAX_INSPECTION_RECORDS))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_artifacts WHERE id = ?", (identifier,)
            ).fetchone()
        if row is None:
            raise KeyError(identifier)

        path = self._resolve_storage(str(row["storage_key"]))
        records = self._lifecycle_records_from_path(path)
        selected = records[-bounded_limit:]
        returned_reversed: list[dict[str, object]] = []
        output_bytes = 0
        for value in reversed(selected):
            record = _public_artifact_record(value)
            encoded = json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded) > _MAX_INSPECTION_RECORD_BYTES:
                record = {
                    "schemaVersion": "rag-ime.agent-artifact-record.v1",
                    "recordId": str(value.get("recordId") or "")[:240],
                    "eventType": str(value.get("eventType") or "")[:120],
                    "createdAtMs": max(0, int(value.get("createdAtMs") or 0)),
                    "payload": {
                        "omitted": True,
                        "reason": "record exceeds the public inspection limit",
                    },
                }
                encoded = json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            if returned_reversed and output_bytes + len(encoded) > _MAX_INSPECTION_BYTES:
                break
            returned_reversed.append(record)
            output_bytes += len(encoded)

        returned = list(reversed(returned_reversed))
        payload = {
            "schemaVersion": "rag-ime.agent-artifact-inspection.v1",
            "artifact": self.reference_by_id(identifier),
            "records": returned,
            "totalRecords": len(records),
            "returnedRecords": len(returned),
            "truncated": len(returned) < len(records),
            "limits": {
                "requestedRecords": bounded_limit,
                "maxRecords": _MAX_INSPECTION_RECORDS,
                "maxOutputBytes": _MAX_INSPECTION_BYTES,
            },
        }
        validate_contract(payload, "agent-artifact-inspection.v1.json")
        return payload

    def reference_by_id(self, artifact_id: str) -> dict[str, object]:
        identifier = str(artifact_id or "").strip()
        if not identifier:
            raise ValueError("artifactId is required")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_artifacts WHERE id = ?", (identifier,)
            ).fetchone()
            snapshot = conn.execute(
                "SELECT * FROM agent_artifact_snapshots WHERE artifact_id = ?",
                (identifier,),
            ).fetchone()
        if row is None:
            raise KeyError(identifier)
        return self._reference_payload(row, snapshot)

    def reference(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        artifact_kind: str = "lifecycle",
    ) -> dict[str, object]:
        owner = _owner(owner_kind, owner_id)
        kind = _bounded_identifier(artifact_kind, field="artifact kind")
        artifact_id = _artifact_id(owner[0], owner[1], kind)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            snapshot = conn.execute(
                "SELECT * FROM agent_artifact_snapshots WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return self._reference_payload(row, snapshot)

    @staticmethod
    def _reference_payload(
        row: sqlite3.Row,
        snapshot: sqlite3.Row | None,
    ) -> dict[str, object]:
        payload = {
            "schemaVersion": "rag-ime.agent-artifact-ref.v1",
            "artifactId": str(row["id"]),
            "ownerKind": str(row["owner_kind"]),
            "ownerId": str(row["owner_id"]),
            "kind": str(row["artifact_kind"]),
            "mediaType": str(row["media_type"]),
            "appendOnly": bool(row["append_only"]),
            "byteSize": int(row["byte_size"]),
            "sha256": str(row["sha256"]),
            "recordCount": int(row["record_count"]),
            "snapshotRevision": int(snapshot["revision"]) if snapshot is not None else 0,
            "snapshotSha256": str(snapshot["sha256"]) if snapshot is not None else "",
            "createdAtMs": int(row["created_at_ms"]),
            "updatedAtMs": max(
                int(row["updated_at_ms"]),
                int(snapshot["updated_at_ms"]) if snapshot is not None else 0,
            ),
        }
        validate_contract(payload, "agent-artifact-ref.v1.json")
        return payload

    def _lifecycle_records_from_path(self, path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        _assert_private_regular_file(path)
        if path.stat().st_size > _MAX_LIFECYCLE_BYTES:
            raise ValueError("artifact lifecycle exceeds the managed size limit")
        values: list[dict[str, object]] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"artifact lifecycle has invalid JSON at line {line_number}"
                ) from exc
            if not isinstance(item, dict):
                raise ValueError("artifact lifecycle contains a non-object record")
            values.append(item)
        return values

    def _refresh_lifecycle_metadata(self, artifact_id: str, path: Path) -> None:
        _assert_private_regular_file(path)
        blob = path.read_bytes()
        if len(blob) > _MAX_LIFECYCLE_BYTES:
            raise ValueError("artifact lifecycle exceeds the managed size limit")
        record_count = sum(1 for line in blob.splitlines() if line)
        now = _now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_artifacts
                SET byte_size = ?, sha256 = ?, record_count = ?, updated_at_ms = ?
                WHERE id = ?
                """,
                (len(blob), hashlib.sha256(blob).hexdigest() if blob else "", record_count, now, artifact_id),
            )

    def _storage_keys(self, owner_kind: str, owner_id: str, artifact_kind: str) -> tuple[str, str]:
        owner = _owner(owner_kind, owner_id)
        kind = _bounded_identifier(artifact_kind, field="artifact kind")
        digest = hashlib.sha256(f"{owner[0]}\0{owner[1]}".encode("utf-8")).hexdigest()
        directory = f"{owner[0]}/{digest[:32]}"
        return f"{directory}/{kind}.jsonl", f"{directory}/{kind}-snapshot.json"

    def _resolve_storage(self, storage_key: str) -> Path:
        path = (self.root / storage_key).resolve(strict=False)
        root = self.root.resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("artifact storage key escapes the managed root") from exc
        return path

    @staticmethod
    def _read_snapshot_path(path: Path) -> dict[str, object] | None:
        if not path.exists():
            return None
        _assert_private_regular_file(path)
        blob = path.read_bytes()
        if len(blob) > _MAX_SNAPSHOT_BYTES:
            raise ValueError("agent run snapshot exceeds the managed size limit")
        try:
            value = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise ValueError("agent run snapshot contains invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("agent run snapshot must be an object")
        return value

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _owner(owner_kind: object, owner_id: object) -> tuple[str, str]:
    kind = str(owner_kind or "").strip()
    identity = str(owner_id or "").strip()
    if kind not in _OWNER_KINDS:
        raise ValueError("unsupported agent artifact owner kind")
    if not identity or len(identity) > 240:
        raise ValueError("agent artifact owner id is invalid")
    return kind, identity


def _artifact_id(owner_kind: str, owner_id: str, artifact_kind: str) -> str:
    digest = hashlib.sha256(
        f"{owner_kind}\0{owner_id}\0{artifact_kind}".encode("utf-8")
    ).hexdigest()
    return f"artifact:{digest[:40]}"


def _bounded_identifier(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 80 or not all(
        character.isalnum() or character in "._-" for character in text
    ):
        raise ValueError(f"{field} is invalid")
    return text


def _bounded_media_type(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text or len(text) > 120 or "/" not in text:
        raise ValueError("artifact media type is invalid")
    return text


def _mapping_or_empty(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _merged_mapping(current: object, update: Mapping[str, object] | None) -> dict[str, object]:
    value = _mapping_or_empty(current)
    if update is not None:
        value.update(dict(update))
    return value


def _public_artifact_record(value: Mapping[str, object]) -> dict[str, object]:
    record: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-artifact-record.v1",
        "recordId": str(value.get("recordId") or "")[:240],
        "eventType": str(value.get("eventType") or "")[:120],
        "createdAtMs": _nonnegative_int(value.get("createdAtMs")),
        "payload": _public_artifact_value(value.get("payload"), depth=0),
    }
    if "sequence" in value:
        record["sequence"] = _nonnegative_int(value.get("sequence"))
    return record


def _public_artifact_value(value: object, *, depth: int) -> object:
    if depth >= 5:
        return "[inspection depth limit]"
    if isinstance(value, Mapping):
        public: dict[str, object] = {}
        for raw_key, item in list(value.items())[:80]:
            key = str(raw_key)[:120]
            if _secret_field(key):
                public[key] = "[redacted]"
                continue
            public[key] = _public_artifact_value(item, depth=depth + 1)
        return public
    if isinstance(value, (list, tuple)):
        return [
            _public_artifact_value(item, depth=depth + 1)
            for item in list(value)[:50]
        ]
    if isinstance(value, str):
        return value[:2_000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


def _secret_field(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    if any(
        token in normalized
        for token in (
            "apikey",
            "authorization",
            "cookie",
            "credential",
            "password",
            "secret",
        )
    ):
        return True
    return normalized in {
        "token",
        "accesstoken",
        "apitoken",
        "bearertoken",
        "refreshtoken",
        "sessiontoken",
    }


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _ensure_private_directory(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError("agent artifact directory must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("agent artifact directory is invalid")
    path.chmod(0o700)


def _ensure_private_file(path: Path) -> None:
    if path.exists():
        _assert_private_regular_file(path)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    os.close(descriptor)


def _assert_private_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("agent artifact file is invalid")
    if path.stat().st_mode & 0o077:
        raise ValueError("agent artifact file permissions are broader than 0600")


def _atomic_private_write(path: Path, blob: bytes) -> None:
    _ensure_private_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _now_ms() -> int:
    return int(time.time() * 1000)
