from __future__ import annotations

import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rag_ime.agent_lab.optimization_knowledge import AgentLabOptimizationKnowledge
from rag_ime.agent_lab.projects import (
    AgentLabProjectConflict,
    AgentLabProjectNotFound,
    AgentLabProjectStore,
    AgentLabProjectValidationError,
)
from rag_ime.trace_diagnostics import inspect_trace_targets


class OptimizationKnowledgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="paw-optimization-knowledge-")
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / "paw.sqlite"
        self.projects = AgentLabProjectStore(self.db)
        self.project = self.projects.command({"action": "create", "expectedRevision": 0,
            "clientRequestId": "project", "input": {"description": "优化开发对话中的工具使用"}})["project"]
        self.project_id = self.project["projectId"]
        self.receipts = {("trace_optimization_comparison", "comparison-1"): {
            "comparisonId": "comparison-1", "candidateId": "candidate-1", "reportId": "report-1",
            "optimizationProjectId": self.project_id, "executionStatus": "completed",
            "effectStatus": "regressed", "decision": "rejected", "evidenceRefs": ["eval:before", "eval:after"],
            "createdAtMs": 1000,
        }}
        self.candidate = {"candidateId": "candidate-1", "reportId": "report-1",
            "optimizationProjectId": self.project_id, "targetKind": "skill", "targetRef": "skill:search",
            "parentVersionRef": "v1", "candidateVersionRef": "v2", "summary": "去掉空结果重试",
            "comparisonContract": {"inputClass": "missing-result"}}
        self.service = self.make_service()
        self.serial = 0
        self.report = self.make_report()

    def make_service(self):
        return AgentLabOptimizationKnowledge(AgentLabProjectStore(self.db),
            receipt_reader=lambda kind, identifier: copy.deepcopy(self.receipts.get((kind, identifier))))

    def record(self):
        return self.service.record_outcome(self.project_id,
            {"kind": "trace_optimization_comparison", "id": "comparison-1"}, candidate_context=self.candidate)

    def make_report(self):
        sessions = {f"session-{number}": {"sessionId": f"session-{number}", "items": [
            {"id": f"user-{number}", "role": "user", "status": "completed", "blocks": [
                {"id": f"user-block-{number}", "type": "text", "data": {"text": "先搜索已有文件，再处理空结果。"}}]},
            {"id": f"assistant-{number}", "role": "assistant", "status": "completed", "blocks": [
                {"id": f"assistant-block-{number}", "type": "text", "data": {"text": "工具失败后重试了；声称已经完成不构成成功证据。"}}]},
        ]} for number in range(1, 4)}
        inspection = inspect_trace_targets(targets=[{"kind": "session", "id": identifier} for identifier in sessions],
            session_reader=lambda identifier: sessions.get(identifier), room_reader=lambda _: None,
            observation_reader=lambda _: {"items": []}, trace_reader=lambda _: None, eval_reader=lambda _: [], now_ms=1)
        return {"reportId": "report-1", "optimizationProjectId": self.project_id, "revision": 2,
            "status": "completed", "inspection": inspection, "result": {"findings": [{
                "findingId": "empty-retry", "dimensionId": "tool_runtime", "observation": "三个对话都出现空搜索结果",
                "hypothesis": "先检查参数再重试可以减少无效调用", "conclusion": "保留错误恢复步骤",
                "evidenceIds": [item["evidenceId"] for item in inspection["evidence"][:3]]}]}}

    def pattern(self, **updates):
        value = {"title": "空结果需要恢复步骤", "summary": "删除重试导致缺失输出，适用条件仍需区分。",
            "scope": {"componentRef": "skill:search", "componentVersion": "v1", "inputClass": "missing-result"},
            "symptoms": ["empty result", "搜索失败"],
            "observations": [{"statement": "来源包含空结果后的恢复过程。", "evidenceIds": [self.report["inspection"]["evidence"][0]["evidenceId"]]}],
            "hypotheses": [{"statement": "先校验参数可以减少重试次数。", "evidenceIds": [], "uncertainty": "尚未做同条件比较。"}]}
        value.update(updates)
        return value

    def save(self, value=None, **kwargs):
        self.serial += 1
        return self.service.save_pattern(self.project_id, value or self.pattern(),
            expected_revision=self.projects.read(self.project_id)["project"]["revision"],
            client_request_id=f"pattern-{self.serial}", evidence_context=self.report, **kwargs)

    def packet(self, capabilities=None, **kwargs):
        return self.service.prepare_distillation(self.project_id, inspection=self.report,
            capabilities=capabilities or [], **kwargs)

    def test_second_iteration_reads_rejected_attempt_after_restart_without_repeating_write(self):
        first = self.record()
        replay = self.make_service().record_outcome(self.project_id,
            {"kind": "trace_optimization_comparison", "id": "comparison-1"}, candidate_context=self.candidate)
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["artifactId"], replay["artifactId"])
        packet = self.make_service().query(self.project_id, component_ref="skill:search", component_version="v1")
        self.assertEqual(len(packet["attempts"]), 1)
        attempt = packet["attempts"][0]
        self.assertEqual(attempt["decision"], "rejected")
        self.assertEqual(attempt["effectStatus"], "regressed")
        self.assertEqual(attempt["retryAssessment"], "same_context_requires_reason")
        self.assertNotIn("content", json.dumps(packet))

    def test_outcome_retries_are_concurrent_idempotent_and_changed_receipt_is_conflict(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: self.record(), range(2)))
        self.assertEqual(sorted(value["replayed"] for value in values), [False, True])
        self.receipts[("trace_optimization_comparison", "comparison-1")]["decision"] = "needs_validation"
        with self.assertRaises(AgentLabProjectConflict):
            self.record()
        self.assertEqual(self.service.query(self.project_id)["attempts"][0]["decision"], "rejected")

    def test_unrun_rejection_and_interruption_are_retained_without_effect_claims(self):
        receipt = self.receipts[("trace_optimization_comparison", "comparison-1")]
        receipt.update(executionStatus="not_started", effectStatus="not_run")
        self.record()
        receipt = {**receipt, "comparisonId": "comparison-2", "executionStatus": "interrupted", "effectStatus": "unverified"}
        self.receipts[("trace_optimization_comparison", "comparison-2")] = receipt
        self.service.record_outcome(self.project_id, {"kind": "trace_optimization_comparison", "id": "comparison-2"}, candidate_context=self.candidate)
        items = self.service.query(self.project_id)["attempts"]
        self.assertEqual({item["executionStatus"] for item in items}, {"not_started", "interrupted"})
        self.assertTrue(all(item["effectStatus"] not in {"improved", "neutral"} for item in items))

    def test_changed_component_version_input_class_or_contract_allows_reconsideration(self):
        self.record()
        for args in ({"component_version": "v3"}, {"input_class": "new-result"}, {"context_fingerprint": "new-evidence"}):
            with self.subTest(args=args):
                item = self.service.query(self.project_id, component_ref="skill:search", **args)["attempts"][0]
                self.assertEqual(item["retryAssessment"], "context_changed_reconsider")
                self.assertEqual(item["decision"], "rejected")

    def test_project_and_host_scope_isolation_including_direct_refs_and_receipts(self):
        saved = self.save()
        other = self.projects.command({"action": "create", "expectedRevision": 0, "clientRequestId": "other",
            "input": {"description": "另一个任务"}})["project"]["projectId"]
        self.assertEqual(self.service.query(other)["patterns"], [])
        with self.assertRaises(AgentLabProjectNotFound):
            self.service.read(other, saved["artifactId"])
        with self.assertRaises(AgentLabProjectValidationError):
            self.service.record_outcome(other, {"kind": "trace_optimization_comparison", "id": "comparison-1"}, candidate_context=self.candidate)
        with self.assertRaises(AgentLabProjectValidationError):
            self.service.save_pattern(other, self.pattern(), expected_revision=1, client_request_id="foreign", evidence_context=self.report)
        isolated = AgentLabOptimizationKnowledge(AgentLabProjectStore(self.db, scope_id="another-host"))
        with self.assertRaises(AgentLabProjectNotFound):
            isolated.query(self.project_id)

    def test_corrections_preserve_exact_prior_version_and_rejected_attempts(self):
        outcome = self.record()
        value = self.pattern(interventions=[{"outcomeId": outcome["artifactId"], "relationship": "rejected", "note": "不能由失败直接证明假设错误。"}])
        first = self.save(value)
        old = self.service.read(self.project_id, first["artifactId"], revision=1)["body"]
        corrected = self.save(self.pattern(summary="问题只限缺失结果输入，不扩展到全部搜索。", correctionReason="新证据缩小适用范围。"),
            pattern_id=first["artifactId"], expected_pattern_revision=1)
        self.assertEqual(corrected["artifactRevision"], 2)
        self.assertEqual(self.service.read(self.project_id, first["artifactId"], revision=1)["body"], old)
        self.assertEqual(self.service.read(self.project_id, first["artifactId"])["body"]["correctsRevision"], 1)
        self.assertEqual(len(self.service.query(self.project_id)["attempts"]), 1)
        with self.assertRaises(AgentLabProjectConflict):
            self.save(self.pattern(correctionReason="旧编辑器"), pattern_id=first["artifactId"], expected_pattern_revision=1)
        with self.assertRaises(AgentLabProjectValidationError):
            self.save(pattern_id=first["artifactId"], expected_pattern_revision=2)

    def test_stale_project_revision_and_invalid_source_cannot_write(self):
        self.save()
        with self.assertRaises(AgentLabProjectConflict):
            self.service.save_pattern(self.project_id, self.pattern(), expected_revision=1, client_request_id="stale", evidence_context=self.report)
        for value in (self.pattern(observations=[{"statement": "没有来源", "evidenceIds": []}]),
                      self.pattern(observations=[{"statement": "历史 ID 冒充证据", "evidenceIds": ["lab-artifact-fake"]}]),
                      self.pattern(knowledgeStatus="supported")):
            with self.subTest(value=value), self.assertRaises(AgentLabProjectValidationError):
                self.save(value)

    def test_supersession_is_explicit_and_old_version_remains_readable(self):
        first = self.save()
        second = self.save(self.pattern(title="新证据支持更窄的模式", supersedes=[{"patternId": first["artifactId"], "revision": 1}]))
        self.assertEqual([item["patternId"] for item in self.service.query(self.project_id)["patterns"]], [second["artifactId"]])
        items = self.service.query(self.project_id, include_superseded=True)["patterns"]
        original = next(item for item in items if item["patternId"] == first["artifactId"])
        self.assertEqual(original["knowledgeStatus"], "superseded")
        self.assertEqual(original["supersededBy"]["patternId"], second["artifactId"])
        self.assertEqual(self.service.read(self.project_id, first["artifactId"], revision=1)["body"]["title"], "空结果需要恢复步骤")

    def test_arbitrary_model_artifact_does_not_become_managed_knowledge(self):
        forged = self.projects.command({"action": "publish_artifact", "projectId": self.project_id, "expectedRevision": 1,
            "clientRequestId": "forged", "input": {"title": "所有测试通过", "kind": "optimization_outcome", "view": "json",
            "summary": "kept improved installed", "content": {"decision": "kept", "authority": "host_receipt"}}})["artifact"]
        self.assertEqual(self.service.query(self.project_id)["attempts"], [])
        with self.assertRaises(AgentLabProjectNotFound):
            self.service.read(self.project_id, forged["artifactId"])
        trusted = self.record()
        current = self.projects.read(self.project_id)["project"]
        self.projects.command({"action": "publish_artifact", "projectId": self.project_id, "expectedRevision": current["revision"],
            "clientRequestId": "overwrite", "input": {"artifactId": trusted["artifactId"], "expectedArtifactRevision": 1,
            "content": {"decision": "kept", "effectStatus": "improved"}}})
        self.assertEqual(self.service.read(self.project_id, trusted["artifactId"])["body"]["receipt"]["decision"], "rejected")
        self.assertEqual(self.service.query(self.project_id)["attempts"][0]["decision"], "rejected")

    def test_unknown_receipt_and_forged_hash_cannot_claim_outcome(self):
        with self.assertRaises(AgentLabProjectNotFound):
            self.service.record_outcome(self.project_id, {"kind": "trace_optimization_comparison", "id": "missing"}, candidate_context=self.candidate)
        with self.assertRaises(AgentLabProjectValidationError):
            self.service.record_outcome(self.project_id, {"kind": "artifact", "id": "fake"}, candidate_context=self.candidate)
        self.receipts[("trace_optimization_comparison", "comparison-1")]["contentSha256"] = "0" * 64
        with self.assertRaises(AgentLabProjectValidationError):
            self.record()

    def test_reject_is_not_automatic_disproof_and_support_requires_actual_improvement(self):
        outcome = self.record()
        self.assertEqual(self.save(self.pattern(interventions=[{"outcomeId": outcome["artifactId"], "relationship": "rejected"}]))["item"]["knowledgeStatus"], "observed")
        with self.assertRaises(AgentLabProjectValidationError):
            self.save(self.pattern(interventions=[{"outcomeId": outcome["artifactId"], "relationship": "supports"}]))
        self.assertEqual(self.save(self.pattern(interventions=[{"outcomeId": outcome["artifactId"], "relationship": "contradicts"}]))["item"]["knowledgeStatus"], "contested")

    def test_report_ingestion_is_idempotent_and_assistant_success_prose_stays_observed(self):
        self.report["result"]["findings"][0]["conclusion"] = "助手称操作成功，但尚未有重测回执。"
        first = self.service.record_report(self.report)
        again = self.make_service().record_report({**self.report, "revision": 3})
        self.assertTrue(again["items"][0]["replayed"])
        self.assertEqual(first["items"][0]["artifactId"], again["items"][0]["artifactId"])
        packet = self.service.query(self.project_id)
        self.assertEqual(packet["patterns"][0]["knowledgeStatus"], "observed")
        self.assertEqual(packet["attempts"], [])

    def test_query_and_body_reads_are_bounded_with_reassemblable_exact_version(self):
        value = self.pattern(observations=[{"statement": ("完整观察正文" + str(number)) * 250,
            "evidenceIds": [self.report["inspection"]["evidence"][0]["evidenceId"]]} for number in range(6)])
        saved = self.save(value)
        query = self.service.query(self.project_id, max_chars=1024)
        self.assertLessEqual(len(json.dumps(query, ensure_ascii=False, sort_keys=True, separators=(",", ":"))), 1024)
        self.assertNotIn("完整观察正文", str(query))
        chunks, offset = [], 0
        while True:
            page = self.service.read(self.project_id, saved["artifactId"], revision=1, max_chars=1024, offset=offset)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False, sort_keys=True, separators=(",", ":"))), 1024)
            self.assertIsNone(page["body"])
            chunks.append(page["bodyText"])
            if page["nextOffset"] is None:
                break
            offset = page["nextOffset"]
        self.assertEqual(json.loads("".join(chunks))["observations"][5]["statement"], value["observations"][5]["statement"])

    def test_three_conversation_packet_has_exact_provenance_and_does_not_copy_private_fields(self):
        self.report["inspection"]["businessGold"] = {"answer": "BUSINESS_GOLD_SECRET"}
        self.report["inspection"]["personalMemory"] = "PERSONAL_MEMORY_SECRET"
        self.report["inspection"]["evidence"][0]["rawToolArgs"] = {"token": "PRIVATE_TOKEN"}
        packet = self.packet()
        self.assertEqual(len(packet["sources"]), 3)
        self.assertTrue(all(item["sourceSha256"] for item in packet["sources"]))
        self.assertTrue(all(item["resultStatus"] == "unverified" for item in packet["sources"]))
        for secret in ("BUSINESS_GOLD_SECRET", "PERSONAL_MEMORY_SECRET", "PRIVATE_TOKEN"):
            self.assertNotIn(secret, str(packet))
        refs = {row["sourceRef"] for source in packet["sources"] for row in source["records"]}
        self.assertTrue(all(ref.startswith("session:session-") for ref in refs))

    def test_large_context_reports_truncation_and_preserves_every_selected_source(self):
        for row in self.report["inspection"]["evidence"]:
            row["summary"] = "a public source statement " * 1500
        capabilities = [{"kind": "skill", "id": "skill-" + str(number), "summary": "ability " * 250,
            "version": "1", "capabilityKeys": ["need-" + str(number)]} for number in range(100)]
        packet = self.packet(capabilities, max_chars=4096)
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))), 4096)
        self.assertEqual(len(packet["sources"]), 3)
        self.assertTrue(packet["truncated"])
        self.assertFalse(packet["inventoryComplete"])

    def proposal(self, packet, **updates):
        refs = [source["records"][0]["evidenceId"] for source in packet["sources"] if source["records"]]
        value = {"suggestionId": "search-recovery", "outcome": "new_skill", "title": "空结果恢复", "reason": "三个来源反复需要相同的恢复方法。",
            "evidenceIds": refs, "capabilityNeeds": ["search-recovery"], "existingCapabilityIds": [],
            "proposedChange": "遇到空结果时先核对参数再执行一次有界重试。"}
        return {**value, **updates}

    def test_existing_capability_prevents_false_new_skill_and_sources_remain_multiple(self):
        packet = self.packet([{"kind": "skill", "id": "skill:search", "version": "v1",
            "summary": "搜索与失败恢复", "capabilityKeys": ["search-recovery"]}])
        result = self.service.evaluate_distillation(packet, [self.proposal(packet)])
        suggestion = result["items"][0]
        self.assertEqual(suggestion["outcome"], "update_existing")
        self.assertEqual(suggestion["requestedOutcome"], "new_skill")
        self.assertEqual(suggestion["existingCapabilityIds"], ["skill:search"])
        self.assertEqual(suggestion["validationStatus"], "candidate_draft")
        self.assertEqual(len({key for ref in suggestion["sourceRefs"] for key in ref["targetKeys"]}), 3)
        self.assertEqual(result["authority"], "analysis_proposal")

    def test_all_five_distillation_outcomes_are_drafts_or_non_capability_knowledge(self):
        packet = self.packet([{"kind": "skill", "id": "skill:existing", "capabilityKeys": ["another-need"]}])
        for outcome in ("new_skill", "new_tool", "experience_only", "no_change", "update_existing"):
            with self.subTest(outcome=outcome):
                proposal = self.proposal(packet, outcome=outcome,
                    existingCapabilityIds=["skill:existing"] if outcome == "update_existing" else [])
                result = self.service.evaluate_distillation(packet, [proposal])["items"][0]
                self.assertEqual(result["outcome"], outcome)
                self.assertEqual(result["candidateIds"], [])
                self.assertNotIn("decision", result)
        with self.assertRaises(AgentLabProjectValidationError):
            self.service.evaluate_distillation(packet, [self.proposal(packet, evidenceIds=["history:fake"])])
        with self.assertRaises(AgentLabProjectValidationError):
            self.service.evaluate_distillation(packet, [self.proposal(packet, existingCapabilityIds=["invented-skill"])])

    def test_truncated_catalog_cannot_hide_existing_capability_or_accept_drift(self):
        capabilities = [{"kind": "skill", "id": f"skill-{number:03d}", "version": "1", "summary": "search " * 70,
            "capabilityKeys": ["search-recovery"] if number == 99 else [f"need-{number}"]} for number in range(100)]
        packet = self.packet(capabilities, max_chars=8000)
        self.assertFalse(packet["inventoryComplete"])
        proposal = self.proposal(packet)
        limited = self.service.evaluate_distillation(packet, [proposal])["items"][0]
        self.assertEqual(limited["outcome"], "experience_only")
        complete = self.service.evaluate_distillation(packet, [proposal], capabilities=capabilities)["items"][0]
        self.assertEqual(complete["outcome"], "update_existing")
        self.assertEqual(complete["existingCapabilityIds"], ["skill-099"])
        changed = copy.deepcopy(capabilities)
        changed[99]["version"] = "2"
        with self.assertRaises(AgentLabProjectValidationError):
            self.service.evaluate_distillation(packet, [proposal], capabilities=changed)


if __name__ == "__main__":
    unittest.main()
