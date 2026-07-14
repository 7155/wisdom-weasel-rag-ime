from __future__ import annotations

import ipaddress
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from urllib.parse import quote, urlencode, urlparse

from .errors import ControlApiError, ControlErrorCode
from .models import ControlAccessContext, ControlMethod, ControlRequest
from .route_policy import ControlRouteSpec


@dataclass(frozen=True)
class PreparedControlRequest:
    request_id: str
    path_id: str
    adapter_id: str
    method: ControlMethod
    url: str
    path: str
    query: Mapping[str, str] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    body: Mapping[str, object] = field(default_factory=dict)
    subscription: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", MappingProxyType(dict(self.query)))
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "body", MappingProxyType(deepcopy(dict(self.body))))


class ControlTargetAdapter:
    adapter_id = ""
    target_port = 0
    remote_capable = False

    def __init__(self, base_url: str) -> None:
        self.base_url = _validate_base_url(
            base_url,
            required_loopback=not self.remote_capable,
            expected_port=self.target_port if not self.remote_capable else None,
        )

    def prepare(
        self,
        route: ControlRouteSpec,
        request: ControlRequest,
        context: ControlAccessContext,
    ) -> PreparedControlRequest:
        if context.is_remote and not self.remote_capable:
            raise ControlApiError(
                ControlErrorCode.ROUTE_NOT_ALLOWED,
                "remote clients cannot connect to the local 8766 adapter",
                details={"pathId": route.path_id.value, "adapterId": self.adapter_id},
                status=403,
            )
        target = self._target(route)
        if target is None:
            raise ControlApiError(
                ControlErrorCode.ADAPTER_UNAVAILABLE,
                "control route is not available on this adapter",
                details={"pathId": route.path_id.value, "adapterId": self.adapter_id},
                status=503,
            )
        path = _render_path(target, request.params)
        query: dict[str, str] = {}
        headers: dict[str, str] = {"Accept": "text/event-stream" if route.subscription else "application/json"}
        for key, value in sorted(request.query.items()):
            if key == "lastEventId":
                headers["Last-Event-ID"] = str(value)
                continue
            query[key] = _query_value(value)
        query_string = urlencode(query)
        url = f"{self.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"
        return PreparedControlRequest(
            request_id=request.request_id,
            path_id=route.path_id.value,
            adapter_id=self.adapter_id,
            method=route.method,
            url=url,
            path=path,
            query=query,
            headers=headers,
            body=request.body,
            subscription=route.subscription,
        )

    def public_descriptor(self, *, wired: bool) -> dict[str, object]:
        return {
            "id": self.adapter_id,
            "targetPort": self.target_port,
            "remoteCapable": self.remote_capable,
            "wired": bool(wired),
        }

    def _target(self, route: ControlRouteSpec) -> str | None:
        raise NotImplementedError


class Local8766Adapter(ControlTargetAdapter):
    adapter_id = "local-8766"
    target_port = 8766
    remote_capable = False

    def __init__(self, base_url: str = "http://127.0.0.1:8766") -> None:
        super().__init__(base_url)

    def _target(self, route: ControlRouteSpec) -> str | None:
        return route.local_8766_path


class Gateway8768Adapter(ControlTargetAdapter):
    adapter_id = "gateway-8768"
    target_port = 8768
    remote_capable = True

    def __init__(self, base_url: str = "http://127.0.0.1:8768") -> None:
        super().__init__(base_url)

    def _target(self, route: ControlRouteSpec) -> str | None:
        return route.gateway_8768_path


def _validate_base_url(
    value: str,
    *,
    required_loopback: bool,
    expected_port: int | None,
) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("control adapter base URL must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("control adapter base URL cannot include credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("control adapter base URL cannot include a path")
    loopback = _is_loopback(parsed.hostname)
    if required_loopback and not loopback:
        raise ValueError("local 8766 adapter must use a loopback host")
    if expected_port is not None and parsed.port != expected_port:
        raise ValueError(f"control adapter must use port {expected_port}")
    if not loopback and parsed.scheme != "https":
        raise ValueError("non-loopback gateway adapters require https")
    return raw.rstrip("/")


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _render_path(template: str, params: Mapping[str, object]) -> str:
    path = template
    for key, value in params.items():
        path = path.replace(f"{{{key}}}", quote(str(value), safe=""))
    if "{" in path or "}" in path:
        raise ControlApiError(
            ControlErrorCode.INVALID_REQUEST,
            "control request is missing a path parameter",
        )
    return path


def _query_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
