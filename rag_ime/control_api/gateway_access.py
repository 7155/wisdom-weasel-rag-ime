from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from .errors import ControlApiError, ControlErrorCode
from .models import ControlAccessContext, ControlScope


TAILSCALE_LOGIN_HEADER = "Tailscale-User-Login"


@dataclass(frozen=True)
class GatewayAccessDecision:
    context: ControlAccessContext
    login: str = ""

    @property
    def is_remote(self) -> bool:
        return self.context.is_remote


def resolve_gateway_access(
    *,
    server_name: str,
    host_header: str,
    headers: Mapping[str, str],
    allowed_logins: str,
) -> GatewayAccessDecision:
    """Build remote authority only from Tailscale Serve's stripped identity header."""

    login = _login(headers.get(TAILSCALE_LOGIN_HEADER, ""))
    if server_name != "agent gateway":
        if login:
            raise _denied("Tailscale remote access is available only on the Agent Gateway")
        return GatewayAccessDecision(ControlAccessContext.loopback_web())

    if login:
        allowed = _allowed_logins(allowed_logins)
        if not allowed:
            raise _denied("Agent Gateway remote login allowlist is not configured")
        if login.casefold() not in allowed:
            raise _denied("Tailscale login is not allowed to use this Agent Gateway")
        device_id = "tailscale:" + hashlib.sha256(login.casefold().encode("utf-8")).hexdigest()[:20]
        return GatewayAccessDecision(
            ControlAccessContext.remote(
                device_id=device_id,
                scopes={scope.value for scope in ControlScope},
            ),
            login=login,
        )

    if _host_header_is_loopback(host_header):
        return GatewayAccessDecision(ControlAccessContext.loopback_web())

    raise _denied(
        "remote Agent Gateway requests must arrive through authenticated Tailscale Serve"
    )


def _allowed_logins(raw: str) -> frozenset[str]:
    result: set[str] = set()
    for value in str(raw or "").split(","):
        login = _login(value)
        if login:
            result.add(login.casefold())
    return frozenset(result)


def _login(value: object) -> str:
    text = str(value or "").strip()
    if (
        not text
        or len(text) > 320
        or any(ord(character) < 33 or ord(character) == 127 for character in text)
        or "," in text
    ):
        return ""
    return text


def _host_header_is_loopback(value: str) -> bool:
    host_header = str(value or "").strip()
    if not host_header:
        return False
    try:
        host = urlsplit(f"//{host_header}").hostname or ""
    except ValueError:
        return False
    normalized = host.rstrip(".").casefold()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _denied(message: str) -> ControlApiError:
    return ControlApiError(
        ControlErrorCode.SCOPE_REQUIRED,
        message,
        status=403,
    )
