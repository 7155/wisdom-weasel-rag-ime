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
    """Attribute path on the application service that serves this route.

    Dotted for handlers reached through a sub-service, e.g.
    `management.configuration_import_preview`, so a descriptor can name any
    real call site rather than only top-level methods.
    """
    remote_safe: bool = False
    """Whether the Agent Gateway may reach it; local surfaces stay local."""
    status: int = 200
    query_args: tuple[str, ...] = ()
    """Query parameters lifted into the handler payload, for GET routes."""
    payload_args: Mapping[str, Any] = field(default_factory=dict)
    """Fixed keyword arguments, e.g. an action discriminator."""
    transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    """Optional payload adjustment applied before the handler runs."""
    aliases: tuple[str, ...] = ()
    """Legacy paths serving the same route, e.g. the un-prefixed `/prediction/*`.

    They are registered as ordinary table entries so an alias can never drift
    from the route it mirrors.
    """
    contract: str = ""
    """JSON-schema contract validated against the payload before dispatch.

    Several chain branches called `validate_contract` before their handler;
    naming the schema keeps that a property of the route rather than a step a
    future migration could silently drop.
    """
    response_contract: str = ""
    """JSON-schema contract validated against the response before it is sent.

    Distinct from `contract`, which validates the request: the frontend
    capabilities route checked its own output, and collapsing the two would
    silently move where validation happens.
    """
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

# Settings: one argument-free schema read plus five payload writes.
SETTINGS_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(
        method="GET", path="/api/settings/schema",
        handler="settings_schema", takes_arguments=False,
    ),
    RouteDescriptor(method="POST", path="/api/settings/preview", handler="configuration_settings_preview"),
    RouteDescriptor(method="POST", path="/api/settings/apply", handler="configuration_settings_apply"),
    RouteDescriptor(method="POST", path="/api/settings/rollback", handler="configuration_settings_rollback"),
    RouteDescriptor(method="POST", path="/api/settings/update", handler="settings_update"),
    RouteDescriptor(method="POST", path="/api/settings/reset-section", handler="settings_reset_section"),
)

# Configuration: reached through the management sub-service. These are already
# declared in route_policy, so migrating them consolidates ownership without
# moving the ratchet.
CONFIGURATION_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(method="POST", path="/api/configuration/import-preview", handler="management.configuration_import_preview"),
    RouteDescriptor(method="POST", path="/api/configuration/import-apply", handler="management.configuration_import_apply"),
    RouteDescriptor(method="POST", path="/api/configuration/backup-export", handler="management.portable_backup_export"),
    RouteDescriptor(method="POST", path="/api/configuration/restore-preview", handler="management.portable_restore_preview"),
    RouteDescriptor(method="POST", path="/api/configuration/restore-apply", handler="management.portable_restore_apply"),
)

# Prediction, memories and rime-lexicon. Prediction keeps its un-prefixed
# aliases, which the chain served from the same branch.
PREDICTION_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(
        method="GET", path="/api/prediction/live-trace",
        aliases=("/prediction/live-trace",),
        handler="prediction_live_trace", query_args=("limit", "sessionId"),
    ),
    RouteDescriptor(
        method="GET", path="/api/prediction/drop-stats",
        aliases=("/prediction/drop-stats",),
        handler="prediction_drop_stats", query_args=("limit",),
    ),
)

MEMORIES_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(
        method="GET", path="/api/memories", handler="management_memories",
        query_args=("limit", "project", "status", "kind"),
    ),
    RouteDescriptor(
        method="POST", path="/api/memories/action", handler="management_memory_action",
    ),
)

RIME_LEXICON_ROUTES: tuple[RouteDescriptor, ...] = (
    RouteDescriptor(
        method="GET", path="/api/rime-lexicon/review",
        handler="rime_lexicon_review", query_args=("limit", "project"),
    ),
    RouteDescriptor(method="POST", path="/api/rime-lexicon/apply", handler="rime_lexicon_apply"),
    RouteDescriptor(method="POST", path="/api/rime-lexicon/rollback", handler="rime_lexicon_rollback"),
)

def _post(path, handler, *, aliases=(), contract="", takes_arguments=True):
    return RouteDescriptor(
        method="POST", path=path, handler=handler, aliases=aliases,
        contract=contract, takes_arguments=takes_arguments,
    )


# Foreground and memory single-path writes. Each kept its un-prefixed alias,
# and the three contract-validated routes keep validation as a declared field.
FOREGROUND_ROUTES: tuple[RouteDescriptor, ...] = (
    _post("/api/action", "action", aliases=("/action",)),
    _post("/api/cache-probe", "cache_probe", aliases=("/cache-probe",)),
    _post("/api/candidate-edit-feedback", "candidate_edit_feedback", aliases=("/candidate-edit-feedback",)),
    _post("/api/commit", "commit", aliases=("/commit",), contract="foreground-commit.v1.json"),
    _post("/api/predictor-ttfc", "predictor_ttfc", aliases=("/predictor-ttfc",)),
    _post("/api/rime-rank-feedback", "rime_rank_feedback", aliases=("/rime-rank-feedback",), contract="rime-rank-selection.v1.json"),
    _post("/api/assistant-candidate-action", "assistant_candidate_action", aliases=("/assistant-candidate-action",), contract="assistant-candidate-action.v1.json"),
    _post("/api/seed", "seed", aliases=("/seed",), takes_arguments=False),
)

MEMORY_TOOL_ROUTES: tuple[RouteDescriptor, ...] = (
    _post("/api/generate-memory", "generate_memory", aliases=("/generate-memory",)),
    _post("/api/memory-candidate-explain", "memory_candidate_explain", aliases=("/memory-candidate-explain",)),
    _post("/api/memory-cleanup-runs", "memory_cleanup_runs", aliases=("/memory-cleanup-runs",)),
    _post("/api/memory-governance", "memory_governance", aliases=("/memory-governance",)),
    _post("/api/memory-history", "memory_history", aliases=("/memory-history",)),
    _post("/api/memory-optimizer-trace", "memory_optimizer_trace", aliases=("/memory-optimizer-trace",)),
    _post("/api/memory-tombstone", "memory_tombstone", aliases=("/memory-tombstone", "/api/memory/tombstone")),
    _post("/api/organize-rag-db", "organize_rag_database", aliases=("/organize-rag-db",)),
    _post("/api/rebuild-vector-index", "rebuild_vector_index", aliases=("/rebuild-vector-index",)),
    _post("/api/deepseek/completion-preview", "deepseek_completion_preview"),
)

def _get(path, handler, *, aliases=(), query_args=(), takes_arguments=False, response_contract=""):
    """Most migrated reads take no request data, so that is the default here."""

    return RouteDescriptor(
        method="GET", path=path, handler=handler, aliases=aliases,
        query_args=query_args, takes_arguments=takes_arguments,
        response_contract=response_contract,
    )


# Status and catalog reads. Handlers are dotted where the chain reached through
# a sub-service; none of them take request data except `/api/profiles`.
READ_ROUTES: tuple[RouteDescriptor, ...] = (
    _get("/api/health", "health", aliases=("/health",)),
    _get("/api/input-source", "input_source_status", aliases=("/input-source",)),
    _get("/api/overview", "management.overview"),
    _get("/api/settings", "settings"),
    _get("/api/predictor/status", "predictor_status"),
    _get("/api/predictor/cache/stats", "predictor_cache_stats"),
    _get("/api/active-rag/settings", "active_rag_settings"),
    _get("/api/knowledge/route-status", "knowledge_workbench_route_status"),
    _get("/api/memory/summary", "management.memory_summary"),
    _get("/api/runtime/status", "management.runtime_status"),
    _get("/api/runtime/config", "runtime_config"),
    _get("/api/runtime/components", "management.runtime_components"),
    _get("/api/browser/status", "browser_control.status"),
    _get("/api/browser/pairing", "browser_control.pairing"),
    _get("/api/browser/tabs", "browser_control.tabs"),
    _get("/api/agent/runtime", "agent.runtime_status"),
    _get("/api/agent/providers", "pi_provider_auth.catalog"),
    _get("/api/agent/extensions", "agent_extensions.list"),
    _get("/api/agent/extensions/catalog", "agent_extensions.catalog"),
    _get("/api/agent/extensions/proposals", "agent_extensions.proposals"),
    _get("/api/agent/roles", "agent.list_roles"),
    _get("/api/agent/roles/models", "agent.role_model_catalog"),
    _get("/api/agent/subagents/templates", "agent.list_agent_templates"),
    _get("/api/agent/configuration", "agent.configuration"),
    _get("/api/profiles", "profiles", query_args=("kind",), takes_arguments=True),
    _get(
        "/api/frontend/v1/capabilities", "frontend_capabilities",
        aliases=("/frontend/v1/capabilities",),
        response_contract="frontend-capabilities.v1.json",
    ),
)

# Browser: only the argument-free lifecycle commands. The rest of this family
# stays in the chains on purpose -- extension routes carry their own
# authentication, snapshots return binary, several handlers take keyword
# arguments or path parameters, and permission routes map BrowserControlError
# to specific statuses. Migrating those needs descriptor support that does not
# exist yet, and inventing it for one family would make the table describe
# less than the chain does.
BROWSER_ROUTES: tuple[RouteDescriptor, ...] = (
    _post("/api/browser/pairing/rotate", "browser_control.rotate_pairing", takes_arguments=False),
    _post("/api/browser/stop", "browser_control.stop", takes_arguments=False),
    _post("/api/browser/managed/start", "browser_control.start_managed", takes_arguments=False),
    _post("/api/browser/managed/stop", "browser_control.stop_managed", takes_arguments=False),
)

MIGRATED_ROUTES: tuple[RouteDescriptor, ...] = (
    *VOCABULARY_ROUTES,
    *BROWSER_ROUTES,
    *READ_ROUTES,
    *FOREGROUND_ROUTES,
    *MEMORY_TOOL_ROUTES,
    *PREDICTION_ROUTES,
    *MEMORIES_ROUTES,
    *RIME_LEXICON_ROUTES,
    *SETTINGS_ROUTES,
    *CONFIGURATION_ROUTES,
    *MODEL_ROUTES,
    *PROFILE_ROUTES,
    *RAG_CORE_V3_ROUTES,
    *LEXICON_ROUTES,
    *CLEANUP_DIFF_ROUTES,
)

ROUTE_TABLE: dict[tuple[str, str], RouteDescriptor] = {}
for _route in MIGRATED_ROUTES:
    for _path in (_route.path, *_route.aliases):
        _key = (_route.method, _path)
        if _key in ROUTE_TABLE:  # pragma: no cover - import-time guard
            raise RuntimeError(f"duplicate route {_key}")
        ROUTE_TABLE[_key] = _route




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
