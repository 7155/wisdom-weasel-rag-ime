from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MANAGEMENT_SCHEMA_VERSION = "rag-ime.management.v1"


@dataclass(frozen=True)
class ManagementRevision:
    settings_revision: str
    runtime_revision: int
    audit_id: int | None = None

    def payload(self) -> dict[str, object]:
        result: dict[str, object] = {
            "schemaVersion": MANAGEMENT_SCHEMA_VERSION,
            "settingsRevision": self.settings_revision,
            "runtimeRevision": self.runtime_revision,
        }
        if self.audit_id is not None:
            result["auditId"] = self.audit_id
        return result


@dataclass
class RuntimeJob:
    job_id: str
    action: str
    status: str = "queued"
    created_at_ms: int = 0
    started_at_ms: int = 0
    finished_at_ms: int = 0
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def payload(self) -> dict[str, object]:
        return {
            "jobId": self.job_id,
            "action": self.action,
            "status": self.status,
            "createdAtMs": self.created_at_ms,
            "startedAtMs": self.started_at_ms,
            "finishedAtMs": self.finished_at_ms,
            "result": self.result,
            "error": self.error,
        }


@dataclass(frozen=True)
class PageRequest:
    limit: int = 50
    cursor: str = ""
    query: str = ""
    status: str = ""
    kind: str = ""
    visible_owners: tuple[tuple[str, str], ...] = ()
    project: str = ""
