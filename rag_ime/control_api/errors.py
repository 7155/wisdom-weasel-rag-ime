from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class ControlErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    ROUTE_NOT_FOUND = "route_not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    ROUTE_NOT_ALLOWED = "route_not_allowed"
    SCOPE_REQUIRED = "scope_required"
    ADAPTER_UNAVAILABLE = "adapter_unavailable"
    SUBSCRIPTION_REQUIRED = "subscription_required"
    UPSTREAM_ERROR = "upstream_error"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class ControlApiError(Exception):
    code: ControlErrorCode
    message: str
    retryable: bool = False
    details: Mapping[str, object] = field(default_factory=dict)
    status: int = 400

    def __str__(self) -> str:
        return self.message

    def payload(self) -> dict[str, object]:
        error: dict[str, object] = {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            error["details"] = dict(self.details)
        return error


def error_response(request_id: str, error: ControlApiError) -> dict[str, object]:
    return {"id": request_id, "ok": False, "error": error.payload()}


def success_response(request_id: str, result: object) -> dict[str, object]:
    return {"id": request_id, "ok": True, "result": result}
