from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


MISSING_WORKSPACE_ROOT_ERROR = (
    "workspaceRoots contains a directory that no longer exists"
)
TRACE_BINDING_REQUIRED_ERROR = (
    "binding_required: Trace diagnostic and repair Sessions require an "
    "authoritative project workspace binding"
)
TRACE_AGENT_OWNER_APP_ID = "extension:trace-agent"
TRACE_AGENT_PROJECT_SURFACE_KEYS = frozenset({"diagnostic", "repair"})


def existing_workspace_roots(
    values: Iterable[object],
    *,
    maximum: int = 4,
) -> tuple[str, ...]:
    """Resolve authorized workspace directories before durable objects exist.

    A Session or Room whose workspace already disappeared cannot ever reach Pi.
    Reject it at the lifecycle boundary instead of persisting a ghost object
    that fails later on model discovery, snapshot restore, and prompt delivery.
    """

    roots: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        try:
            path = Path(raw).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(MISSING_WORKSPACE_ROOT_ERROR) from exc
        if not path.is_dir():
            raise ValueError(MISSING_WORKSPACE_ROOT_ERROR)
        normalized = str(path)
        if normalized not in roots:
            roots.append(normalized)
    if len(roots) > maximum:
        raise ValueError(
            f"workspaceRoots accepts at most {maximum} directories"
        )
    return tuple(roots)


def system_wide_workspace_roots(values: Iterable[object]) -> tuple[str, ...]:
    """Keep optional project context first and make system access explicit."""

    roots: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        normalized = str(Path(raw).expanduser().resolve(strict=False))
        if normalized not in roots:
            roots.append(normalized)
    if "/" not in roots:
        roots.append("/")
    return tuple(roots)


def is_trace_project_bound_surface(
    surface_kind: object,
    owner_app_id: object,
    surface_key: object,
) -> bool:
    """Identify Trace-owned Sessions whose persisted roots are project identity.

    Full-trust Tool access is projected at execution time.  These durable roots
    therefore remain the exact source-project binding and must never be widened
    to ``/`` by the generic unrestricted Session policy.
    """

    return (
        str(surface_kind or "").strip() == "extension_app"
        and str(owner_app_id or "").strip() == TRACE_AGENT_OWNER_APP_ID
        and str(surface_key or "").strip() in TRACE_AGENT_PROJECT_SURFACE_KEYS
    )


def exact_trace_project_workspace_roots(
    values: Iterable[object],
) -> tuple[str, ...]:
    """Validate an explicit, non-system Trace project binding."""

    raw_roots = [str(value or "").strip() for value in values]
    if not raw_roots or any(root == "/" for root in raw_roots):
        raise ValueError(TRACE_BINDING_REQUIRED_ERROR)
    roots = existing_workspace_roots(raw_roots)
    if not roots:
        raise ValueError(TRACE_BINDING_REQUIRED_ERROR)
    return roots
