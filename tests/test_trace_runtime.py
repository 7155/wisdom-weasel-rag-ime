from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import unittest

from rag_ime.trace_runtime import (
    ArtifactRef,
    EvidenceRef,
    TraceLink,
    SandboxRun,
    TraceContractError,
    TraceEnvelope,
    TraceSpan,
    EvalRun,
    build_eval_run,
    build_sandbox_run,
    build_trace_envelope,
    fingerprint_text,
    make_span,
    validate_eval_run,
    validate_trace_envelope,
)


class TraceRuntimeContractTests(unittest.TestCase):
    def test_trace_links_and_bindings_are_typed_bounded_and_deduplicated(self) -> None:
        links = (
            {"traceId": "trace:retry", "relation": "retry", "targetKind": "trace"},
            {"traceId": "trace:retry", "relation": "retry", "targetKind": "trace"},
            {"traceId": "trace:related", "relation": "related", "targetKind": "trace"},
        )
        trace = build_trace_envelope(
            trace_id="trace:child",
            source_kind="vertical_agent",
            input_text="",
            binding={"workItemId": "work:sgg", "caseId": "case:001"},
            parent_trace_id="trace:root",
            links=links,
            now_ms=2,
        )

        payload = trace.to_dict()
        self.assertEqual(payload["binding"], {"workItemId": "work:sgg", "caseId": "case:001"})
        self.assertEqual(payload["parentTraceId"], "trace:root")
        self.assertEqual(
            payload["links"],
            [
                {"traceId": "trace:retry", "relation": "retry", "targetKind": "trace"},
                {"traceId": "trace:related", "relation": "related", "targetKind": "trace"},
            ],
        )
        validate_trace_envelope(payload)
        with self.assertRaises(TypeError):
            trace.links[0]["traceId"] = "trace:private"

    def test_trace_links_reject_raw_paths_urls_and_unsupported_types(self) -> None:
        for field_name, value in (
            ("trace_id", "/private/trace"),
            ("trace_id", "https://private.example/trace"),
            ("parent_trace_id", "file:///private/parent"),
        ):
            with self.subTest(field_name=field_name, value=value):
                kwargs = {
                    "trace_id": "trace:links",
                    "source_kind": "agent",
                    "input_text": "",
                    "now_ms": 1,
                }
                kwargs[field_name] = value
                with self.assertRaises(TraceContractError):
                    build_trace_envelope(**kwargs)

        for link in (
            {"traceId": "/private/trace", "relation": "related", "targetKind": "trace"},
            {"traceId": "https://private.example/trace", "relation": "related", "targetKind": "trace"},
            {"traceId": "trace:target", "relation": "parent", "targetKind": "trace"},
            {"traceId": "trace:target", "relation": "dispatch", "targetKind": "trace"},
            {"traceId": "trace:target", "relation": "related", "targetKind": "workItem"},
            {"traceId": "trace:target", "relation": "related", "targetKind": "url"},
            {"traceId": "trace:target", "relation": "related", "targetKind": "trace", "label": "raw"},
        ):
            with self.subTest(link=link):
                with self.assertRaises(TraceContractError):
                    build_trace_envelope(
                        trace_id="trace:links",
                        source_kind="agent",
                        input_text="",
                        links=(link,),
                        now_ms=1,
                    )

    def test_direct_trace_envelope_validates_and_freezes_typed_links(self) -> None:
        direct = TraceEnvelope(
            trace_id="trace:direct",
            source_kind="agent",
            status="completed",
            binding={"workItemId": "work:direct", "caseId": "case:direct"},
            input_fingerprint=fingerprint_text(""),
            input_content_policy="hash_only",
            input_normalization="none",
            spans=(),
            evidence=(),
            artifacts=(),
            created_at_ms=1,
            updated_at_ms=1,
            parent_trace_id="trace:parent",
            links=(TraceLink("trace:related", "related"),),
        )
        self.assertEqual(direct.to_dict()["binding"]["caseId"], "case:direct")
        with self.assertRaises(TypeError):
            direct.links[0]["relation"] = "related"
        with self.assertRaises(TraceContractError):
            TraceEnvelope(
                trace_id="trace:direct",
                source_kind="agent",
                status="completed",
                binding={"workItemId": "/private/work"},
                input_fingerprint=fingerprint_text(""),
                input_content_policy="hash_only",
                input_normalization="none",
                spans=(),
                evidence=(),
                artifacts=(),
                created_at_ms=1,
                updated_at_ms=1,
            )

        for binding in (
            {"workItemId": "/private/work"},
            {"caseId": "https://private.example/case"},
            {"workItemId": "PRIVATE RAW WORK ITEM"},
        ):
            with self.subTest(binding=binding):
                with self.assertRaises(TraceContractError):
                    build_trace_envelope(
                        trace_id="trace:links",
                        source_kind="agent",
                        input_text="",
                        binding=binding,
                        now_ms=1,
                    )

    def test_trace_envelope_is_common_and_privacy_safe_by_default(self) -> None:
        trace = build_trace_envelope(
            trace_id="trace:sgg:001",
            source_kind="vertical_agent",
            input_text="掌柜问数：本月销售额",
            binding={"runId": "run:sgg:001"},
            spans=(
                make_span(
                    span_id="span:retrieve",
                    name="rag.retrieve",
                    started_at_ms=100,
                    ended_at_ms=135,
                    parent_span_id=None,
                ),
                make_span(
                    span_id="span:judge",
                    name="eval.judge",
                    started_at_ms=140,
                    recorded=False,
                    unavailable_reason="judge_not_configured",
                ),
            ),
            evidence=(
                {
                    "evidenceId": "doc:revenue",
                    "sourceKind": "knowledge",
                    "sourceRef": "knowledge://sales/revenue",
                    "sourceLane": "hybrid_reranked",
                    "evidenceStage": "retrieval_output",
                    "disposition": "included",
                    "rankBefore": 2,
                    "rankAfter": 1,
                },
            ),
        )

        payload = trace.to_dict()
        self.assertNotIn("掌柜问数", str(payload))
        self.assertEqual(payload["schemaVersion"], "rag-ime.trace-envelope.v1")
        self.assertEqual(payload["input"]["contentPolicy"], "hash_only")
        self.assertEqual(payload["spans"][0]["durationMs"], 35)
        self.assertIsNone(payload["spans"][1]["durationMs"])
        self.assertEqual(payload["evidence"][0]["sourceLane"], "hybrid_reranked")
        self.assertEqual(payload["evidence"][0]["evidenceStage"], "retrieval_output")
        validate_trace_envelope(payload)

    def test_eval_separates_ground_truth_metrics_from_ai_judge_estimates(self) -> None:
        grounded = build_eval_run(
            eval_run_id="eval:grounded:001",
            trace_ids=("trace:sgg:001",),
            mode="ground_truth",
            truth_kind="frozen",
            dataset_id="sgg-v1",
            label_revision="2026-08-28",
            metrics={"precision": 1.0, "recall": 0.5, "f1": 2 / 3},
        ).to_dict()
        judged = build_eval_run(
            eval_run_id="eval:judge:001",
            trace_ids=("trace:sgg:001",),
            mode="ai_judge",
            truth_kind="none",
            evaluator={
                "provider": "openai-codex",
                "model": "gpt-5.6-luna",
                "thinking": "max",
                "displayName": "Luna Max",
            },
            metrics={"relevance": 0.8, "groundedness": 0.9},
        ).to_dict()

        self.assertEqual(grounded["metricAuthority"], "ground_truth")
        self.assertEqual(grounded["truth"]["status"], "frozen")
        self.assertEqual(judged["metricAuthority"], "ai_judge_estimate")
        self.assertEqual(judged["truth"]["status"], "none")
        self.assertNotIn("precision", judged["metrics"])
        validate_eval_run(grounded)
        validate_eval_run(judged)

        human = build_eval_run(
            eval_run_id="eval:human:001",
            trace_ids=("trace:sgg:001",),
            mode="ground_truth",
            truth_kind="human",
            dataset_id="sgg-manual-v1",
            label_revision="review-1",
            metrics={"precision": 1.0, "recall": 1.0, "f1": 1.0},
        ).to_dict()
        self.assertEqual(human["evaluator"]["displayName"], "Human labels")

    def test_eval_rejects_unlabelled_deterministic_metrics(self) -> None:
        with self.assertRaisesRegex(TraceContractError, "ground truth"):
            build_eval_run(
                eval_run_id="eval:bad",
                trace_ids=("trace:1",),
                mode="ground_truth",
                truth_kind="none",
                metrics={"precision": 0.4},
            )

        with self.assertRaises(TraceContractError):
            build_eval_run(
                eval_run_id="eval:duplicate-trace",
                trace_ids=("trace:1", "trace:1"),
                mode="ground_truth",
                truth_kind="frozen",
                dataset_id="dataset:v1",
                label_revision="labels:1",
                metrics={"precision": 1.0, "recall": 1.0, "f1": 1.0},
            ).to_dict()

    def test_eval_rejects_invalid_numbers_and_unverified_evaluator_provenance(self) -> None:
        base = {
            "eval_run_id": "eval:invalid",
            "trace_ids": ("trace:1",),
            "mode": "ground_truth",
            "truth_kind": "frozen",
            "dataset_id": "dataset:v1",
            "label_revision": "labels:1",
        }
        for metric in (float("nan"), float("inf"), float("-inf"), -0.1, 1.1):
            with self.subTest(metric=metric):
                with self.assertRaisesRegex(TraceContractError, "finite|between 0 and 1"):
                    build_eval_run(**base, metrics={"precision": metric})
        with self.assertRaisesRegex(TraceContractError, "finite number"):
            build_eval_run(**base, metrics={"precision": "PRIVATE_RAW_METRIC"})

        with self.assertRaisesRegex(TraceContractError, "label authority"):
            build_eval_run(
                **base,
                metrics={"precision": 1.0},
                evaluator={
                    "provider": "openai",
                    "model": "judge",
                    "thinking": "high",
                    "displayName": "Unverified judge",
                },
            )
        with self.assertRaisesRegex(TraceContractError, "explicit evaluator provenance"):
            build_eval_run(
                eval_run_id="eval:judge:missing-provenance",
                trace_ids=("trace:1",),
                mode="ai_judge",
                truth_kind="none",
                metrics={"confidence": 0.5},
            )

        valid = build_eval_run(**base, metrics={"precision": 1.0}).to_dict()
        valid["evaluator"] = {
            "provider": "openai",
            "model": "judge",
            "thinking": "high",
            "displayName": "Forged labels",
        }
        with self.assertRaisesRegex(TraceContractError, "label authority"):
            validate_eval_run(valid)

    def test_trace_evidence_identity_is_stage_scoped(self) -> None:
        staged = build_trace_envelope(
            trace_id="trace:staged",
            source_kind="active_rag",
            input_text="private input",
            evidence=(
                {
                    "evidenceId": "e1",
                    "sourceKind": "knowledge",
                    "sourceRef": "knowledge://e1",
                    "evidenceStage": "retrieval_candidate",
                    "disposition": "included",
                },
                {
                    "evidenceId": "e1",
                    "sourceKind": "knowledge",
                    "sourceRef": "knowledge://e1",
                    "evidenceStage": "retrieval_output",
                    "disposition": "included",
                },
            ),
            now_ms=20,
        ).to_dict()
        self.assertEqual(len(staged["evidence"]), 2)

        duplicate = dict(staged)
        duplicate["evidence"] = [staged["evidence"][1], staged["evidence"][1]]
        with self.assertRaisesRegex(TraceContractError, "evidence identity"):
            validate_trace_envelope(duplicate)

    def test_span_metadata_uses_a_closed_public_projection(self) -> None:
        unsafe_attributes = (
            {"prompt": "PRIVATE_PROMPT"},
            {"url": "https://private.example/token"},
            {"reason": "PRIVATE_REASON"},
            {"snapshotId": "PRIVATE_SNAPSHOT"},
            {"error": "PRIVATE_ERROR"},
            {"candidateText": "PRIVATE_CANDIDATE"},
            {"custom": {"nested": "PRIVATE_NESTED"}},
        )
        for attributes in unsafe_attributes:
            with self.subTest(attributes=attributes):
                with self.assertRaisesRegex(
                    TraceContractError,
                    "unsupported public span attribute",
                ):
                    make_span(
                        span_id="span:unsafe-attribute",
                        name="agent.test",
                        started_at_ms=1,
                        ended_at_ms=1,
                        attributes=attributes,
                    )

        unsafe_metrics = (
            {"result": 1},
            {"candidateText": 1},
            {"elapsedMs": float("nan")},
            {"elapsedMs": "12"},
        )
        for metrics in unsafe_metrics:
            with self.subTest(metrics=metrics):
                with self.assertRaisesRegex(
                    TraceContractError,
                    "span metric|unsupported public span metric",
                ):
                    make_span(
                        span_id="span:unsafe-metric",
                        name="agent.test",
                        started_at_ms=1,
                        ended_at_ms=1,
                        metrics=metrics,
                    )

        payload = build_trace_envelope(
            trace_id="trace:strict-validation",
            source_kind="agent",
            input_text="",
            spans=(
                make_span(
                    span_id="span:strict-validation",
                    name="agent.test",
                    started_at_ms=1,
                    ended_at_ms=1,
                    metrics={"elapsedMs": 0},
                    attributes={"targetParticipantId": "planet-1"},
                ),
            ),
            now_ms=1,
        ).to_dict()
        payload["spans"][0]["attributes"]["title"] = "PRIVATE_TITLE"
        with self.assertRaisesRegex(TraceContractError, "unsupported public span attribute"):
            validate_trace_envelope(payload)

    def test_trace_identity_grammar_rejects_raw_values_at_build_and_persisted_boundaries(self) -> None:
        valid_span = make_span(
            span_id="span:grammar",
            name="agent.answer",
            started_at_ms=1,
            ended_at_ms=2,
        )
        base = build_trace_envelope(
            trace_id="trace:grammar",
            source_kind="vertical_agent",
            input_text="private input",
            binding={"sessionId": "session:grammar"},
            spans=(valid_span,),
            now_ms=2,
        ).to_dict()

        persisted_mutations = (
            ("traceId", "https://user:password@example.test/private?token=secret#fragment"),
            ("sourceKind", "PRIVATE RAW SOURCE"),
            ("binding", {"sessionId": "/private/session/path"}),
            ("input", {**base["input"], "normalization": "PRIVATE RAW NORMALIZATION"}),
        )
        for field_name, value in persisted_mutations:
            with self.subTest(field_name=field_name):
                candidate = deepcopy(base)
                if field_name == "input":
                    candidate[field_name] = value
                else:
                    candidate[field_name] = value
                with self.assertRaises(TraceContractError):
                    validate_trace_envelope(candidate)

        for kwargs in (
            {"trace_id": "/private/trace", "source_kind": "vertical_agent"},
            {"trace_id": "trace:grammar", "source_kind": "PRIVATE RAW SOURCE"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TraceContractError):
                    build_trace_envelope(
                        **kwargs,
                        input_text="",
                        spans=(valid_span,),
                        now_ms=2,
                    )

        for kwargs in (
            {"span_id": "span:raw path", "name": "agent.answer"},
            {"span_id": "span:grammar", "name": "PRIVATE RAW SPAN"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TraceContractError):
                    make_span(**kwargs, started_at_ms=1, ended_at_ms=2)

    def test_evidence_source_refs_allow_safe_schemes_but_reject_content_and_paths(self) -> None:
        for source_ref in (
            "knowledge://sales/revenue",
            "fixture://memory/sgg/pricing-policy",
            "sales-ledger",
            "knowledge:doc-1",
        ):
            with self.subTest(source_ref=source_ref):
                evidence = EvidenceRef("doc:1", "knowledge", source_ref)
                self.assertEqual(evidence.source_ref, source_ref)
                self.assertNotIn("PRIVATE", str(asdict(evidence)))

        for source_ref in (
            "https://user:password@example.test/private",
            "https://example.test/public",
            "http://example.test/public",
            "file://example.test/private",
            "http:private",
            "file:private",
            "custom://internal/resource",
            "knowledge://sales/revenue?token=secret",
            "knowledge://sales/revenue#fragment",
            "/private/source.txt",
            "C:\\private\\source.txt",
            "PRIVATE RAW EVIDENCE SENTENCE",
        ):
            with self.subTest(source_ref=source_ref):
                with self.assertRaises(TraceContractError):
                    EvidenceRef("doc:unsafe", "knowledge", source_ref)

    def test_artifact_and_direct_dataclass_surfaces_are_validated_before_asdict(self) -> None:
        artifact_kwargs = {
            "artifact_id": "artifact:grammar",
            "kind": "eval",
            "media_type": "application/json",
            "sha256": "a" * 64,
            "byte_size": 12,
            "record_count": 1,
        }
        artifact = ArtifactRef(**artifact_kwargs)
        self.assertEqual(asdict(artifact)["artifact_id"], "artifact:grammar")
        for field_name, value in (
            ("artifact_id", "/private/artifact"),
            ("kind", "PRIVATE RAW KIND"),
            ("media_type", "text/plain;PRIVATE"),
            ("sha256", "A" * 64),
            ("byte_size", -1),
            ("record_count", True),
        ):
            with self.subTest(field_name=field_name):
                candidate = {**artifact_kwargs, field_name: value}
                with self.assertRaises(TraceContractError):
                    ArtifactRef(**candidate)

        with self.assertRaises(TraceContractError):
            TraceSpan(
                "span:raw",
                "PRIVATE RAW SPAN",
                None,
                "completed",
                1,
                2,
                1,
                True,
                "",
                {"elapsedMs": 1},
                {"provider": "https://private.example"},
            )

        safe_span = make_span(
            span_id="span:asdict",
            name="agent.answer",
            started_at_ms=1,
            ended_at_ms=2,
            attributes={"provider": "openai-codex"},
        )
        with self.assertRaises(TypeError):
            safe_span.attributes["provider"] = "PRIVATE"
        safe_envelope = build_trace_envelope(
            trace_id="trace:asdict",
            source_kind="vertical_agent",
            input_text="PRIVATE USER INPUT",
            spans=(safe_span,),
            evidence=(EvidenceRef("doc:asdict", "knowledge", "knowledge://doc-1"),),
            artifacts=(artifact,),
            now_ms=2,
        )
        direct = asdict(safe_envelope)
        self.assertNotIn("PRIVATE USER INPUT", str(direct))
        self.assertNotIn("PRIVATE", str(direct))
        with self.assertRaises(TypeError):
            safe_envelope.binding["sessionId"] = "PRIVATE"
        with self.assertRaises(TypeError):
            safe_envelope.evidence[0]["scores"]["PRIVATE"] = 1

    def test_eval_provenance_ids_and_labels_reject_raw_strings(self) -> None:
        base = {
            "eval_run_id": "eval:grammar",
            "trace_ids": ("trace:grammar",),
            "mode": "ai_judge",
            "truth_kind": "none",
            "metrics": {"relevance": 0.5},
            "evaluator": {
                "provider": "openai-codex",
                "model": "gpt-5.6-luna",
                "thinking": "max",
                "displayName": "Luna Max",
            },
        }
        for field_name, value in (
            ("eval_run_id", "https://private.example/eval"),
            ("trace_ids", ("/private/trace",)),
            ("evaluator", {**base["evaluator"], "provider": "PRIVATE RAW PROVIDER"}),
            ("evaluator", {**base["evaluator"], "displayName": "PRIVATE RAW EVALUATION SENTENCE"}),
        ):
            with self.subTest(field_name=field_name):
                candidate = {**base, field_name: value}
                with self.assertRaises(TraceContractError):
                    build_eval_run(**candidate)

        valid = build_eval_run(**base)
        self.assertNotIn("PRIVATE", str(asdict(valid)))
        direct_payload = valid.to_dict()
        direct_payload["evalRunId"] = "PRIVATE RAW EVAL ID"
        with self.assertRaises(TraceContractError):
            EvalRun(direct_payload)

    def test_sandbox_run_discloses_staging_boundary_and_links_traces(self) -> None:
        record = build_sandbox_run(
            sandbox_run_id="sandbox:sgg:001",
            app_id="sgg",
            workspace_root="/workspace/sgg",
            workspace_binding_id="workspace-binding:sgg:self-test",
            mutation_mode="staged",
            trace_ids=("trace:sgg:001",),
            eval_run_ids=("eval:grounded:001",),
        )
        run = record.to_dict()

        self.assertEqual(run["schemaVersion"], "rag-ime.sandbox-run.v1")
        self.assertEqual(run["policy"]["mutationMode"], "staged")
        self.assertTrue(run["policy"]["productionWriteBlocked"])
        self.assertEqual(run["policy"]["workspaceBindingId"], "workspace-binding:sgg:self-test")
        self.assertRegex(run["policy"]["workspaceFingerprint"], r"^sha256:[a-f0-9]{64}$")
        self.assertNotIn("workspaceRoot", run["policy"])
        self.assertNotIn("/workspace/sgg", str(asdict(record)))
        self.assertEqual(run["traceIds"], ["trace:sgg:001"])

        with self.assertRaises(TypeError):
            record.payload["policy"]["network"] = "allowlisted"
        with self.assertRaises(TypeError):
            record.payload["traceIds"] += ("trace:private",)

        detached = record.to_dict()
        detached["policy"]["network"] = "allowlisted"
        self.assertEqual(record.to_dict()["policy"]["network"], "blocked")

        with self.assertRaises(TraceContractError):
            SandboxRun({
                **run,
                "policy": {
                    "workspaceRoot": "/PRIVATE/path",
                    "mutationMode": "staged",
                    "network": "blocked",
                    "productionWriteBlocked": True,
                },
            })

        with self.assertRaises(TraceContractError):
            build_sandbox_run(
                sandbox_run_id="sandbox:duplicate",
                app_id="sgg",
                workspace_root="/workspace/sgg",
                trace_ids=("trace:sgg:001", "trace:sgg:001"),
            ).to_dict()


if __name__ == "__main__":
    unittest.main()
