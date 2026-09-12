from __future__ import annotations

import copy
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from rag_ime.agent_lab.projects import (
    AgentLabProjectConflict,
    AgentLabProjectNotFound,
    AgentLabProjectStore,
    AgentLabProjectValidationError,
)
from rag_ime.agent_lab.golden import AgentLabGoldenStore
from rag_ime.agent_lab.project_application import AgentLabProjectApplication


class LabProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="paw-lab-project-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / "paw.sqlite"
        self.store = AgentLabProjectStore(self.db)
        self.serial = 0
        self.project = None

    def payload(self, action: str, value: dict | None = None, *, request_id: str = "") -> dict:
        self.serial += 1
        return {"action": action, "projectId": self.project["projectId"] if self.project else "",
                "expectedRevision": self.project["revision"] if self.project else 0,
                "clientRequestId": request_id or f"request-{self.serial}", "input": value or {}}

    def command(self, action: str, value: dict | None = None) -> dict:
        response = self.store.command(self.payload(action, value))
        self.project = response["project"]
        return response

    def create(self, **value) -> dict:
        return self.command("create", {"description": "让客服能准确回答新的售后规则", **value})

    def test_description_only_creates_durable_project_without_invented_materials_or_runs(self):
        payload = self.payload("create", {"description": "把业务需求变成可运行的应用"}, request_id="create-once")
        first = self.store.command(payload)
        project = first["project"]
        self.assertEqual(project["description"], "把业务需求变成可运行的应用")
        self.assertNotIn("goal", project)
        self.assertNotIn("deliveryTargets", project)
        self.assertEqual(project["materialSet"]["materials"], [])
        self.assertEqual(project["artifacts"], [])
        self.assertEqual(project["bindings"], [])
        self.assertEqual(project["guideSessionId"], "")
        self.assertEqual(project["intake"]["state"], "needs_materials")
        self.assertEqual(project["workspace"]["artifactOrder"], [])
        replay = AgentLabProjectStore(self.db).command(payload)
        self.assertEqual(replay, {**first, "replayed": True})
        self.assertEqual(len(self.store.read()["items"]), 1)
        self.assertNotIn("text", str(self.store.read()["items"][0]))
        with self.assertRaises(AgentLabProjectConflict):
            self.store.command({**payload, "input": {"description": "另一份业务需求"}})

    def test_read_projection_exposes_resume_state_without_inventing_execution_outcome(self):
        self.create()
        summary = self.store.read()["items"][0]
        self.assertEqual(summary["workState"], {
            "status": "draft", "label": "待接入材料", "reason": "项目还没有可用于验证的当前材料。",
        })
        self.assertEqual(summary["nextAction"]["kind"], "add_materials")
        self.assertEqual(summary["rerunReadiness"]["status"], "not_ready")
        self.assertIsNone(summary["latestRecord"])
        self.assertNotIn("executionOutcome", summary)

        self.command("publish_artifact", {"title": "排查记录", "kind": "investigation", "view": "markdown", "content": "已观察到连接超时。"})
        updated = self.store.read()["items"][0]
        self.assertEqual(updated["latestRecord"]["status"], "available")
        self.assertEqual(updated["latestRecord"]["title"], "排查记录")
        self.assertEqual(updated["workState"]["status"], "draft")

    def test_history_projection_separates_viewable_snapshot_from_rerun_readiness(self):
        def bind(_conn, _project, _request):
            return {"ownerRef": {"kind": "scene", "id": "cloudops"}, "summary": "历史场景回执"}

        self.store = AgentLabProjectStore(self.db, bind_execution=bind)
        prepared = {
            "sceneId": "cloudops", "sourceHash": "source-1", "experimentCount": 2,
            "project": {"title": "云上事故诊断", "description": "继续历史诊断"},
            "artifacts": [{"title": "实验快照", "kind": "history", "view": "markdown", "content": "历史结果；没有重新运行。"}],
        }
        payload = self.payload("import_history", {"sceneId": "cloudops", "sourceHash": "source-1"})
        response = self.store.command(payload, history_import=lambda _value: prepared)
        self.project = response["project"]
        summary = self.store.read()["items"][0]
        self.assertEqual(summary["workState"]["status"], "history_only")
        self.assertEqual(summary["latestRecord"]["status"], "historical")
        self.assertEqual(summary["rerunReadiness"]["status"], "not_ready")
        self.assertIn("至少一份当前材料快照", summary["rerunReadiness"]["missing"])

        snapshot_id = self.project["historyOrigin"]["snapshotArtifactId"]
        self.command("publish_artifact", {"title": "新的复跑准备说明", "view": "markdown", "content": "等待接入当前材料。"})
        catalog = self.store.read()["items"][0]
        detail = self.store.read(self.project["projectId"])["project"]
        self.assertEqual(catalog["latestRecord"]["artifactId"], snapshot_id)
        self.assertEqual(catalog["latestRecord"]["title"], "实验快照")
        self.assertEqual(catalog["latestRecord"], detail["latestRecord"])

    def test_execution_summary_distinguishes_running_completed_and_failed_model_jobs(self):
        running = AgentLabProjectApplication._execution_summary({"jobs": [{
            "jobId": "job-running", "kind": "experiment", "state": "running",
            "progress": "开发题 · 基线 · 第 1 / 4 题", "updatedAtMs": 2,
        }]})
        self.assertEqual(running["status"], "running")
        self.assertFalse(running["canContinue"])
        self.assertIn("第 1 / 4 题", running["reason"])
        completed = AgentLabProjectApplication._execution_summary({"jobs": [{
            "jobId": "job-complete", "kind": "experiment", "state": "completed", "updatedAtMs": 3,
            "result": {"comparison": {"decision": "improved"}},
        }]})
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["canContinue"])
        self.assertIn("improved", completed["reason"])
        nested_completed = AgentLabProjectApplication._execution_summary({
            "ok": True,
            "suite": {"jobs": [{
                "jobId": "job-nested-complete", "kind": "experiment", "state": "completed", "updatedAtMs": 5,
                "result": {"comparison": {"decision": "no_improvement"}},
            }]},
            "items": [],
        })
        self.assertEqual(nested_completed["status"], "completed")
        self.assertEqual(nested_completed["latestJob"]["jobId"], "job-nested-complete")
        self.assertIn("no_improvement", nested_completed["reason"])
        failed = AgentLabProjectApplication._execution_summary({"jobs": [{
            "jobId": "job-failed", "kind": "experiment", "state": "failed", "error": "Pi 回合未完成。", "updatedAtMs": 4,
        }]})
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["canContinue"])
        self.assertIn("Pi 回合未完成", failed["reason"])

    def test_preparation_receipts_do_not_claim_a_completed_model_experiment(self):
        for kind in ("draft", "calibrate", "freeze"):
            with self.subTest(kind=kind):
                result = AgentLabProjectApplication._execution_summary({"jobs": [{
                    "jobId": "prepare", "kind": kind, "state": "completed", "updatedAtMs": 1,
                    "result": {"comparison": {"decision": "no_improvement"}},
                }]})
                self.assertEqual(result["status"], "completed")
                self.assertNotIn("模型运行已完成", result["reason"])
                self.assertNotIn("decision", result["latestJob"])

    def test_concurrent_retry_mutates_once_and_stale_edit_preserves_newer_goal(self):
        self.create()
        payload = self.payload("update_brief", {"description": "新的业务目标：不编造退货条件"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.store.command(payload), range(2)))
        self.assertEqual(sorted(item["replayed"] for item in responses), [False, True])
        self.assertEqual(responses[0]["project"]["revision"], 2)
        with self.assertRaises(AgentLabProjectConflict):
            self.store.command({**payload, "clientRequestId": "stale"})
        current = self.store.read(self.project["projectId"])["project"]
        self.assertEqual(current["description"], "新的业务目标：不编造退货条件")

    def test_local_directory_is_actually_read_with_explicit_skips_and_no_execution_claim(self):
        source = self.root / "customer-project"
        source.mkdir()
        (source / "manual.md").write_text("未使用的商品可以在七日内退回。", encoding="utf-8")
        (source / "SKILL.md").write_text("# 客服方法\n先确认是否使用。", encoding="utf-8")
        (source / "main.py").write_text("print('do not execute during intake')", encoding="utf-8")
        (source / ".env").write_text("TOKEN=do-not-import", encoding="utf-8")
        (source / "node_modules").mkdir()
        (source / "node_modules" / "bundle.js").write_text("excluded", encoding="utf-8")
        (source / "picture.png").write_bytes(b"\x89PNG\x00")
        (source / "outside.md").symlink_to(self.root / "external.md")
        (self.root / "external.md").write_text("outside the selected directory", encoding="utf-8")
        self.create(path=str(source))
        self.assertEqual(self.project["intake"]["state"], "read")
        materials = self.project["materialSet"]["materials"]
        self.assertEqual({item["title"] for item in materials}, {"manual.md", "SKILL.md", "main.py"})
        self.assertEqual({item["kind"] for item in materials}, {"document", "skill", "code"})
        self.assertTrue(all(len(item["contentHash"]) == 64 for item in materials))
        self.assertNotIn("do-not-import", str(self.project))
        self.assertNotIn("outside the selected directory", str(self.project))
        self.assertGreaterEqual(self.project["intake"]["skippedCount"], 4)
        self.assertEqual(self.project["materialCount"], 3)
        self.assertEqual(self.project["bindings"], [])

    def test_missing_path_saves_request_and_gap_then_can_connect_without_recreating(self):
        source = self.root / "not-yet-present"
        self.create(path=str(source))
        project_id = self.project["projectId"]
        self.assertEqual(self.project["intake"]["state"], "unavailable")
        self.assertEqual(self.project["materialSet"]["materials"], [])
        self.assertEqual(self.project["intake"]["issues"][0]["code"], "path_unavailable")
        source.mkdir()
        (source / "manual.txt").write_text("新规则已经提供。", encoding="utf-8")
        self.command("import_materials", {"path": str(source)})
        self.assertEqual(self.project["projectId"], project_id)
        self.assertEqual(self.project["intake"]["state"], "read")
        self.assertEqual(self.project["materialSet"]["materials"][0]["text"], "新规则已经提供。")

    def test_material_edits_create_immutable_sets_and_retry_does_not_reread_changed_path(self):
        source = self.root / "manual.md"
        source.write_text("旧规则：七日。", encoding="utf-8")
        payload = self.payload("create", {"description": "售后问答", "path": str(source)}, request_id="from-path")
        initial = self.store.command(payload)
        self.project = initial["project"]
        original = copy.deepcopy(self.project["materialSet"])
        source.write_text("新规则：十四日。", encoding="utf-8")
        self.assertEqual(self.store.command(payload)["project"]["materialSet"], original)
        self.command("import_materials", {"path": str(source)})
        current = self.project["materialSet"]
        self.assertEqual(len(current["materials"]), 1)
        self.assertNotEqual(current["materialSetId"], original["materialSetId"])
        self.assertEqual(current["materials"][0]["sourceId"], original["materials"][0]["sourceId"])
        self.assertEqual(current["materials"][0]["text"], "新规则：十四日。")
        old = self.store.read(self.project["projectId"], material_set_id=original["materialSetId"])
        self.assertEqual(old["materialSet"], original)
        with closing(sqlite3.connect(self.db)) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE agent_lab_project_material_sets SET payload_json='{}'")

    def test_failed_import_keeps_existing_materials_and_removed_sources_remain_in_history(self):
        self.create(materials=[{"title": "规则", "text": "收到新订单后发送确认。"}])
        original = copy.deepcopy(self.project["materialSet"])
        self.command("import_materials", {"path": str(self.root / "absent.md")})
        self.assertEqual(self.project["materialSet"], original)
        self.assertEqual(self.project["intake"]["state"], "unavailable")
        self.command("remove_materials", {"sourceIds": [original["materials"][0]["sourceId"]]})
        self.assertEqual(self.project["materialSet"]["materials"], [])
        self.assertEqual(self.project["intake"]["state"], "needs_materials")
        self.assertEqual(self.store.read(self.project["projectId"], material_set_id=original["materialSetId"])["materialSet"], original)

    def test_large_or_binary_input_is_reported_without_truncating_it_into_a_valid_source(self):
        source = self.root / "sources"
        source.mkdir()
        (source / "binary.txt").write_bytes(b"a\x00b")
        (source / "too-large.md").write_text("x" * 500_001, encoding="utf-8")
        self.create(path=str(source))
        self.assertEqual(self.project["materialSet"]["materials"], [])
        codes = {item["code"] for item in self.project["intake"]["issues"]}
        self.assertTrue({"binary_or_encoding", "file_too_large"} <= codes)
        self.assertNotEqual(self.project["intake"]["state"], "read")

    def test_invalid_fields_and_unknown_project_are_not_silently_accepted(self):
        for value in ({}, {"description": ""}, {"description": "ok", "deliveryTargets": ["unknown"]},
                      {"description": "ok", "path": 5}, {"description": "ok", "trusted": True}):
            with self.subTest(value=value), self.assertRaises(AgentLabProjectValidationError):
                self.store.command(self.payload("create", value))
        with self.assertRaises(AgentLabProjectNotFound):
            self.store.read("missing")
        self.assertEqual(self.store.read()["items"], [])

    def test_optional_adapter_binds_exact_inputs_without_rewriting_old_suite(self):
        golden = AgentLabGoldenStore(self.db, default_model={"provider": "local-test", "model": "model", "thinkingLevel": "low", "prompt": ""})

        def bind(conn, project, request):
            self.assertEqual(request["adapterId"], "golden.context_qa")
            sources = [{key: item[key] for key in ("sourceId", "title", "kind", "uri", "text")}
                       for item in project["materialSet"]["materials"] if item["kind"] == "document"]
            suite = golden.create_in_transaction(conn, {"title": project["title"], "scenario": project["description"], "sources": sources, **request["input"]})
            return {"ownerRef": {"kind": "golden_suite", "id": suite["suiteId"]}}

        self.store = AgentLabProjectStore(self.db, bind_execution=bind)
        self.create(materials=[{"sourceId": "manual", "title": "规则", "text": "未使用商品七日内可退。"},
                               {"title": "SKILL.md", "text": "必须先确认使用情况。", "kind": "skill"}])
        request = {"adapterId": "golden.context_qa", "input": {"targetCount": 4}}
        self.command("bind_execution", request)
        first = copy.deepcopy(self.project["bindings"][0])
        suite = golden.read(first["ownerRef"]["id"])["suite"]
        self.assertEqual([item["title"] for item in suite["sources"]], ["规则"])
        self.assertEqual(suite["jobs"], [])
        self.command("bind_execution", request)
        self.assertEqual(len(self.project["bindings"]), 1)
        self.command("import_materials", {"materials": [{"sourceId": "manual", "title": "规则", "text": "未使用商品十四日内可退。"}]})
        self.command("bind_execution", request)
        self.assertEqual(len(self.project["bindings"]), 2)
        self.assertEqual(golden.read(first["ownerRef"]["id"])["suite"], suite)
        self.assertEqual(self.project["bindings"][0], first)

    def test_adapter_creation_failure_rolls_back_project_and_owner_resource_together(self):
        golden = AgentLabGoldenStore(self.db)

        def failed_creation(conn, project, _request):
            sources = [{key: item[key] for key in ("sourceId", "title", "kind", "uri", "text")}
                       for item in project["materialSet"]["materials"]]
            golden.create_in_transaction(conn, {"title": project["title"], "scenario": project["description"], "sources": sources})
            raise RuntimeError("injected failure before project binding")

        self.store = AgentLabProjectStore(self.db, bind_execution=failed_creation)
        self.create(materials=[{"title": "规则", "text": "必须先确认使用情况。"}])
        original = copy.deepcopy(self.project)
        with self.assertRaises(RuntimeError):
            self.command("bind_execution", {"adapterId": "golden.context_qa"})
        self.assertEqual(self.store.read(self.project["projectId"])["project"], original)
        self.assertEqual(golden.read()["items"], [])

    def test_another_project_cannot_read_a_material_version_by_id(self):
        self.create(materials=[{"title": "规则", "text": "限定当前项目材料。"}])
        material_set_id = self.project["materialSetId"]
        self.project = None
        self.create()
        with self.assertRaises(AgentLabProjectNotFound):
            self.store.read(self.project["projectId"], material_set_id=material_set_id)

    def test_projects_define_different_artifacts_and_fields_without_a_business_schema(self):
        self.create()
        first_project_id = self.project["projectId"]
        form = self.command("publish_artifact", {"title": "售后条件", "kind": "support_rules", "view": "form", "content": {
            "fields": [{"key": "returnWindow", "label": "退货期限", "type": "number"},
                       {"key": "used", "label": "允许已使用商品", "type": "boolean"}],
            "values": {"returnWindow": 7, "used": False}},
            "templateRef": {"skillId": "support-method", "templateId": "rules", "version": "1"}})["artifact"]
        self.project = None
        self.create(description="诊断支付链路故障")
        incident = self.command("publish_artifact", {"title": "故障时间线", "kind": "incident_timeline", "view": "table", "content": {
            "columns": [{"key": "at", "label": "时间"}, {"key": "service", "label": "服务"}, {"key": "observation", "label": "实际观测"}],
            "rows": [{"at": "10:01", "service": "payments", "observation": "连接超时"}]}})["artifact"]
        custom = self.command("publish_artifact", {"title": "服务依赖", "kind": "service_topology", "view": "html",
            "content": "<!doctype html><html><body><button>展开服务</button><script>document.body.dataset.view='topology'</script></body></html>"})["artifact"]
        self.assertEqual(self.store.read(first_project_id, artifact_id=form["artifactId"])["artifact"], form)
        self.assertEqual([item["kind"] for item in self.project["artifacts"]], ["incident_timeline", "service_topology"])
        self.assertEqual(self.project["workspace"]["artifactOrder"], [incident["artifactId"], custom["artifactId"]])
        self.assertNotIn("goal", self.project)
        self.assertNotIn("content", self.project["artifacts"][0])
        self.assertEqual(self.project["bindings"], [])

    def test_artifact_change_preserves_old_revision_and_stale_editor_cannot_overwrite(self):
        self.create()
        first = self.command("publish_artifact", {"title": "排查记录", "kind": "investigation", "view": "markdown", "content": "已观察到连接超时。"})["artifact"]
        update = self.payload("publish_artifact", {"artifactId": first["artifactId"], "expectedArtifactRevision": 1, "content": "连接超时发生于数据库入口。"})
        response = self.store.command(update)
        self.project = response["project"]
        self.assertEqual(response["artifact"]["revision"], 2)
        self.assertEqual(self.store.command(update)["artifact"], response["artifact"])
        with self.assertRaises(AgentLabProjectConflict):
            self.command("publish_artifact", {"artifactId": first["artifactId"], "expectedArtifactRevision": 1, "content": "旧编辑覆盖"})
        self.assertEqual(self.store.read(self.project["projectId"], artifact_id=first["artifactId"], artifact_revision=1)["artifact"], first)
        with closing(sqlite3.connect(self.db)) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM agent_lab_project_artifact_versions")

    def test_server_owned_scope_isolates_list_lookup_mutation_and_replay(self):
        create = self.payload("create", {"description": "工作空间 A 的业务"}, request_id="same-request-id")
        self.store = AgentLabProjectStore(self.db, scope_id="workspace-a")
        first = self.store.command(create)["project"]
        other = AgentLabProjectStore(self.db, scope_id="workspace-b")
        self.assertEqual(other.read()["items"], [])
        second = other.command(create)["project"]
        self.assertNotEqual(first["projectId"], second["projectId"])
        with self.assertRaises(AgentLabProjectNotFound):
            other.read(first["projectId"])
        with self.assertRaises(AgentLabProjectNotFound):
            other.command({"action": "update_brief", "projectId": first["projectId"], "expectedRevision": 1,
                           "clientRequestId": "cross-scope", "input": {"description": "should not write"}})
        with self.assertRaises(AgentLabProjectValidationError):
            other.command({**create, "scopeId": "workspace-a"})

    def test_artifact_fields_are_defined_by_its_view_and_no_result_is_inferred_from_content(self):
        self.create()
        invalid = {"title": "表格", "view": "table", "content": {"columns": [{"key": "x", "label": "X"}], "rows": [{"unknown": 1}]}}
        with self.assertRaises(AgentLabProjectValidationError):
            self.command("publish_artifact", invalid)
        invalid_form = {"title": "输入", "view": "form", "content": {"fields": [{"key": "x", "label": "X", "type": "number"}], "values": {"x": "incorrect-type"}}}
        with self.assertRaises(AgentLabProjectValidationError):
            self.command("publish_artifact", invalid_form)
        self.command("publish_artifact", {"title": "Agent 的判断", "view": "markdown", "content": "Agent 说：已完成并部署。"})
        self.assertEqual(self.project["bindings"], [])
        self.assertNotIn("status", self.project)
        self.assertNotIn("deployed", self.project)


if __name__ == "__main__":
    unittest.main()
