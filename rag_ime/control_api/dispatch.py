"""Dispatch one declared Control API route.

The HTTP handler owns transport concerns: authentication, streaming and
writing bytes.  This module owns the descriptor seam: resolving the
application handler, building its arguments, validating contracts and
projecting the declared status.  Keeping that sequence here makes the route
table the interface and gives tests a transport-free surface.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from ..contracts.json_schema import validate_contract
from .route_table import RouteDescriptor, build_arguments


@dataclass(frozen=True)
class DispatchResult:
    """The application result and status declared by one route."""

    status: HTTPStatus
    payload: dict[str, object]


class DescriptorRouteDispatcher:
    """Run a route descriptor against one application service.

    The dispatcher has no HTTP server dependency. The caller adapts the
    returned result to HTTP bytes, while the route's implementation and
    contract rules stay in one deep module.
    """

    def __init__(
        self,
        service: Any,
        *,
        query_first: Callable[[Mapping[str, list[str]], str], str],
    ) -> None:
        self._service = service
        self._query_first = query_first

    def dispatch(
        self,
        route: RouteDescriptor,
        *,
        payload: dict[str, object] | None = None,
        query: dict[str, list[str]] | None = None,
    ) -> DispatchResult:
        """Resolve, validate and call one declared route."""

        target = self._service
        for part in route.handler.split("."):
            target = getattr(target, part)
        handler = target
        if route.contract:
            validate_contract(payload or {}, route.contract)

        if route.takes_arguments:
            arguments = build_arguments(
                route,
                payload=payload,
                query_first=lambda name: self._query_first(query or {}, name),
            )
            response = handler(arguments, **dict(route.payload_args))
        else:
            response = handler(**dict(route.payload_args))
        if route.response_contract:
            validate_contract(response, route.response_contract)
        return DispatchResult(status=HTTPStatus(route.status), payload=response)
