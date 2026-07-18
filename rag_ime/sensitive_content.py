from __future__ import annotations

import re


_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[_-])"
    r"(password|passwd|secret|authorization|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token)"
    r"(?:$|[_-])",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]{8,}|sk-[a-z0-9_-]{8,}|"
    r"(?:password|secret|api[_ -]?key|(?:access[_ -]?)?token)"
    r"\s*[:=：]\s*\S+)",
    re.IGNORECASE,
)
_PRIVATE_KEY_HEADER_RE = re.compile(
    r"-----BEGIN [^-\r\n]{0,80}PRIVATE KEY(?: BLOCK)?-----",
    re.IGNORECASE,
)
_LOCAL_USER_PATH_RE = re.compile(
    r"(?:"
    r"(?<![A-Za-z0-9])~[/\\]|"
    r"(?<![A-Za-z0-9])/(?:Users|Volumes|Applications|Library|System|private|"
    r"tmp|home|root|etc|opt|srv|data|mnt|media|var|usr)(?:[/\\]|$)|"
    r"\b[A-Za-z]:\\(?:Users|Documents and Settings|ProgramData|Windows|Temp)"
    r"(?:\\|$)"
    r")",
    re.IGNORECASE,
)
_PERSONAL_IDENTIFIER_RE = re.compile(
    r"(?:\b1[3-9]\d{9}\b|\b\d{17}[\dXx]\b|"
    r"(?:验证码|verification code)\s*[:=：]?\s*\d{4,8}|"
    r"(?:家庭|收货|居住)地址\s*[:=：]\s*\S{4,})",
    re.IGNORECASE,
)


def is_sensitive_mapping_key(value: object) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(str(value or "")))


def contains_sensitive_content(value: object) -> bool:
    text = str(value or "")
    if not text:
        return False
    return bool(
        _SECRET_VALUE_RE.search(text)
        or _PRIVATE_KEY_HEADER_RE.search(text)
        or _LOCAL_USER_PATH_RE.search(text)
        or _PERSONAL_IDENTIFIER_RE.search(text)
    )


def redact_sensitive_text(value: object) -> str:
    text = str(value or "")
    return "[REDACTED]" if contains_sensitive_content(text) else text
