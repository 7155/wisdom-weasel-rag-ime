from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import Any, Callable, Protocol, Sequence

from ..deepseek_config import DeepSeekConfig, load_deepseek_config
from ..deepseek_completion import _direct_deepseek_urlopen


_EXTRACTOR_SCHEMA_VERSION = "graph-extractor-v1"
_LINK_OR_QUOTE_RE = re.compile(
    r"\[([^\]\n]{2,80})\]\([^\)\n]+\)|[\"'“‘]([^\"'”’\n]{2,80})[\"'”’]"
)
_CODE_TERM_RE = re.compile(r"`([^`\n]{2,80})`")
_CODE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./:+-]{2,64}$")
# ``\w`` is Unicode-aware in Python. Require a letter-like first character,
# then allow bounded letters, digits, spaces, underscores, and hyphens. The
# previous ASCII-only contract silently discarded valid Chinese relation types
# such as “审批” after otherwise successful model extraction.
_RELATION_TYPE_RE = re.compile(r"^[^\W\d_][\w -]{0,47}$", re.UNICODE)


@dataclass(frozen=True)
class GraphExtractionInput:
    chunk_id: str
    document_id: str
    content_hash: str
    heading: str
    content: str


@dataclass(frozen=True)
class ExtractedEntity:
    name: str
    entity_type: str = "Entity"
    evidence: str = ""


@dataclass(frozen=True)
class ExtractedRelation:
    source: str
    target: str
    relation_type: str
    evidence: str
    confidence: float


@dataclass(frozen=True)
class GraphExtraction:
    chunk_id: str
    topics: tuple[str, ...] = ()
    entities: tuple[ExtractedEntity, ...] = ()
    terms: tuple[str, ...] = ()
    relations: tuple[ExtractedRelation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunkId": self.chunk_id,
            "topics": list(self.topics),
            "entities": [
                {"name": item.name, "type": item.entity_type, "evidence": item.evidence}
                for item in self.entities
            ],
            "terms": list(self.terms),
            "relations": [
                {
                    "source": item.source,
                    "target": item.target,
                    "type": item.relation_type,
                    "evidence": item.evidence,
                    "confidence": item.confidence,
                }
                for item in self.relations
            ],
        }


class GraphExtractor(Protocol):
    mode: str
    fingerprint: str

    def extract(self, inputs: Sequence[GraphExtractionInput]) -> dict[str, GraphExtraction]:
        ...


class DeterministicGraphExtractor:
    mode = "deterministic"
    fingerprint = "deterministic:quality-v2"

    def extract(self, inputs: Sequence[GraphExtractionInput]) -> dict[str, GraphExtraction]:
        results: dict[str, GraphExtraction] = {}
        for item in inputs:
            entities: list[ExtractedEntity] = []
            for match in _LINK_OR_QUOTE_RE.finditer(item.content[:100_000]):
                label = next((value.strip() for value in match.groups() if value and value.strip()), "")
                if _valid_name(label) and label.casefold() not in {entity.name.casefold() for entity in entities}:
                    entities.append(ExtractedEntity(label, "ExplicitConcept", label))
                if len(entities) >= 4:
                    break
            terms: list[str] = []
            for match in _CODE_TERM_RE.finditer(item.content[:100_000]):
                label = match.group(1).strip()
                if (
                    _valid_name(label)
                    and _CODE_TOKEN_RE.fullmatch(label)
                    and label.casefold() not in {term.casefold() for term in terms}
                ):
                    terms.append(label)
                if len(terms) >= 4:
                    break
            results[item.chunk_id] = GraphExtraction(
                chunk_id=item.chunk_id,
                topics=(),
                entities=tuple(entities),
                terms=tuple(terms),
            )
        return results


class OpenAICompatibleGraphExtractor:
    mode = "model"

    def __init__(
        self,
        config: DeepSeekConfig,
        *,
        urlopen: Callable[..., Any] | None = None,
        extraction_concurrency: int = 2,
        max_entities: int = 5,
        max_relations: int = 4,
        max_topics: int = 2,
    ) -> None:
        self.config = config
        self.configured = bool(config.api_key)
        self.urlopen = urlopen or _direct_deepseek_urlopen
        self.max_entities = max(1, min(8, int(max_entities)))
        self.max_relations = max(0, min(8, int(max_relations)))
        self.max_topics = max(0, min(4, int(max_topics)))
        self.extraction_concurrency = max(1, min(4, int(extraction_concurrency)))
        public_config = {
            "schema": _EXTRACTOR_SCHEMA_VERSION,
            "provider": config.provider_name,
            "baseUrl": config.api_base_url,
            "model": config.model,
            "thinking": config.thinking,
            "reasoningEffort": config.reasoning_effort,
            "jsonMode": config.json_mode,
            "maxTokens": max(512, min(4_096, int(config.knowledge_max_tokens))),
            "maxEntities": self.max_entities,
            "maxRelations": self.max_relations,
            "maxTopics": self.max_topics,
            "extractionConcurrency": self.extraction_concurrency,
        }
        self.fingerprint = "model:sha256:" + hashlib.sha256(
            json.dumps(public_config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def extract(self, inputs: Sequence[GraphExtractionInput]) -> dict[str, GraphExtraction]:
        if not self.config.api_key:
            raise RuntimeError("knowledge graph model extractor requires the configured knowledge API key")
        payload_inputs = [
            {
                "chunkId": item.chunk_id,
                "heading": item.heading[:300],
                "text": item.content[:6_000],
            }
            for item in inputs
        ]
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": json.dumps({"chunks": payload_inputs}, ensure_ascii=False)},
            ],
            "temperature": 0.0,
            "max_tokens": max(512, min(4_096, int(self.config.knowledge_max_tokens))),
            "stream": False,
        }
        if self.config.json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.config.thinking:
            body["thinking"] = {"type": self.config.thinking}
        if self.config.reasoning_effort and self.config.thinking != "disabled":
            body["reasoning_effort"] = self.config.reasoning_effort
        request = urllib.request.Request(
            f"{self.config.api_base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "rag-ime/1.0 offline-knowledge-graph",
                **dict(self.config.extra_headers),
            },
            method="POST",
        )
        try:
            with self.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                raw_response = response.read(2 * 1024 * 1024 + 1)
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise RuntimeError(f"knowledge graph model request failed: {exc}") from exc
        if len(raw_response) > 2 * 1024 * 1024:
            raise RuntimeError("knowledge graph model response exceeded 2 MiB")
        try:
            response_payload = json.loads(raw_response.decode("utf-8"))
            content = _chat_content(response_payload)
            extracted = _json_object(content)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError("knowledge graph model returned invalid JSON") from exc
        by_id = {item.chunk_id: item for item in inputs}
        raw_chunks = extracted.get("chunks")
        if not isinstance(raw_chunks, list):
            raise RuntimeError("knowledge graph model JSON is missing chunks[]")
        results: dict[str, GraphExtraction] = {}
        for raw_chunk in raw_chunks:
            if not isinstance(raw_chunk, dict):
                continue
            chunk_id = str(raw_chunk.get("chunkId") or "")
            source = by_id.get(chunk_id)
            if source is None:
                continue
            results[chunk_id] = _normalize_model_chunk(
                raw_chunk,
                source,
                max_entities=self.max_entities,
                max_relations=self.max_relations,
                max_topics=self.max_topics,
            )
        return results

    def _system_prompt(self) -> str:
        return (
            "You extract a small evidence-grounded knowledge graph from document chunks. "
            "Return one strict JSON object and no Markdown. Output: "
            "{\"chunks\":[{\"chunkId\":\"exact input id\",\"topics\":[\"0-2 canonical topics\"],"
            "\"entities\":[{\"name\":\"canonical name\",\"type\":\"specific type\","
            "\"evidence\":\"exact short quote\"}],\"relations\":[{\"source\":\"entity name\","
            "\"target\":\"entity name\",\"type\":\"specific verb phrase\","
            "\"evidence\":\"exact short quote supporting the relation\",\"confidence\":0.0}]}]}. "
            f"Hard limits per chunk: {self.max_topics} topics, {self.max_entities} entities, "
            f"{self.max_relations} relations. Extract only durable named concepts that matter to the text. "
            "Do not turn every acronym, capitalized word, heading fragment, or generic noun into an entity. "
            "Every entity and relation must be supported by an exact quote in the same chunk. "
            "Omit uncertain items; never invent cross-chunk facts."
        )


def graph_extractor_from_config(
    mode: str,
    *,
    model_id: str = "",
    extraction_concurrency: int = 2,
    max_entities: int = 5,
    max_relations: int = 4,
    max_topics: int = 2,
) -> GraphExtractor:
    normalized_mode = str(mode or "deterministic").strip().lower()
    if normalized_mode == "deterministic":
        return DeterministicGraphExtractor()
    if normalized_mode != "model":
        raise ValueError(f"unsupported graph extractor mode: {mode}")
    config = load_deepseek_config()
    if model_id:
        config = replace(config, model=str(model_id).strip())
    return OpenAICompatibleGraphExtractor(
        config,
        extraction_concurrency=extraction_concurrency,
        max_entities=max_entities,
        max_relations=max_relations,
        max_topics=max_topics,
    )


def extraction_from_dict(value: dict[str, Any], source: GraphExtractionInput) -> GraphExtraction:
    normalized = _normalize_model_chunk(
        value,
        source,
        max_entities=8,
        max_relations=8,
        max_topics=4,
    )
    terms: list[str] = []
    for raw_term in value.get("terms") if isinstance(value.get("terms"), list) else []:
        term = _clean_name(raw_term)
        if _valid_name(term) and term.casefold() in source.content.casefold():
            _append_unique(terms, term, 8)
    return GraphExtraction(
        chunk_id=normalized.chunk_id,
        topics=normalized.topics,
        entities=normalized.entities,
        terms=tuple(terms),
        relations=normalized.relations,
    )


def _normalize_model_chunk(
    raw: dict[str, Any],
    source: GraphExtractionInput,
    *,
    max_entities: int,
    max_relations: int,
    max_topics: int,
) -> GraphExtraction:
    source_folded = source.content.casefold()
    topics: list[str] = []
    for raw_topic in raw.get("topics") if isinstance(raw.get("topics"), list) else []:
        topic = _clean_name(raw_topic)
        if _valid_name(topic) and _topic_grounded(topic, source.content):
            _append_unique(topics, topic, max_topics)
    entities: list[ExtractedEntity] = []
    entity_names: dict[str, str] = {}
    raw_entities = raw.get("entities") if isinstance(raw.get("entities"), list) else []
    for raw_entity in raw_entities:
        if not isinstance(raw_entity, dict):
            continue
        name = _clean_name(raw_entity.get("name"))
        evidence = " ".join(str(raw_entity.get("evidence") or "").split())[:240]
        entity_type = _clean_type(raw_entity.get("type"), default="Entity")
        if not _valid_name(name) or name.casefold() not in source_folded or not _exact_evidence(evidence, source.content):
            continue
        key = name.casefold()
        if key in entity_names:
            continue
        entity_names[key] = name
        entities.append(ExtractedEntity(name, entity_type, evidence))
        if len(entities) >= max_entities:
            break
    relations: list[ExtractedRelation] = []
    raw_relations = raw.get("relations") if isinstance(raw.get("relations"), list) else []
    for raw_relation in raw_relations:
        if not isinstance(raw_relation, dict):
            continue
        source_name = entity_names.get(_clean_name(raw_relation.get("source")).casefold(), "")
        target_name = entity_names.get(_clean_name(raw_relation.get("target")).casefold(), "")
        relation_type = _clean_type(raw_relation.get("type"), default="related_to")
        evidence = " ".join(str(raw_relation.get("evidence") or "").split())[:240]
        try:
            confidence = float(raw_relation.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if (
            not source_name
            or not target_name
            or source_name == target_name
            or confidence < 0.6
            or not _RELATION_TYPE_RE.fullmatch(relation_type)
            or not _exact_evidence(evidence, source.content)
        ):
            continue
        relations.append(
            ExtractedRelation(source_name, target_name, relation_type, evidence, min(1.0, confidence))
        )
        if len(relations) >= max_relations:
            break
    return GraphExtraction(source.chunk_id, tuple(topics), tuple(entities), (), tuple(relations))


def _chat_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ValueError("response must be an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("response choices are missing")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("response message content is missing")
    return str(message["content"])


def _json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("extraction payload must be an object")
    return parsed


def _clean_name(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()[:80]


def _clean_type(value: Any, *, default: str) -> str:
    result = " ".join(str(value or default).replace("\x00", " ").split()).strip()[:48]
    return result or default


def _valid_name(value: str) -> bool:
    return 2 <= len(value) <= 80 and not value.isdigit()


def _exact_evidence(evidence: str, content: str) -> bool:
    return 2 <= len(evidence) <= 240 and evidence.casefold() in content.casefold()


def _topic_grounded(topic: str, content: str) -> bool:
    folded = content.casefold()
    if topic.casefold() in folded:
        return True
    tokens = [token for token in re.split(r"\W+", topic.casefold()) if len(token) >= 2]
    return bool(tokens) and sum(token in folded for token in tokens) >= max(1, len(tokens) // 2)


def _append_unique(values: list[str], value: str, limit: int) -> None:
    if len(values) >= limit or value.casefold() in {item.casefold() for item in values}:
        return
    values.append(value)
