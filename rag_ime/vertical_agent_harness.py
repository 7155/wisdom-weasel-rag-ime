"""Pure manifest and Trace checks for self-hosted vertical-Agent examples.

The harness is a gate for fixtures, not an Agent runtime: it never calls a
provider, creates an index, writes a project, or turns missing evidence into a
passing result.  A future builder can use these same manifests while running
inside the sandbox declared by each profile.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .trace_runtime import TraceContractError, validate_trace_envelope


VERTICAL_MANIFEST_SCHEMA_VERSION = "rag-ime.vertical-agent-manifest.v1"
_REQUIRED_CAPABILITIES = frozenset({"trace.emit", "eval.ground_truth", "rag.retrieval", "memory.recall", "sandbox.self_test"})


class VerticalHarnessError(ValueError):
    """A manifest or candidate Trace failed a declared vertical-app check."""


class VerticalSuiteResolutionError(VerticalHarnessError):
    """A requested built-in Eval suite is not registered at this revision."""

    def __init__(self, message: str, *, code: str) -> None:
        self.code = str(code)
        super().__init__(message)


def load_builtin_manifests() -> dict[str, dict[str, object]]:
    root = Path(__file__).resolve().parents[1] / "examples" / "vertical_agents"
    manifests: dict[str, dict[str, object]] = {}
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise VerticalHarnessError(f"manifest must be an object: {path.name}")
        validate_vertical_manifest(payload)
        app_id = str(payload["appId"])
        if app_id in manifests:
            raise VerticalHarnessError(f"duplicate vertical app id: {app_id}")
        manifests[app_id] = payload
    return manifests


def list_builtin_eval_suites() -> list[dict[str, object]]:
    """Return the privacy-safe public catalog for the registered Eval suites.

    ``load_builtin_manifests`` is deliberately the only registry authority.
    This projection exposes enough metadata for a caller to choose and pin a
    suite revision, while keeping fixture labels, truth, paths, and content
    inside the local harness.
    """

    catalog: list[dict[str, object]] = []
    for suite_id, manifest in sorted(load_builtin_manifests().items()):
        capabilities = manifest.get("capabilities")
        fixtures = manifest.get("fixtures")
        if not isinstance(capabilities, list) or not isinstance(fixtures, list):
            raise VerticalHarnessError("registered Eval suite manifest is malformed")
        catalog.append(
            {
                "suiteId": suite_id,
                "suiteRevision": str(manifest["suiteRevision"]),
                "displayName": str(manifest["displayName"]),
                "fixtureCount": len(fixtures),
                "capabilities": sorted(
                    {str(value) for value in capabilities if str(value).strip()}
                )[:16],
            }
        )
    return catalog


def resolve_builtin_vertical_suite(
    suite_id: object,
    suite_revision: object,
) -> dict[str, object]:
    """Resolve one registered deterministic suite and its exact revision.

    The checked-in vertical manifests are the registry authority for both
    scheduled creation and scheduled execution.  Callers receive the same
    bounded manifest that the vertical harness validates; no second list of
    suite IDs or revisions is maintained at a scheduling boundary.
    """

    if not isinstance(suite_id, str) or not suite_id.strip():
        raise VerticalSuiteResolutionError(
            "vertical suite id is required",
            code="suite_id_required",
        )
    normalized_suite_id = suite_id.strip()
    manifests = load_builtin_manifests()
    manifest = manifests.get(normalized_suite_id)
    if manifest is None:
        raise VerticalSuiteResolutionError(
            "vertical suite is not allowlisted",
            code="unknown_suite",
        )
    if not isinstance(suite_revision, str) or not suite_revision.strip():
        raise VerticalSuiteResolutionError(
            "vertical suite revision is required",
            code="suite_revision_required",
        )
    declared_revision = manifest.get("suiteRevision")
    if not isinstance(declared_revision, str) or suite_revision != declared_revision:
        raise VerticalSuiteResolutionError(
            "vertical suite revision does not match the allowlisted manifest",
            code="suite_revision_mismatch",
        )
    return manifest


def validate_vertical_manifest(manifest: Mapping[str, object]) -> None:
    if manifest.get("schemaVersion") != VERTICAL_MANIFEST_SCHEMA_VERSION:
        raise VerticalHarnessError("unsupported vertical manifest schema")
    _required_text(manifest, "appId")
    _required_text(manifest, "suiteRevision")
    _required_text(manifest, "displayName")
    capabilities = _string_set(manifest.get("capabilities"), "capabilities")
    missing = _REQUIRED_CAPABILITIES - capabilities
    if missing:
        raise VerticalHarnessError(f"manifest is missing capabilities: {sorted(missing)}")

    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise VerticalHarnessError("manifest requires at least one fixture")
    for fixture in fixtures:
        if not isinstance(fixture, Mapping):
            raise VerticalHarnessError("fixture must be an object")
        _required_text(fixture, "fixtureId")
        truth = fixture.get("truth")
        if not isinstance(truth, Mapping):
            raise VerticalHarnessError("fixture requires deterministic truth")
        raw_ids = truth.get("requiredEvidenceIds")
        if (
            not isinstance(raw_ids, list)
            or any(not isinstance(value, str) or not value.strip() for value in raw_ids)
            or len(raw_ids) != len(set(raw_ids))
        ):
            raise VerticalHarnessError("truth.requiredEvidenceIds must be unique non-empty strings")
        ids = _string_list(raw_ids, "truth.requiredEvidenceIds")
        if not ids:
            raise VerticalHarnessError("deterministic truth requires evidence IDs")
        rag_evidence = _mapping(fixture, "ragEvidence")
        _required_text(rag_evidence, "evidenceId")
        if _required_text(rag_evidence, "sourceKind") != "knowledge":
            raise VerticalHarnessError("ragEvidence.sourceKind must be knowledge")
        _required_text(rag_evidence, "sourceLane")
        _required_text(rag_evidence, "sourceRef")

    self_test = _mapping(manifest, "selfTest")
    fixture_path = _fixture_path(self_test.get("fixturePath"))
    document_id = _required_text(self_test, "documentId")
    _required_text(self_test, "baseAlias")
    _required_text(self_test, "baseName")
    _required_text(self_test, "query")
    memory = _mapping(self_test, "memory")
    memory_id = _required_text(memory, "memoryId")
    source_ref = _required_text(memory, "sourceRef")
    summary_fingerprint = _required_text(memory, "summaryFingerprint")
    if not source_ref.startswith("fixture://memory/"):
        raise VerticalHarnessError("selfTest.memory.sourceRef must be a fixture URI")
    if source_ref == "fixture://memory/":
        raise VerticalHarnessError("selfTest.memory.sourceRef must name a fixture")
    if not summary_fingerprint.startswith("sha256:"):
        raise VerticalHarnessError("selfTest.memory.summaryFingerprint must be a sha256 fingerprint")
    if summary_fingerprint == "sha256:":
        raise VerticalHarnessError("selfTest.memory.summaryFingerprint must not be empty")
    if not memory_id.startswith("memory:"):
        raise VerticalHarnessError("selfTest.memory.memoryId must start with memory:")
    if memory_id == "memory:":
        raise VerticalHarnessError("selfTest.memory.memoryId must name a fixture")
    expected_truth = {f"knowledge:{document_id}", memory_id}
    first_fixture = fixtures[0]
    assert isinstance(first_fixture, Mapping)
    truth = first_fixture.get("truth")
    if not isinstance(truth, Mapping):
        raise VerticalHarnessError("fixture truth is required")
    truth_ids = truth.get("requiredEvidenceIds")
    if (
        not isinstance(truth_ids, list)
        or any(not isinstance(value, str) for value in truth_ids)
        or len(truth_ids) != len(set(truth_ids))
    ):
        raise VerticalHarnessError("fixture truth evidence IDs must be unique")
    if set(_string_list(truth_ids, "truth.requiredEvidenceIds")) != expected_truth:
        raise VerticalHarnessError("fixture truth must declare its knowledge and memory evidence IDs")
    for fixture in fixtures:
        assert isinstance(fixture, Mapping)
        fixture_truth = fixture.get("truth")
        assert isinstance(fixture_truth, Mapping)
        if memory_id not in _string_list(fixture_truth.get("requiredEvidenceIds"), "truth.requiredEvidenceIds"):
            raise VerticalHarnessError("every fixture truth must declare the self-test memory evidence ID")
        rag_evidence = _mapping(fixture, "ragEvidence")
        expected_knowledge_id = f"knowledge:{document_id}"
        if _required_text(rag_evidence, "evidenceId") != expected_knowledge_id:
            raise VerticalHarnessError(
                "ragEvidence.evidenceId must match the self-test document"
            )
        if _required_text(rag_evidence, "evidenceId") not in _string_list(
            fixture_truth.get("requiredEvidenceIds"),
            "truth.requiredEvidenceIds",
        ):
            raise VerticalHarnessError(
                "fixture truth must declare its ragEvidence.evidenceId"
            )

    trace_requirements = _mapping(manifest, "traceRequirements")
    if not _string_list(trace_requirements.get("requiredSpanNames"), "traceRequirements.requiredSpanNames"):
        raise VerticalHarnessError("trace requirements need required span names")
    for section_name in ("ragChecks", "memoryChecks"):
        section = _mapping(manifest, section_name)
        if section.get("required") is not True:
            raise VerticalHarnessError(f"{section_name} must be required")
        if not _string_list(section.get("requiredSpanNames"), f"{section_name}.requiredSpanNames"):
            raise VerticalHarnessError(f"{section_name} needs required span names")
        if not _string_list(section.get("requiredEvidenceSourceKinds"), f"{section_name}.requiredEvidenceSourceKinds"):
            raise VerticalHarnessError(f"{section_name} needs evidence source kinds")
        if not _string_list(section.get("requiredEvidenceStages"), f"{section_name}.requiredEvidenceStages"):
            raise VerticalHarnessError(f"{section_name} needs evidence stages")

    sandbox = _mapping(manifest, "sandbox")
    _required_text(sandbox, "workspaceRoot")
    if sandbox.get("mutationMode") not in {"read_only", "staged"}:
        raise VerticalHarnessError("sandbox mutationMode must be read_only or staged")
    if sandbox.get("network") != "blocked":
        raise VerticalHarnessError("vertical fixture sandbox network must be blocked")
    if sandbox.get("productionWriteBlocked") is not True:
        raise VerticalHarnessError("sandbox must block production writes")


def verify_vertical_trace(
    manifest: Mapping[str, object],
    trace: Mapping[str, object],
    *,
    fixture_id: str | None = None,
) -> dict[str, object]:
    """Verify one completed Trace against manifest-declared checks.

    This returns a positive report only after all declared requirements pass;
    every missing Trace/RAG/Memory fact raises ``VerticalHarnessError``.
    """

    try:
        validate_trace_envelope(trace)
    except TraceContractError as exc:
        raise VerticalHarnessError(f"trace contract invalid: {exc}") from exc
    validate_vertical_manifest(manifest)
    if not str(trace.get("traceId") or "").strip():
        raise VerticalHarnessError("traceId is required")
    if trace.get("sourceKind") != "vertical_agent":
        raise VerticalHarnessError(
            "vertical Trace sourceKind must be vertical_agent"
        )
    if trace.get("status") not in {None, "completed"}:
        raise VerticalHarnessError("trace must be completed")
    spans = trace.get("spans")
    if not isinstance(spans, list):
        raise VerticalHarnessError("trace spans are required")
    span_names = {str(item.get("name")) for item in spans if isinstance(item, Mapping)}
    trace_requirements = _mapping(manifest, "traceRequirements")
    required_span_names = _string_list(
        trace_requirements.get("requiredSpanNames"),
        "required span names",
    )
    missing_spans = [name for name in required_span_names if name not in span_names]
    if missing_spans:
        raise VerticalHarnessError(f"required span missing: {', '.join(missing_spans)}")
    non_completed_spans = [
        name
        for name in required_span_names
        if any(
            isinstance(item, Mapping)
            and item.get("name") == name
            and item.get("status") != "completed"
            for item in spans
        )
    ]
    if non_completed_spans:
        raise VerticalHarnessError(
            "required span must be completed: "
            + ", ".join(non_completed_spans)
        )

    evidence = trace.get("evidence")
    if not isinstance(evidence, list):
        raise VerticalHarnessError("trace evidence is required")
    evidence_keys: set[tuple[str, str, str]] = set()
    for item in evidence:
        if not isinstance(item, Mapping):
            raise VerticalHarnessError("trace evidence items must be objects")
        key = (str(item.get("evidenceId") or ""), str(item.get("evidenceStage") or ""), str(item.get("sourceLane") or ""))
        if key in evidence_keys:
            raise VerticalHarnessError("trace contains duplicate evidence at the same stage and lane")
        evidence_keys.add(key)
    included = [item for item in evidence if item.get("disposition") == "included"]
    included_ids = {str(item.get("evidenceId")) for item in included}
    selected_fixture = _select_fixture(manifest, fixture_id)
    truth = _mapping(selected_fixture, "truth")
    required_truth_ids = _string_list(truth.get("requiredEvidenceIds"), "truth.requiredEvidenceIds")
    missing_truth = [item for item in required_truth_ids if item not in included_ids]
    if missing_truth:
        raise VerticalHarnessError(f"deterministic truth evidence missing: {', '.join(missing_truth)}")

    self_test = _mapping(manifest, "selfTest")
    memory = _mapping(self_test, "memory")
    memory_id = _required_text(memory, "memoryId")
    memory_source_ref = _required_text(memory, "sourceRef")
    memory_evidence_id = memory_id
    memory_items = [item for item in included if str(item.get("evidenceId") or "") == memory_evidence_id]
    if not memory_items or any(
        str(item.get("sourceKind") or "") != "memory"
        or str(item.get("sourceLane") or "") != "fixture_memory"
        or str(item.get("sourceRef") or "") != memory_source_ref
        for item in memory_items
    ):
        raise VerticalHarnessError("Memory fixture evidence must remain explicitly marked as fixture")

    rag_requirements = _mapping(manifest, "ragChecks")
    rag_declaration = _mapping(selected_fixture, "ragEvidence")
    declared_rag_fields = {
        key: _required_text(rag_declaration, key)
        for key in ("evidenceId", "sourceKind", "sourceLane", "sourceRef")
    }
    rag_matches = [
        item
        for item in included
        if str(item.get("evidenceId") or "") == declared_rag_fields["evidenceId"]
    ]
    if len(rag_matches) != 1 or any(
        str(item.get(key) or "") != expected
        for item in rag_matches
        for key, expected in declared_rag_fields.items()
        if key != "evidenceId"
    ):
        raise VerticalHarnessError(
            "RAG evidence provenance does not match fixture declaration"
        )

    rag = _verify_stage("RAG", rag_requirements, spans, included)
    memory = _verify_stage("Memory", _mapping(manifest, "memoryChecks"), spans, included)
    return {
        "verified": True,
        "traceId": str(trace["traceId"]),
        "fixtureId": str(selected_fixture["fixtureId"]),
        "truth": {"requiredEvidenceIds": required_truth_ids, "matchedEvidenceIds": [item for item in required_truth_ids if item in included_ids]},
        "rag": rag,
        "memory": memory,
    }


def _verify_stage(stage: str, requirements: Mapping[str, object], spans: list[object], included: list[Mapping[str, object]]) -> dict[str, object]:
    names = {str(item.get("name")) for item in spans if isinstance(item, Mapping)}
    missing_spans = [name for name in _string_list(requirements.get("requiredSpanNames"), f"{stage} span names") if name not in names]
    if missing_spans:
        raise VerticalHarnessError(f"{stage} required span missing: {', '.join(missing_spans)}")
    source_kinds = _string_list(requirements.get("requiredEvidenceSourceKinds"), f"{stage} evidence kinds")
    required_stages = _string_list(requirements.get("requiredEvidenceStages"), f"{stage} evidence stages")
    kind_matches = [item for item in included if str(item.get("sourceKind")) in source_kinds]
    missing_kinds = [kind for kind in source_kinds if not any(str(item.get("sourceKind")) == kind for item in kind_matches)]
    if missing_kinds:
        raise VerticalHarnessError(f"{stage} evidence missing: {', '.join(missing_kinds)}")
    matches = [item for item in kind_matches if str(item.get("evidenceStage")) in required_stages]
    missing_stage_kinds = [
        kind
        for kind in source_kinds
        if not any(
            str(item.get("sourceKind")) == kind
            and str(item.get("evidenceStage")) in required_stages
            for item in matches
        )
    ]
    if missing_stage_kinds:
        raise VerticalHarnessError(
            f"{stage} evidence stage missing for {', '.join(missing_stage_kinds)}; "
            f"required: {', '.join(required_stages)}"
        )
    return {
        "requiredSourceKinds": source_kinds,
        "requiredEvidenceStages": required_stages,
        "evidenceCount": len(matches),
    }


def _select_fixture(manifest: Mapping[str, object], fixture_id: str | None) -> Mapping[str, object]:
    fixtures = manifest["fixtures"]
    assert isinstance(fixtures, list)
    selected = next((item for item in fixtures if isinstance(item, Mapping) and (fixture_id is None or item.get("fixtureId") == fixture_id)), None)
    if selected is None:
        raise VerticalHarnessError(f"fixture not found: {fixture_id or '<default>'}")
    return selected


def _mapping(parent: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise VerticalHarnessError(f"{key} must be an object")
    return value


def _required_text(parent: Mapping[str, object], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VerticalHarnessError(f"{key} is required")
    return value.strip()


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise VerticalHarnessError(f"{name} must be a list of non-empty strings")
    return list(dict.fromkeys(item.strip() for item in value))


def _string_set(value: object, name: str) -> set[str]:
    return set(_string_list(value, name))


def _fixture_path(value: object) -> Path:
    relative = str(value or "").strip()
    if not relative:
        raise VerticalHarnessError("selfTest.fixturePath is required")
    root = Path(__file__).resolve().parents[1] / "examples" / "vertical_agents"
    candidate = root / relative
    if candidate.is_symlink():
        raise VerticalHarnessError("self-test fixture path may not be a symlink")
    resolved = candidate.resolve(strict=False)
    if root not in resolved.parents or not resolved.is_file():
        raise VerticalHarnessError("self-test fixture path must stay inside examples/vertical_agents")
    return resolved
