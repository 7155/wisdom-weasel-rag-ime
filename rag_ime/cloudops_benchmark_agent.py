"""Session-bound Tool gateway for a frozen Cloud-OpsBench blind suite.

The gateway exposes only case metadata, compact observation indexes, exact
cache-key reads, and one terminal answer submission.  Host-only labels and
filesystem locators never enter a Tool manifest, Tool result, or public ledger.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections.abc import Mapping, Sequence
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


TOOL_NAME = "cloudops_benchmark"
PROFILE = "cloudops-benchmark-v1"
_CALL_FIELDS = frozenset(
    {"schemaVersion", "sessionId", "tool", "toolCallId", "sourceLoopId", "args", "loadReceiptId"}
)
_OPERATIONS = ("index", "list", "search", "read", "submit")
_WORKFLOW_PROFILES = frozenset(
    {"baseline-v1", "evidence-search-v1", "evidence-search-v2", "observation-id-v1"}
)
_SEARCH_WORKFLOW_PROFILES = frozenset(
    {"evidence-search-v1", "evidence-search-v2", "observation-id-v1"}
)
_BOUNDED_WORKFLOW_PROFILES = frozenset({"evidence-search-v2", "observation-id-v1"})
_CASE_ID = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\Z")
_FAULT_OBJECT = re.compile(r"(app|node)/[A-Za-z0-9._-]+\Z")
_TOOL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,119}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_INDEX_DESCRIPTOR_FIELDS = frozenset(
    {"cacheKey", "toolName", "observationChars", "observationSha256", "preview"}
)
_POSIX_HOST_LOCATOR = re.compile(
    r"(?:^|[^A-Za-z0-9])/(?:Users|Volumes|private|tmp|home)(?:/|\Z)",
    re.IGNORECASE,
)
_WINDOWS_DRIVE_LOCATOR = re.compile(r"(?:^|[^A-Za-z0-9])[A-Za-z]:[\\/]")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    raw = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _contains_host_locator(value: object) -> bool:
    text = str(value or "")
    has_unc = any(
        len(match.group()) >= 2
        and re.match(r"[^\\/\s]+[\\/]+[^\\/\s]+", text[match.end() :]) is not None
        for match in re.finditer(r"\\+", text)
    )
    return bool(
        "file://" in text.lower()
        or _POSIX_HOST_LOCATOR.search(text)
        or _WINDOWS_DRIVE_LOCATOR.search(text)
        or has_unc
    )


def _reject_public_locators(value: object, *, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_public_locators(key, label=label)
            _reject_public_locators(item, label=label)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _reject_public_locators(item, label=label)
        return
    if isinstance(value, str) and _contains_host_locator(value):
        raise ValueError(f"CloudOps {label} contains a host locator")


def _observation_text(value: object) -> str:
    # The frozen Cloud-OpsBench builder hashes structured Tool values with
    # json.dumps' stable, human-readable separators.  Do not reuse the compact
    # receipt serializer here or the public index and cache will disagree.
    return (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )


def _read_json(path: Path, *, expected: type = dict) -> object:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, expected):
        raise ValueError(f"CloudOps fixture has invalid JSON shape: {path.name}")
    return value


class CloudOpsBlindSuite:
    """Validated, read-only projection of one already-built blind suite."""

    def __init__(
        self,
        blind_root: str | Path,
        *,
        batches: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        requested = Path(blind_root).expanduser()
        if requested.is_symlink():
            raise ValueError("CloudOps blind root may not be a symlink")
        self._root = requested.resolve(strict=True)
        for path in self._root.rglob("*"):
            lowered = path.name.lower()
            if (
                path.is_symlink()
                or lowered in {"gold.json", "metadata.json", "milestone.json"}
                or "golden" in lowered
            ):
                raise ValueError("CloudOps blind suite has a leakage boundary violation")
        suite_path = self._root / "suite.json"
        contract_path = self._root / "diagnosis-contract.json"
        suite = _read_json(suite_path)
        contract = _read_json(contract_path)
        assert isinstance(suite, dict) and isinstance(contract, dict)
        _reject_public_locators(suite, label="suite metadata")
        _reject_public_locators(contract, label="diagnosis contract")
        if suite.get("schemaVersion") != "paw.cloudops-blind-suite.v1":
            raise ValueError("unsupported CloudOps blind suite schema")
        if contract.get("schemaVersion") != "paw.cloudops-diagnosis-contract.v1":
            raise ValueError("unsupported CloudOps diagnosis contract schema")
        raw_cases = suite.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ValueError("CloudOps blind suite has no cases")
        cases: dict[str, dict[str, object]] = {}
        for raw in raw_cases:
            if not isinstance(raw, Mapping):
                raise ValueError("CloudOps case metadata must be an object")
            case = dict(raw)
            case_id = str(case.get("case_id") or "").strip()
            if _CASE_ID.fullmatch(case_id) is None or case_id in cases:
                raise ValueError("CloudOps case id is invalid or duplicated")
            self._case_root(case_id, require=False).resolve(strict=True).relative_to(self._root)
            for filename in ("case.json", "tool_cache_index.json", "tool_cache.json"):
                path = self._case_root(case_id, require=False) / filename
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"CloudOps blind case is missing {filename}")
            self._validated_index(case_id)
            cases[case_id] = case
        self._suite = suite
        self._contract = contract
        self._suite_path = suite_path
        self._cases = cases
        self._suite_sha256 = _sha256(suite)
        self._contract_sha256 = _sha256(contract)
        self._batches = self._validated_batches(batches)

    @property
    def suite_sha256(self) -> str:
        return self._suite_sha256

    @property
    def contract_sha256(self) -> str:
        return self._contract_sha256

    @property
    def source_revision(self) -> str:
        return str(self._suite.get("sourceRevision") or "unknown")

    @property
    def batch_ids(self) -> tuple[str, ...]:
        return tuple(self._batches)

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(self._cases)

    def assigned_case_ids(self, batch_id: str) -> tuple[str, ...]:
        try:
            return self._batches[batch_id]
        except KeyError as exc:
            raise ValueError("CloudOps batch is not registered") from exc

    def public_index(self, batch_id: str) -> dict[str, object]:
        assigned = self.assigned_case_ids(batch_id)
        return {
            "schemaVersion": "paw.cloudops-agent-index.v1",
            "batchId": batch_id,
            "suiteSha256": self.suite_sha256,
            "diagnosisContractSha256": self.contract_sha256,
            "sourceRevision": self.source_revision,
            "cases": [
                {
                    "caseId": case_id,
                    "system": str(self._cases[case_id].get("system") or ""),
                    "faultCategory": str(self._cases[case_id].get("fault_category") or ""),
                    "namespace": str(self._cases[case_id].get("namespace") or ""),
                    "query": str(self._cases[case_id].get("query") or ""),
                    "difficulty": str(self._cases[case_id].get("difficulty") or ""),
                }
                for case_id in assigned
            ],
            "diagnosisContract": deepcopy(self._contract),
        }

    def list_observations(
        self,
        case_id: str,
        *,
        tool_name: str = "",
        cursor: int = 0,
        limit: int = 30,
    ) -> dict[str, object]:
        index = self._validated_index(case_id)
        selected = [
            self._public_descriptor(case_id, item)
            for item in index
            if isinstance(item, Mapping)
            and (not tool_name or str(item.get("toolName") or "") == tool_name)
        ]
        offset = max(0, int(cursor))
        bounded_limit = max(1, min(int(limit), 50))
        page = selected[offset : offset + bounded_limit]
        next_offset = offset + len(page)
        return {
            "schemaVersion": "paw.cloudops-observation-index.v1",
            "caseId": case_id,
            "items": page,
            "total": len(selected),
            "nextCursor": str(next_offset) if next_offset < len(selected) else "",
        }

    def search_observations(
        self,
        case_id: str,
        *,
        query: str,
        limit: int = 10,
    ) -> dict[str, object]:
        """Rank blind index descriptors without exposing full observations."""

        normalized = " ".join(str(query).strip().lower().split())
        if (
            not 2 <= len(normalized) <= 200
            or _contains_host_locator(normalized)
            or re.search(r"[\x00-\x1f\x7f]", normalized)
        ):
            raise ValueError("CloudOps observation search query is invalid")
        all_terms = tuple(dict.fromkeys(re.findall(r"[a-z0-9_.:/-]+", normalized)))
        if not all_terms:
            raise ValueError("CloudOps observation search terms are invalid")
        terms = all_terms[:12]
        ignored_term_count = len(all_terms) - len(terms)
        bounded_limit = max(1, min(int(limit), 20))
        ranked: list[tuple[int, str, str, dict[str, object]]] = []
        for descriptor in self._validated_index(case_id):
            tool_name = str(descriptor.get("toolName") or "").lower()
            cache_key = str(descriptor.get("cacheKey") or "").lower()
            preview = str(descriptor.get("preview") or "").lower()
            haystack = f"{tool_name}\n{cache_key}\n{preview}"
            score = 10 if normalized in haystack else 0
            matched_terms = 0
            for term in terms:
                matched = False
                if term in tool_name:
                    score += 5
                    matched = True
                if term in cache_key:
                    score += 3
                    matched = True
                if term in preview:
                    score += 1
                    matched = True
                matched_terms += int(matched)
            if matched_terms == 0:
                continue
            item = self._public_descriptor(case_id, descriptor)
            item["matchScore"] = score
            item["matchedTermCount"] = matched_terms
            ranked.append((score, tool_name, cache_key, item))
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        items = [item[3] for item in ranked[:bounded_limit]]
        return {
            "schemaVersion": "paw.cloudops-observation-search.v1",
            "caseId": case_id,
            "querySha256": _sha256(normalized),
            "usedTermCount": len(terms),
            "ignoredTermCount": ignored_term_count,
            "items": items,
            "totalMatches": len(ranked),
            "truncated": len(ranked) > len(items),
        }

    def read_observation(
        self,
        case_id: str,
        cache_key: str = "",
        *,
        observation_id: str = "",
    ) -> dict[str, object]:
        if bool(cache_key) == bool(observation_id):
            raise ValueError("CloudOps read requires exactly one cache key or observation id")
        if observation_id:
            self._assert_suite_snapshot()
            if re.fullmatch(r"obs_[0-9a-f]{24}", observation_id) is None:
                raise ValueError("CloudOps observation id is invalid")
        index = self._validated_index(case_id)
        if observation_id:
            descriptor = next(
                (
                    dict(item)
                    for item in index
                    if isinstance(item, Mapping)
                    and hmac.compare_digest(
                        self._observation_id(case_id, item),
                        observation_id,
                    )
                ),
                None,
            )
            if descriptor is None:
                raise ValueError("CloudOps observation id is not present in the assigned case")
            cache_key = str(descriptor.get("cacheKey") or "")
        else:
            descriptor = next(
                (
                    dict(item)
                    for item in index
                    if isinstance(item, Mapping) and item.get("cacheKey") == cache_key
                ),
                None,
            )
        if descriptor is None:
            raise ValueError("CloudOps cache key is not present in the blind index")
        cache = _read_json(self._case_root(case_id) / "tool_cache.json")
        assert isinstance(cache, dict)
        if cache_key not in cache:
            raise ValueError("CloudOps cache key has no observation")
        raw = cache[cache_key]
        observation = _observation_text(raw)
        digest = _sha256(observation)
        if digest != str(descriptor.get("observationSha256") or ""):
            raise ValueError("CloudOps observation hash does not match its blind index")
        if len(observation) != descriptor.get("observationChars"):
            raise ValueError("CloudOps observation character count does not match its blind index")
        identity = _sha256({"suite": self.suite_sha256, "case": case_id, "observation": digest})
        return {
            "schemaVersion": "paw.cloudops-observation.v1",
            "caseId": case_id,
            "cacheKey": cache_key,
            "observationId": self._observation_id(case_id, descriptor),
            "toolName": str(descriptor.get("toolName") or cache_key.split(":", 1)[0]),
            "observation": observation,
            "observationChars": len(observation),
            "observationSha256": digest,
            "evidenceId": f"evidence:cloudops:{identity[:32]}",
        }

    def _assert_suite_snapshot(self) -> None:
        try:
            current = _read_json(self._suite_path)
        except (OSError, ValueError) as exc:
            raise ValueError(
                "CloudOps observation id is stale because the blind suite changed"
            ) from exc
        if not isinstance(current, dict) or _sha256(current) != self._suite_sha256:
            raise ValueError(
                "CloudOps observation id is stale because the blind suite changed"
            )

    def validate_answers(self, batch_id: str, value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            raise ValueError("CloudOps answers must be an array")
        assigned = list(self.assigned_case_ids(batch_id))
        if len(value) != len(assigned):
            raise ValueError("CloudOps answers must cover exactly the assigned cases")
        answers: dict[str, dict[str, object]] = {}
        root_causes = {str(item) for item in self._contract.get("rootCauses") or []}
        valid_apps = {
            str(name)
            for names in (self._contract.get("validServices") or {}).values()
            if isinstance(names, list)
            for name in names
        }
        valid_nodes = {str(item) for item in self._contract.get("validNodes") or []}
        for raw in value:
            if not isinstance(raw, Mapping):
                raise ValueError("CloudOps answer must be an object")
            answer = deepcopy(dict(raw))
            if set(answer) != {"case_id", "key_evidence_summary", "top_3_predictions"}:
                raise ValueError("CloudOps answer fields are invalid")
            case_id = str(answer.get("case_id") or "").strip()
            if case_id not in assigned or case_id in answers:
                raise ValueError("CloudOps answers must cover exactly the assigned cases")
            summary = answer.get("key_evidence_summary")
            if not isinstance(summary, str) or not summary.strip() or len(summary) > 2_000:
                raise ValueError("CloudOps evidence summary is invalid")
            predictions = answer.get("top_3_predictions")
            if not isinstance(predictions, list) or len(predictions) != 3:
                raise ValueError("CloudOps answer requires exactly three predictions")
            ranks: list[int] = []
            pairs: list[tuple[str, str]] = []
            for prediction in predictions:
                if not isinstance(prediction, Mapping):
                    raise ValueError("CloudOps prediction must be an object")
                if set(prediction) != {"rank", "fault_object", "root_cause"}:
                    raise ValueError("CloudOps prediction fields are invalid")
                rank = prediction.get("rank")
                fault_object = str(prediction.get("fault_object") or "")
                root_cause = str(prediction.get("root_cause") or "")
                if rank not in {1, 2, 3} or _FAULT_OBJECT.fullmatch(fault_object) is None:
                    raise ValueError("CloudOps prediction rank or fault object is invalid")
                kind, name = fault_object.split("/", 1)
                if (kind == "app" and name not in valid_apps) or (kind == "node" and name not in valid_nodes):
                    raise ValueError("CloudOps fault object is outside the diagnosis contract")
                if root_cause not in root_causes:
                    raise ValueError("CloudOps root cause is outside the diagnosis contract")
                ranks.append(int(rank))
                pairs.append((fault_object, root_cause))
            if sorted(ranks) != [1, 2, 3] or len(set(pairs)) != 3:
                raise ValueError("CloudOps predictions must be distinct ranks 1, 2 and 3")
            answers[case_id] = answer
        if set(answers) != set(assigned):
            raise ValueError("CloudOps answers must cover exactly the assigned cases")
        return [answers[case_id] for case_id in assigned]

    def _case_root(self, case_id: str, *, require: bool = True) -> Path:
        if _CASE_ID.fullmatch(case_id) is None:
            raise ValueError("CloudOps case id is invalid")
        path = self._root / "cases" / Path(*case_id.split("/"))
        resolved = path.resolve(strict=require)
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("CloudOps case escapes the blind root") from exc
        return resolved

    def _validated_index(self, case_id: str) -> list[dict[str, object]]:
        raw_index = _read_json(
            self._case_root(case_id) / "tool_cache_index.json",
            expected=list,
        )
        assert isinstance(raw_index, list)
        result: list[dict[str, object]] = []
        for raw in raw_index:
            if not isinstance(raw, Mapping) or not set(raw) <= _INDEX_DESCRIPTOR_FIELDS:
                raise ValueError("CloudOps observation descriptor fields are invalid")
            if not {"cacheKey", "toolName", "observationChars", "observationSha256"} <= set(raw):
                raise ValueError("CloudOps observation descriptor is incomplete")
            cache_key = str(raw.get("cacheKey") or "")
            tool_name = str(raw.get("toolName") or "")
            observation_chars = raw.get("observationChars")
            observation_sha256 = str(raw.get("observationSha256") or "")
            preview = raw.get("preview", "")
            if not cache_key or len(cache_key) > 4_096 or _contains_host_locator(cache_key):
                raise ValueError("CloudOps observation descriptor cache key is invalid")
            if _TOOL_NAME.fullmatch(tool_name) is None:
                raise ValueError("CloudOps observation descriptor Tool name is invalid")
            if (
                isinstance(observation_chars, bool)
                or not isinstance(observation_chars, int)
                or observation_chars < 0
            ):
                raise ValueError("CloudOps observation descriptor character count is invalid")
            if _SHA256.fullmatch(observation_sha256) is None:
                raise ValueError("CloudOps observation descriptor hash is invalid")
            if not isinstance(preview, str) or len(preview) > 4_000:
                raise ValueError("CloudOps observation descriptor preview is invalid")
            descriptor = {
                "cacheKey": cache_key,
                "toolName": tool_name,
                "observationChars": observation_chars,
                "observationSha256": observation_sha256,
            }
            if "preview" in raw:
                descriptor["preview"] = preview
            result.append(descriptor)
        return result

    def _public_descriptor(
        self,
        case_id: str,
        descriptor: Mapping[str, object],
    ) -> dict[str, object]:
        result = {
            key: descriptor[key]
            for key in ("cacheKey", "toolName", "observationChars", "observationSha256")
        }
        result["observationId"] = self._observation_id(case_id, descriptor)
        return result

    def _observation_id(
        self,
        case_id: str,
        descriptor: Mapping[str, object],
    ) -> str:
        return "obs_" + _sha256(
            {
                "suite": self.suite_sha256,
                "case": case_id,
                "index": {
                    "cacheKey": str(descriptor.get("cacheKey") or ""),
                    "toolName": str(descriptor.get("toolName") or ""),
                    "observationChars": descriptor.get("observationChars"),
                    "observationSha256": str(descriptor.get("observationSha256") or ""),
                },
            }
        )[:24]

    def _validated_batches(
        self, batches: Mapping[str, Sequence[str]] | None
    ) -> dict[str, tuple[str, ...]]:
        if batches is None:
            ids = list(self._cases)
            if len(ids) != 12:
                raise ValueError("default CloudOps plan requires exactly 12 cases")
            batches = {f"batch-{index + 1}": ids[index * 4 : (index + 1) * 4] for index in range(3)}
        result: dict[str, tuple[str, ...]] = {}
        flattened: list[str] = []
        for raw_batch_id, raw_ids in batches.items():
            batch_id = str(raw_batch_id).strip()
            ids = tuple(str(item).strip() for item in raw_ids)
            if not batch_id or not ids or len(ids) != len(set(ids)):
                raise ValueError("CloudOps batch is invalid")
            if any(case_id not in self._cases for case_id in ids):
                raise ValueError("CloudOps batch references an unknown case")
            result[batch_id] = ids
            flattened.extend(ids)
        if len(flattened) != len(set(flattened)) or set(flattened) != set(self._cases):
            raise ValueError("CloudOps batches must partition the frozen suite")
        return result


class CloudOpsBenchmarkGateway:
    """Ephemeral authorization and Tool ledger for evaluation Sessions."""

    def __init__(self, suite: CloudOpsBlindSuite, *, max_reads_per_case: int = 40) -> None:
        self.suite = suite
        self.max_reads_per_case = max(1, int(max_reads_per_case))
        self._lock = threading.RLock()
        self._bindings: dict[str, tuple[str, str]] = {}
        self._binding_receipts: dict[str, str] = {}
        self._read_counts: dict[tuple[str, str], int] = {}
        self._search_query_hashes: dict[tuple[str, str], set[str]] = {}
        self._list_counts: dict[tuple[str, str], int] = {}
        self._read_cache_key_hashes: dict[tuple[str, str], set[str]] = {}
        self._answers: dict[str, list[dict[str, object]]] = {}
        self._ledger: list[dict[str, object]] = []

    def bind_session(
        self,
        session_id: object,
        *,
        batch_id: str,
        workflow_profile: str = "baseline-v1",
    ) -> dict[str, object]:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("CloudOps Session id is required")
        if workflow_profile not in _WORKFLOW_PROFILES:
            raise ValueError("CloudOps workflow profile is unsupported")
        assigned = self.suite.assigned_case_ids(batch_id)
        receipt = {
            "schemaVersion": "paw.cloudops-agent-binding.v1",
            "sessionId": normalized,
            "batchId": batch_id,
            "assignedCaseIdsSha256": _sha256(list(assigned)),
            "suiteSha256": self.suite.suite_sha256,
            "profile": PROFILE,
            "workflowProfile": workflow_profile,
            "ephemeral": True,
        }
        receipt["bindingReceiptId"] = "binding:cloudops:" + _sha256(receipt)[:32]
        with self._lock:
            if normalized in self._bindings:
                raise ValueError("CloudOps Session is already bound")
            self._bindings[normalized] = (batch_id, workflow_profile)
            self._binding_receipts[normalized] = str(receipt["bindingReceiptId"])
        return receipt

    def unbind_session(self, session_id: object) -> bool:
        normalized = str(session_id or "").strip()
        with self._lock:
            removed = self._bindings.pop(normalized, None) is not None
            self._binding_receipts.pop(normalized, None)
            self._search_query_hashes = {
                key: value for key, value in self._search_query_hashes.items() if key[0] != normalized
            }
            self._list_counts = {
                key: value for key, value in self._list_counts.items() if key[0] != normalized
            }
            self._read_cache_key_hashes = {
                key: value for key, value in self._read_cache_key_hashes.items() if key[0] != normalized
            }
        return removed

    def runtime_manifests(self, session: Mapping[str, object]) -> list[dict[str, object]]:
        session_id = str(session.get("id") or "").strip()
        with self._lock:
            binding = self._bindings.get(session_id)
            if binding is None:
                return []
        return [
            self._manifest(
                include_search=binding[1] in _SEARCH_WORKFLOW_PROFILES,
                observation_ids=binding[1] == "observation-id-v1",
            )
        ]

    def execute(self, payload: Mapping[str, object]) -> dict[str, object]:
        request = self._request(payload)
        session_id = str(request["sessionId"])
        args = request["args"]
        assert isinstance(args, Mapping)
        operation = str(args.get("op") or "")
        with self._lock:
            binding = self._bindings.get(session_id)
            receipt_id = self._binding_receipts.get(session_id, "")
        if binding is None or not receipt_id:
            raise ValueError("cloudops_benchmark is not bound to this evaluation Session")
        batch_id, workflow_profile = binding
        if operation == "search" and workflow_profile not in _SEARCH_WORKFLOW_PROFILES:
            raise ValueError("CloudOps search is unavailable for this workflow profile")
        started_at_ms = int(time.time() * 1_000)
        started_ns = time.perf_counter_ns()
        reservation: tuple[str, tuple[str, str], str] | None = None
        try:
            reservation = self._check_workflow_budget(
                session_id,
                workflow_profile=workflow_profile,
                operation=operation,
                args=args,
            )
            result = self._execute_operation(
                session_id,
                batch_id,
                workflow_profile,
                operation,
                args,
            )
            self._commit_workflow_budget(reservation)
            if workflow_profile in _BOUNDED_WORKFLOW_PROFILES and operation in {"list", "search", "read"}:
                result = dict(result)
                result["workflowBudget"] = self._workflow_budget(session_id, str(args.get("caseId") or ""))
            if workflow_profile == "observation-id-v1":
                result = self._without_cache_keys(result)
        except Exception as exc:
            self._record(
                request,
                batch_id=batch_id,
                operation=operation,
                started_at_ms=started_at_ms,
                started_ns=started_ns,
                result=None,
                error=exc,
                binding_receipt_id=receipt_id,
            )
            raise
        self._record(
            request,
            batch_id=batch_id,
            operation=operation,
            started_at_ms=started_at_ms,
            started_ns=started_ns,
            result=result,
            error=None,
            binding_receipt_id=receipt_id,
        )
        return {
            "schemaVersion": "paw.cloudops-agent-tool-result.v1",
            "ok": True,
            "tool": TOOL_NAME,
            "operation": operation,
            "result": result,
        }

    def _check_workflow_budget(
        self,
        session_id: str,
        *,
        workflow_profile: str,
        operation: str,
        args: Mapping[str, object],
    ) -> tuple[str, tuple[str, str], str] | None:
        if workflow_profile not in _BOUNDED_WORKFLOW_PROFILES or operation not in {"search", "list", "read"}:
            return None
        case_id = str(args.get("caseId") or "")
        key = (session_id, case_id)
        with self._lock:
            if operation == "list":
                if self._list_counts.get(key, 0) >= 1:
                    raise ValueError("CloudOps list fallback budget exhausted")
                return ("list", key, "")
            if operation == "read":
                cache_key_sha256 = _sha256(
                    str(args.get("observationId") or args.get("cacheKey") or "")
                )
                if cache_key_sha256 in self._read_cache_key_hashes.get(key, set()):
                    raise ValueError("CloudOps duplicate observation read is not allowed")
                return ("read", key, cache_key_sha256)
            normalized = " ".join(str(args.get("query") or "").strip().lower().split())
            query_sha256 = _sha256(normalized)
            prior = self._search_query_hashes.get(key, set())
            if query_sha256 in prior:
                raise ValueError("CloudOps duplicate search query is not allowed")
            if len(prior) >= 2:
                raise ValueError("CloudOps search budget exhausted")
            return ("search", key, query_sha256)

    def _commit_workflow_budget(
        self,
        reservation: tuple[str, tuple[str, str], str] | None,
    ) -> None:
        if reservation is None:
            return
        operation, key, value = reservation
        with self._lock:
            if operation == "list":
                self._list_counts[key] = self._list_counts.get(key, 0) + 1
            elif operation == "read":
                self._read_cache_key_hashes.setdefault(key, set()).add(value)
            else:
                self._search_query_hashes.setdefault(key, set()).add(value)

    def _workflow_budget(self, session_id: str, case_id: str) -> dict[str, int]:
        key = (session_id, case_id)
        with self._lock:
            return {
                "searchCalls": len(self._search_query_hashes.get(key, set())),
                "searchLimit": 2,
                "listCalls": self._list_counts.get(key, 0),
                "listLimit": 1,
                "readCalls": self._read_counts.get(key, 0),
                "readLimit": self.max_reads_per_case,
            }

    @staticmethod
    def _without_cache_keys(result: Mapping[str, object]) -> dict[str, object]:
        public = deepcopy(dict(result))
        public.pop("cacheKey", None)
        items = public.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    item.pop("cacheKey", None)
        return public

    def answers(self, session_id: str) -> list[dict[str, object]]:
        with self._lock:
            return deepcopy(self._answers.get(str(session_id), []))

    def ledger(self, *, session_id: str = "") -> dict[str, object]:
        with self._lock:
            items = [
                deepcopy(item)
                for item in self._ledger
                if not session_id or item["sessionId"] == session_id
            ]
        return {
            "schemaVersion": "paw.cloudops-agent-ledger.v1",
            "sessionId": session_id,
            "itemCount": len(items),
            "items": items,
            "ledgerSha256": _sha256(items),
        }

    def _execute_operation(
        self,
        session_id: str,
        batch_id: str,
        workflow_profile: str,
        operation: str,
        args: Mapping[str, object],
    ) -> dict[str, object]:
        if operation == "index":
            self._only_fields(args, {"op"})
            return self.suite.public_index(batch_id)
        if operation in {"list", "search", "read"}:
            case_id = str(args.get("caseId") or "").strip()
            if case_id not in self.suite.assigned_case_ids(batch_id):
                raise ValueError("CloudOps case is not assigned to this Session")
            if operation == "list":
                self._only_fields(args, {"op", "caseId", "toolName", "cursor", "limit"})
                tool_name = str(args.get("toolName") or "")
                if tool_name and _TOOL_NAME.fullmatch(tool_name) is None:
                    raise ValueError("CloudOps Tool name filter is invalid")
                cursor = str(args.get("cursor") or "0")
                if not cursor.isdigit():
                    raise ValueError("CloudOps list cursor is invalid")
                raw_limit = args.get("limit", 30)
                if (
                    isinstance(raw_limit, bool)
                    or not isinstance(raw_limit, int)
                    or not 1 <= raw_limit <= 50
                ):
                    raise ValueError("CloudOps list limit is invalid")
                return self.suite.list_observations(
                    case_id,
                    tool_name=tool_name,
                    cursor=int(cursor),
                    limit=raw_limit,
                )
            if operation == "search":
                self._only_fields(args, {"op", "caseId", "query", "limit"})
                raw_limit = args.get("limit", 10)
                if (
                    isinstance(raw_limit, bool)
                    or not isinstance(raw_limit, int)
                    or not 1 <= raw_limit <= 20
                ):
                    raise ValueError("CloudOps search limit is invalid")
                return self.suite.search_observations(
                    case_id,
                    query=str(args.get("query") or ""),
                    limit=raw_limit,
                )
            key = (session_id, case_id)
            with self._lock:
                used = self._read_counts.get(key, 0)
                if used >= self.max_reads_per_case:
                    raise ValueError("CloudOps observation read budget exhausted")
            if workflow_profile == "observation-id-v1":
                self._only_fields(args, {"op", "caseId", "observationId"})
                observation_id = str(args.get("observationId") or "")
                result = self.suite.read_observation(case_id, observation_id=observation_id)
            else:
                self._only_fields(args, {"op", "caseId", "cacheKey"})
                result = self.suite.read_observation(case_id, str(args.get("cacheKey") or ""))
            with self._lock:
                used = self._read_counts.get(key, 0)
                if used >= self.max_reads_per_case:
                    raise ValueError("CloudOps observation read budget exhausted")
                self._read_counts[key] = used + 1
            return result
        if operation == "submit":
            self._only_fields(args, {"op", "answers"})
            with self._lock:
                if session_id in self._answers:
                    raise ValueError("CloudOps answers were already submitted")
            answers = self.suite.validate_answers(batch_id, args.get("answers"))
            with self._lock:
                if session_id in self._answers:
                    raise ValueError("CloudOps answers were already submitted")
                self._answers[session_id] = deepcopy(answers)
            return {
                "schemaVersion": "paw.cloudops-answer-submission.v1",
                "batchId": batch_id,
                "answerCount": len(answers),
                "answersSha256": _sha256(answers),
                "accepted": True,
            }
        raise ValueError("unsupported cloudops_benchmark operation")

    @staticmethod
    def _only_fields(args: Mapping[str, object], allowed: set[str]) -> None:
        unknown = sorted(str(key) for key in set(args) - allowed)
        if unknown:
            raise ValueError(f"CloudOps Tool args contain unknown fields: {', '.join(unknown)}")

    def _record(
        self,
        request: Mapping[str, object],
        *,
        batch_id: str,
        operation: str,
        started_at_ms: int,
        started_ns: int,
        result: Mapping[str, object] | None,
        error: Exception | None,
        binding_receipt_id: str,
    ) -> None:
        args = request["args"]
        assert isinstance(args, Mapping)
        elapsed_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)
        summary: dict[str, object] = {"op": operation}
        for key in ("caseId", "toolName", "cursor", "limit"):
            if key in args:
                summary[key] = args[key]
        if "query" in args:
            normalized_query = " ".join(str(args.get("query") or "").strip().lower().split())
            summary["querySha256"] = _sha256(normalized_query)
            summary["queryTermCount"] = len(
                tuple(dict.fromkeys(re.findall(r"[a-z0-9_.:/-]+", normalized_query)))
            )
        if "cacheKey" in args:
            cache_key = str(args.get("cacheKey") or "")
            summary.update(
                {
                    "cacheKeySha256": _sha256(cache_key),
                    "originalToolName": cache_key.split(":", 1)[0],
                }
            )
        if "observationId" in args:
            summary["observationId"] = str(args.get("observationId") or "")
        result_summary: dict[str, object] = {}
        if result is not None:
            for key in (
                "caseId", "batchId", "answerCount", "answersSha256", "accepted",
                "total", "nextCursor", "totalMatches", "truncated",
                "usedTermCount", "ignoredTermCount",
                "observationChars", "observationSha256",
                "observationId", "evidenceId", "toolName",
            ):
                if key in result:
                    result_summary[key] = result[key]
            if operation == "index":
                result_summary["caseCount"] = len(result.get("cases") or [])
                result_summary["suiteSha256"] = result.get("suiteSha256")
            if operation == "list":
                result_summary["returned"] = len(result.get("items") or [])
            if operation == "search":
                result_summary["returned"] = len(result.get("items") or [])
            if isinstance(result.get("workflowBudget"), Mapping):
                result_summary["workflowBudget"] = dict(result["workflowBudget"])
        item = {
            "sessionId": str(request["sessionId"]),
            "batchId": batch_id,
            "toolCallId": str(request["toolCallId"]),
            "sourceLoopIdSha256": _sha256(str(request.get("sourceLoopId") or "")),
            "operation": operation,
            "args": summary,
            "resultSummary": result_summary,
            "bindingReceiptId": binding_receipt_id,
            "startedAtMs": started_at_ms,
            "endedAtMs": started_at_ms + max(0, int(round(elapsed_ms))),
            "durationMs": elapsed_ms,
            "ok": error is None,
            "errorType": "" if error is None else type(error).__name__,
            "errorFingerprint": "" if error is None else "sha256:" + _sha256(f"{type(error).__name__}:{error}"),
            "stopReason": self._stop_reason(error),
        }
        with self._lock:
            self._ledger.append(item)

    @staticmethod
    def _stop_reason(error: Exception | None) -> str:
        if error is None:
            return ""
        message = str(error).lower()
        if "duplicate search" in message:
            return "duplicate_search_query"
        if "search budget" in message:
            return "search_budget_exhausted"
        if "list fallback budget" in message:
            return "list_fallback_budget_exhausted"
        if "duplicate observation read" in message:
            return "duplicate_observation_read"
        if "read budget" in message:
            return "read_budget_exhausted"
        return "tool_error"

    @staticmethod
    def _request(payload: Mapping[str, object]) -> dict[str, object]:
        unknown = set(payload) - _CALL_FIELDS
        if unknown:
            raise ValueError("CloudOps Tool envelope contains unknown fields")
        if payload.get("schemaVersion") != "rag-ime.agent-tool-call.v1":
            raise ValueError("CloudOps Tool envelope has the wrong schema")
        if payload.get("tool") != TOOL_NAME:
            raise ValueError("CloudOps Tool envelope has the wrong tool")
        session_id = str(payload.get("sessionId") or "").strip()
        tool_call_id = str(payload.get("toolCallId") or "").strip()
        args = payload.get("args")
        if not session_id or not tool_call_id or not isinstance(args, Mapping):
            raise ValueError("CloudOps Tool envelope is incomplete")
        operation = str(args.get("op") or "")
        if operation not in _OPERATIONS:
            raise ValueError("unsupported cloudops_benchmark operation")
        return {
            "sessionId": session_id,
            "toolCallId": tool_call_id,
            "sourceLoopId": str(payload.get("sourceLoopId") or ""),
            "args": dict(args),
        }

    @staticmethod
    def _manifest(*, include_search: bool, observation_ids: bool = False) -> dict[str, object]:
        prediction = {
            "type": "object",
            "additionalProperties": False,
            "required": ["rank", "fault_object", "root_cause"],
            "properties": {
                "rank": {"type": "integer", "minimum": 1, "maximum": 3},
                "fault_object": {"type": "string", "pattern": r"^(app|node)/[A-Za-z0-9._-]+$"},
                "root_cause": {"type": "string", "minLength": 1, "maxLength": 120},
            },
        }
        answer = {
            "type": "object",
            "additionalProperties": False,
            "required": ["case_id", "key_evidence_summary", "top_3_predictions"],
            "properties": {
                "case_id": {"type": "string", "minLength": 1},
                "key_evidence_summary": {"type": "string", "minLength": 1, "maxLength": 2_000},
                "top_3_predictions": {"type": "array", "minItems": 3, "maxItems": 3, "items": prediction},
            },
        }
        schemas = [
            {"type": "object", "additionalProperties": False, "required": ["op"], "properties": {"op": {"const": "index"}}},
            {
                "type": "object", "additionalProperties": False, "required": ["op", "caseId"],
                "properties": {
                    "op": {"const": "list"}, "caseId": {"type": "string"},
                    "toolName": {"type": "string"}, "cursor": {"type": "string", "pattern": r"^[0-9]+$"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
            },
            {
                "type": "object", "additionalProperties": False,
                "required": ["op", "caseId", "query"],
                "properties": {
                    "op": {"const": "search"},
                    "caseId": {"type": "string"},
                    "query": {"type": "string", "minLength": 2, "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
            },
            (
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["op", "caseId", "observationId"],
                    "properties": {
                        "op": {"const": "read"},
                        "caseId": {"type": "string"},
                        "observationId": {"type": "string", "pattern": r"^obs_[0-9a-f]{24}$"},
                    },
                }
                if observation_ids
                else {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["op", "caseId", "cacheKey"],
                    "properties": {
                        "op": {"const": "read"},
                        "caseId": {"type": "string"},
                        "cacheKey": {"type": "string", "minLength": 1},
                    },
                }
            ),
            {
                "type": "object", "additionalProperties": False, "required": ["op", "answers"],
                "properties": {"op": {"const": "submit"}, "answers": {"type": "array", "items": answer}},
            },
        ]
        if not include_search:
            schemas = [
                schema
                for schema in schemas
                if schema.get("properties", {}).get("op", {}).get("const") != "search"
            ]
        return {
            "name": TOOL_NAME,
            "description": (
                "Inspect one assigned frozen CloudOps blind batch. Search or list its observation index, "
                "read exact evidence, then submit one evidence-backed Top-3 diagnosis."
                if include_search
                else "Inspect one assigned frozen CloudOps blind batch. List its observation index, "
                "read exact evidence, then submit one evidence-backed Top-3 diagnosis."
            ),
            "parameters": {"type": "object", "oneOf": schemas},
            "profile": PROFILE,
            "risk": "R0",
        }


class CloudOpsBenchmarkGatewayServer:
    """Loopback capability-token bridge for managed Pi evaluation Sessions."""

    transport = "loopback-http-v1"

    def __init__(
        self,
        gateway: CloudOpsBenchmarkGateway,
        *,
        token: str | None = None,
        max_request_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.gateway = gateway
        self.token = str(token or secrets.token_urlsafe(32))
        self.max_request_bytes = max(1_024, int(max_request_bytes))
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def tool_gateway_url(self) -> str:
        if self._server is None:
            raise RuntimeError("CloudOps Agent gateway server is not running")
        return f"http://127.0.0.1:{self._server.server_port}/api/agent/tool/execute"

    def start(self) -> "CloudOpsBenchmarkGatewayServer":
        if self._server is not None:
            return self
        gateway = self.gateway
        expected_token = self.token
        maximum = self.max_request_bytes

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/api/agent/tool/execute":
                    self._write(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
                    return
                provided = self.headers.get("X-RAG-IME-Agent-Token", "")
                if not provided or not hmac.compare_digest(provided, expected_token):
                    self._write(
                        HTTPStatus.FORBIDDEN,
                        {"ok": False, "error": "agent capability token required"},
                    )
                    return
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except ValueError:
                    length = 0
                if length <= 0 or length > maximum:
                    self._write(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        {"ok": False, "error": "invalid CloudOps Tool request size"},
                    )
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(payload, Mapping):
                        raise ValueError("CloudOps Tool request must be an object")
                    response = gateway.execute(payload)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    self._write(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "ok": False,
                            "error": str(exc),
                            "errorCode": "invalid_request",
                        },
                    )
                    return
                self._write(HTTPStatus.OK, response)

            def _write(self, status: HTTPStatus, payload: Mapping[str, object]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(int(status))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="cloudops-benchmark-agent-gateway",
            daemon=True,
        )
        self._thread.start()
        return self

    def close(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def __enter__(self) -> "CloudOpsBenchmarkGatewayServer":
        return self.start()

    def __exit__(self, *_args: object) -> None:
        self.close()
