from __future__ import annotations

import re
from typing import Any, Mapping


ALLOWED = "allowed"
SENSITIVE = "sensitive"
UNKNOWN = "unknown"
SUPPORTED_DISPOSITIONS = frozenset({ALLOWED, SENSITIVE, UNKNOWN})
_PASSWORD_MANAGER_TOKENS = (
    "1password",
    "bitwarden",
    "dashlane",
    "enpass",
    "keepass",
    "keychain",
    "lastpass",
    "onepassword",
    "passwordmanager",
    "protonpass",
)
_BANKING_TOKENS = ("bank", "banking", "mobilebank", "netbank", "网银", "银行")
_PRIVATE_MODE_TOKENS = ("incognito", "inprivate", "privatebrowsing", "privatebrowser")
_BROWSER_TOKENS = ("browser", "chrome", "chromium", "edge", "firefox", "safari")
_CREDENTIAL_FIELD_KINDS = {
    "account",
    "account-name",
    "api-key",
    "credential",
    "current-password",
    "email",
    "login",
    "new-password",
    "one-time-code",
    "otp",
    "passcode",
    "password",
    "pin",
    "secret",
    "token",
    "user-name",
    "username",
}


def assess_foreground_write(payload: Mapping[str, Any]) -> dict[str, object]:
    foreground = payload.get("foregroundText")
    foreground_payload = foreground if isinstance(foreground, Mapping) else {}
    rime_context = payload.get("rimeContext")
    rime_payload = rime_context if isinstance(rime_context, Mapping) else {}
    if any(
        _truthy(value)
        for value in (
            payload.get("sensitiveField"),
            payload.get("secureInput"),
            payload.get("isPasswordField"),
            payload.get("credentialField"),
            foreground_payload.get("sensitiveField"),
            foreground_payload.get("secureInput"),
            foreground_payload.get("isPasswordField"),
            foreground_payload.get("credentialField"),
            rime_payload.get("sensitiveField"),
            rime_payload.get("secureInput"),
            rime_payload.get("isPasswordField"),
            rime_payload.get("credentialField"),
        )
    ) or _sensitive_field_metadata_detected(payload, foreground_payload, rime_payload):
        disposition = SENSITIVE
        reason = "sensitive_foreground_flag"
        source = "foreground_guard"
    elif _sensitive_app_detected(payload, foreground_payload, rime_payload):
        disposition = SENSITIVE
        reason = "sensitive_app_denylist"
        source = "backend_app_denylist"
    else:
        raw_disposition = payload.get("privacyDisposition")
        normalized = str(raw_disposition).strip().lower() if raw_disposition is not None else ""
        if normalized in SUPPORTED_DISPOSITIONS:
            disposition = normalized
            reason = f"explicit_{normalized}"
            source = "request"
        elif raw_disposition is None:
            disposition = UNKNOWN
            reason = "missing_privacy_disposition"
            source = "fail_closed_default"
        else:
            disposition = UNKNOWN
            reason = "invalid_privacy_disposition"
            source = "fail_closed_default"

    return {
        "schemaVersion": "rag-ime.foreground-privacy-assessment.v1",
        "disposition": disposition,
        "storeAllowed": disposition == ALLOWED,
        "reason": reason,
        "source": source,
    }


def storage_receipt(
    assessment: Mapping[str, object],
    *,
    stored: bool,
    event_id: str | int | None = None,
    outcome: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schemaVersion": "rag-ime.foreground-storage-receipt.v1",
        "outcome": outcome or ("stored" if stored else "no_store"),
        "stored": stored,
        "privacyDisposition": str(assessment.get("disposition") or UNKNOWN),
        "reason": reason
        or (
            "stored_with_explicit_consent"
            if stored
            else str(assessment.get("reason") or "privacy_not_allowed")
        ),
    }
    if stored and event_id not in (None, "", 0):
        receipt["eventId"] = event_id
    return receipt


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _sensitive_app_detected(
    payload: Mapping[str, Any],
    foreground_payload: Mapping[str, Any],
    rime_payload: Mapping[str, Any],
) -> bool:
    values = (
        payload.get("app"),
        payload.get("frontAppBundleId"),
        payload.get("frontmostApp"),
        payload.get("bundleId"),
        foreground_payload.get("app"),
        foreground_payload.get("frontAppBundleId"),
        foreground_payload.get("frontmostApp"),
        foreground_payload.get("bundleId"),
        rime_payload.get("app"),
        rime_payload.get("frontAppBundleId"),
        rime_payload.get("frontmostApp"),
        rime_payload.get("bundleId"),
    )
    for value in values:
        compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())
        if not compact:
            continue
        if any(token in compact for token in _PASSWORD_MANAGER_TOKENS):
            return True
        if any(token in compact for token in _BANKING_TOKENS):
            return True
        if any(token in compact for token in _PRIVATE_MODE_TOKENS):
            return True
        if "private" in compact and any(token in compact for token in _BROWSER_TOKENS):
            return True
    return False


def _sensitive_field_metadata_detected(
    *mappings: Mapping[str, Any],
) -> bool:
    for mapping in mappings:
        for key in ("fieldType", "inputPurpose", "autocomplete", "textContentType", "fieldRole"):
            value = str(mapping.get(key) or "").strip().lower().replace("_", "-")
            compact = re.sub(r"[^a-z0-9-]+", "", value)
            if compact in _CREDENTIAL_FIELD_KINDS:
                return True
            if "securetextfield" in compact or "password" in compact:
                return True
    return False
