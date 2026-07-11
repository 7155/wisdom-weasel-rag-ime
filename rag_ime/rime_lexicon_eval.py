from __future__ import annotations

import json
from pathlib import Path


SCHEMA_VERSION = "rag-ime.rime-lexicon-eval.v1"
REPORT_SCHEMA_VERSION = "rag-ime.rime-lexicon-eval-report.v1"


def load_rime_lexicon_eval(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"eval fixture schemaVersion must be {SCHEMA_VERSION}")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("eval fixture requires cases")
    seen_ids: set[str] = set()
    seen_inputs: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"cases[{index}] must be an object")
        case_id = str(case.get("id") or "").strip()
        raw_input = str(case.get("input") or "").strip()
        expected = str(case.get("expectedTop1") or "").strip()
        if not case_id or case_id in seen_ids:
            raise ValueError(f"invalid or duplicate case id: {case_id!r}")
        if not raw_input or raw_input in seen_inputs or not raw_input.isascii() or not raw_input.isalpha():
            raise ValueError(f"invalid or duplicate ASCII pinyin input: {raw_input!r}")
        if not expected:
            raise ValueError(f"cases[{index}] requires expectedTop1")
        seen_ids.add(case_id)
        seen_inputs.add(raw_input)
    return payload


def parse_librime_probe_output(output: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line_number, raw_line in enumerate(output.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("["):
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            raise ValueError(f"probe output line {line_number} has no candidates")
        raw_input = fields[0].strip()
        if raw_input in rows:
            raise ValueError(f"duplicate probe input: {raw_input}")
        rows[raw_input] = [candidate.strip() for candidate in fields[1:] if candidate.strip()]
    return rows


def evaluate_librime_probe(fixture: dict[str, object], output: str) -> dict[str, object]:
    rows = parse_librime_probe_output(output)
    raw_cases = fixture.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("fixture cases must be an array")
    results: list[dict[str, object]] = []
    group_top1: dict[str, set[str]] = {}
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            continue
        raw_input = str(raw_case["input"])
        candidates = rows.get(raw_input, [])
        expected = str(raw_case["expectedTop1"])
        actual = candidates[0] if candidates else ""
        passed = actual == expected
        group = str(raw_case.get("equivalenceGroup") or "").strip()
        if group and actual:
            group_top1.setdefault(group, set()).add(actual)
        results.append(
            {
                "id": raw_case["id"],
                "category": raw_case.get("category", ""),
                "input": raw_input,
                "expectedTop1": expected,
                "actualTop1": actual,
                "candidateCount": len(candidates),
                "passed": passed,
            }
        )
    missing = sorted({str(case["input"]) for case in raw_cases if isinstance(case, dict)} - rows.keys())
    unexpected = sorted(rows.keys() - {str(case["input"]) for case in raw_cases if isinstance(case, dict)})
    inconsistent_groups = sorted(group for group, values in group_top1.items() if len(values) > 1)
    passed_count = sum(1 for result in results if result["passed"])
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "ok": passed_count == len(results) and not missing and not unexpected and not inconsistent_groups,
        "caseCount": len(results),
        "passedCount": passed_count,
        "top1Accuracy": round(passed_count / len(results), 6) if results else 0.0,
        "missingInputs": missing,
        "unexpectedInputs": unexpected,
        "inconsistentEquivalenceGroups": inconsistent_groups,
        "results": results,
        "boundary": "standalone deployed librime only; does not claim foreground Squirrel selection",
    }
