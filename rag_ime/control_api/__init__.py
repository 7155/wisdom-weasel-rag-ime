"""Transport-neutral Control API policy and facade.

The package intentionally does not mount an HTTP server.  A native bridge,
the current 8766 process, or the future 8768 gateway can wire the facade to an
executor without giving UI code a generic URL or host escape hatch.
"""

from .adapters import Gateway8768Adapter, Local8766Adapter, PreparedControlRequest
from .capabilities import NativeCapabilityState, build_bootstrap, build_capabilities
from .errors import ControlApiError, ControlErrorCode
from .facade import ControlApiFacade, ControlUpstreamExecutor
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
    default_route_policy,
    route_manifest,
)

__all__ = [
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
    "default_route_policy",
    "route_manifest",
]
