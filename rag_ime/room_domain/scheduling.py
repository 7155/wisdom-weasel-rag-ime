from __future__ import annotations

from collections.abc import Mapping, Sequence

from .model import DomainPolicyError


def dependency_ids(payload: Mapping[str, object]) -> list[str]:
    raw = payload.get("dependsOnDispatchIds")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DomainPolicyError("dependsOnDispatchIds must be an array")
    values = [str(value).strip() for value in raw]
    dispatch_id = str(payload.get("dispatchId") or "").strip()
    if (
        any(not value for value in values)
        or len(values) != len(set(values))
        or bool(dispatch_id and dispatch_id in values)
    ):
        raise DomainPolicyError("dependsOnDispatchIds contains an invalid identity")
    return values


def validate_task_graph(graph: Mapping[str, Sequence[str]]) -> None:
    task_ids = set(graph)
    for task_id, dependencies in graph.items():
        if not task_id:
            raise DomainPolicyError("task identity is empty")
        values = [str(value).strip() for value in dependencies]
        if len(values) != len(set(values)) or any(not value for value in values):
            raise DomainPolicyError("task dependencies contain an invalid identity")
        if task_id in values:
            raise DomainPolicyError("task cannot depend on itself")
        missing = set(values) - task_ids
        if missing:
            raise DomainPolicyError("task dependency target is missing")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise DomainPolicyError("task dependency graph contains a cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency_id in graph[task_id]:
            visit(str(dependency_id))
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(graph):
        visit(task_id)


def runnable_frontier(
    graph: Mapping[str, Sequence[str]],
    *,
    completed: set[str],
    active: set[str] | None = None,
) -> list[str]:
    validate_task_graph(graph)
    active_ids = set(active or ())
    return [
        task_id
        for task_id in sorted(graph)
        if task_id not in completed
        and task_id not in active_ids
        and all(str(value) in completed for value in graph[task_id])
    ]


def dependent_closure(
    graph: Mapping[str, Sequence[str]],
    *,
    affected: set[str],
) -> list[str]:
    """Return affected Tasks plus every Task that transitively depends on them."""

    validate_task_graph(graph)
    unknown = set(affected) - set(graph)
    if unknown:
        raise DomainPolicyError("affected Task is outside the approved graph")
    closure = set(affected)
    changed = True
    while changed:
        changed = False
        for task_id, dependencies in graph.items():
            if task_id not in closure and closure.intersection(dependencies):
                closure.add(task_id)
                changed = True
    return sorted(closure)


def derived_task_waves(
    graph: Mapping[str, Sequence[str]],
) -> dict[str, int]:
    """Project stable waves from the dependency authority; never trust prose."""

    validate_task_graph(graph)
    completed: set[str] = set()
    waves: dict[str, int] = {}
    wave = 1
    while len(completed) < len(graph):
        ready = runnable_frontier(graph, completed=completed)
        if not ready:
            raise DomainPolicyError("task dependency graph cannot advance")
        for task_id in ready:
            waves[task_id] = wave
        completed.update(ready)
        wave += 1
    return waves


def payload_depends_on(
    payload: Mapping[str, object],
    target_dispatch_id: str,
    *,
    dispatches_by_id: Mapping[str, Mapping[str, object]],
    visited: set[str] | None = None,
) -> bool:
    seen = set(visited or ())
    dispatch_id = str(payload.get("dispatchId") or "")
    if dispatch_id in seen:
        return False
    seen.add(dispatch_id)
    for dependency_id in dependency_ids(payload):
        if dependency_id == target_dispatch_id:
            return True
        dependency = dispatches_by_id.get(dependency_id)
        if dependency is not None and payload_depends_on(
            dependency,
            target_dispatch_id,
            dispatches_by_id=dispatches_by_id,
            visited=seen,
        ):
            return True
    return False
