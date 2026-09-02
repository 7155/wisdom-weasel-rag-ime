from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


MISSING_WORKSPACE_ROOT_ERROR = (
    "workspaceRoots contains a directory that no longer exists"
)


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
