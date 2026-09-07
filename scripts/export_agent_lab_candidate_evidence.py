#!/usr/bin/env python3
"""Export a reproducible public Lab evidence receipt from frozen local inputs.

No Agent, Provider, Judge, live database, installation, or Held-out is used.
An existing different output is rejected; historical receipts are immutable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_lab.candidate_evidence import PUBLIC_EVIDENCE_REF, build_candidate_evidence
from rag_ime.contracts.json_schema import load_contract, validate_contract
from scripts.import_agent_lab_experiments import read_public_experiments


def build_public_receipt(root: Path) -> dict[str, object]:
    _, _, experiments = read_public_experiments(ledger_path=root / "eval/interview-metrics/agent-experiments.v1.json")
    experiment = next(item for item in experiments if item["experimentId"] == "enterprise-rag.luna-prompt-v4-standard-r6.v1")
    evidence = build_candidate_evidence(experiment, root=root)
    if not evidence or evidence["patch"]["status"] != "available" or len(evidence["caseComparisons"]) != experiment["dataset"]["caseCount"]:
        raise ValueError("frozen source inputs cannot produce the full public candidate evidence")
    validate_contract(evidence, {"$ref": "#/$defs/optimizationEvidence", "$defs": load_contract("agent-lab-experiment.v1.json")["$defs"]})
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-lab-candidate-evidence.v1",
        "experimentId": experiment["experimentId"],
        "experimentRevisionSha256": experiment["revisionSha256"],
        "baselineRunId": experiment["baseline"]["runId"],
        "candidateRunId": experiment["candidate"]["runId"],
        "manifestSha256": experiment["dataset"]["manifestSha256"],
        "sourceReceipts": [
            {"ref": ref, "fileSha256": hashlib.sha256((root / ref).read_bytes()).hexdigest()}
            for ref in sorted(set(experiment["baseline"]["evidenceRefs"] + experiment["candidate"]["evidenceRefs"]))
        ],
        "evidence": evidence,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["receiptSha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


def write_or_verify(path: Path, payload: dict[str, object]) -> str:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError("existing public candidate evidence differs; choose a new append-only receipt")
        return "verified"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    return "written"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    payload = build_public_receipt(root)
    output = args.output or root / PUBLIC_EVIDENCE_REF
    print(json.dumps({"action": write_or_verify(output, payload), "output": str(output), "receiptSha256": payload["receiptSha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
