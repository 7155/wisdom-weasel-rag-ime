from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import build_paw_backend_web_model_package as package_builder


class PawBackendWebModelPackageTests(unittest.TestCase):
    def test_agent_lab_index_projects_current_four_project_evidence(self) -> None:
        sources = (
            "eval/interview-metrics/runs/agent-lab-optimal-path-enterpriseops-luna-prompt-20260904.v1.json",
            "eval/interview-metrics/runs/agent-lab-optimal-path-cloudops-luna-prompt-20260904.v1.json",
            "eval/interview-metrics/runs/memory-maintenance-sol-to-luna-model-only-optimization-20260904.r1.json",
            "eval/interview-metrics/runs/enterprise-rag-answer-evidence-sol-max-frozen-v19-r4-attention-r6-exact-offline-rescore-20260905.v1.json",
            "eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-model-only-v19-r4-attention-r6-exact-offline-rescore-20260905.v1.json",
            "eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-coverage-balanced-v4-r4-attention-r6-exact-offline-rescore-20260905.v1.json",
            "eval/interview-metrics/runs/agent-lab-cost-enterprise-rag-sol-max-frozen-v19-20260904.r4.v1.json",
            "eval/interview-metrics/runs/agent-lab-cost-enterprise-rag-luna-max-model-only-v19-20260904.r4.v1.json",
            "eval/interview-metrics/runs/agent-lab-cost-enterprise-rag-luna-max-coverage-balanced-v4-20260904.r4.v1.json",
        )

        with tempfile.TemporaryDirectory() as raw_temp:
            staging = Path(raw_temp)
            receipts: list[package_builder.SourceReceipt] = []
            for source_relative in sources:
                source = package_builder.PAW_ROOT / source_relative
                target_relative = f"evaluation/agent-lab-results/{source_relative}"
                target = staging / target_relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                receipts.append(
                    package_builder.SourceReceipt(
                        repository="paw",
                        category="agent-lab-evaluation-result",
                        source_relative=source_relative,
                        target=target_relative,
                        git_status="test-fixture",
                        original_bytes=source.stat().st_size,
                        original_sha256=digest,
                        package_bytes=target.stat().st_size,
                        package_sha256=digest,
                        redactions={},
                    )
                )

            rendered = package_builder.render_agent_lab_evidence_index(staging, receipts)

        self.assertIn("Sol baseline -> Luna model-only Reject -> Luna + Prompt", rendered)
        self.assertIn("exact citation facts 7/9 -> 8/9 -> 9/9", rendered)
        self.assertIn("$2.170603 -> $0.1029376; -95.2576% (21.0866x)", rendered)
        self.assertIn("$0.10594896 -> $0.1029376; -2.8423%", rendered)
        self.assertIn("Validation-quality Keep", rendered)
        self.assertIn("rescoredDecision=reject", rendered)
        self.assertIn("rescoredDecision=keep", rendered)
        self.assertIn("candidate-aware", rendered)
        self.assertIn("Held-out remains unopened", rendered)
        self.assertNotIn("Stage 1 preflight only", rendered)
        self.assertNotIn("three-qualified/one-invalid", rendered)

        for source_relative in sources[3:]:
            self.assertIn(source_relative, package_builder.AGENT_LAB_EVIDENCE_FILES)
        self.assertIn(
            "control-center-web/src/features/eval-lab/optimization/OptimizationWorkbench.tsx",
            package_builder.AGENT_LAB_UI_FILES,
        )

        trace_receipt = package_builder.TRACE_TEST_RESULTS_MARKDOWN
        self.assertIn("2026-09-05", trace_receipt)
        self.assertIn("78/78 passed", trace_receipt)
        self.assertIn("45/45", trace_receipt)
        self.assertIn("real loopback HTTP", trace_receipt)
        self.assertNotIn("were not rerun", trace_receipt)
        self.assertNotIn("66/66 passed", trace_receipt)


if __name__ == "__main__":
    unittest.main()
