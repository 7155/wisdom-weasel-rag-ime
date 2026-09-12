"""No-store decisions and redaction BEFORE hashing, journaling or indexing."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

MAX_TEXT = 64_000
MAX_JSON_BYTES = 128 * 1024
REDACTED = "[REDACTED]"
_DEFAULT_EXCLUDED = frozenset({"password_manager", "private_message", "credential", "raw_screenshot"})
_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|AKIA[A-Z0-9]{16})\b"),
    re.compile(r'''(?i)(?:["']?)(?:password|passwd|secret|api[_-]?key|(?:access|refresh|id)[_-]?token|token|signature|x-amz-signature|authorization|cookie|密码|验证码)["']?\s*[:=：]\s*(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;&<>]+)'''),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"(?<!\w)(?:\+?86[ -]?)?1[3-9]\d{9}(?!\w)"),
    re.compile(r"(?<!\w)(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\w)"),
    re.compile(r"(?<!\w)\d{3}-\d{2}-\d{4}(?!\w)"),
    re.compile(r"(?<!\w)\d{17}[0-9Xx](?!\w)"),
)
_PRIVATE_FLAGS = ("privateWindow", "isPrivateWindow", "isIncognito", "incognito", "privateCommunication", "sessionOnly", "onlyThisTime")
_METADATA_CONTAINERS = ("privacy", "memoryPrivacy", "captureMetadata", "metadata", "provenance")
_NO_STORE_TAGS = frozenset({"session-only", "memory:session-only", "not-for-memory", "private-window", "only-this-time"})


class PrivacyInputError(ValueError):
    """Invalid input; messages deliberately contain no source content."""


@dataclass(frozen=True)
class CapturePolicy:
    excluded_sources: frozenset[str] = _DEFAULT_EXCLUDED
    redact: bool = True
    revision: str = "memory-ingress-v1"

    @classmethod
    def from_environment(cls) -> CapturePolicy:
        """Optional process-local JSON configuration; malformed config fails closed."""
        raw = os.environ.get("PAW_MEMORY_INGRESS_POLICY", "{}")
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            raise PrivacyInputError("invalid_memory_ingress_policy") from None
        if not isinstance(value, dict) or set(value) - {"excludedSources", "redact", "revision"}:
            raise PrivacyInputError("invalid_memory_ingress_policy")
        sources = value.get("excludedSources", [])
        if not isinstance(sources, list) or len(sources) > 128 or any(not isinstance(x, str) or len(x) > 160 for x in sources):
            raise PrivacyInputError("invalid_excluded_sources")
        redact = value.get("redact", True)
        revision = value.get("revision", "memory-ingress-v1")
        if type(redact) is not bool or not isinstance(revision, str) or not 1 <= len(revision) <= 80:
            raise PrivacyInputError("invalid_memory_ingress_policy")
        return cls(_DEFAULT_EXCLUDED | frozenset(x.strip().lower() for x in sources), redact, revision)


@dataclass(frozen=True)
class CaptureDecision:
    allowed: bool
    reason: str
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    redacted: bool = False
    policy_revision: str = "memory-ingress-v1"

    def receipt(self) -> dict[str, object]:
        # A denial receipt contains no text, source id, URL or content hash.
        return {"stored": False, "reason": self.reason, "redacted": self.redacted, "policyRevision": self.policy_revision}


def redact_text(text: str) -> str:
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise PrivacyInputError("invalid_or_oversized_text")
    result = text
    for pattern in _PATTERNS:
        result = pattern.sub(REDACTED, result)
    # Card-shaped numeric strings are only redacted when their Luhn check passes.
    def card(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group())
        if not 13 <= len(digits) <= 19:
            return match.group()
        numbers = [int(x) for x in digits[::-1]]
        total = sum((n * 2 - 9 if n * 2 > 9 else n * 2) if i % 2 else n for i, n in enumerate(numbers))
        return REDACTED if total % 10 == 0 else match.group()
    return re.sub(r"(?<!\w)(?:\d[ -]?){12,18}\d(?!\w)", card, result)


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", key.lower())
    return normalized in {
        "password", "passwd", "secret", "token", "apikey", "apitoken", "idtoken", "jwt",
        "authorization", "proxyauthorization", "cookie", "setcookie", "email", "emailaddress",
        "phone", "phonenumber", "mobile", "ssn", "身份证", "密码", "手机号", "验证码",
    } or normalized.endswith(("password", "secretkey", "privatekey", "apikey", "accesstoken", "refreshtoken", "bearertoken", "sessioncookie"))


def sanitize_json(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 12:
        raise PrivacyInputError("metadata_too_deep")
    if isinstance(value, Mapping):
        if len(value) > 512 or any(not isinstance(k, str) or len(k) > 240 for k in value):
            raise PrivacyInputError("invalid_metadata_keys")
        return {redact_text(k): REDACTED if _sensitive_key(k) else sanitize_json(v, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 2_000:
            raise PrivacyInputError("metadata_list_too_large")
        return [sanitize_json(v, _depth=_depth + 1) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or type(value) in {int, float, bool}:
        try:
            json.dumps(value, allow_nan=False)
        except ValueError:
            raise PrivacyInputError("invalid_metadata_number") from None
        return value
    raise PrivacyInputError("metadata_is_not_json")


def _denial(metadata: Mapping[str, Any], *, depth: int = 0) -> str:
    if depth > 8:
        return "invalid_privacy_metadata"
    for key in _PRIVATE_FLAGS:
        if key in metadata:
            if type(metadata[key]) is not bool:
                return "invalid_privacy_signal"
            if metadata[key]:
                return "session_only" if key in {"sessionOnly", "onlyThisTime"} else "private_context"
    if "memoryAllowed" in metadata and metadata["memoryAllowed"] is not True:
        return "memory_not_allowed"
    if "memoryRetention" in metadata:
        if not isinstance(metadata["memoryRetention"], str):
            return "invalid_retention"
        if metadata["memoryRetention"] in {"session_only", "none", "only_this_time"}:
            return "session_only"
        if metadata["memoryRetention"] != "durable":
            return "invalid_retention"
    if metadata.get("derivedArtifactType") == "daily_memory_report":
        return "generated_report_not_evidence"
    for key in _METADATA_CONTAINERS:
        if key in metadata:
            child = metadata[key]
            if not isinstance(child, Mapping):
                return "invalid_privacy_metadata"
            reason = _denial(child, depth=depth + 1)
            if reason:
                return reason
    return ""


def assess_capture(*, source: str, text: str, metadata: Mapping[str, Any] | None = None,
                   tags: tuple[str, ...] = (), disposition: str = "allowed",
                   policy: CapturePolicy | None = None) -> CaptureDecision:
    policy = policy or CapturePolicy.from_environment()
    if not isinstance(source, str):
        raise PrivacyInputError("invalid_source_type")
    if disposition != "allowed":
        return CaptureDecision(False, "privacy_" + disposition if disposition in {"sensitive", "unknown"} else "privacy_not_allowed", policy_revision=policy.revision)
    if source.strip().lower() in policy.excluded_sources:
        return CaptureDecision(False, "excluded_source_type", policy_revision=policy.revision)
    if _NO_STORE_TAGS.intersection(tags):
        return CaptureDecision(False, "session_only", policy_revision=policy.revision)
    data = dict(metadata or {})
    reason = _denial(data)
    if reason:
        return CaptureDecision(False, reason, policy_revision=policy.revision)
    if not isinstance(text, str) or not text.strip():
        raise PrivacyInputError("empty_capture")
    safe_text = redact_text(text)
    safe_data = sanitize_json(data)
    if len(json.dumps(safe_data, ensure_ascii=False, allow_nan=False).encode()) > MAX_JSON_BYTES:
        raise PrivacyInputError("metadata_too_large")
    changed = safe_text != text or safe_data != data
    if changed and not policy.redact:
        return CaptureDecision(False, "sensitive_content", policy_revision=policy.revision)
    return CaptureDecision(True, "redacted" if changed else "allowed", safe_text, safe_data, changed, policy.revision)
