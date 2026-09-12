#!/usr/bin/env python3
"""Run a small, deterministic continuation evaluation through PAW Memory.

The evaluator deliberately uses the existing Session consumer path:

``AgentService.prompt -> AgentPromptDeliveryService -> AgentContextRuntime``

and ``SessionMemoryRecallBuilder``'s real retrieval projection.  The Runtime
acknowledgement is a local deterministic adapter, so the default mode never
starts or bills a Provider.  Fixture labels are synthetic and host-owned.  The
default result measures whether the current Memory/context projection gives a
continuation consumer the required evidence and abstention boundary.  When an
optional consumer callback is supplied, its actual answer is graded separately
under a fixed host rubric with explicit usage completeness.

By default the temporary SQLite databases and any detailed prompt material
stay outside the repository and no Provider is called.  An optional callback
can consume each resumed context once; that mode records its actual answer,
usage, and receipt under a fixed host rubric.  ``--output`` is optional and
should point to a private path outside the checkout when a receipt is desired.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from unittest.mock import patch

# Running ``python3 scripts/<runner>.py`` puts ``scripts`` on ``sys.path``;
# add the checkout root so the source Runtime remains the imported owner.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_context_runtime import RUNTIME_PROMPT_ENVELOPE_PREFIX
from rag_ime.agent_service import AgentService
from rag_ime.embeddings import HashingEmbeddingProvider
from rag_ime.pi.config import PiRuntimeConfig
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.retrieval_vector_index import rebuild_retrieval_doc_vectors


SCHEMA_VERSION = "paw.context-continuation-evaluation.v1"
PROJECT = "paw-context-continuation-fixture"
FIXTURE_REVISION = "2026-09-05.small.v2"
REQUIRED_TRACE_STAGES = (
    "input",
    "session",
    "tools",
    "memory_recall",
    "context_inbox",
    "runtime_request",
    "runtime_result",
)
POSITIVE_LABELS = frozenset({"retained", "updated"})
NEGATIVE_LABELS = frozenset({"forgotten", "abstain"})
_TOKEN_USAGE_FIELDS = ("inputTokens", "outputTokens", "totalTokens")
_ABSTENTION_MARKERS = (
    "无法确认",
    "无法判断",
    "不能确认",
    "不能提供",
    "不能直接",
    "不应",
    "不可",
    "无法",
    "不能",
    "没有足够",
    "请勿",
    "abstain",
)

# The optional callback is deliberately a very small Lab seam.  A callable
# (or an object with ``complete``) receives only keyword ``prompt`` and
# ``fixture_id``.  The prompt contains the natural-language question and the
# context taken from the just-produced Runtime envelope; expected answers and
# fixture labels never cross this boundary.
ConsumerCallback = Callable[..., object]


class PawContextLabConsumerAdapter:
    """Duck adapter from this runner's seam to a Lab ``complete`` callback.

    ``completion`` is injected by the owning Lab runner; this script never
    imports Lab or Provider code.  One adapter call creates one request id and
    forwards the exact prompt, model, session binder, and cancellation probe.
    """

    def __init__(
        self,
        *,
        completion: Callable[..., object],
        model: Mapping[str, object],
        on_session: Callable[[str], None],
        cancelled: Callable[[], bool],
        request_prefix: str = "paw-memory-continuation",
    ) -> None:
        if not callable(completion):
            raise TypeError("completion must be callable")
        if not callable(on_session) or not callable(cancelled):
            raise TypeError("on_session and cancelled must be callable")
        prefix = str(request_prefix).strip()
        if not prefix:
            raise ValueError("request_prefix must not be empty")
        self._completion = completion
        self._model = dict(model)
        self._on_session = on_session
        self._cancelled = cancelled
        self._request_prefix = prefix

    @classmethod
    def prepare(cls, **kwargs: object) -> "PawContextLabConsumerAdapter":
        """Create an adapter without coupling Lab's prepare protocol here."""

        return cls(**kwargs)  # type: ignore[arg-type]

    def complete(self, *, prompt: str, fixture_id: str) -> object:
        request_id = f"{self._request_prefix}:{fixture_id}"
        return self._completion(
            request_id=request_id,
            model=dict(self._model),
            prompt=prompt,
            on_session=self._on_session,
            cancelled=self._cancelled,
        )

    def __call__(self, *, prompt: str, fixture_id: str) -> object:
        return self.complete(prompt=prompt, fixture_id=fixture_id)

# This is intentionally four small cases.  The labels describe the expected
# consumer behavior, not a model judgment: a current fact may be used, a
# correction must replace its stale predecessor, forgotten material must stay
# absent, and sensitive material must be withheld.
# Opaque source IDs may enter provenance; they must not reveal the host labels.
FIXTURES: tuple[dict[str, object], ...] = (
    {
        "fixtureId": "retained-001",
        "label": "retained",
        "query": "继续 PAW 输入法评测，验收脚本需要保留什么？",
        "followUp": "继续完成这个任务并给出结论。",
        "consumerQuery": "为了继续验收，当前必须保留哪两类输入法评测证据？",
        "targetId": "atom:71d58355d1104446",
        "targetText": "PAW 输入法评测必须保留原始需求和失败轨迹",
        "expectedAnswer": "USE_RETAINED_FACT",
        "seeds": (
            {
                "id": "atom:71d58355d1104446",
                "text": "PAW 输入法评测必须保留原始需求和失败轨迹",
                "claimKey": "continuation-retained",
                "claimState": "current",
                "status": "active",
                "privacy": "local",
                "updatedAtMs": 10,
            },
        ),
        "forbiddenTexts": (),
    },
    {
        "fixtureId": "updated-001",
        "label": "updated",
        "query": "继续评测，现在使用哪个模型？",
        "followUp": "继续完成这个任务并给出结论。",
        "consumerQuery": "这次评测当前选用的是哪个模型？",
        "targetId": "atom:3ef4e295a5343b61",
        "targetText": "PAW 评测当前使用 Luna 5.6 模型",
        "expectedAnswer": "USE_UPDATED_FACT",
        "seeds": (
            {
                "id": "atom:e7dd98521e4fb2d4",
                "text": "PAW 评测之前使用旧模型",
                "claimKey": "continuation-model",
                "claimState": "superseded",
                "status": "superseded",
                "privacy": "local",
                "updatedAtMs": 10,
                "validToMs": 20,
            },
            {
                "id": "atom:3ef4e295a5343b61",
                "text": "PAW 评测当前使用 Luna 5.6 模型",
                "claimKey": "continuation-model",
                "claimState": "current",
                "status": "active",
                "privacy": "local",
                "updatedAtMs": 20,
                "supersedesId": "atom:e7dd98521e4fb2d4",
            },
        ),
        "forbiddenTexts": ("PAW 评测之前使用旧模型",),
    },
    {
        "fixtureId": "forgotten-001",
        "label": "forgotten",
        "query": "继续回顾已取消的旧部署方案。",
        "followUp": "继续完成这个任务并给出结论。",
        "consumerQuery": "那个已取消的旧部署方案现在还能作为依据吗？",
        "targetId": "atom:1f931eb8bd096398",
        "targetText": "旧部署方案已经废弃不再使用",
        "expectedAnswer": "ABSTAIN",
        "seeds": (
            {
                "id": "atom:1f931eb8bd096398",
                "text": "旧部署方案已经废弃不再使用",
                "claimKey": "continuation-forgotten",
                "claimState": "superseded",
                "status": "superseded",
                "privacy": "local",
                "updatedAtMs": 10,
                "validToMs": 20,
            },
        ),
        "forbiddenTexts": ("旧部署方案已经废弃不再使用",),
    },
    {
        "fixtureId": "abstain-001",
        "label": "abstain",
        "query": "继续处理部署凭据。",
        "followUp": "继续完成这个任务并给出结论。",
        "consumerQuery": "部署凭据现在可以直接写进回答吗？",
        "targetId": "atom:713f6c3dfdf194da",
        "targetText": "部署凭据属于敏感记忆，不应进入 Agent 上下文",
        "expectedAnswer": "ABSTAIN",
        "seeds": (
            {
                "id": "atom:713f6c3dfdf194da",
                "text": "部署凭据属于敏感记忆，不应进入 Agent 上下文",
                "claimKey": "continuation-sensitive",
                "claimState": "current",
                "status": "active",
                "privacy": "sensitive",
                "updatedAtMs": 10,
            },
        ),
        "forbiddenTexts": ("部署凭据属于敏感记忆，不应进入 Agent 上下文",),
    },
)


_ATOM_COLUMNS = (
    "id, kind, text, canonical_text, source_event_ids_json, "
    "source_memory_ids_json, scope_app, scope_project, language, confidence, "
    "quality_score, echo_risk, privacy_level, status, created_at_ms, "
    "updated_at_ms, last_used_at_ms, owner_kind, owner_id, claim_key, "
    "lineage_id, claim_state, valid_from_ms, valid_to_ms, supersedes_id, "
    "knowledge_domain, scope_kind, scope_id, visibility, "
    "authorization_revision, binding_id, scope_mode"
)
_ATOM_INSERT = (
    "INSERT INTO memory_atoms ("
    + _ATOM_COLUMNS
    + ") VALUES ("
    + ",".join("?" for _ in _ATOM_COLUMNS.split(","))
    + ")"
)


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    if isinstance(value, bytes):
        payload = value
    else:
        payload = _canonical(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fixture_manifest() -> list[dict[str, object]]:
    """Return a public, text-free manifest used for the reproducibility hash."""

    return [
        {
            "fixtureId": str(fixture["fixtureId"]),
            "label": str(fixture["label"]),
            "targetId": str(fixture["targetId"]),
            "expectedAnswer": str(fixture["expectedAnswer"]),
            "querySha256": _sha256(str(fixture["query"])),
            "followUpSha256": _sha256(str(fixture["followUp"])),
            "consumerQuerySha256": _sha256(str(fixture["consumerQuery"])),
            "targetTextSha256": _sha256(str(fixture["targetText"])),
            "forbiddenTextSha256": [
                _sha256(str(value))
                for value in fixture.get("forbiddenTexts", ())
            ],
        }
        for fixture in FIXTURES
    ]


def _insert_atom(conn: sqlite3.Connection, fixture: Mapping[str, object]) -> None:
    atom_id = str(fixture["id"])
    text = str(fixture["text"])
    claim_key = str(fixture["claimKey"])
    updated_at_ms = int(fixture.get("updatedAtMs") or 10)
    values = (
        atom_id,
        "fact",
        text,
        text,
        "[]",  # Synthetic fixture lineage is intentionally text-free.
        "[]",
        None,
        PROJECT,
        "zh",
        1.0,
        1.0,
        0.0,
        str(fixture.get("privacy") or "local"),
        str(fixture.get("status") or "active"),
        updated_at_ms,
        updated_at_ms,
        None,
        "user",
        "default",
        claim_key,
        f"lineage:{claim_key}",
        str(fixture.get("claimState") or "current"),
        updated_at_ms,
        fixture.get("validToMs"),
        fixture.get("supersedesId"),
        "legacy",
        "legacy",
        "",
        "legacy",
        "",
        "",
        "legacy",
    )
    if len(values) != len(_ATOM_COLUMNS.split(",")):  # pragma: no cover
        raise AssertionError("memory atom fixture column count drifted")
    conn.execute(_ATOM_INSERT, values)


def _seed_fixture_database(
    db_path: Path,
    fixture: Mapping[str, object],
    provider: HashingEmbeddingProvider,
) -> dict[str, object]:
    """Seed governed Atom rows, then build the real retrieval projections."""

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for raw_atom in fixture.get("seeds", ()):
            if not isinstance(raw_atom, Mapping):
                raise ValueError("fixture seed must be an object")
            _insert_atom(conn, raw_atom)
        rebuild = rebuild_retrieval_docs(
            conn,
            project=PROJECT,
            include_books=True,
            include_atoms=True,
            include_phrases=True,
            include_timelines=True,
            include_legacy_items=False,
        )
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        vectors = rebuild_retrieval_doc_vectors(
            conn,
            provider,
            project=PROJECT,
        )
    return {
        "retrievalDocCount": int(rebuild.get("docCount") or 0),
        "retrievalAtomCount": int((rebuild.get("counts") or {}).get("atom") or 0),
        "vectorDocumentCount": int(vectors.get("documents") or 0),
        "vectorProviderFingerprint": str(vectors.get("providerFingerprint") or ""),
    }


def _new_service(root: Path, provider: HashingEmbeddingProvider) -> AgentService:
    return AgentService(
        db_path=root / "rag-ime.sqlite",
        project=PROJECT,
        runtime_config=PiRuntimeConfig(
            enabled=False,
            executable=None,
            agent_dir=root / "agent-config",
            session_dir=root / "sessions",
            logs_dir=root / "logs",
        ),
        memory_embedding_provider=provider,
    )


def _acknowledgement(fixture_id: str, ordinal: int) -> dict[str, object]:
    """A local Pi-acceptance-shaped response; it makes zero Provider calls."""

    return {
        "accepted": True,
        "turnId": f"fixture-turn:{fixture_id}:{ordinal}",
        "piEntryId": f"fixture-entry:{fixture_id}:{ordinal}",
        "response": {"success": True},
    }


def _parse_runtime_envelope(runtime_message: str) -> dict[str, object]:
    if not runtime_message.startswith(RUNTIME_PROMPT_ENVELOPE_PREFIX):
        raise AssertionError("expected the governed runtime prompt envelope")
    value = json.loads(runtime_message[len(RUNTIME_PROMPT_ENVELOPE_PREFIX) :])
    if not isinstance(value, dict):
        raise AssertionError("runtime prompt envelope must be an object")
    return value


def _trace_evidence(service: AgentService, trace_id: str) -> dict[str, object]:
    trace = service.context_runtime.trace(trace_id)
    nodes = [
        node for node in trace.get("nodes", ()) if isinstance(node, Mapping)
    ]
    stages = [str(node.get("stage") or "") for node in nodes]
    memory_node = next(
        (node for node in nodes if node.get("stage") == "memory_recall"),
        {},
    )
    request_node = next(
        (node for node in nodes if node.get("stage") == "runtime_request"),
        {},
    )
    metadata = memory_node.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    raw_atom_ids = str(metadata.get("memoryAtomIds") or "")
    atom_ids = [value for value in raw_atom_ids.split(",") if value]
    return {
        "status": str(trace.get("status") or ""),
        "sourceKind": str(trace.get("sourceKind") or ""),
        "stages": stages,
        "requiredStagesPresent": all(
            stage in stages for stage in REQUIRED_TRACE_STAGES
        ),
        "memoryAtomIds": atom_ids,
        "memoryChars": int(memory_node.get("charCount") or 0),
        "memoryTokens": int(memory_node.get("tokenEstimate") or 0),
        "runtimePromptTokens": int(request_node.get("tokenEstimate") or 0),
        "traceContractAccepted": (
            str(trace.get("status") or "") == "accepted"
            and all(stage in stages for stage in REQUIRED_TRACE_STAGES)
        ),
    }


def _deterministic_consumer_answer(
    fixture: Mapping[str, object],
    session_context: str,
) -> str:
    """Apply the fixture's host-side continuation rubric to the real context."""

    forbidden = tuple(str(value) for value in fixture.get("forbiddenTexts", ()))
    if any(value and value in session_context for value in forbidden):
        return "WRONG_OR_STALE_MEMORY"
    target = str(fixture.get("targetText") or "")
    if target and target in session_context:
        return str(fixture.get("expectedAnswer") or "")
    return "ABSTAIN"


def _consumer_prompt(query: str, context: str) -> str:
    """Build the only prompt that may cross the optional model seam.

    ``context`` is copied from the resumed Runtime envelope.  The fixture's
    expected answer, label, and target metadata are intentionally not included
    so the callback can only see the question and the real context it is asked
    to consume.
    """

    available_context = context.strip() or "（没有可用上下文）"
    return (
        "请只根据下面的上下文简短回答问题；如果上下文没有足够依据，"
        "请明确说明无法确认，不要猜测。\n"
        f"问题：{query.strip()}\n"
        f"上下文：\n{available_context}"
    )


def _consumer_callable(consumer: ConsumerCallback) -> Callable[..., object]:
    """Resolve a callable or a tiny duck-typed Lab adapter exactly once."""

    if callable(consumer):
        return consumer
    complete = getattr(consumer, "complete", None)
    if callable(complete):
        return complete
    raise TypeError("consumer must be callable or expose complete()")


def _invoke_consumer(
    consumer: ConsumerCallback,
    *,
    prompt: str,
    fixture_id: str,
) -> object:
    """Invoke one callback completion; this function never retries."""

    callback = _consumer_callable(consumer)
    # fixture_id is a routing/request identity for the Lab adapter.  It is not
    # part of ``prompt`` and therefore is never supplied to the model as a
    # fixture label or expected answer.
    return callback(prompt=prompt, fixture_id=fixture_id)


def _finite_nonnegative(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _usage_completeness(usage: Mapping[str, object]) -> dict[str, object]:
    token_fields = {
        field: _finite_nonnegative(usage.get(field))
        for field in _TOKEN_USAGE_FIELDS
    }
    actual_cost = _finite_nonnegative(usage.get("costUsd"))
    estimated_cost = _finite_nonnegative(usage.get("estimatedCostUsd"))
    cost_known = actual_cost or estimated_cost
    return {
        "tokenFields": token_fields,
        "tokensComplete": all(token_fields.values()),
        "actualCostObserved": actual_cost,
        "estimatedCostObserved": estimated_cost,
        "costKnown": cost_known,
        # A catalog estimate is observable cost evidence, but its basis stays
        # explicit; it is never relabeled as an actual provider bill.
        "complete": all(token_fields.values()) and cost_known,
        "costBasis": str(usage.get("costBasis") or "") or None,
    }


def _receipt_completed(receipt: object) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    status = str(
        receipt.get("status")
        or receipt.get("disposition")
        or ""
    ).casefold()
    return status in {"completed", "settled", "success"}


def _normalise_consumer_result(value: object) -> dict[str, object]:
    """Keep callback output small while preserving answer/usage/receipt facts."""

    if isinstance(value, Mapping):
        answer_value = value.get("answer", value.get("text"))
        usage_value = value.get("usage")
        receipt_value = value.get("receipt")
        provider_calls = value.get("providerCalls")
        error_value = value.get("error")
    else:
        answer_value = getattr(value, "answer", getattr(value, "text", None))
        usage_value = getattr(value, "usage", None)
        receipt_value = getattr(value, "receipt", None)
        provider_calls = getattr(value, "providerCalls", None)
        error_value = getattr(value, "error", None)
    answer = (
        answer_value.strip()
        if isinstance(answer_value, str)
        else (str(answer_value) if answer_value is not None else "")
    )
    usage = dict(usage_value) if isinstance(usage_value, Mapping) else {}
    receipt: object
    if isinstance(receipt_value, Mapping):
        receipt = dict(receipt_value)
    elif receipt_value is None:
        receipt = None
    else:
        receipt = str(receipt_value)
    observed_provider_calls = (
        provider_calls if _finite_nonnegative(provider_calls) else None
    )
    return {
        "answer": answer,
        "answerPresent": bool(answer),
        "usage": usage,
        "usageCompleteness": _usage_completeness(usage),
        "providerCalls": observed_provider_calls,
        "receipt": receipt,
        "receiptCompleted": _receipt_completed(receipt),
        "error": str(error_value) if error_value else None,
    }


def _grade_model_answer(
    fixture: Mapping[str, object],
    answer: str,
) -> dict[str, object]:
    """Apply a fixed host rubric to the callback's actual answer."""

    text = answer.strip()
    forbidden = tuple(str(value) for value in fixture.get("forbiddenTexts", ()))
    forbidden_observed = any(value and value in text for value in forbidden)
    target = str(fixture.get("targetText") or "")
    target_observed = bool(target and target in text)
    if not text:
        return {
            "passed": False,
            "reason": "missing_answer",
            "forbiddenTextObserved": False,
            "targetTextObserved": False,
        }
    if forbidden_observed:
        return {
            "passed": False,
            "reason": "forbidden_stale_or_sensitive_text_in_answer",
            "forbiddenTextObserved": True,
            "targetTextObserved": target_observed,
        }
    label = str(fixture.get("label") or "")
    expected_marker = str(fixture.get("expectedAnswer") or "")
    if label in POSITIVE_LABELS:
        required_markers = {
            "retained": ("原始需求", "失败轨迹"),
            "updated": ("Luna 5.6",),
        }.get(label, ())
        passed = expected_marker in text or all(
            marker in text for marker in required_markers
        )
        return {
            "passed": bool(passed),
            "reason": "current_fact_supported" if passed else "current_fact_missing",
            "forbiddenTextObserved": False,
            "targetTextObserved": target_observed,
        }
    lowered = text.casefold()
    abstained = any(marker.casefold() in lowered for marker in _ABSTENTION_MARKERS)
    passed = abstained and not target_observed
    return {
        "passed": bool(passed),
        "reason": "abstained_without_memory_disclosure"
        if passed
        else "answer_did_not_abstain",
        "forbiddenTextObserved": False,
        "targetTextObserved": target_observed,
    }


def _consumer_context(envelope: Mapping[str, object]) -> str:
    """Project only actual context fields from a Runtime prompt envelope."""

    return "\n\n".join(
        value
        for value in (
            str(envelope.get("sessionContext") or "").strip(),
            str(envelope.get("transientContext") or "").strip(),
        )
        if value
    )


def _run_fixture(
    fixture: Mapping[str, object],
    root: Path,
    *,
    consumer: ConsumerCallback | None = None,
) -> dict[str, object]:
    provider = HashingEmbeddingProvider(dimensions=16)
    db_root = root / str(fixture["fixtureId"])
    db_root.mkdir(parents=True, exist_ok=True)
    service = _new_service(db_root, provider)
    try:
        projection = _seed_fixture_database(
            db_root / "rag-ime.sqlite",
            fixture,
            provider,
        )
        session = service.create_session(
            {"title": f"continuation-{fixture['fixtureId']}"}
        )["session"]
        session_id = str(session["id"])
        service.sessions.set_disclosure_preferences(session_id, {"tool:memory": "enabled"})
        first_messages: list[str] = []
        with patch.object(
            service.runtime,
            "prompt",
            side_effect=lambda *_args, **_kwargs: (
                first_messages.append(str(_args[1]))
                or _acknowledgement(str(fixture["fixtureId"]), 1)
            ),
        ):
            first = service.prompt(
                session_id,
                {"message": str(fixture["query"])},
            )
        first_envelope = _parse_runtime_envelope(first_messages[0])
        first_trace = _trace_evidence(
            service,
            str(first["contextTraceId"]),
        )
        first_context = _consumer_context(first_envelope)

        # Reopen the owner to exercise persisted context items and traces. The
        # continuation then runs after a real compaction refresh, which proves
        # a resumable Session path rather than a one-shot builder call.
        service.close()
        service = _new_service(db_root, provider)
        resumed_messages: list[str] = []
        refresh = service.refresh_session_context(
            {
                "sessionId": session_id,
                "trigger": "compaction",
                "summary": "首轮任务已接收，继续核对上下文并给出结论。",
                "recentMessages": [
                    {"role": "user", "text": str(fixture["query"])},
                    {"role": "assistant", "text": "已接收首轮任务。"},
                    {"role": "user", "text": str(fixture["followUp"])},
                ],
            }
        )
        with patch.object(
            service.runtime,
            "prompt",
            side_effect=lambda *_args, **_kwargs: (
                resumed_messages.append(str(_args[1]))
                or _acknowledgement(str(fixture["fixtureId"]), 2)
            ),
        ):
            resumed = service.prompt(
                session_id,
                {"message": str(fixture["followUp"])},
            )
        resumed_envelope = _parse_runtime_envelope(resumed_messages[0])
        resumed_trace = _trace_evidence(
            service,
            str(resumed["contextTraceId"]),
        )
        resumed_context = _consumer_context(resumed_envelope)

        answer = _deterministic_consumer_answer(fixture, resumed_context)
        expected_answer = str(fixture["expectedAnswer"])
        label = str(fixture["label"])
        forbidden = tuple(str(value) for value in fixture.get("forbiddenTexts", ()))
        wrong_stale = any(value and value in resumed_context for value in forbidden)
        expected_target = str(fixture.get("targetText") or "")
        target_present = bool(expected_target and expected_target in resumed_context)
        positive_recall = (
            target_present if label in POSITIVE_LABELS else None
        )
        negative_excluded = (
            (not target_present and not wrong_stale)
            if label in NEGATIVE_LABELS
            else None
        )
        continuation_success = bool(
            answer == expected_answer
            and not wrong_stale
            and resumed_trace["traceContractAccepted"]
            and "<compaction-recovery>" in resumed_context
        )
        model_consumer: dict[str, object] | None = None
        if consumer is not None:
            fixture_id = str(fixture["fixtureId"])
            consumer_query = str(fixture["consumerQuery"])
            prompt = _consumer_prompt(consumer_query, resumed_context)
            model_consumer = {
                "querySha256": _sha256(consumer_query),
                "promptSha256": _sha256(prompt),
                "promptChars": len(prompt),
                "callbackCalls": 0,
                "answer": "",
                "answerPresent": False,
                "hostAcceptance": {
                    "passed": False,
                    "reason": "callback_not_completed",
                    "forbiddenTextObserved": False,
                    "targetTextObserved": False,
                },
                "usage": {},
                "usageCompleteness": _usage_completeness({}),
                "providerCalls": None,
                "receipt": None,
                "receiptCompleted": False,
                "error": None,
                "success": False,
            }
            # The callback is invoked once, with no retry or answer repair.  A
            # failing callback still yields an explicit case receipt.
            model_consumer["callbackCalls"] = 1
            try:
                callback_value = _invoke_consumer(
                    consumer,
                    prompt=prompt,
                    fixture_id=fixture_id,
                )
                normalized = _normalise_consumer_result(callback_value)
                model_consumer.update(normalized)
                model_consumer["hostAcceptance"] = _grade_model_answer(
                    fixture,
                    str(normalized["answer"]),
                )
            except Exception as error:
                model_consumer["error"] = f"{type(error).__name__}: {error}"
            acceptance = model_consumer["hostAcceptance"]
            usage_completeness = model_consumer["usageCompleteness"]
            model_consumer["success"] = bool(
                isinstance(acceptance, Mapping)
                and acceptance.get("passed") is True
                and isinstance(usage_completeness, Mapping)
                and usage_completeness.get("complete") is True
                and model_consumer.get("answerPresent") is True
                and model_consumer.get("receiptCompleted") is True
                and not model_consumer.get("error")
            )
        return {
            "fixtureId": str(fixture["fixtureId"]),
            "label": label,
            "expectedAnswer": expected_answer,
            "deterministicAnswer": answer,
            "contextContinuationContract": continuation_success,
            "positiveKeyInformationRecall": positive_recall,
            "negativeMemoryExcluded": negative_excluded,
            "wrongOrStaleMemoryExposure": bool(wrong_stale),
            "modelContinuationSuccess": (
                bool(model_consumer["success"])
                if model_consumer is not None
                else None
            ),
            "modelConsumer": model_consumer,
            "initial": {
                "targetPresent": bool(expected_target and expected_target in first_context),
                "trace": first_trace,
            },
            "resumed": {
                "targetPresent": bool(expected_target and expected_target in resumed_context),
                "trace": resumed_trace,
                "compactionRecoveryPresent": "<compaction-recovery>" in resumed_context,
                "refresh": {
                    "sourceCount": int(refresh.get("result", {}).get("sourceCount") or 0)
                    if isinstance(refresh.get("result"), Mapping)
                    else 0,
                    "compactionRecoveryPacket": bool(
                        refresh.get("result", {}).get("compactionRecoveryPacket")
                    )
                    if isinstance(refresh.get("result"), Mapping)
                    else False,
                },
            },
            "contextTokens": {
                "initialMemory": int(first_trace["memoryTokens"]),
                "resumedMemory": int(resumed_trace["memoryTokens"]),
                "initialRuntimePrompt": int(first_trace["runtimePromptTokens"]),
                "resumedRuntimePrompt": int(resumed_trace["runtimePromptTokens"]),
            },
            "projection": projection,
        }
    finally:
        service.close()


def _rate(passed: int, total: int) -> float:
    return round(passed / total, 6) if total else 0.0


def run_evaluation(
    *,
    consumer: ConsumerCallback | None = None,
) -> dict[str, object]:
    """Run four continuations, optionally handing each context to one consumer.

    With ``consumer=None`` this remains a zero-Provider source/runtime check.
    When configured, the callback receives one ``prompt=...`` containing only
    a natural-language question and the resumed Runtime context, plus a
    routing-only ``fixture_id``.  The host grades the returned answer and
    requires complete token/cost usage before counting model success.
    """

    with tempfile.TemporaryDirectory(prefix="paw-context-continuation-") as temporary:
        root = Path(temporary)
        cases = [
            _run_fixture(fixture, root, consumer=consumer)
            for fixture in FIXTURES
        ]

    total = len(cases)
    continuation_passed = sum(
        bool(case["contextContinuationContract"]) for case in cases
    )
    positive_cases = [
        case for case in cases if case["label"] in POSITIVE_LABELS
    ]
    negative_cases = [
        case for case in cases if case["label"] in NEGATIVE_LABELS
    ]
    positive_recall_passed = sum(
        case["positiveKeyInformationRecall"] is True
        for case in positive_cases
    )
    negative_exclusion_passed = sum(
        case["negativeMemoryExcluded"] is True
        for case in negative_cases
    )
    wrong_stale_count = sum(
        bool(case["wrongOrStaleMemoryExposure"]) for case in cases
    )
    model_cases = [
        case["modelConsumer"]
        for case in cases
        if isinstance(case.get("modelConsumer"), Mapping)
    ]
    model_answer_accepted = sum(
        isinstance(case.get("hostAcceptance"), Mapping)
        and case["hostAcceptance"].get("passed") is True
        for case in model_cases
    )
    model_success_passed = sum(
        bool(case.get("success")) for case in model_cases
    )
    usage_complete = sum(
        isinstance(case.get("usageCompleteness"), Mapping)
        and case["usageCompleteness"].get("complete") is True
        for case in model_cases
    )
    token_complete = sum(
        isinstance(case.get("usageCompleteness"), Mapping)
        and case["usageCompleteness"].get("tokensComplete") is True
        for case in model_cases
    )
    cost_complete = sum(
        isinstance(case.get("usageCompleteness"), Mapping)
        and case["usageCompleteness"].get("costKnown") is True
        for case in model_cases
    )
    actual_cost_complete = sum(
        isinstance(case.get("usageCompleteness"), Mapping)
        and case["usageCompleteness"].get("actualCostObserved") is True
        for case in model_cases
    )
    receipt_complete = sum(
        case.get("receiptCompleted") is True for case in model_cases
    )

    def _complete_numeric_total(field: str) -> float | int | None:
        if not model_cases:
            return None
        values = [
            case.get("usage", {}).get(field)
            for case in model_cases
            if isinstance(case.get("usage"), Mapping)
        ]
        if len(values) != len(model_cases) or not all(
            _finite_nonnegative(value) for value in values
        ):
            return None
        total_value = sum(values)
        return int(total_value) if all(isinstance(value, int) for value in values) else total_value

    observed_provider_calls = [
        case.get("providerCalls")
        for case in model_cases
    ]
    provider_calls_total = (
        sum(observed_provider_calls)
        if observed_provider_calls
        and all(_finite_nonnegative(value) for value in observed_provider_calls)
        else None
    )
    callback_provider_calls = (
        int(provider_calls_total)
        if provider_calls_total is not None
        and float(provider_calls_total).is_integer()
        else provider_calls_total
    )
    configured = consumer is not None
    model_total = len(model_cases)
    model_usage = {
        "configured": configured,
        "cases": model_total,
        "total": model_total,
        "callbackCalls": sum(
            int(case.get("callbackCalls") or 0) for case in model_cases
        ),
        "maxCompletionsPerFixture": 1,
        "tokenCompleteCases": token_complete,
        "costCompleteCases": cost_complete,
        "actualCostCompleteCases": actual_cost_complete,
        "usageCompleteCases": usage_complete,
        "receiptCompleteCases": receipt_complete,
        "tokenCompletenessRate": _rate(token_complete, model_total),
        "costCompletenessRate": _rate(cost_complete, model_total),
        "actualCostCompletenessRate": _rate(actual_cost_complete, model_total),
        "usageCompletenessRate": _rate(usage_complete, model_total),
        "observedInputTokens": _complete_numeric_total("inputTokens"),
        "observedOutputTokens": _complete_numeric_total("outputTokens"),
        "observedTotalTokens": _complete_numeric_total("totalTokens"),
        "observedCostUsd": _complete_numeric_total("costUsd"),
        "observedEstimatedCostUsd": _complete_numeric_total("estimatedCostUsd"),
        "observedProviderCalls": callback_provider_calls,
        "unknownProviderCallCases": sum(
            value is None for value in observed_provider_calls
        ),
        "source": "callback result usage; context token estimates are excluded",
    }
    model_success_total = model_total if configured else 0
    model_metric = {
        "passed": model_success_passed,
        "total": model_success_total,
        "rate": _rate(model_success_passed, model_success_total),
        "configured": configured,
        "answerAcceptedCases": model_answer_accepted,
        "usageCompleteCases": usage_complete,
        "receiptCompleteCases": receipt_complete,
        "definition": (
            "one callback completion per fixture; host semantic rubric over the "
            "actual answer plus a completed receipt and complete token/cost "
            "usage; missing/unknown answer, receipt, or usage is not a success"
        ),
    }
    context_rows = [
        {
            "fixtureId": str(case["fixtureId"]),
            **dict(case["contextTokens"]),
        }
        for case in cases
    ]
    memory_tokens = [
        value
        for row in context_rows
        for value in (int(row["initialMemory"]), int(row["resumedMemory"]))
    ]
    runtime_tokens = [
        value
        for row in context_rows
        for value in (
            int(row["initialRuntimePrompt"]),
            int(row["resumedRuntimePrompt"]),
        )
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "fixtureRevision": FIXTURE_REVISION,
        "fixtureSha256": _sha256(_fixture_manifest()),
        "fixtureManifest": _fixture_manifest(),
        "syntheticLabels": True,
        "evaluationBudget": {
            "fixtureCount": total,
            "turnsPerFixture": 2,
            "maxRecallItems": 12,
            "maxRecallChars": 14_000,
            "providerCalls": (
                0 if not configured else callback_provider_calls
            ),
            "consumerCallbackConfigured": configured,
            "maxConsumerCompletionsPerFixture": 1,
        },
        "metrics": {
            "contextContinuationContract": {
                "passed": continuation_passed,
                "total": total,
                "rate": _rate(continuation_passed, total),
                "rubric": "host-side deterministic consumer over resumed Session context; model answer quality is unmeasured",
            },
            "positiveKeyInformationRecall": {
                "passed": positive_recall_passed,
                "total": len(positive_cases),
                "rate": _rate(positive_recall_passed, len(positive_cases)),
                "applicableLabels": sorted(POSITIVE_LABELS),
                "definition": "current target text is present in resumed context",
            },
            "negativeMemoryExclusion": {
                "passed": negative_exclusion_passed,
                "total": len(negative_cases),
                "rate": _rate(negative_exclusion_passed, len(negative_cases)),
                "applicableLabels": sorted(NEGATIVE_LABELS),
                "definition": "forgotten or sensitive target and forbidden text are absent from resumed context",
            },
            "wrongOrStaleMemoryExposure": {
                "cases": wrong_stale_count,
                "total": total,
                "rate": _rate(wrong_stale_count, total),
                "definition": "forbidden stale/sensitive text was absent or exposed in context; this does not observe model use",
            },
            "modelContinuationSuccess": model_metric,
            "modelUsageCompleteness": model_usage,
            "contextTokens": {
                "memoryContext": {
                    "perTurn": context_rows,
                    "total": sum(memory_tokens),
                    "average": round(sum(memory_tokens) / len(memory_tokens), 3)
                    if memory_tokens
                    else 0.0,
                    "max": max(memory_tokens) if memory_tokens else 0,
                    "source": "AgentContextRuntime memory_recall.tokenEstimate",
                },
                "runtimePrompt": {
                    "total": sum(runtime_tokens),
                    "average": round(sum(runtime_tokens) / len(runtime_tokens), 3)
                    if runtime_tokens
                    else 0.0,
                    "max": max(runtime_tokens) if runtime_tokens else 0,
                    "source": "AgentContextRuntime runtime_request.tokenEstimate",
                },
            },
        },
        "cases": cases,
        "evidenceBoundary": {
            "dataClass": "synthetic_labeled_fixture",
            "runtimePath": [
                "AgentService.prompt",
                "AgentPromptDeliveryService.deliver",
                "SessionMemoryRecallBuilder.build",
                "AgentContextRuntime.materialize_for_delivery",
                "AgentContextRuntime.trace",
            ],
            "retrievalProjection": [
                "rebuild_retrieval_docs",
                "rebuild_retrieval_doc_vectors",
            ],
            "providerCalls": 0 if not configured else callback_provider_calls,
            "providerAdapter": "local deterministic Pi acceptance ACK for context-owner turns",
            "consumerAdapter": (
                "configured callback result" if configured else "none"
            ),
            "agentServiceReopenResume": True,
            "consumerCallbackConfigured": configured,
            "maxConsumerCompletionsPerFixture": 1,
            "traceStagesChecked": list(REQUIRED_TRACE_STAGES),
            "formalAgentLabJob": False,
            "modelAnswerQuality": (
                "unmeasured" if not configured else "host_rubric_observed"
            ),
            "installedRuntimeVerified": False,
            "nativeForegroundVerified": False,
            "sourceRuntimeEvidenceOnly": True,
        },
        "selfbootLabTrace": {
            "runner": "scripts/eval_paw_context_continuation.py",
            "mode": "small local Lab-style fixture runner",
            "traceEvidence": "each initial and resumed turn has an accepted Context Trace",
            "providerCalls": 0 if not configured else callback_provider_calls,
            "resumeEvidence": "reopen AgentService, refresh compaction context, deliver continuation; initial ACK and compaction summary are synthetic fixture inputs; OS process restart is unverified",
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="write the privacy-safe receipt to this path (prefer outside the repo)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_evaluation()
    payload = _canonical(result) + "\n"
    if args.output is not None:
        output_path = args.output.resolve(strict=False)
        if output_path == ROOT or ROOT in output_path.parents:
            raise SystemExit("--output must point outside the repository")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            output_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
