"""Deterministic JSONL evaluation through the existing Lab adapter contract.

Run from the checkout: python -m examples.lab.exact_match
Each fixture row has string fields `actual` and `expected`. No Provider is used.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from rag_ime.agent_lab.trial_execution import AgentLabTrialApplication, TrialObserver
from rag_ime.agent_lab.trials import AgentLabTrialStore


class ExactMatchTrial:
    def __init__(self, fixture_root: Path) -> None:
        self.fixture_root = fixture_root.resolve(strict=True)

    def prepare(self, spec: Mapping[str, object], job_id: str) -> Mapping[str, object]:
        if set(spec) != {"fixture"} or not isinstance(spec["fixture"], str):
            raise ValueError("spec must name one fixture")
        fixture = (self.fixture_root / spec["fixture"]).resolve(strict=True)
        if not fixture.is_relative_to(self.fixture_root) or not fixture.is_file():
            raise ValueError(
                "fixture must be a file inside the registered fixture root"
            )
        return {
            "publicSpec": {"evaluator": "exact-match.v1"},
            "privateInput": {"fixture": str(fixture)},
        }

    def execute(
        self,
        private_input: Mapping[str, object],
        observer: TrialObserver,
        cancelled: Callable[[], bool],
    ) -> Mapping[str, object]:
        fixture = Path(str(private_input["fixture"])).resolve(strict=True)
        if not fixture.is_relative_to(self.fixture_root):
            raise ValueError("fixture left its registered root")
        matched = total = 0
        # The handle is closed on success, cancellation and malformed input,
        # before control returns to the scheduler and it publishes terminality.
        with fixture.open(encoding="utf-8") as rows:
            for line in rows:
                if cancelled():
                    return {"status": "cancelled", "evaluated": total}
                if total >= 1000 or len(line) > 65536:
                    raise ValueError("fixture exceeds the example evaluation budget")
                row = json.loads(line)
                if (
                    not isinstance(row, dict)
                    or set(row) != {"actual", "expected"}
                    or not all(isinstance(value, str) for value in row.values())
                ):
                    raise ValueError("fixture rows require actual and expected strings")
                total += 1
                matched += row["actual"] == row["expected"]
                observer.progress(f"Evaluated case {total}")
        if not total:
            raise ValueError("fixture has no cases")
        return {
            "status": "completed",
            "evaluated": total,
            "matched": matched,
            "score": matched / total,
            "qualityVerdict": "pass" if matched == total else "reject",
        }


def main() -> None:
    fixture_root = Path(__file__).parent
    with tempfile.TemporaryDirectory(prefix="paw-lab-example-") as scratch:
        application = AgentLabTrialApplication(
            AgentLabTrialStore(Path(scratch) / "trial.sqlite"),
            {"exact-match": ExactMatchTrial(fixture_root)},
            start_workers=False,
        )
        try:
            admitted = application.start(
                "example-1", "exact-match", {"fixture": "answers.jsonl"}
            )
            result = application.run_job(str(admitted["job"]["jobId"]))
            print(json.dumps(result["job"]["result"], ensure_ascii=False, indent=2))
        finally:
            application.close()


if __name__ == "__main__":
    main()
