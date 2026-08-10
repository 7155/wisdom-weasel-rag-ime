#!/usr/bin/env python3
"""Build the project-level Wayfinder projection from authoritative Markdown.

The reconstruction manifest owns only Project/Room identity, island geometry,
and source receipts.  This module owns the deterministic translation from the
reviewed Markdown package into the user-facing project meaning: initial vision,
destination, vertical requirement Rooms, semantic relations, delivery stages,
and document/source traceability.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Collection, Mapping, Sequence


WAYFINDER_PROJECTION_SCHEMA = "personal-agent.project-wayfinder.v2"
WAYFINDER_PACKAGE_RELATIVE = Path(
    "design-system/rag-ime-control-center/prototypes/room-navigation-wayfinder"
)

DELIVERY_STAGES: tuple[tuple[str, str], ...] = (
    ("alignment-and-decision", "需求对齐"),
    ("implementation-planning", "实现规划"),
    ("implementation-execution", "实现执行"),
    ("quality-gate", "质量门"),
    ("independent-review", "独立复核"),
)
DELIVERY_STAGE_IDS = {stage_id for stage_id, _ in DELIVERY_STAGES}
DELIVERY_STATES = {"accepted", "active", "queued"}
RELATION_KINDS = {"refines", "led-to", "requires"}
TOPOLOGY_ROLES = {"room", "release-lane"}
PROGRESS_STATES = {"verified", "pending"}
DOCUMENT_ROLES = {"map", "initial-vision", "destination", "room"}

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SOURCE_REF = re.compile(r"^- `([^`]+)`$")
MAP_LINK = re.compile(r"^- \[([^\]]+)\]\(([^)]+)\) — (.+)$")
RELATION = re.compile(
    r"^- `([^`]+)` -> `([^`]+)` \| `(refines|led-to|requires)` \| (.+?) \| refs: (.+)$"
)
ACCEPTANCE = re.compile(r"^- \[([ x])\] (.+?) \| refs: (.+)$")
EPOCH = re.compile(r"^- `([^`]+)` \| `([^`]+)` \| `([^`]+)` \| (.+)$")
RELEASE_LANE_ROOM = re.compile(r"^- Room: `([^`]+)`$")
RELEASE_CHECKPOINT = re.compile(r"^- `([^`]+)` \| `([^`]+)` \| (.+)$")
BACKTICK_REF = re.compile(r"`([^`]+)`")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STAGE = re.compile(r"^- `([^`]+)` \| (.+)$")
INNER_METHOD = re.compile(r"^- Inner method: `([^`]+)` -> `([^`]+)` \| (.+)$")
SAFE_REF = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+\.md$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ABSOLUTE_PATH = re.compile(r"(?:^|[\s'\"])(?:/Users/|/Volumes/|[A-Za-z]:\\)")
FORBIDDEN_PROJECT_COPY = (
    "仍在迷雾中",
    "assistant reasoning",
    "chain of thought",
    "思考过程",
)


class WayfinderProjectionError(ValueError):
    """Raised when authoritative docs or their projection violate the contract."""


@dataclass(frozen=True)
class MarkdownDocument:
    ref: str
    title: str
    metadata: Mapping[str, str]
    sections: Mapping[str, str]
    source_refs: tuple[str, ...]
    sha256: str
    text: str


def _plain(value: str) -> str:
    text = value.strip()
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", text).strip()


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WayfinderProjectionError(f"{label} must be a non-empty string")
    if ABSOLUTE_PATH.search(value):
        raise WayfinderProjectionError(f"{label} contains an absolute machine path")
    return value.strip()


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WayfinderProjectionError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise WayfinderProjectionError(f"{label} must be an array")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: Collection[str], label: str) -> None:
    actual = set(value)
    expected_set = set(expected)
    if actual != expected_set:
        missing = sorted(expected_set - actual)
        extra = sorted(actual - expected_set)
        raise WayfinderProjectionError(
            f"{label} keys drifted; missing={missing}, extra={extra}"
        )


def _require_unique_strings(value: Any, label: str, *, minimum: int = 0) -> list[str]:
    items = _require_list(value, label)
    if len(items) < minimum:
        raise WayfinderProjectionError(f"{label} must contain at least {minimum} item(s)")
    parsed = [_require_string(item, f"{label}[{index}]") for index, item in enumerate(items)]
    if len(set(parsed)) != len(parsed):
        raise WayfinderProjectionError(f"{label} must not contain duplicates")
    return parsed


def _safe_ref(value: str, label: str = "document ref") -> str:
    ref = _require_string(value, label)
    if SAFE_REF.fullmatch(ref) is None:
        raise WayfinderProjectionError(f"unsafe Markdown document ref: {ref}")
    return ref


def _metadata(text: str, ref: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith(">"):
            continue
        match = re.match(r"^>\s*([^：:]+)[：:]\s*(.*?)\s*$", line)
        if match is None:
            continue
        key = _plain(match.group(1))
        value = _plain(match.group(2))
        if key in result:
            raise WayfinderProjectionError(f"duplicate metadata key {key!r} in {ref}")
        result[key] = value
    return result


def _sections(text: str, ref: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        match = HEADING.match(line)
        if match is not None and len(match.group(1)) == 2:
            if current is not None:
                result[current] = "\n".join(buffer).strip()
            current = _plain(match.group(2))
            if current in result:
                raise WayfinderProjectionError(f"duplicate section {current!r} in {ref}")
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        result[current] = "\n".join(buffer).strip()
    return result


def _title(text: str, ref: str) -> str:
    titles = [
        _plain(match.group(2))
        for line in text.splitlines()
        if (match := HEADING.match(line)) is not None and len(match.group(1)) == 1
    ]
    if len(titles) != 1:
        raise WayfinderProjectionError(f"{ref} must contain exactly one H1")
    return _require_string(titles[0], f"{ref} title")


def _section(document: MarkdownDocument, name: str) -> str:
    value = document.sections.get(name)
    if value is None or not value.strip():
        raise WayfinderProjectionError(f"{document.ref} is missing section {name!r}")
    return value


def _paragraphs(section: str, label: str) -> list[str]:
    paragraphs: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        rendered = _plain(" ".join(buffer))
        if rendered:
            paragraphs.append(rendered)
        buffer.clear()

    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith(("- ", "|", "```", "### ")):
            flush()
            continue
        buffer.append(line)
    flush()
    if not paragraphs:
        raise WayfinderProjectionError(f"{label} must contain prose")
    return paragraphs


def _first_paragraph(document: MarkdownDocument, section_name: str) -> str:
    return _paragraphs(
        _section(document, section_name),
        f"{document.ref} section {section_name}",
    )[0]


def _bullets(document: MarkdownDocument, section_name: str) -> list[str]:
    values = [
        _plain(line[2:])
        for line in _section(document, section_name).splitlines()
        if line.startswith("- ")
    ]
    if not values or any(not value for value in values):
        raise WayfinderProjectionError(
            f"{document.ref} section {section_name!r} must contain non-empty bullets"
        )
    if len(set(values)) != len(values):
        raise WayfinderProjectionError(
            f"{document.ref} section {section_name!r} must not contain duplicate bullets"
        )
    return values


def _receipt_refs(value: str, label: str) -> list[str]:
    refs = BACKTICK_REF.findall(value)
    normalized = ", ".join(f"`{ref}`" for ref in refs)
    if not refs or normalized != value.strip() or len(set(refs)) != len(refs):
        raise WayfinderProjectionError(
            f"{label} must contain unique backticked receipt ids separated by ', '"
        )
    return refs


def _acceptance_progress(document: MarkdownDocument) -> tuple[list[str], dict[str, Any]]:
    observations: list[str] = []
    items: list[dict[str, Any]] = []
    for index, raw_line in enumerate(_section(document, "Observable acceptance").splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        match = ACCEPTANCE.fullmatch(line)
        if match is None:
            raise WayfinderProjectionError(
                f"{document.ref} Observable acceptance must use '- [x] criterion | refs: `receipt`'"
            )
        label = _plain(match.group(2))
        if not label or label in observations:
            raise WayfinderProjectionError(
                f"{document.ref} Observable acceptance items must be non-empty and unique"
            )
        state = "verified" if match.group(1) == "x" else "pending"
        source_refs = _receipt_refs(
            match.group(3),
            f"{document.ref} Observable acceptance item {index} refs",
        )
        observations.append(label)
        items.append({"label": label, "state": state, "sourceRefs": source_refs})
    if not items:
        raise WayfinderProjectionError(
            f"{document.ref} Observable acceptance must not be empty"
        )
    completed = sum(item["state"] == "verified" for item in items)
    return observations, {
        "basis": "acceptance-evidence",
        "completed": completed,
        "total": len(items),
        "items": items,
    }


def _source_refs(document: MarkdownDocument) -> tuple[str, ...]:
    refs: list[str] = []
    for line in _section(document, "Source refs").splitlines():
        if not line.strip():
            continue
        match = SOURCE_REF.fullmatch(line.strip())
        if match is None:
            raise WayfinderProjectionError(
                f"{document.ref} Source refs must be one receipt id per bullet"
            )
        refs.append(match.group(1))
    if not refs or len(set(refs)) != len(refs):
        raise WayfinderProjectionError(f"{document.ref} Source refs must be non-empty and unique")
    return tuple(refs)


def _read_document(package_root: Path, ref: str) -> MarkdownDocument:
    safe_ref = _safe_ref(ref)
    root = package_root.resolve()
    path = (root / safe_ref).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WayfinderProjectionError(f"document escaped Wayfinder package: {safe_ref}") from exc
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WayfinderProjectionError(f"cannot read Wayfinder document {safe_ref}: {exc}") from exc
    document = MarkdownDocument(
        ref=safe_ref,
        title=_title(text, safe_ref),
        metadata=_metadata(text, safe_ref),
        sections=_sections(text, safe_ref),
        source_refs=(),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
    )
    return MarkdownDocument(
        **{**document.__dict__, "source_refs": _source_refs(document)},
    )


def _single_map_link(document: MarkdownDocument, section_name: str) -> tuple[str, str, str]:
    lines = [line.strip() for line in _section(document, section_name).splitlines() if line.strip()]
    if len(lines) != 1 or (match := MAP_LINK.fullmatch(lines[0])) is None:
        raise WayfinderProjectionError(
            f"{document.ref} {section_name} must contain one '- [title](ref) — summary' link"
        )
    return _plain(match.group(1)), _safe_ref(match.group(2)), _plain(match.group(3))


def _room_links(document: MarkdownDocument) -> list[tuple[str, str, str]]:
    links: list[tuple[str, str, str]] = []
    for line in _section(document, "Rooms").splitlines():
        if not line.strip():
            continue
        match = MAP_LINK.fullmatch(line.strip())
        if match is None:
            raise WayfinderProjectionError(
                f"{document.ref} Rooms must use '- [title](ref) — requirement summary'"
            )
        links.append((_plain(match.group(1)), _safe_ref(match.group(2)), _plain(match.group(3))))
    if not links:
        raise WayfinderProjectionError(f"{document.ref} must index at least one Room")
    if len({ref for _, ref, _ in links}) != len(links):
        raise WayfinderProjectionError(f"{document.ref} Room refs must be unique")
    return links


def _relations(document: MarkdownDocument) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in _section(document, "Relations").splitlines():
        if not line.strip():
            continue
        match = RELATION.fullmatch(line.strip())
        if match is None:
            raise WayfinderProjectionError(
                f"{document.ref} Relations must use '- `from` -> `to` | `kind` | label'"
            )
        key = (match.group(1), match.group(2), match.group(3))
        if key in seen:
            raise WayfinderProjectionError(f"duplicate relation in {document.ref}: {key}")
        seen.add(key)
        relations.append(
            {
                "from": match.group(1),
                "to": match.group(2),
                "kind": match.group(3),
                "label": _plain(match.group(4)),
                "sourceRefs": _receipt_refs(
                    match.group(5),
                    f"{document.ref} relation {match.group(1)} -> {match.group(2)} refs",
                ),
            }
        )
    if not relations:
        raise WayfinderProjectionError(f"{document.ref} Relations must not be empty")
    return relations


def _evolution(document: MarkdownDocument) -> dict[str, Any]:
    epochs: list[dict[str, str]] = []
    epoch_ids: set[str] = set()
    for raw_line in _section(document, "Evolution epochs").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = EPOCH.fullmatch(line)
        if match is None:
            raise WayfinderProjectionError(
                f"{document.ref} Evolution epochs must use '- `id` | `range` | `label` | summary'"
            )
        epoch_id = match.group(1)
        if epoch_id in epoch_ids:
            raise WayfinderProjectionError(f"duplicate evolution epoch: {epoch_id}")
        epoch_ids.add(epoch_id)
        epochs.append(
            {
                "id": epoch_id,
                "range": match.group(2),
                "label": match.group(3),
                "summary": _plain(match.group(4)),
            }
        )
    if not epochs:
        raise WayfinderProjectionError(f"{document.ref} Evolution epochs must not be empty")

    release_room_id: str | None = None
    checkpoints: list[dict[str, Any]] = []
    for index, raw_line in enumerate(_section(document, "Release lane").splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        room_match = RELEASE_LANE_ROOM.fullmatch(line)
        if room_match is not None:
            if release_room_id is not None:
                raise WayfinderProjectionError("Release lane must define one Room")
            release_room_id = room_match.group(1)
            continue
        checkpoint_match = RELEASE_CHECKPOINT.fullmatch(line)
        if checkpoint_match is None:
            raise WayfinderProjectionError(
                f"{document.ref} Release lane checkpoints must use '- `date` | `label` | `receipt`'"
            )
        observed_at = checkpoint_match.group(1)
        if ISO_DATE.fullmatch(observed_at) is None:
            raise WayfinderProjectionError(
                f"{document.ref} Release lane checkpoint {index} has an invalid date"
            )
        checkpoints.append(
            {
                "observedAt": observed_at,
                "label": checkpoint_match.group(2),
                "sourceRefs": _receipt_refs(
                    checkpoint_match.group(3),
                    f"{document.ref} Release lane checkpoint {index} refs",
                ),
            }
        )
    if release_room_id is None or not checkpoints:
        raise WayfinderProjectionError("Release lane must define a Room and checkpoints")
    if len({(item["observedAt"], item["label"]) for item in checkpoints}) != len(checkpoints):
        raise WayfinderProjectionError("Release lane checkpoints must be unique")
    if [item["observedAt"] for item in checkpoints] != sorted(
        item["observedAt"] for item in checkpoints
    ):
        raise WayfinderProjectionError("Release lane checkpoints must be chronological")
    return {
        "direction": "left-to-right",
        "epochs": epochs,
        "releaseLane": {"roomId": release_room_id, "checkpoints": checkpoints},
    }


def _delivery_engine(document: MarkdownDocument) -> dict[str, Any]:
    stages: list[dict[str, str]] = []
    inner_method: dict[str, str] | None = None
    for line in _section(document, "Delivery engine").splitlines():
        line = line.strip()
        if not line:
            continue
        inner_match = INNER_METHOD.fullmatch(line)
        if inner_match is not None:
            if inner_method is not None:
                raise WayfinderProjectionError("Delivery engine must define one inner method")
            inner_method = {
                "id": inner_match.group(1),
                "parentStage": inner_match.group(2),
                "title": _plain(inner_match.group(3)),
            }
            continue
        stage_match = STAGE.fullmatch(line)
        if stage_match is None:
            raise WayfinderProjectionError(
                "Delivery engine stages must use '- `stage-id` | title'"
            )
        stages.append({"id": stage_match.group(1), "title": _plain(stage_match.group(2))})
    expected = [{"id": stage_id, "title": title} for stage_id, title in DELIVERY_STAGES]
    if stages != expected:
        raise WayfinderProjectionError("Delivery engine outer stages drifted")
    if inner_method != {
        "id": "test-driven-implementation",
        "parentStage": "implementation-execution",
        "title": "测试驱动实现",
    }:
        raise WayfinderProjectionError(
            "test-driven-implementation must remain the inner method of implementation-execution"
        )
    return {"stages": stages, "innerMethod": inner_method}


def _detail_document_refs(document: MarkdownDocument) -> list[str]:
    section = document.sections.get("Delivery docs")
    if section is None or not section.strip():
        return []
    refs: list[str] = []
    for line in section.splitlines():
        if not line.strip():
            continue
        match = MAP_LINK.fullmatch(line.strip())
        if match is None:
            raise WayfinderProjectionError(
                f"{document.ref} Delivery docs must use '- [title](ref) — summary'"
            )
        refs.append(_safe_ref(match.group(2)))
    if len(set(refs)) != len(refs):
        raise WayfinderProjectionError(f"{document.ref} Delivery docs must be unique")
    return refs


def _document_entry(role: str, document: MarkdownDocument, *, room_id: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "role": role,
        "ref": document.ref,
        "title": document.title,
        "sha256": document.sha256,
        "sourceRefs": list(document.source_refs),
    }
    if room_id is not None:
        entry["roomId"] = room_id
    return entry


def _ordered_union(groups: Sequence[Sequence[str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            if value not in seen:
                seen.add(value)
                result.append(value)
    return result


def build_wayfinder_projection(
    package_root: Path,
    *,
    expected_project_id: str,
    expected_current_room_id: str,
    room_boundaries: Mapping[str, str],
    available_source_ids_by_room: Mapping[str, Collection[str]],
) -> dict[str, Any]:
    """Parse the authoritative docs package into one deterministic projection."""

    map_document = _read_document(package_root, "00-map.md")
    if map_document.metadata.get("Project") != expected_project_id:
        raise WayfinderProjectionError("00-map.md Project metadata does not match the manifest")
    if map_document.metadata.get("Current Room") != expected_current_room_id:
        raise WayfinderProjectionError("00-map.md Current Room metadata does not match the manifest")

    initial_title, initial_ref, _ = _single_map_link(map_document, "Initial vision")
    destination_title, destination_ref, _ = _single_map_link(map_document, "Destination")
    initial_document = _read_document(package_root, initial_ref)
    destination_document = _read_document(package_root, destination_ref)
    if initial_document.title != initial_title:
        raise WayfinderProjectionError("Initial vision title drifted from 00-map.md")
    if destination_document.title != destination_title:
        raise WayfinderProjectionError("Destination title drifted from 00-map.md")
    if destination_document.metadata.get("State") != "unreached":
        raise WayfinderProjectionError("Destination must remain unreached until every Room is accepted")

    evolution = _evolution(map_document)
    epoch_ids = {epoch["id"] for epoch in evolution["epochs"]}
    room_documents: list[MarkdownDocument] = []
    room_projections: list[dict[str, Any]] = []
    indexed_room_ids: list[str] = []
    for indexed_title, ref, indexed_requirement in _room_links(map_document):
        document = _read_document(package_root, ref)
        room_id = document.metadata.get("Room")
        if room_id is None:
            raise WayfinderProjectionError(f"{ref} is missing Room metadata")
        if room_id not in room_boundaries:
            raise WayfinderProjectionError(f"{ref} names an unknown Room: {room_id}")
        if room_id in indexed_room_ids:
            raise WayfinderProjectionError(f"Room is indexed more than once: {room_id}")
        if document.title != indexed_title or room_boundaries[room_id] != indexed_title:
            raise WayfinderProjectionError(f"Room title drifted for {room_id}")
        current_stage = document.metadata.get("Stage")
        delivery_state = document.metadata.get("Delivery")
        if current_stage not in DELIVERY_STAGE_IDS:
            raise WayfinderProjectionError(f"{ref} has unsupported Stage metadata")
        if delivery_state not in DELIVERY_STATES:
            raise WayfinderProjectionError(f"{ref} has unsupported Delivery metadata")
        if delivery_state == "accepted" and current_stage != "independent-review":
            raise WayfinderProjectionError(f"accepted Room {room_id} must be at independent-review")
        epoch_id = document.metadata.get("Epoch")
        emerged_at = document.metadata.get("Emerged")
        topology_role = document.metadata.get("Topology")
        if epoch_id not in epoch_ids:
            raise WayfinderProjectionError(f"{ref} has an unknown Epoch")
        if emerged_at is None or ISO_DATE.fullmatch(emerged_at) is None:
            raise WayfinderProjectionError(f"{ref} has invalid Emerged metadata")
        if topology_role not in TOPOLOGY_ROLES:
            raise WayfinderProjectionError(f"{ref} has unsupported Topology metadata")
        requirement = _first_paragraph(document, "Requirement")
        if indexed_requirement != requirement:
            raise WayfinderProjectionError(f"00-map.md requirement summary drifted for {room_id}")
        detail_refs = _detail_document_refs(document)
        for detail_ref in detail_refs:
            detail_path = (package_root / detail_ref).resolve()
            try:
                detail_path.relative_to(package_root.resolve())
            except ValueError as exc:
                raise WayfinderProjectionError(f"delivery doc escaped package: {detail_ref}") from exc
            if not detail_path.is_file():
                raise WayfinderProjectionError(f"delivery doc does not exist: {detail_ref}")
        room_documents.append(document)
        indexed_room_ids.append(room_id)
        acceptance_observations, progress = _acceptance_progress(document)
        room_projections.append(
            {
                "roomId": room_id,
                "title": document.title,
                "requirement": requirement,
                "problem": _first_paragraph(document, "Problem"),
                "decisions": _bullets(document, "Decisions"),
                "acceptanceObservations": acceptance_observations,
                "currentStage": current_stage,
                "deliveryState": delivery_state,
                "emergedAt": emerged_at,
                "epochId": epoch_id,
                "topologyRole": topology_role,
                "progress": progress,
                "currentDelivery": _first_paragraph(document, "Current delivery"),
                "nextMove": _first_paragraph(document, "Next move"),
                "documentRef": document.ref,
                "detailDocumentRefs": detail_refs,
                "sourceRefs": list(document.source_refs),
            }
        )

    if set(indexed_room_ids) != set(room_boundaries):
        raise WayfinderProjectionError(
            "00-map.md Rooms must match manifest Room boundaries exactly"
        )

    relations = _relations(map_document)
    delivery_engine = _delivery_engine(map_document)
    all_source_ids = set().union(
        *(set(source_ids) for source_ids in available_source_ids_by_room.values())
    )
    documents = [
        _document_entry("map", map_document),
        _document_entry("initial-vision", initial_document),
        _document_entry("destination", destination_document),
        *(
            _document_entry("room", document, room_id=room_id)
            for room_id, document in zip(indexed_room_ids, room_documents, strict=True)
        ),
    ]
    projection = {
        "schemaVersion": WAYFINDER_PROJECTION_SCHEMA,
        "projectId": expected_project_id,
        "currentRoomId": expected_current_room_id,
        "initialVision": {
            "title": initial_document.title,
            "statement": _first_paragraph(initial_document, "Statement"),
            "observableAnchors": _bullets(initial_document, "Observable anchors"),
            "documentRef": initial_document.ref,
            "sourceRefs": list(initial_document.source_refs),
        },
        "destination": {
            "title": destination_document.title,
            "statement": _first_paragraph(destination_document, "Statement"),
            "state": "unreached",
            "acceptanceObservations": _bullets(destination_document, "Completion observations"),
            "documentRef": destination_document.ref,
            "sourceRefs": list(destination_document.source_refs),
        },
        "deliveryEngine": delivery_engine,
        "evolution": evolution,
        "rooms": room_projections,
        "relations": relations,
        "documents": documents,
        "sourceRefs": _ordered_union([document["sourceRefs"] for document in documents]),
    }
    validate_wayfinder_projection(
        projection,
        expected_project_id=expected_project_id,
        expected_current_room_id=expected_current_room_id,
        room_boundaries=room_boundaries,
        available_source_ids_by_room=available_source_ids_by_room,
    )
    if set(projection["sourceRefs"]) != all_source_ids:
        raise WayfinderProjectionError("Wayfinder docs do not cover every manifest source receipt")
    return projection


def validate_wayfinder_projection(
    value: Mapping[str, Any],
    *,
    expected_project_id: str,
    expected_current_room_id: str,
    room_boundaries: Mapping[str, str],
    available_source_ids_by_room: Mapping[str, Collection[str]],
) -> None:
    """Fail closed across meaning, Room network, delivery flow, docs, and receipts."""

    projection = _require_mapping(value, "wayfinder")
    _require_exact_keys(
        projection,
        {
            "schemaVersion",
            "projectId",
            "currentRoomId",
            "initialVision",
            "destination",
            "deliveryEngine",
            "evolution",
            "rooms",
            "relations",
            "documents",
            "sourceRefs",
        },
        "wayfinder",
    )
    if projection.get("schemaVersion") != WAYFINDER_PROJECTION_SCHEMA:
        raise WayfinderProjectionError("unsupported project Wayfinder schema")
    if projection.get("projectId") != expected_project_id:
        raise WayfinderProjectionError("Wayfinder projectId drifted")
    if projection.get("currentRoomId") != expected_current_room_id:
        raise WayfinderProjectionError("Wayfinder currentRoomId drifted")

    all_available = set().union(
        *(set(source_ids) for source_ids in available_source_ids_by_room.values())
    )
    source_refs = _require_unique_strings(projection.get("sourceRefs"), "wayfinder.sourceRefs", minimum=1)
    if set(source_refs) != all_available:
        raise WayfinderProjectionError("Wayfinder sourceRefs must cover all manifest receipts exactly")

    initial = _require_mapping(projection.get("initialVision"), "wayfinder.initialVision")
    _require_exact_keys(
        initial,
        {"title", "statement", "observableAnchors", "documentRef", "sourceRefs"},
        "wayfinder.initialVision",
    )
    _require_string(initial.get("title"), "wayfinder.initialVision.title")
    _require_string(initial.get("statement"), "wayfinder.initialVision.statement")
    _require_unique_strings(initial.get("observableAnchors"), "wayfinder.initialVision.observableAnchors", minimum=1)
    _safe_ref(_require_string(initial.get("documentRef"), "wayfinder.initialVision.documentRef"))
    if not set(_require_unique_strings(initial.get("sourceRefs"), "wayfinder.initialVision.sourceRefs", minimum=1)) <= all_available:
        raise WayfinderProjectionError("initial vision cites an unknown source receipt")

    destination = _require_mapping(projection.get("destination"), "wayfinder.destination")
    _require_exact_keys(
        destination,
        {"title", "statement", "state", "acceptanceObservations", "documentRef", "sourceRefs"},
        "wayfinder.destination",
    )
    _require_string(destination.get("title"), "wayfinder.destination.title")
    _require_string(destination.get("statement"), "wayfinder.destination.statement")
    if destination.get("state") != "unreached":
        raise WayfinderProjectionError("Destination must remain unreached")
    _require_unique_strings(
        destination.get("acceptanceObservations"),
        "wayfinder.destination.acceptanceObservations",
        minimum=1,
    )
    _safe_ref(_require_string(destination.get("documentRef"), "wayfinder.destination.documentRef"))
    if not set(_require_unique_strings(destination.get("sourceRefs"), "wayfinder.destination.sourceRefs", minimum=1)) <= all_available:
        raise WayfinderProjectionError("Destination cites an unknown source receipt")

    engine = _require_mapping(projection.get("deliveryEngine"), "wayfinder.deliveryEngine")
    _require_exact_keys(engine, {"stages", "innerMethod"}, "wayfinder.deliveryEngine")
    stages = _require_list(engine.get("stages"), "wayfinder.deliveryEngine.stages")
    expected_stages = [{"id": stage_id, "title": title} for stage_id, title in DELIVERY_STAGES]
    if stages != expected_stages:
        raise WayfinderProjectionError("Wayfinder delivery stages drifted")
    inner_method = _require_mapping(engine.get("innerMethod"), "wayfinder.deliveryEngine.innerMethod")
    if inner_method != {
        "id": "test-driven-implementation",
        "parentStage": "implementation-execution",
        "title": "测试驱动实现",
    }:
        raise WayfinderProjectionError("TDD must remain inside implementation-execution")

    evolution = _require_mapping(projection.get("evolution"), "wayfinder.evolution")
    _require_exact_keys(evolution, {"direction", "epochs", "releaseLane"}, "wayfinder.evolution")
    if evolution.get("direction") != "left-to-right":
        raise WayfinderProjectionError("Wayfinder evolution must read left-to-right")
    epochs = _require_list(evolution.get("epochs"), "wayfinder.evolution.epochs")
    if not epochs:
        raise WayfinderProjectionError("Wayfinder evolution epochs must not be empty")
    epoch_ids: list[str] = []
    for index, raw_epoch in enumerate(epochs):
        path = f"wayfinder.evolution.epochs[{index}]"
        epoch = _require_mapping(raw_epoch, path)
        _require_exact_keys(epoch, {"id", "range", "label", "summary"}, path)
        epoch_id = _require_string(epoch.get("id"), f"{path}.id")
        if epoch_id in epoch_ids:
            raise WayfinderProjectionError(f"{path}.id is duplicated")
        epoch_ids.append(epoch_id)
        _require_string(epoch.get("range"), f"{path}.range")
        _require_string(epoch.get("label"), f"{path}.label")
        _require_string(epoch.get("summary"), f"{path}.summary")
    release_lane = _require_mapping(
        evolution.get("releaseLane"), "wayfinder.evolution.releaseLane"
    )
    _require_exact_keys(release_lane, {"roomId", "checkpoints"}, "wayfinder.evolution.releaseLane")
    release_lane_room_id = _require_string(
        release_lane.get("roomId"), "wayfinder.evolution.releaseLane.roomId"
    )
    checkpoints = _require_list(
        release_lane.get("checkpoints"), "wayfinder.evolution.releaseLane.checkpoints"
    )
    if not checkpoints:
        raise WayfinderProjectionError("Wayfinder release lane checkpoints must not be empty")
    checkpoint_dates: list[str] = []
    for index, raw_checkpoint in enumerate(checkpoints):
        path = f"wayfinder.evolution.releaseLane.checkpoints[{index}]"
        checkpoint = _require_mapping(raw_checkpoint, path)
        _require_exact_keys(checkpoint, {"observedAt", "label", "sourceRefs"}, path)
        observed_at = _require_string(checkpoint.get("observedAt"), f"{path}.observedAt")
        if ISO_DATE.fullmatch(observed_at) is None:
            raise WayfinderProjectionError(f"{path}.observedAt is invalid")
        checkpoint_dates.append(observed_at)
        _require_string(checkpoint.get("label"), f"{path}.label")
        refs = _require_unique_strings(checkpoint.get("sourceRefs"), f"{path}.sourceRefs", minimum=1)
        if not set(refs) <= all_available:
            raise WayfinderProjectionError(f"{path}.sourceRefs includes an unknown receipt")
    if checkpoint_dates != sorted(checkpoint_dates):
        raise WayfinderProjectionError("Wayfinder release lane checkpoints must be chronological")

    rooms = _require_list(projection.get("rooms"), "wayfinder.rooms")
    if len(rooms) != len(room_boundaries):
        raise WayfinderProjectionError("Wayfinder Room count drifted")
    room_ids: list[str] = []
    accepted_count = 0
    for index, raw_room in enumerate(rooms):
        path = f"wayfinder.rooms[{index}]"
        room = _require_mapping(raw_room, path)
        _require_exact_keys(
            room,
            {
                "roomId",
                "title",
                "requirement",
                "problem",
                "decisions",
                "acceptanceObservations",
                "currentStage",
                "deliveryState",
                "emergedAt",
                "epochId",
                "topologyRole",
                "progress",
                "currentDelivery",
                "nextMove",
                "documentRef",
                "detailDocumentRefs",
                "sourceRefs",
            },
            path,
        )
        room_id = _require_string(room.get("roomId"), f"{path}.roomId")
        if room_id in room_ids or room_id not in room_boundaries:
            raise WayfinderProjectionError(f"{path}.roomId is duplicate or unknown")
        room_ids.append(room_id)
        if room.get("title") != room_boundaries[room_id]:
            raise WayfinderProjectionError(f"{path}.title drifted from manifest boundary")
        _require_string(room.get("requirement"), f"{path}.requirement")
        _require_string(room.get("problem"), f"{path}.problem")
        _require_unique_strings(room.get("decisions"), f"{path}.decisions", minimum=1)
        _require_unique_strings(room.get("acceptanceObservations"), f"{path}.acceptanceObservations", minimum=1)
        emerged_at = _require_string(room.get("emergedAt"), f"{path}.emergedAt")
        if ISO_DATE.fullmatch(emerged_at) is None:
            raise WayfinderProjectionError(f"{path}.emergedAt is invalid")
        if room.get("epochId") not in epoch_ids:
            raise WayfinderProjectionError(f"{path}.epochId is unknown")
        if room.get("topologyRole") not in TOPOLOGY_ROLES:
            raise WayfinderProjectionError(f"{path}.topologyRole is unsupported")
        stage = room.get("currentStage")
        if stage not in DELIVERY_STAGE_IDS:
            raise WayfinderProjectionError(f"{path}.currentStage is unsupported")
        delivery_state = room.get("deliveryState")
        if delivery_state not in DELIVERY_STATES:
            raise WayfinderProjectionError(f"{path}.deliveryState is unsupported")
        accepted_count += int(delivery_state == "accepted")
        if delivery_state == "accepted" and stage != "independent-review":
            raise WayfinderProjectionError(f"{path} accepted state is not independently reviewed")
        _require_string(room.get("currentDelivery"), f"{path}.currentDelivery")
        _require_string(room.get("nextMove"), f"{path}.nextMove")
        _safe_ref(_require_string(room.get("documentRef"), f"{path}.documentRef"))
        _require_unique_strings(room.get("detailDocumentRefs"), f"{path}.detailDocumentRefs")
        room_refs = _require_unique_strings(room.get("sourceRefs"), f"{path}.sourceRefs", minimum=1)
        expected_room_refs = set(available_source_ids_by_room[room_id])
        if set(room_refs) != expected_room_refs:
            raise WayfinderProjectionError(f"{path}.sourceRefs must match its Room receipts exactly")
        progress = _require_mapping(room.get("progress"), f"{path}.progress")
        _require_exact_keys(progress, {"basis", "completed", "total", "items"}, f"{path}.progress")
        if progress.get("basis") != "acceptance-evidence":
            raise WayfinderProjectionError(f"{path}.progress basis drifted")
        completed = progress.get("completed")
        total = progress.get("total")
        if not isinstance(completed, int) or isinstance(completed, bool) or completed < 0:
            raise WayfinderProjectionError(f"{path}.progress.completed is invalid")
        if not isinstance(total, int) or isinstance(total, bool) or total < 1:
            raise WayfinderProjectionError(f"{path}.progress.total is invalid")
        items = _require_list(progress.get("items"), f"{path}.progress.items")
        verified = 0
        item_labels: list[str] = []
        for item_index, raw_item in enumerate(items):
            item_path = f"{path}.progress.items[{item_index}]"
            item = _require_mapping(raw_item, item_path)
            _require_exact_keys(item, {"label", "state", "sourceRefs"}, item_path)
            label = _require_string(item.get("label"), f"{item_path}.label")
            if label in item_labels:
                raise WayfinderProjectionError(f"{item_path}.label is duplicated")
            item_labels.append(label)
            state = item.get("state")
            if state not in PROGRESS_STATES:
                raise WayfinderProjectionError(f"{item_path}.state is unsupported")
            verified += int(state == "verified")
            item_refs = _require_unique_strings(
                item.get("sourceRefs"), f"{item_path}.sourceRefs", minimum=1
            )
            if not set(item_refs) <= expected_room_refs:
                raise WayfinderProjectionError(f"{item_path}.sourceRefs escapes its Room receipts")
        if total != len(items) or completed != verified or item_labels != room.get("acceptanceObservations"):
            raise WayfinderProjectionError(f"{path}.progress does not match observable acceptance")

    if set(room_ids) != set(room_boundaries):
        raise WayfinderProjectionError("Wayfinder Room boundaries drifted from manifest")
    if accepted_count == len(rooms):
        raise WayfinderProjectionError("Destination cannot be unreached after every Room is accepted")
    current_room = next(room for room in rooms if room["roomId"] == expected_current_room_id)
    if current_room["deliveryState"] != "active":
        raise WayfinderProjectionError("current Room must remain active")
    release_rooms = [room for room in rooms if room["topologyRole"] == "release-lane"]
    if len(release_rooms) != 1 or release_rooms[0]["roomId"] != release_lane_room_id:
        raise WayfinderProjectionError("Wayfinder must define exactly one matching release lane Room")

    relations = _require_list(projection.get("relations"), "wayfinder.relations")
    if not relations:
        raise WayfinderProjectionError("Wayfinder relations must not be empty")
    allowed_endpoints = set(room_boundaries) | {"@origin"}
    relation_keys: set[tuple[str, str, str]] = set()
    origin_targets: set[str] = set()
    adjacency: dict[str, set[str]] = {"@origin": set()}
    for room_id in room_boundaries:
        adjacency[room_id] = set()
    for index, raw_relation in enumerate(relations):
        path = f"wayfinder.relations[{index}]"
        relation = _require_mapping(raw_relation, path)
        _require_exact_keys(relation, {"from", "to", "kind", "label", "sourceRefs"}, path)
        source = _require_string(relation.get("from"), f"{path}.from")
        target = _require_string(relation.get("to"), f"{path}.to")
        kind = _require_string(relation.get("kind"), f"{path}.kind")
        _require_string(relation.get("label"), f"{path}.label")
        if source not in allowed_endpoints or target not in room_boundaries or source == target:
            raise WayfinderProjectionError(f"{path} has an invalid endpoint")
        if kind not in RELATION_KINDS:
            raise WayfinderProjectionError(f"{path}.kind is unsupported")
        relation_refs = _require_unique_strings(
            relation.get("sourceRefs"), f"{path}.sourceRefs", minimum=1
        )
        if not set(relation_refs) <= all_available:
            raise WayfinderProjectionError(f"{path}.sourceRefs includes an unknown receipt")
        key = (source, target, kind)
        if key in relation_keys:
            raise WayfinderProjectionError(f"{path} duplicates another relation")
        relation_keys.add(key)
        adjacency[source].add(target)
        if source == "@origin":
            origin_targets.add(target)
    if len(origin_targets) != 1:
        raise WayfinderProjectionError("Initial vision must enter the historical DAG through one first Room")
    reachable = {"@origin"}
    queue = ["@origin"]
    while queue:
        source = queue.pop(0)
        for target in adjacency[source]:
            if target not in reachable:
                reachable.add(target)
                queue.append(target)
    if set(room_boundaries) - reachable:
        raise WayfinderProjectionError("Every Room must be reachable from the initial vision")
    indegree = {node: 0 for node in adjacency}
    for targets in adjacency.values():
        for target in targets:
            indegree[target] += 1
    topological_queue = [node for node, degree in indegree.items() if degree == 0]
    visited_count = 0
    while topological_queue:
        source = topological_queue.pop(0)
        visited_count += 1
        for target in adjacency[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                topological_queue.append(target)
    if visited_count != len(adjacency):
        raise WayfinderProjectionError("Wayfinder relations must remain acyclic")

    emerged_by_room = {room["roomId"]: room["emergedAt"] for room in rooms}
    for relation in relations:
        if relation["from"] == "@origin" or relation["kind"] == "requires":
            continue
        if emerged_by_room[relation["from"]] > emerged_by_room[relation["to"]]:
            raise WayfinderProjectionError(
                "refines and led-to relations must follow Room emergence chronology"
            )

    documents = _require_list(projection.get("documents"), "wayfinder.documents")
    if len(documents) != len(room_boundaries) + 3:
        raise WayfinderProjectionError("Wayfinder document index must cover map, vision, destination, and Rooms")
    document_refs: set[str] = set()
    indexed_room_docs: set[str] = set()
    indexed_sources: set[str] = set()
    role_counts = {role: 0 for role in DOCUMENT_ROLES}
    for index, raw_document in enumerate(documents):
        path = f"wayfinder.documents[{index}]"
        document = _require_mapping(raw_document, path)
        role = document.get("role")
        expected_keys = {"role", "ref", "title", "sha256", "sourceRefs"}
        if role == "room":
            expected_keys.add("roomId")
        _require_exact_keys(document, expected_keys, path)
        if role not in DOCUMENT_ROLES:
            raise WayfinderProjectionError(f"{path}.role is unsupported")
        role_counts[str(role)] += 1
        ref = _safe_ref(_require_string(document.get("ref"), f"{path}.ref"))
        if ref in document_refs:
            raise WayfinderProjectionError(f"{path}.ref is duplicated")
        document_refs.add(ref)
        _require_string(document.get("title"), f"{path}.title")
        if SHA256.fullmatch(_require_string(document.get("sha256"), f"{path}.sha256")) is None:
            raise WayfinderProjectionError(f"{path}.sha256 is invalid")
        refs = _require_unique_strings(document.get("sourceRefs"), f"{path}.sourceRefs", minimum=1)
        if not set(refs) <= all_available:
            raise WayfinderProjectionError(f"{path}.sourceRefs includes an unknown receipt")
        indexed_sources.update(refs)
        if role == "room":
            room_id = _require_string(document.get("roomId"), f"{path}.roomId")
            if room_id not in room_boundaries or room_id in indexed_room_docs:
                raise WayfinderProjectionError(f"{path}.roomId is duplicate or unknown")
            indexed_room_docs.add(room_id)
    if role_counts != {
        "map": 1,
        "initial-vision": 1,
        "destination": 1,
        "room": len(room_boundaries),
    }:
        raise WayfinderProjectionError("Wayfinder document roles drifted")
    if indexed_room_docs != set(room_boundaries):
        raise WayfinderProjectionError("Wayfinder Room documents do not cover every Room")
    if indexed_sources != all_available:
        raise WayfinderProjectionError("Wayfinder document index does not cover every source receipt")

    serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    if ABSOLUTE_PATH.search(serialized):
        raise WayfinderProjectionError("Wayfinder projection contains an absolute machine path")
    lowered = serialized.lower()
    for forbidden in FORBIDDEN_PROJECT_COPY:
        if forbidden.lower() in lowered:
            raise WayfinderProjectionError(
                f"Wayfinder projection contains forbidden process copy: {forbidden}"
            )
