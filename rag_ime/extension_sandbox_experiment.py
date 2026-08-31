"""Local Extension App boundary for one explicit sandbox experiment decision.

The App chooses only ``run`` or ``skip``.  PAW re-reads the durable Session and
the managed Pi Package inventory, derives the registered suite, and delegates
execution to the existing Host-owned sandbox Connector.  No caller-controlled
command, path, network, or write policy crosses this boundary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from http import HTTPStatus
from typing import Protocol


RECEIPT_SCHEMA_VERSION = "rag-ime.extension-sandbox-experiment-receipt.v1"
CONNECTOR_PACKAGE_ID = "vertical-agent-sandbox"
POLICY_ID = "vertical-readonly-v1"
_REQUEST_FIELDS = frozenset(
    {
        "sessionId",
        "ownerAppId",
        "experimentId",
        "candidateBindingSha256",
        "requestedDecision",
    }
)
_OWNER_APP_ID = re.compile(r"extension:[a-z0-9][a-z0-9-]{0,63}\Z")
_EXPERIMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class _Sessions(Protocol):
    def get(self, session_id: str) -> Mapping[str, object]: ...


class _Extensions(Protocol):
    def list(self) -> Mapping[str, object]: ...


class _Connector(Protocol):
    def execute(
        self,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class ExtensionSandboxExperimentError(ValueError):
    """Stable public failure for the local experiment route."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: HTTPStatus = HTTPStatus.BAD_REQUEST,
    ) -> None:
        self.error_code = str(code)
        self.http_status = status
        super().__init__(message)

    def response_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.extension-sandbox-experiment-error.v1",
            "ok": False,
            "errorCode": self.error_code,
        }


class ExtensionSandboxExperimentService:
    """Validate App ownership and execute one Host-managed sandbox run."""

    def __init__(
        self,
        *,
        sessions: _Sessions,
        extensions: _Extensions,
        connector: _Connector | None,
    ) -> None:
        self.sessions = sessions
        self.extensions = extensions
        self.connector = connector

    def execute(self, payload: Mapping[str, object]) -> dict[str, object]:
        request = _request(payload)
        try:
            session = self.sessions.get(request["sessionId"])
        except KeyError as exc:
            raise ExtensionSandboxExperimentError(
                "session_not_found",
                "Extension App Session was not found",
                status=HTTPStatus.NOT_FOUND,
            ) from exc
        if (
            str(session.get("surfaceKind") or "") != "extension_app"
            or str(session.get("ownerAppId") or "") != request["ownerAppId"]
        ):
            raise ExtensionSandboxExperimentError(
                "session_owner_mismatch",
                "Extension App Session owner does not match the experiment owner",
                status=HTTPStatus.CONFLICT,
            )

        inventory = self.extensions.list()
        if inventory.get("runtimeAvailable") is False:
            raise ExtensionSandboxExperimentError(
                "extension_runtime_unavailable",
                "Installed Extension App evidence is unavailable",
                status=HTTPStatus.CONFLICT,
            )
        items = inventory.get("items")
        if not isinstance(items, list):
            raise ExtensionSandboxExperimentError(
                "extension_inventory_invalid",
                "Installed Extension App inventory is invalid",
                status=HTTPStatus.CONFLICT,
            )
        app_item, app_evidence = _installed_app(items, request["ownerAppId"])
        binding_sha256 = _required_evidence_text(
            app_evidence,
            "bindingSha256",
            code="extension_binding_missing",
        )
        if binding_sha256 != request["candidateBindingSha256"]:
            raise ExtensionSandboxExperimentError(
                "candidate_binding_mismatch",
                "Candidate binding does not match the installed Extension App",
                status=HTTPStatus.CONFLICT,
            )
        suite_id = _required_evidence_text(
            app_evidence,
            "verticalSuiteId",
            code="extension_suite_missing",
        )
        suite_revision = _required_evidence_text(
            app_evidence,
            "verticalSuiteRevision",
            code="extension_suite_missing",
        )
        base: dict[str, object] = {
            "schemaVersion": RECEIPT_SCHEMA_VERSION,
            "ok": True,
            "sessionId": request["sessionId"],
            "ownerAppId": request["ownerAppId"],
            "experimentId": request["experimentId"],
            "candidateBindingSha256": binding_sha256,
            "requestedDecision": request["requestedDecision"],
            "appPackageId": _required_evidence_text(
                app_evidence,
                "packageId",
                fallback=app_item.get("id"),
                code="extension_package_missing",
            ),
            "appVersion": _required_evidence_text(
                app_evidence,
                "version",
                fallback=app_item.get("version"),
                code="extension_version_missing",
            ),
            "suiteId": suite_id,
            "suiteRevision": suite_revision,
            "connectorPackageId": CONNECTOR_PACKAGE_ID,
            "policyId": POLICY_ID,
        }
        if request["requestedDecision"] == "skip":
            return {
                **base,
                "executionStatus": "skipped",
                "executed": False,
                "connectorVersion": "",
            }

        connector_item = _enabled_package(items, CONNECTOR_PACKAGE_ID)
        if connector_item is None or self.connector is None:
            raise ExtensionSandboxExperimentError(
                "sandbox_connector_unavailable",
                "Vertical Agent Sandbox Connector is not installed and enabled",
                status=HTTPStatus.CONFLICT,
            )
        try:
            result = self.connector.execute(
                request["sessionId"],
                "run",
                {"suiteId": suite_id, "suiteRevision": suite_revision},
            )
        except Exception as exc:
            raise ExtensionSandboxExperimentError(
                "sandbox_execution_failed",
                "Vertical Agent Sandbox Connector execution failed",
                status=HTTPStatus.BAD_GATEWAY,
            ) from exc
        if not isinstance(result, Mapping):
            raise ExtensionSandboxExperimentError(
                "sandbox_receipt_incomplete",
                "Vertical Agent Sandbox Connector returned an invalid receipt",
                status=HTTPStatus.BAD_GATEWAY,
            )
        identifiers = {
            key: _required_result_text(result, key)
            for key in ("sandboxRunId", "traceId", "evalRunId")
        }
        return {
            **base,
            "executionStatus": "completed",
            "executed": True,
            "connectorVersion": _required_evidence_text(
                connector_item,
                "version",
                code="sandbox_connector_version_missing",
            ),
            **identifiers,
        }


def _request(payload: Mapping[str, object]) -> dict[str, str]:
    unknown = sorted(str(key) for key in set(payload) - _REQUEST_FIELDS)
    missing = sorted(key for key in _REQUEST_FIELDS if key not in payload)
    if unknown or missing:
        detail = ", ".join([*(f"unknown:{key}" for key in unknown), *(f"missing:{key}" for key in missing)])
        raise ExtensionSandboxExperimentError(
            "invalid_request",
            f"Extension sandbox experiment request fields are invalid ({detail})",
        )
    session_id = _text(payload.get("sessionId"), maximum=240)
    owner_app_id = _text(payload.get("ownerAppId"), maximum=80)
    experiment_id = _text(payload.get("experimentId"), maximum=160)
    candidate_binding = _text(payload.get("candidateBindingSha256"), maximum=64)
    decision = _text(payload.get("requestedDecision"), maximum=8)
    if not session_id:
        raise ExtensionSandboxExperimentError("invalid_session_id", "sessionId is invalid")
    if _OWNER_APP_ID.fullmatch(owner_app_id) is None:
        raise ExtensionSandboxExperimentError("invalid_owner_app_id", "ownerAppId is invalid")
    if _EXPERIMENT_ID.fullmatch(experiment_id) is None:
        raise ExtensionSandboxExperimentError("invalid_experiment_id", "experimentId is invalid")
    if _SHA256.fullmatch(candidate_binding) is None:
        raise ExtensionSandboxExperimentError(
            "invalid_candidate_binding",
            "candidateBindingSha256 is invalid",
        )
    if decision not in {"run", "skip"}:
        raise ExtensionSandboxExperimentError(
            "invalid_requested_decision",
            "requestedDecision must be run or skip",
        )
    return {
        "sessionId": session_id,
        "ownerAppId": owner_app_id,
        "experimentId": experiment_id,
        "candidateBindingSha256": candidate_binding,
        "requestedDecision": decision,
    }


def _installed_app(
    items: list[object],
    owner_app_id: str,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    for candidate in items:
        if (
            not isinstance(candidate, Mapping)
            or candidate.get("installed") is not True
            or candidate.get("enabled") is not True
        ):
            continue
        evidence = candidate.get("extensionApp")
        if isinstance(evidence, Mapping) and str(evidence.get("id") or "") == owner_app_id:
            return candidate, evidence
    raise ExtensionSandboxExperimentError(
        "extension_app_unavailable",
        "Extension App is not installed and enabled",
        status=HTTPStatus.CONFLICT,
    )


def _enabled_package(
    items: list[object],
    package_id: str,
) -> Mapping[str, object] | None:
    return next(
        (
            item
            for item in items
            if isinstance(item, Mapping)
            and str(item.get("id") or "") == package_id
            and item.get("installed") is True
            and item.get("enabled") is True
        ),
        None,
    )


def _required_evidence_text(
    evidence: Mapping[str, object],
    key: str,
    *,
    fallback: object = "",
    code: str,
) -> str:
    value = str(evidence.get(key) or fallback or "").strip()
    if not value:
        raise ExtensionSandboxExperimentError(
            code,
            f"Installed Extension App evidence has no {key}",
            status=HTTPStatus.CONFLICT,
        )
    return value


def _required_result_text(result: Mapping[str, object], key: str) -> str:
    value = str(result.get(key) or "").strip()
    if not value:
        raise ExtensionSandboxExperimentError(
            "sandbox_receipt_incomplete",
            f"Sandbox Connector returned no {key}",
            status=HTTPStatus.BAD_GATEWAY,
        )
    return value


def _text(value: object, *, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text) > maximum or any(ord(character) < 32 for character in text):
        return ""
    return text
