from __future__ import annotations

import copy
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from rag_ime.agent_lab.golden import (
    AgentLabGoldenConflict,
    AgentLabGoldenServiceUnavailable,
    AgentLabGoldenStore,
    AgentLabGoldenValidationError,
)


MODEL = {"provider": "test-provider", "model": "test-model", "thinkingLevel": "high", "prompt": ""}
SOURCE = {"sourceId": "source-1", "title": "运行手册", "kind": "document", "uri": "docs:manual", "text": "失败任务需要人工确认。普通任务可以重试一次。"}


def case(case_id: str, split: str = "development") -> dict:
    value = {
        "caseId": case_id, "question": "普通任务可以重试几次？", "taskType": "context_qa", "answerable": True,
        "requiredFacts": ["重试一次"], "evidence": [{"sourceId": "source-1", "quote": "普通任务可以重试一次。"}],
        "rubric": ["准确回答次数"], "split": split,
        "review": {"status": "approved", "note": "模型自称已批准", "reviewedAtMs": 1},
        "samples": [
            {"sampleId": f"{case_id}-positive", "answer": "一次", "category": "correct", "humanVerdict": "pass", "humanNote": "模型伪造人审"},
            {"sampleId": f"{case_id}-negative", "answer": "无限次", "category": "incorrect", "humanVerdict": "fail", "humanNote": ""},
            {"sampleId": f"{case_id}-boundary", "answer": "通常一次，但另有例外吗", "category": "boundary", "humanVerdict": "uncertain", "humanNote": ""},
        ],
    }
    if split == "holdout":
        value.update(question="失败任务需要谁来确认？", requiredFacts=["人工确认"],
                     evidence=[{"sourceId": "source-1", "quote": "失败任务需要人工确认。"}], rubric=["不声称自动确认"])
    return value


class GoldenStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="paw-golden-test-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "test.sqlite"
        self.store = AgentLabGoldenStore(self.path, default_model=MODEL)
        self.serial = 0
        self.suite = self.store.command(self.payload("create", {"title": "接口 Golden", "scenario": "文档问答", "sources": [SOURCE], "targetCount": 4}, revision=0))["suite"]

    def payload(self, action: str, value: dict | None = None, *, revision: int | None = None, request_id: str | None = None) -> dict:
        self.serial += 1
        return {"action": action, "suiteId": "" if action == "create" else getattr(self, "suite", {}).get("suiteId", ""),
                "expectedRevision": revision if revision is not None else self.suite["revision"],
                "clientRequestId": request_id or f"request-{self.serial}", "input": value or {}}

    def command(self, action: str, value: dict | None = None, **kwargs) -> dict:
        response = self.store.command(self.payload(action, value, **kwargs))
        self.suite = self.store.read(self.suite["suiteId"])["suite"]
        return response

    def refresh(self) -> None:
        self.suite = self.store.read(self.suite["suiteId"])["suite"]

    def draft(self) -> dict:
        response = self.command("draft")
        job = response["job"]
        self.store.update_job(job["jobId"], {"state": "running", "sessionId": "pi:draft"})
        result = self.store.finish_job(job["jobId"], {"cases": [case("dev"), case("hold", "holdout")], "receipts": [{"turnId": "pi:turn"}]})
        self.refresh()
        return result

    def reviewed(self) -> None:
        self.draft()
        for item in copy.deepcopy(self.suite["cases"]):
            self.command("review_case", {**item, "verdict": "approved", "note": "人工确认"})
        for item, verdict in zip(self.suite["cases"][0]["samples"], ["pass", "fail", "uncertain"]):
            self.command("label_sample", {"caseId": "dev", "sampleId": item["sampleId"], "answer": item["answer"], "humanVerdict": verdict, "humanNote": "人工标签"})

    def calibration(self, *, false_pass: bool = False, unknown: bool = False) -> dict:
        response = self.command("calibrate")
        job = response["job"]
        self.store.update_job(job["jobId"], {"state": "running"})
        judgments = [{"caseId": "dev", "sampleId": f"dev-{label}", "verdict": verdict,
                      "reason": "根据冻结标准判断", "evidence": [{"sourceId": "source-1", "quote": "普通任务可以重试一次。"}]} for label, verdict in [
                          ("positive", "uncertain" if unknown else "pass"),
                          ("negative", "pass" if false_pass else "fail"), ("boundary", "fail")]]
        self.store.finish_job(job["jobId"], {"judgments": judgments, "receipts": [{"turnId": "pi:judge"}]})
        self.refresh()
        return self.suite["calibration"]

    def test_agent_assisted_labels_remain_distinct_from_human_reference_labels(self) -> None:
        self.reviewed()
        for item in copy.deepcopy(self.suite["cases"]):
            self.command("review_case", {**item, "verdict": "approved", "note": "Agent source review", "reviewAuthor": "agent"})
        for sample in copy.deepcopy(self.suite["cases"][0]["samples"]):
            self.command("label_sample", {"caseId": "dev", **sample, "labelAuthor": "agent"})
        self.assertEqual(self.suite["cases"][0]["review"]["author"], "agent")
        calibration = self.calibration()
        self.assertTrue(calibration["ready"])
        self.assertEqual(calibration["labelAuthors"], {"human": 0, "agent": 3, "unrecorded": 0})
        self.assertEqual(calibration["referenceAuthority"], "agent_assisted")
        self.command("freeze")
        job = self.command("experiment", {"snapshotId": self.suite["snapshot"]["snapshotId"], "baseline": MODEL, "candidate": MODEL})["job"]
        self.assertEqual(self.store.job_input(job["jobId"])["snapshot"]["calibration"]["referenceAuthority"], "agent_assisted")

    def test_create_is_durable_and_duplicate_command_replays_original_receipt(self) -> None:
        payload = self.payload("create", {"title": "另一个 Golden", "scenario": "历史任务", "sources": [SOURCE]}, revision=0, request_id="create-once")
        first = self.store.command(payload)
        replay = AgentLabGoldenStore(self.path, default_model=MODEL).command(payload)
        self.assertEqual(replay, {**first, "replayed": True})
        self.assertEqual(first["suite"]["targetCount"], 30)
        self.assertEqual(first["suite"]["judgeConfig"], MODEL)
        self.assertEqual(first["suite"]["cases"], [])
        self.assertEqual(len(self.store.read()["items"]), 2)
        with self.assertRaises(AgentLabGoldenConflict):
            self.store.command({**payload, "input": {**payload["input"], "title": "冲突内容"}})

    def test_draft_never_authors_human_reviews_or_labels_and_freezes_inputs(self) -> None:
        self.draft()
        self.assertEqual(self.suite["revision"], 2)
        for item in self.suite["cases"]:
            self.assertEqual(item["review"], {"status": "pending", "note": "", "reviewedAtMs": None})
            self.assertTrue(all(sample["humanVerdict"] is None and sample["humanNote"] == "" for sample in item["samples"]))
        draft_job = self.suite["jobs"][0]
        bound = self.store.job_input(draft_job["jobId"])
        self.assertEqual(bound["suite"]["revision"], 1)
        self.assertEqual(bound["input"]["model"], MODEL)
        bound["suite"]["sources"][0]["text"] = "caller mutation"
        self.assertEqual(self.store.job_input(draft_job["jobId"])["suite"]["sources"][0]["text"], SOURCE["text"])

    def test_stale_and_concurrent_duplicate_reviews_mutate_once(self) -> None:
        self.draft()
        item = self.suite["cases"][0]
        payload = self.payload("review_case", {**item, "verdict": "approved", "note": "已核对"}, request_id="review-once")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.command(payload), range(2)))
        self.assertEqual(sorted(row["replayed"] for row in results), [False, True])
        self.refresh()
        self.assertEqual(self.suite["revision"], 3)
        self.assertEqual(self.suite["cases"][0]["review"]["status"], "approved")
        with self.assertRaises(AgentLabGoldenConflict):
            self.store.command({**payload, "clientRequestId": "new-stale"})

    def test_draft_with_nonexistent_quote_is_not_committed(self) -> None:
        job = self.command("draft")["job"]
        self.store.update_job(job["jobId"], {"state": "running"})
        invalid = case("invalid")
        invalid["evidence"][0]["quote"] = "源文档不存在的事实"
        with self.assertRaises(AgentLabGoldenValidationError):
            self.store.finish_job(job["jobId"], {"cases": [invalid]})
        self.refresh()
        self.assertEqual(self.suite["cases"], [])
        self.assertNotEqual(self.suite["jobs"][0]["state"], "completed")

    def test_late_draft_cannot_overwrite_newer_review(self) -> None:
        self.draft()
        job = self.command("draft")["job"]
        self.store.update_job(job["jobId"], {"state": "running"})
        item = self.suite["cases"][0]
        self.command("review_case", {**item, "verdict": "approved", "note": "new review"})
        with self.assertRaises(AgentLabGoldenConflict):
            self.store.finish_job(job["jobId"], {"cases": [case("replacement")]})
        self.refresh()
        self.assertEqual(self.suite["cases"][0]["review"]["note"], "new review")

    def test_calibration_uses_labeled_development_only_and_computes_real_metrics(self) -> None:
        self.reviewed()
        value = self.calibration()
        self.assertEqual(value["metrics"], {"total": 3, "comparable": 2, "agreement": 1.0, "falsePasses": 0, "falseFails": 0, "uncertain": 1})
        self.assertTrue(value["ready"])
        self.assertTrue(any("样本" in reason for reason in value["reasons"]))
        self.assertEqual(value["suiteRevision"], self.suite["revision"])

    def test_false_pass_or_unknown_judge_prevents_freeze(self) -> None:
        self.reviewed()
        self.assertFalse(self.calibration(false_pass=True)["ready"])
        with self.assertRaises(AgentLabGoldenValidationError):
            self.command("freeze")
        self.assertFalse(self.calibration(unknown=True)["ready"])

    def test_missing_judgment_and_holdout_judgment_are_rejected(self) -> None:
        self.reviewed()
        job = self.command("calibrate")["job"]
        self.store.update_job(job["jobId"], {"state": "running"})
        with self.assertRaises(AgentLabGoldenValidationError):
            self.store.finish_job(job["jobId"], {"judgments": []})
        with self.assertRaises(AgentLabGoldenValidationError):
            self.store.finish_job(job["jobId"], {"judgments": [{"caseId": "hold", "sampleId": "hold-positive", "verdict": "pass", "reason": "bad", "evidence": []}]})
        self.assertIsNone(self.store.read(self.suite["suiteId"])["suite"]["calibration"])

    def test_standard_edits_invalidate_calibration_but_never_mutate_frozen_snapshot(self) -> None:
        self.reviewed()
        self.calibration()
        snapshot = self.command("freeze")["suite"]["snapshot"]
        self.assertEqual(snapshot["developmentCount"], 1)
        self.assertEqual(snapshot["holdoutCount"], 1)
        again = self.command("freeze")["suite"]["snapshot"]
        self.assertEqual(again, snapshot)
        experiment = self.command("experiment", {"snapshotId": snapshot["snapshotId"], "baseline": {}, "candidate": {}, "maxCandidates": 1})["job"]
        frozen_before = self.store.job_input(experiment["jobId"])["snapshot"]
        item = copy.deepcopy(self.suite["cases"][0])
        self.command("review_case", {**item, "question": "文档允许多少次普通任务重试？", "verdict": "approved", "note": "修改表述"})
        self.assertIsNone(self.suite["calibration"])
        self.assertEqual(self.suite["snapshot"], snapshot)
        self.assertEqual(self.store.job_input(experiment["jobId"])["snapshot"], frozen_before)
        self.assertEqual(self.store.job_input(experiment["jobId"])["input"]["baseline"], MODEL)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE agent_lab_golden_snapshots SET payload_json = '{}' WHERE snapshot_id = ?", (snapshot["snapshotId"],))

    def test_validation_reuse_counts_started_validation_and_recovery_keeps_its_ordinal(self) -> None:
        self.reviewed(); self.calibration()
        snapshot = self.command('freeze')['suite']['snapshot']
        inputs = {'snapshotId':snapshot['snapshotId'],'baseline':{},'candidate':{},'optimizePrompt':False}
        first = self.command('experiment', inputs)['job']
        self.store.update_job(first['jobId'], {'state':'running'})
        use = self.store.begin_validation(first['jobId'])
        self.assertEqual(use['ordinal'], 1); self.assertFalse(use['reused'])
        self.assertEqual(self.store.begin_validation(first['jobId']), use)
        self.store.update_job(first['jobId'], {'state':'failed','error':'provider stopped'})
        second = self.command('experiment', inputs)['job']
        self.store.update_job(second['jobId'], {'state':'running'})
        later = self.store.begin_validation(second['jobId'])
        self.assertEqual(later['ordinal'], 2); self.assertTrue(later['reused'])
        self.assertEqual(later['priorStartedRuns'], 1)

    def test_cancelled_development_does_not_count_as_a_validation_use(self) -> None:
        self.reviewed(); self.calibration()
        snapshot = self.command('freeze')['suite']['snapshot']
        inputs = {'snapshotId':snapshot['snapshotId'],'baseline':{},'candidate':{}}
        cancelled = self.command('experiment',inputs)['job']
        self.command('cancel', {'jobId':cancelled['jobId']})
        with self.assertRaises(AgentLabGoldenConflict): self.store.begin_validation(cancelled['jobId'])
        actual = self.command('experiment',inputs)['job']
        self.store.update_job(actual['jobId'], {'state':'running'})
        self.assertEqual(self.store.begin_validation(actual['jobId'])['ordinal'], 1)

    def test_new_judge_protocol_requires_new_calibration_and_preserves_old_snapshot(self) -> None:
        with patch('rag_ime.agent_lab.golden.GOLDEN_JUDGE_PROTOCOL_VERSION', 'older-judge-protocol'):
            self.reviewed(); self.calibration()
            old = self.command('freeze')['suite']['snapshot']
        self.refresh()
        self.assertFalse(self.suite['calibration']['ready'])
        with self.assertRaisesRegex(AgentLabGoldenValidationError, '旧评审协议'):
            self.command('experiment', {'snapshotId':old['snapshotId'],'baseline':{},'candidate':{}})
        self.calibration()
        self.assertEqual(self.suite['revision'], old['sourceRevision']+1)
        self.assertEqual(self.suite['calibration']['suiteRevision'], self.suite['revision'])
        new = self.command('freeze')['suite']['snapshot']
        self.assertNotEqual(old['snapshotId'], new['snapshotId'])
        self.assertEqual(new['version'], old['version']+1)
        with closing(sqlite3.connect(self.path)) as conn:
            previous = conn.execute('SELECT payload_json FROM agent_lab_golden_snapshots WHERE snapshot_id=?',(old['snapshotId'],)).fetchone()[0]
        self.assertIn('older-judge-protocol', previous)

    def test_new_snapshot_does_not_disguise_reused_holdout_questions_as_fresh(self) -> None:
        self.reviewed(); self.calibration()
        old = self.command('freeze')['suite']['snapshot']
        first = self.command('experiment',{'snapshotId':old['snapshotId'],'baseline':{},'candidate':{}})['job']
        self.store.update_job(first['jobId'],{'state':'running'}); self.store.begin_validation(first['jobId'])
        self.store.update_job(first['jobId'],{'state':'failed','error':'stopped'})
        self.command('judge_config', {'judgeConfig':{**MODEL,'prompt':'clarify the judge protocol'}})
        self.calibration(); new = self.command('freeze')['suite']['snapshot']
        second = self.command('experiment',{'snapshotId':new['snapshotId'],'baseline':{},'candidate':{}})['job']
        self.store.update_job(second['jobId'],{'state':'running'})
        use = self.store.begin_validation(second['jobId'])
        self.assertTrue(use['reused']); self.assertEqual(use['overlappingQuestionCount'],1)

    def test_label_and_judge_edits_clear_calibration(self) -> None:
        self.reviewed()
        self.calibration()
        self.command("label_sample", {"caseId": "dev", "sampleId": "dev-positive", "answer": "只能重试一次", "humanVerdict": "pass", "humanNote": "更准确"})
        self.assertIsNone(self.suite["calibration"])
        self.calibration()
        self.command("judge_config", {"judgeConfig": {**MODEL, "prompt": "新评审标准"}})
        self.assertIsNone(self.suite["calibration"])

    def test_cancel_recover_resume_and_terminal_callbacks_do_not_invent_success(self) -> None:
        queued = self.command("draft")["job"]
        self.command("cancel", {"jobId": queued["jobId"]})
        self.assertEqual(self.store.job_input(queued["jobId"])["job"]["state"], "cancelled")
        job = self.command("draft")["job"]
        self.store.update_job(job["jobId"], {"state": "running", "sessionId": "pi:known"})
        cancel = self.command("cancel", {"jobId": job["jobId"]})
        self.assertEqual(cancel["job"]["state"], "running")
        self.assertTrue(self.store.job_input(job["jobId"])["cancelRequested"])
        self.store.update_job(job["jobId"], {"state": "cancelled"})
        self.assertEqual(self.store.finish_job(job["jobId"], {"cases": [case("late")]} )["state"], "cancelled")
        recovering = self.command("draft")["job"]
        self.store.update_job(recovering["jobId"], {"state": "running", "sessionId": "pi:recover"})
        affected = self.store.recover_interrupted_jobs()
        self.assertEqual([row["jobId"] for row in affected], [recovering["jobId"]])
        resumed = self.command("resume", {"jobId": recovering["jobId"]})["job"]
        self.assertEqual(resumed["jobId"], recovering["jobId"])
        self.assertEqual(resumed["state"], "queued")
        self.assertEqual(resumed["sessionId"], "pi:recover")
        with self.assertRaises(AgentLabGoldenValidationError):
            self.store.update_job(resumed["jobId"], {"state": "completed"})

    def test_errors_are_safe_and_model_call_checkpoint_table_exists(self) -> None:
        with self.assertRaises(AgentLabGoldenValidationError) as caught:
            self.command("create", {"title": "bad", "scenario": "bad", "sources": []}, revision=0)
        self.assertEqual(caught.exception.http_status, 422)
        self.assertEqual(set(caught.exception.response_payload()), {"ok", "code", "message"})
        with closing(sqlite3.connect(self.path)) as conn, conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_lab_golden_model_calls)")}
        self.assertTrue({"request_id", "session_id", "turn_id", "model_json", "prompt", "state", "output_text", "receipt_json", "error", "created_at_ms", "updated_at_ms"}.issubset(columns))

    def test_resumed_queued_cancel_does_not_claim_an_existing_pi_call_was_stopped(self) -> None:
        job = self.command("draft")["job"]
        self.store.update_job(job["jobId"], {"state": "running", "sessionId": "pi:accepted"})
        self.store.recover_interrupted_jobs()
        self.command("resume", {"jobId": job["jobId"]})
        response = self.command("cancel", {"jobId": job["jobId"]})
        self.assertEqual(response["job"]["state"], "interrupted")
        self.assertEqual(response["job"]["sessionId"], "pi:accepted")
        self.assertTrue(self.store.job_input(job["jobId"])["cancelRequested"])

    def test_approval_requires_reference_standards_but_rejection_remains_possible(self) -> None:
        self.draft()
        item = self.suite["cases"][0]
        for case_patch in ({"requiredFacts": []}, {"rubric": []}, {"evidence": []}):
            with self.subTest(patch=case_patch), self.assertRaises(AgentLabGoldenValidationError):
                self.command("review_case", {**item, **case_patch, "verdict": "approved", "note": ""})
        self.command("review_case", {**item, "requiredFacts": [], "rubric": [], "evidence": [], "verdict": "rejected", "note": "标准不足"})
        self.assertEqual(self.suite["cases"][0]["review"]["status"], "rejected")

    def test_cross_split_duplicate_is_rejected_before_freezing(self) -> None:
        self.reviewed()
        holdout = copy.deepcopy(self.suite["cases"][1])
        self.command("review_case", {**holdout, "question": self.suite["cases"][0]["question"], "verdict": "approved", "note": "重复题"})
        self.calibration()
        with self.assertRaises(AgentLabGoldenValidationError):
            self.command("freeze")

    def test_calibration_and_freeze_pin_judge_protocol_and_reject_other_versions(self) -> None:
        self.reviewed()
        calibration = self.calibration()
        self.assertEqual(calibration["judgeProtocolVersion"], "paw.golden.context-qa-judge.v2")
        snapshot = self.command("freeze")["suite"]["snapshot"]
        self.assertEqual(snapshot["judgeProtocolVersion"], calibration["judgeProtocolVersion"])
        job = self.command("calibrate")["job"]
        self.store.update_job(job["jobId"], {"state": "running"})
        with self.assertRaises(AgentLabGoldenValidationError):
            self.store.finish_job(job["jobId"], {"judgeProtocolVersion": "different-protocol", "judgments": calibration["judgments"]})

    def test_concrete_models_and_multiple_snapshot_versions_survive_default_changes(self) -> None:
        self.reviewed()
        self.calibration()
        first = self.command("freeze")["suite"]["snapshot"]
        old_job = self.command("experiment", {"snapshotId": first["snapshotId"], "baseline": {}, "candidate": {}})["job"]
        self.command("judge_config", {"judgeConfig": {**MODEL, "model": "next-judge", "thinkingLevel": "low"}})
        self.calibration()
        second = self.command("freeze")["suite"]["snapshot"]
        self.assertEqual((first["version"], second["version"]), (1, 2))
        self.assertNotEqual(first["snapshotId"], second["snapshotId"])
        reopened = AgentLabGoldenStore(self.path, default_model={**MODEL, "model": "another-default"})
        bound = reopened.job_input(old_job["jobId"])
        self.assertEqual(bound["input"]["baseline"], MODEL)
        self.assertEqual(bound["snapshot"]["judgeConfig"], MODEL)
        self.assertEqual(reopened.read(self.suite["suiteId"])["suite"]["judgeConfig"]["model"], "next-judge")
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_lab_golden_snapshots").fetchone()[0], 2)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM agent_lab_golden_snapshots WHERE snapshot_id = ?", (first["snapshotId"],))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE agent_lab_golden_jobs SET input_json = '{}' WHERE job_id = ?", (old_job["jobId"],))

    def test_storage_errors_do_not_expose_database_details(self) -> None:
        with self.assertRaises(AgentLabGoldenServiceUnavailable) as caught:
            AgentLabGoldenStore(self.path.parent, default_model=MODEL).read()
        response = caught.exception.response_payload()
        self.assertEqual(caught.exception.http_status, 503)
        self.assertNotIn(str(self.path.parent), response["message"])

    def test_failed_draft_can_reprocess_only_a_completed_model_receipt(self) -> None:
        for completed in (False, True):
            with self.subTest(completed=completed):
                job = self.command("draft")["job"]
                self.store.update_job(job["jobId"], {"state": "running"})
                self.store.update_job(job["jobId"], {"state": "failed", "result": {"receipts": [{
                    "stage": "draft", "requestId": "original-request", "sessionId": "original-session",
                    "turnId": "original-turn", "receipt": {"status": "completed" if completed else "failed"},
                }]}})
                self.refresh()
                self.assertEqual(self.suite["jobs"][0].get("canReprocess", False), completed)
                if not completed:
                    with self.assertRaises(AgentLabGoldenConflict):
                        self.command("resume", {"jobId": job["jobId"]})
                    continue
                resumed = self.command("resume", {"jobId": job["jobId"]})["job"]
                self.assertEqual(resumed["jobId"], job["jobId"])
                self.assertTrue(resumed["reprocessOnly"])
                self.assertEqual(resumed["state"], "queued")
                self.assertEqual(self.store.job_input(job["jobId"])["job"]["result"]["receipts"][0]["requestId"], "original-request")

    def test_confirmed_failed_call_gets_a_new_attempt_without_replacing_successful_receipts(self) -> None:
        self.reviewed(); job = self.command('calibrate')['job']
        base = quote(job['jobId'], safe='-_.') + ':calibration:dev:dev-negative'
        successful = {'requestId':quote(job['jobId'],safe='-_.')+':calibration:dev:dev-positive','sessionId':'s-ok','turnId':'t-ok','stage':'calibration','receipt':{'status':'completed'}}
        failed = {'requestId':base,'sessionId':'s-failed','turnId':'t-failed','stage':'calibration','receipt':{'status':'failed'}}
        self.store.update_job(job['jobId'],{'state':'running'})
        self.store.update_job(job['jobId'],{'state':'failed','result':{'partial':True,'pendingRequestId':base,'receipts':[successful,failed]}})
        self.refresh(); self.assertTrue(self.suite['jobs'][0].get('canRetryFailedCall'))
        request = self.payload('resume',{'jobId':job['jobId']})
        resumed = self.store.command(request)['job']; replayed = self.store.command(request)['job']
        self.assertEqual(resumed,replayed)
        self.assertEqual(resumed['requestRetries'][base]['requestId'],base+':retry:1')
        self.assertEqual(resumed['result']['receipts'],[successful,failed])
        self.assertEqual(self.store.job_input(job['jobId'])['suite']['judgeConfig'],self.suite['judgeConfig'])
        self.store.update_job(job['jobId'],{'state':'running'})
        self.store.update_job(job['jobId'],{'state':'interrupted'})
        interrupted = self.command('resume',{'jobId':job['jobId']})['job']
        self.assertEqual(interrupted['requestRetries'],resumed['requestRetries'])

    def test_confirmed_cancelled_pi_call_can_be_explicitly_retried_after_host_recovery(self) -> None:
        for status in ('cancelled', 'aborted'):
            with self.subTest(status=status):
                job = self.command('draft')['job']; base = quote(job['jobId'],safe='-_.')+':draft'
                receipt = {'requestId':base,'sessionId':'stopped-session','turnId':'stopped-turn','stage':'draft','receipt':{'status':status}}
                self.store.update_job(job['jobId'],{'state':'running'})
                self.store.update_job(job['jobId'],{'state':'failed','result':{'partial':True,'pendingRequestId':base,'receipts':[receipt]}})
                self.refresh(); self.assertTrue(self.suite['jobs'][0]['canRetryFailedCall'])
                resumed = self.command('resume',{'jobId':job['jobId']})['job']
                self.assertEqual(resumed['requestRetries'][base]['requestId'],base+':retry:1')
                self.assertEqual(resumed['result']['receipts'],[receipt])
                self.store.update_job(job['jobId'],{'state':'running'})
                self.store.update_job(job['jobId'],{'state':'cancelled'})

    def test_unknown_or_unbound_failed_receipt_cannot_authorize_a_new_paid_attempt(self) -> None:
        for status in ('accepted','interrupted','completed'):
            with self.subTest(status=status):
                job = self.command('draft')['job']; base=quote(job['jobId'],safe='-_.')+':draft'
                self.store.update_job(job['jobId'],{'state':'running'})
                self.store.update_job(job['jobId'],{'state':'failed','result':{'pendingRequestId':base,'receipts':[{'requestId':'another-job:draft','sessionId':'s','turnId':'t','receipt':{'status':status}}]}})
                self.refresh(); self.assertFalse(self.suite['jobs'][0].get('canRetryFailedCall',False))
                if status != 'completed':
                    with self.assertRaises(AgentLabGoldenConflict): self.command('resume',{'jobId':job['jobId']})

    def test_bound_unknown_pi_receipt_still_requires_reconciliation(self) -> None:
        for status in ('accepted', 'interrupted', 'unknown'):
            with self.subTest(status=status):
                job = self.command('draft')['job']; base = quote(job['jobId'],safe='-_.')+':draft'
                self.store.update_job(job['jobId'],{'state':'running'})
                self.store.update_job(job['jobId'],{'state':'failed','result':{'pendingRequestId':base,
                    'receipts':[{'requestId':base,'sessionId':'s','turnId':'t','receipt':{'status':status}}]}})
                self.refresh(); self.assertFalse(self.suite['jobs'][0]['canRetryFailedCall'])
                with self.assertRaises(AgentLabGoldenConflict): self.command('resume',{'jobId':job['jobId']})


if __name__ == "__main__":
    unittest.main()
