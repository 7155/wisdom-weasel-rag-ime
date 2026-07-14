from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from ..contracts.json_schema import validate_contract
from .adapters import ControlTargetAdapter, Local8766Adapter, PreparedControlRequest
from .capabilities import (
    AgentCapabilityGateway,
    NativeCapabilityState,
    build_bootstrap,
    build_capabilities,
    public_capability_catalog,
)
from .errors import ControlApiError, ControlErrorCode, error_response, success_response
from .kernel import AgentControlKernel
from .models import ControlAccessContext, ControlRequest
from .route_policy import (
    ControlPathId,
    ControlRoutePolicy,
    control_route_catalog,
    default_route_policy,
)


class ControlUpstreamExecutor(Protocol):
    """Return a successful decoded result or raise a sanitized ControlApiError."""

    def __call__(self, request: PreparedControlRequest) -> object: ...


class ControlApiFacade:
    """Validate a pathId request and dispatch it through one configured adapter.

    This class is intentionally HTTP-framework agnostic.  The 8766 handler,
    the future 8768 gateway, and the native bridge must each construct the
    access context from their trusted connection/authentication state before
    calling it.
    """

    def __init__(
        self,
        *,
        policy: ControlRoutePolicy | None = None,
        adapter: ControlTargetAdapter | None = None,
        executor: ControlUpstreamExecutor | None = None,
        native_capabilities: NativeCapabilityState | None = None,
        http_mounted: bool = False,
    ) -> None:
        self.policy = policy or default_route_policy()
        self.adapter = adapter or Local8766Adapter()
        self.executor = executor
        self.native_capabilities = native_capabilities or NativeCapabilityState()
        self.http_mounted = bool(http_mounted)

    def handle(
        self,
        payload: object,
        *,
        context: ControlAccessContext,
    ) -> dict[str, object]:
        request_id = _response_id(payload)
        try:
            request = _control_request(payload)
            request_id = request.request_id
            route = self.policy.authorize(request, context)
            if route.path_id is ControlPathId.CONTROL_BOOTSTRAP:
                return success_response(request_id, self.bootstrap(context=context))
            if route.path_id is ControlPathId.CONTROL_CAPABILITIES:
                return success_response(request_id, self.capabilities(context=context))
            if route.subscription:
                raise ControlApiError(
                    ControlErrorCode.SUBSCRIPTION_REQUIRED,
                    "subscription pathId must be opened through the subscription interface",
                    details={"pathId": route.path_id.value},
                )
            if self.executor is None:
                raise ControlApiError(
                    ControlErrorCode.ADAPTER_UNAVAILABLE,
                    "control adapter executor is not wired",
                    retryable=True,
                    details={"adapterId": self.adapter.adapter_id},
                    status=503,
                )
            prepared = self.adapter.prepare(route, request, context)
            try:
                result = self.executor(prepared)
            except ControlApiError:
                raise
            except Exception as exc:
                raise ControlApiError(
                    ControlErrorCode.UPSTREAM_ERROR,
                    "control upstream request failed",
                    retryable=True,
                    details={"pathId": route.path_id.value},
                    status=502,
                ) from exc
            return success_response(request_id, result)
        except ControlApiError as exc:
            return error_response(request_id, exc)
        except Exception:
            return error_response(
                request_id,
                ControlApiError(
                    ControlErrorCode.INTERNAL_ERROR,
                    "control request failed",
                    retryable=False,
                    status=500,
                ),
            )

    def prepare_request(
        self,
        payload: object,
        *,
        context: ControlAccessContext,
    ) -> PreparedControlRequest:
        request = _control_request(payload)
        route = self.policy.authorize(request, context)
        if route.facade_handler:
            raise ControlApiError(
                ControlErrorCode.INVALID_REQUEST,
                "facade pathId does not have an upstream target",
                details={"pathId": route.path_id.value},
            )
        if route.subscription:
            raise ControlApiError(
                ControlErrorCode.SUBSCRIPTION_REQUIRED,
                "subscription pathId must use prepare_subscription",
                details={"pathId": route.path_id.value},
            )
        return self.adapter.prepare(route, request, context)

    def prepare_subscription(
        self,
        payload: object,
        *,
        context: ControlAccessContext,
    ) -> PreparedControlRequest:
        request = _control_request(payload)
        route = self.policy.authorize(request, context)
        if not route.subscription:
            raise ControlApiError(
                ControlErrorCode.INVALID_REQUEST,
                "control pathId is not a subscription",
                details={"pathId": route.path_id.value},
            )
        return self.adapter.prepare(route, request, context)

    def capabilities(self, *, context: ControlAccessContext) -> dict[str, object]:
        return build_capabilities(
            policy=self.policy,
            context=context,
            adapter=self.adapter,
            adapter_wired=self.executor is not None,
            http_mounted=self.http_mounted,
            native=self.native_capabilities,
        )

    def bootstrap(self, *, context: ControlAccessContext) -> dict[str, object]:
        return build_bootstrap(
            policy=self.policy,
            context=context,
            adapter=self.adapter,
            adapter_wired=self.executor is not None,
            http_mounted=self.http_mounted,
            native=self.native_capabilities,
        )

    def route_manifest(self) -> list[dict[str, object]]:
        """Return the internal 8766/8768 mapping for host/gateway integration."""

        return self.policy.manifest(include_targets=True)


def _control_request(payload: object) -> ControlRequest:
    if isinstance(payload, ControlRequest):
        return payload
    if not isinstance(payload, Mapping):
        raise ControlApiError(
            ControlErrorCode.INVALID_REQUEST,
            "control request must be an object",
        )
    return ControlRequest.from_payload(payload)


def _response_id(payload: object) -> str:
    if isinstance(payload, ControlRequest):
        return payload.request_id
    value = payload.get("id") if isinstance(payload, Mapping) else ""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) > 128 or any(ord(char) < 32 for char in value):
        return ""
    return value


class AgentKernelControlFacade:
    """Frontend-neutral bootstrap over Agent Kernel and capability plugins."""

    def __init__(
        self,
        *,
        agent: AgentControlKernel,
        capabilities: AgentCapabilityGateway,
        platform_capabilities: Callable[[], Mapping[str, object]] | None = None,
    ) -> None:
        self.agent = agent
        self.capabilities = capabilities
        self.platform_capabilities = platform_capabilities or (lambda: {})

    def bootstrap(self) -> dict[str, object]:
        configuration_response = self.agent.configuration()
        configuration = configuration_response.get("configuration")
        if not isinstance(configuration, Mapping):
            raise ValueError("Agent Kernel returned an invalid configuration snapshot")
        runtime = self.agent.runtime_status()
        payload = {
            "schemaVersion": "rag-ime.agent-control-bootstrap.v1",
            "apiVersion": "control-api.v1",
            "configuration": dict(configuration),
            "runtime": _public_runtime(runtime),
            "capabilities": public_capability_catalog(self.capabilities),
            "platform": dict(self.platform_capabilities()),
            "routes": control_route_catalog(),
        }
        validate_contract(payload, "agent-control-bootstrap.v1.json")
        return payload


def _public_runtime(runtime: Mapping[str, object]) -> dict[str, object]:
    allowed = (
        "schemaVersion",
        "enabled",
        "managed",
        "status",
        "driverId",
        "runtimeKind",
        "runtimeVersion",
        "piVersion",
        "idleTimeoutSeconds",
        "activeSessionId",
        "capabilities",
        "configurationRevision",
        "configurationSyncState",
    )
    return {key: runtime.get(key) for key in allowed if key in runtime}
