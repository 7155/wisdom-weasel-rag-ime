"""Transport-neutral Control API policy and facades.

The package intentionally does not mount an HTTP server. A native bridge, the
current 8766 process, or the future 8768 gateway can wire the strict pathId
facade to an executor without giving UI code a generic URL or host escape
hatch. ``AgentKernelControlFacade`` remains the backend bootstrap facade for
the Agent Kernel itself.
"""

from .adapters import Gateway8768Adapter, Local8766Adapter, PreparedControlRequest
from .capabilities import (
    AgentCapabilityGateway,
    NativeCapabilityState,
    build_bootstrap,
    build_capabilities,
    capability_feature_flags,
    public_capability_catalog,
)
from .errors import ControlApiError, ControlErrorCode
from .facade import AgentKernelControlFacade, ControlApiFacade, ControlUpstreamExecutor
from .kernel import AgentControlKernel
from .models import (
    ControlAccessContext,
    ControlClientKind,
    ControlMethod,
    ControlRequest,
    ControlScope,
)
from .route_policy import (
    ControlPathId,
    ControlRoutePolicy,
    ControlRouteSpec,
    RouteId,
    control_route,
    control_route_catalog,
    default_route_policy,
    route_manifest,
)

__all__ = [
    "AgentCapabilityGateway",
    "AgentControlKernel",
    "AgentKernelControlFacade",
    "ControlAccessContext",
    "ControlApiError",
    "ControlApiFacade",
    "ControlClientKind",
    "ControlErrorCode",
    "ControlMethod",
    "ControlPathId",
    "ControlRequest",
    "ControlRoutePolicy",
    "ControlRouteSpec",
    "ControlScope",
    "ControlUpstreamExecutor",
    "Gateway8768Adapter",
    "Local8766Adapter",
    "NativeCapabilityState",
    "PreparedControlRequest",
    "RouteId",
    "build_bootstrap",
    "build_capabilities",
    "capability_feature_flags",
    "control_route",
    "control_route_catalog",
    "default_route_policy",
    "public_capability_catalog",
    "route_manifest",
]
