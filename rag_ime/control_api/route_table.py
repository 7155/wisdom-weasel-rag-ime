"""One descriptor per route, replacing hand-written dispatch branches.

`debug_server` grew a 1,205-line `do_GET` and an 821-line `do_POST`, each an
if/elif chain in which every route restates method matching, parsing, the
application call and the response shape. Nothing links a branch to the policy
that declares the same route, which is how a branch came to be tested twice
with the second copy unreachable.

A `RouteDescriptor` states one route once: method, path, whether it is exposed
remotely, how the request becomes handler arguments, and which application
method serves it. The dispatcher below is the single owner for the families
that have been migrated; families still in the chains are untouched, and a
route is never served by both, because `debug_server` consults the table first
and returns immediately on a hit.

Migration is per-family on purpose. Moving all 237 routes at once could not be
reviewed, and the route-ownership gate ratchets the remaining count down as
families arrive.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RouteDescriptor:
    """Everything one route needs, in one place."""

    method: str
    path: str
    handler: str
    """Attribute name on the application service that serves this route."""
    remote_safe: bool = False
    """Whether the Agent Gateway may reach it; local surfaces stay local."""
    status: int = 200
    query_args: tuple[str, ...] = ()
    """Query parameters lifted into the handler payload, for GET routes."""
    payload_args: Mapping[str, Any] = field(default_factory=dict)
    """Fixed keyword arguments, e.g. an action discriminator."""
    transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    """Optional payload adjustment applied before the handler runs."""
    takes_arguments: bool = True
    """False for handlers that take no request data at all, e.g. status reads.

    Passing an empty dict to those would be a TypeError, so the descriptor has
    to say which shape the handler expects rather than the dispatcher guessing.
    """


def _as_model_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """`/api/models/profile/save` is the profile saver pinned to one kind."""

    return {**payload, "kind": "model_profile"}


def _tag_phonetic_correction(payload: dict[str, Any]) -> dict[str, Any]:
    """Preserve the one non-uniform vocabulary branch exactly.

    The original chain appended the `phonetic_correction` tag to whatever tags
    the caller sent before delegating to the shared save handler. Keeping it as
    a declared transform means the descriptor still describes the route fully,
    instead of pushing a special case back into the dispatcher.
    """

    tags = payload.get("tags")
    existing = [str(item) for item in tags if str(item)] if isinstance(tags, list) else []
    return {**payload, "tags": [*existing, "phonetic_correction"]}


# Vocabulary is the first migrated family: seven routes, entirely local, each a
# straight payload-to-service call, so the descriptor shape can be proven
# against a family whose behaviour is unambiguous.
VOCABULARY_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(
        method="GET",
        path="/api/vocabulary/items",
        handler="vocabulary_items",
        # Exactly the two the original branch forwarded; adding others would
        # change the payload the service receives.
        query_args=("status", "query"),
    ),
    RouteDescriptor(
        method="POST",
        path="/api/vocabulary/item/add",
        handler="vocabulary_item_save",
        payload_args={"action": "add"},
    ),
    RouteDescriptor(
        method="POST",
        path="/api/vocabulary/item/edit",
        handler="vocabulary_item_save",
        payload_args={"action": "edit"},
    ),
    RouteDescriptor(
        method="POST",
        path="/api/vocabulary/item/delete",
        handler="vocabulary_item_delete",
    ),
    RouteDescriptor(
        method="POST",
        path="/api/vocabulary/phonetic-correction/add",
        handler="vocabulary_item_save",
        payload_args={"action": "phonetic_correction_add"},
        transform=_tag_phonetic_correction,
    ),
    RouteDescriptor(
        method="POST",
        path="/api/vocabulary/rime-export-preview",
        handler="vocabulary_rime_export_preview",
    ),
    RouteDescriptor(
        method="POST",
        path="/api/vocabulary/rime-export-apply",
        handler="vocabulary_rime_export_apply",
    ),
)

# RAG core v3: two reads that forward named query parameters, three writes that
# hand the payload straight to the service. Same shape as vocabulary, so it
# migrates without extending the descriptor.
RAG_CORE_V3_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(
        method="GET",
        path="/api/rag-core-v3/doc",
        handler="rag_core_v3_doc",
        query_args=("id",),
    ),
    RouteDescriptor(
        method="GET",
        path="/api/rag-core-v3/tag-graph",
        handler="rag_core_v3_tag_graph",
        query_args=("tag", "limit"),
    ),
    RouteDescriptor(
        method="POST",
        path="/api/rag-core-v3/query-preview",
        handler="rag_core_v3_query_preview",
    ),
    RouteDescriptor(
        method="POST",
        path="/api/rag-core-v3/rebuild-retrieval-docs",
        handler="rag_core_v3_rebuild_retrieval_docs",
    ),
    RouteDescriptor(
        method="POST",
        path="/api/rag-core-v3/memory-book-preview",
        handler="rag_core_v3_memory_book_preview",
    ),
)

# Lexicon and cleanup-diff: small write families with one paired read.
LEXICON_ROUTES: tuple[RouteDescriptor, ...] = (
    # GET and POST on this path share one service method; the descriptors are
    # distinct because the request becomes handler arguments differently
    # (named query parameters versus the JSON payload).
    RouteDescriptor(
        method="GET",
        path="/api/lexicon/export-rime",
        handler="management_lexicon_export_rime",
        query_args=("limit", "project", "status", "kind", "dryRun"),
    ),
    RouteDescriptor(
        method="POST",
        path="/api/lexicon/action",
        handler="management_lexicon_action",
    ),
    RouteDescriptor(
        method="POST",
        path="/api/lexicon/export-rime",
        handler="management_lexicon_export_rime",
    ),
)

CLEANUP_DIFF_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(
        method="POST",
        path="/api/cleanup-diff/apply",
        handler="management_cleanup_diff_apply",
    ),
    RouteDescriptor(
        method="POST",
        path="/api/cleanup-diff/rollback",
        handler="management_cleanup_diff_rollback",
    ),
)

# Models and profiles: two argument-free status reads, plus writes that are
# straight payload calls except the model profile save, which is the shared
# profile saver pinned to one kind.
MODEL_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(
        method="GET", path="/api/models/status",
        handler="models_status", takes_arguments=False,
    ),
    RouteDescriptor(
        method="GET", path="/api/models/profiles",
        handler="model_profiles", takes_arguments=False,
    ),
    RouteDescriptor(method="POST", path="/api/models/probe", handler="model_probe"),
    RouteDescriptor(method="POST", path="/api/models/benchmark", handler="model_benchmark_job"),
    RouteDescriptor(method="POST", path="/api/models/matrix-eval", handler="model_benchmark_job"),
    RouteDescriptor(
        method="POST", path="/api/models/profile/save",
        handler="profile_save", transform=_as_model_profile,
    ),
    RouteDescriptor(
        method="POST", path="/api/models/profile/activate-dry-run",
        handler="model_activate_dry_run",
    ),
)

PROFILE_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(method="POST", path="/api/profiles/save", handler="profile_save"),
    RouteDescriptor(
        method="POST", path="/api/profiles/activate-dry-run",
        handler="profile_activate_dry_run",
    ),
)

MIGRATED_ROUTES: tuple[RouteDescriptor, ...] = (
    *VOCABULARY_ROUTES,
    *MODEL_ROUTES,
    *PROFILE_ROUTES,
    *RAG_CORE_V3_ROUTES,
    *LEXICON_ROUTES,
    *CLEANUP_DIFF_ROUTES,
)

ROUTE_TABLE: dict[tuple[str, str], RouteDescriptor] = {
    (route.method, route.path): route for route in MIGRATED_ROUTES
}

if len(ROUTE_TABLE) != len(MIGRATED_ROUTES):  # pragma: no cover - import-time guard
    raise RuntimeError("duplicate (method, path) in the route table")


def find_route(method: str, path: str) -> RouteDescriptor | None:
    return ROUTE_TABLE.get((str(method).upper(), str(path)))


def build_arguments(
    route: RouteDescriptor,
    *,
    payload: Mapping[str, Any] | None,
    query_first: Callable[[str], str],
) -> dict[str, Any]:
    """Turn one request into the handler's payload, per the descriptor."""

    if route.method == "GET":
        arguments: dict[str, Any] = {name: query_first(name) for name in route.query_args}
    else:
        arguments = dict(payload or {})
    if route.transform is not None:
        arguments = route.transform(arguments)
    return arguments
