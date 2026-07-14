from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeControlCenterTests(unittest.TestCase):
    def test_native_app_has_all_workspace_pages_and_no_web_runtime(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.swift"))

        for page in (
            "OverviewPage", "InputMethodPage", "VoiceInputPage", "PlanningPage",
            "MemoryPage", "RagAndModelsPage", "HistoryPage", "ConfigurationPage",
            "DiagnosticsPage",
        ):
            self.assertIn(page, text)
        for forbidden in ("WKWebView", "Electron", "Tauri", "node_modules"):
            self.assertNotIn(forbidden, text)
        self.assertIn("NSTableView", text)
        self.assertIn("applicationShouldTerminateAfterLastWindowClosed", text)
        self.assertIn("defaultSize(width: 1280, height: 820)", text)
        self.assertIn("frame(minWidth: 1080, minHeight: 720)", text)

    def test_agent_inspector_exposes_typed_tool_catalog_and_native_receipts(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        api = (root / "API" / "AgentAPIClient.swift").read_text(encoding="utf-8")
        models = (root / "Models" / "AgentModels.swift").read_text(encoding="utf-8")
        store = (root / "Stores" / "AgentConversationStore.swift").read_text(encoding="utf-8")
        page = (root / "Pages" / "AgentConversationPage.swift").read_text(encoding="utf-8")

        self.assertIn('get(path: ["api", "agent", "tools"])', api)
        self.assertIn('get(path: ["api", "agent", "roles"])', api)
        self.assertIn('get(path: ["api", "agent", "sessions", sessionId, "models"])', api)
        self.assertIn('path: ["api", "agent", "sessions", sessionId, "model"]', api)
        self.assertIn('path: ["api", "agent", "sessions", sessionId, "thinking"]', api)
        self.assertIn('path: ["api", "agent", "memory-maintenance"]', api)
        self.assertIn("struct AgentMemoryMaintenanceStatus", models)
        self.assertIn("struct AgentModelProvider", models)
        self.assertIn("struct AgentModelCatalogResponse", models)
        self.assertIn("struct AgentPersonaVisualProfile", models)
        self.assertIn("struct AgentPersonaDefaults", models)
        self.assertIn("selectableModes", models)
        self.assertIn("case memoryMaintenanceUpdated", models)
        self.assertIn("@Published private(set) var toolCatalog", store)
        self.assertIn("@Published private(set) var roleCatalog", store)
        self.assertIn("@Published private(set) var memoryMaintenance", store)
        self.assertIn("@Published private(set) var modelCatalog", store)
        self.assertIn("func selectModel(_ model: AgentModelOption) async", store)
        self.assertIn("func selectThinkingLevel(_ level: String) async", store)
        self.assertIn("func switchSessionMode(_ mode: String) async", store)
        self.assertIn('case tools = "工具"', page)
        self.assertIn("toolsInspector", page)
        self.assertIn('tool.approvalOperationCount == 0', page)
        self.assertIn('"\\(tool.approvalOperationCount) 项需确认"', page)
        self.assertIn('Text("\\(tool.operations.count) 个动作")', page)
        self.assertIn("AgentApprovalCard", page)
        self.assertIn("AgentApprovalReceiptCard", page)
        self.assertIn("remainingSeconds", page)
        self.assertIn("记忆来源检查点", page)
        self.assertIn("等待异步整理", page)
        self.assertIn("memoryMaintenanceBand", page)
        self.assertIn("定时任务只生成草案，不会自动应用", page)
        self.assertIn('case ("ime_memory", "maintenance_preview")', store)
        self.assertIn('case ("ime_memory", "maintenance_review")', store)
        self.assertIn('case ("ime_memory", "maintenance_apply")', store)
        self.assertIn('case ("ime_memory", "maintenance_rollback")', store)
        self.assertIn('case ("ime_input", "preview_settings")', store)
        self.assertIn('case ("ime_input", "apply_settings")', store)
        self.assertIn('case ("ime_input", "lexicon_apply")', store)
        self.assertIn('case ("ime_voice", "provider_preview")', store)
        self.assertIn('case ("ime_voice", "provider_apply")', store)
        self.assertIn('case ("ime_voice", "provider_rollback")', store)
        self.assertIn('case ("ime_runtime", "pause_ai")', store)
        self.assertIn('case ("ime_runtime", "restart_sidecar")', store)
        self.assertIn('case ("ime_runtime", "restart_predictor")', store)
        self.assertIn('case ("ime_models", "profile_preview")', store)
        self.assertIn('case ("ime_models", "profile_apply")', store)
        self.assertIn('case ("ime_models", "profile_rollback")', store)
        self.assertIn("记忆草案已应用", page)
        self.assertIn("记忆整理已回滚", page)
        self.assertIn('Button("让\\(selectedPersona.displayName)审阅"', page)
        self.assertIn("申请应用", page)
        self.assertIn("生成审阅草案", page)
        self.assertIn('if approval.toolId == "ime_memory" { return "记忆变更" }', page)
        self.assertIn("准备撤销", page)
        self.assertIn("输入设置已更新", page)
        self.assertIn("输入设置已恢复", page)
        self.assertIn("个人词表已应用", page)
        self.assertIn("Rime 已重新部署", page)
        self.assertIn("AI 辅助已暂停", page)
        self.assertIn("Sidecar 已重启", page)
        self.assertIn("本地预测器已重启", page)
        self.assertIn("运行组件变更", page)
        self.assertIn("模型配置变更", page)
        self.assertIn("语音配置变更", page)
        self.assertIn("语音 Provider 已保存", page)
        self.assertIn("等待语音代理重启后激活", page)
        self.assertIn("Provider 配置已保存", page)
        self.assertIn("等待 Sidecar 重启后激活", page)
        self.assertIn("便携备份已导出", page)
        self.assertIn('Label("不含密钥", systemImage: "key.slash")', page)
        self.assertIn("revertedSettingsApprovalId", store)
        self.assertIn("revertedLexiconApprovalId", store)
        self.assertIn("revertedModelProfileApprovalId", store)
        self.assertIn("revertedVoiceProviderApprovalId", store)
        self.assertIn("timeoutInterval: approved ? 110 : nil", api)
        self.assertIn('"external-result"', api)
        self.assertIn("finalizeExternalApproval", api)
        self.assertIn("waitForPiTurnToFinish", store)
        self.assertIn("ExternalRuntimeSupervisor.execute", store)
        self.assertIn("继续执行", page)
        self.assertIn("Pi 回合结束后执行", page)
        self.assertIn("@Published private(set) var memorySources", store)
        self.assertIn('Button("批准并继续", systemImage: "checkmark")', page)
        self.assertIn("payloadSha256: approval.payloadSha256", store)
        self.assertIn("今天想先从哪里开始？", page)
        self.assertIn("回顾今天", page)
        self.assertIn("找最近进展", page)
        self.assertIn('case "needs_configuration": return "对话模型待配置"', page)
        self.assertIn('Text("Pi 对话模型")', page)
        self.assertIn("piModelMenu", page)
        self.assertIn("sessionPermissionMenu", page)
        self.assertIn("model.thinkingLevels", page)
        self.assertNotIn('Image(systemName: "slash.circle")', page)

    def test_agent_media_and_compact_composer_are_native_managed_surfaces(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        page = (root / "Pages" / "AgentConversationPage.swift").read_text(encoding="utf-8")
        api = (root / "API" / "AgentAPIClient.swift").read_text(encoding="utf-8")
        cache = (root / "API" / "AgentMediaCache.swift").read_text(encoding="utf-8")
        store = (root / "Stores" / "AgentConversationStore.swift").read_text(encoding="utf-8")
        root_view = (root / "Navigation" / "ControlRootView.swift").read_text(encoding="utf-8")
        build = (ROOT / "scripts" / "build_control_center.sh").read_text(encoding="utf-8")

        for view in (
            "AgentImageBlockView",
            "AgentAudioBlockView",
            "AgentFileBlockView",
            "AgentStickerBlockView",
            "AgentQuickLookPresenter",
        ):
            self.assertIn(view, page)
        self.assertIn("AVAudioPlayer(data:", page)
        self.assertIn("QLPreviewPanel.shared()", page)
        self.assertIn('"^[A-Za-z0-9_-]+$"', page)
        self.assertIn("maximumObjects = 96", cache)
        self.assertIn("maximumBytes = 64 * 1024 * 1024", cache)
        self.assertIn("materializedURL", cache)
        self.assertNotIn("WKWebView", page)
        self.assertIn("-framework AVFoundation", build)
        self.assertIn("-framework QuickLookUI", build)
        self.assertIn(".focused($composerFocused)", page)
        self.assertIn('Image(systemName: "plus")', page)
        self.assertIn("输入消息、/ 命令，或直接粘贴路径", page)
        self.assertIn('"roleId": .string(roleId)', api)
        self.assertIn('"roleVersion": .string(roleVersion)', api)
        self.assertIn("acceptComposerDrop", page)
        self.assertIn("store.selectSessionInteractively(session.id)", page)
        self.assertIn(".contentShape(Rectangle())", page)
        self.assertIn("func selectSessionInteractively(_ id: String)", store)
        self.assertIn("loadConversationAndStream(expectedSessionId: id)", store)
        self.assertNotIn("VoiceAgentStatusStore.read()", page)
        self.assertNotIn("mic.badge.plus", page)
        self.assertIn("AgentNewSessionSheet", page)
        self.assertIn("personaSelectionRow", page)
        self.assertIn('case "hermes-v1"', page)
        self.assertIn('case "vcp-v1"', page)
        self.assertIn("AgentPersonaMark", page)
        persona_snapshot = (ROOT / "tests" / "swift" / "AgentPersonaSheetSnapshot.swift").read_text(encoding="utf-8")
        persona_script = (ROOT / "scripts" / "render_agent_persona_snapshot.sh").read_text(encoding="utf-8")
        self.assertIn("AgentNewSessionSheet(roles: roles)", persona_snapshot)
        self.assertIn("AgentPersonaSheetSnapshot.swift", persona_script)
        self.assertIn('Label("运行协调", systemImage: "terminal")', page)
        self.assertIn("授权工作区", page)
        self.assertIn("Command Harness", page)
        self.assertIn(
            "return store.toolCatalog.filter { $0.sessionModes.contains(mode) }",
            page,
        )
        self.assertIn("com.rag-ime.control.open-agent", root_view)
        self.assertIn("navigation.destination = .assistant", root_view)
        self.assertIn("focusExternalSession", root_view)
        self.assertIn("func focusExternalSession", store)

    def test_bundle_and_build_script_contract(self) -> None:
        with (ROOT / "macos" / "RagImeControl" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        script = (ROOT / "scripts" / "build_control_center.sh").read_text(encoding="utf-8")

        self.assertEqual(info["CFBundleIdentifier"], "com.rag-ime.control")
        self.assertIn("$HOME/Applications/RagImeControl.app", script)
        self.assertIn("codesign --verify", script)
        self.assertIn("scripts/support/build_app_icon.sh", script)
        self.assertIn("CompanionStates", script)
        self.assertNotIn("RagImeMac.app", script)
        self.assertNotIn("open \"$DEST\"", script)

        icon_script = (ROOT / "scripts" / "support" / "build_app_icon.sh").read_text(encoding="utf-8")
        icon_source = ROOT / "assets" / "brand" / "rag-ime-icon.png"
        self.assertIn("assets/brand/rag-ime-icon.png", icon_script)
        self.assertTrue(icon_source.is_file())
        self.assertEqual(icon_source.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_native_knowledge_workbench_uses_async_sessions_and_visible_provenance(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        app_model = (root / "AppModel.swift").read_text(encoding="utf-8")
        page = (root / "Pages" / "RagAndModelsPage.swift").read_text(encoding="utf-8")
        models = (root / "Models" / "ManagementModels.swift").read_text(encoding="utf-8")

        self.assertIn('api.post(\n                "api/knowledge/start"', app_model)
        self.assertIn('api.get(\n                    "api/knowledge/status"', app_model)
        self.assertIn('"api/knowledge/cancel"', app_model)
        self.assertIn('"api/knowledge/database/\\(action)"', app_model)
        self.assertIn("knowledgeGeneration += 1", app_model)
        for mode in ("knowledge_answer", "long_form", "recall", "organize_database"):
            self.assertIn(mode, models)
        self.assertIn("个人知识工作台", page)
        self.assertIn("包含 Notion", page)
        self.assertIn("contextInjection", page)
        self.assertIn("notionStatusTitle", page)
        self.assertIn("ProgressView", page)
        self.assertIn("应用草案", page)
        self.assertIn("回滚", page)
        self.assertIn("confirmationDialog", page)
        self.assertIn("告诉知识管家怎么整理", page)
        self.assertIn("knowledgeOrganizationInstruction", app_model)
        self.assertIn("defaultOrganizationInstruction", models)
        self.assertIn("恢复项目默认", page)
        self.assertIn("合并零散分组", page)
        self.assertIn("清洗语音和错别字", page)
        self.assertIn("整理标签关系", page)
        self.assertIn("更新常用词表", page)
        self.assertIn("AI 整理草案可审阅", page)
        self.assertIn('title: "模型整理"', page)
        self.assertIn('title: "正式记忆库"', page)
        self.assertNotIn('answer += "\\n\\n" + "；".join', (ROOT / "rag_ime" / "knowledge_workbench.py").read_text(encoding="utf-8"))
        self.assertIn(
            "case .knowledgeAnswer, .longForm, .recall, .organizeDatabase: return 0",
            models,
        )

    def test_overview_does_not_apply_a_profile_during_programmatic_startup_sync(self) -> None:
        source = (ROOT / "macos" / "RagImeControl" / "Pages" / "OverviewPage.swift").read_text(encoding="utf-8")
        components = (ROOT / "macos" / "RagImeControl" / "Components" / "ControlComponents.swift").read_text(encoding="utf-8")
        root = (ROOT / "macos" / "RagImeControl" / "Navigation" / "ControlRootView.swift").read_text(encoding="utf-8")

        self.assertIn('Picker("运行模式", selection: profileSelection)', source)
        self.assertIn("private var profileSelection: Binding<String>", source)
        self.assertNotIn(".onChange(of: selectedProfile)", source)
        self.assertIn("SourceLaneLabel", source)
        self.assertIn('case "生成": return "bolt.horizontal.circle"', components)
        self.assertIn('case "RAG": return "doc.text.magnifyingglass"', components)
        self.assertIn('default: return "本地实时补全"', components)
        self.assertIn('value: "\\(memory.retrievalDocCount)"', source)
        self.assertIn('Text("\\(prediction.providerCallCount ?? 0) 次调用")', source)
        self.assertIn("ControlReadinessItem", source)
        self.assertIn("ControlMetricItem", source)
        self.assertIn("ControlShortcutKey", source)
        self.assertIn('Section("工作台")', root)
        self.assertIn('Section("输入体验")', root)
        self.assertIn('Section("知识与系统")', root)
        self.assertIn("ControlNoticeBanner", root)
        self.assertIn("else if model.showingRuntimeActionReport", root)
        self.assertNotIn('.alert("操作失败"', root)
        self.assertIn("RagImeAnimeCompanion", root)
        self.assertIn(".fixedSize(horizontal: true, vertical: false)", components)

    def test_knowledge_workbench_hides_internal_source_ids_and_shows_evidence_text(self) -> None:
        page = (ROOT / "macos" / "RagImeControl" / "Pages" / "RagAndModelsPage.swift").read_text(encoding="utf-8")
        model = (ROOT / "macos" / "RagImeControl" / "AppModel.swift").read_text(encoding="utf-8")

        self.assertIn("displayAnswer(answer)", page)
        self.assertIn('with: "[\\(index + 1)]"', page)
        self.assertIn("evidenceExcerpt(item)", page)
        self.assertIn('case "phrase": return "常用短语"', page)
        self.assertIn("if model.expertMode, let sourceId", page)
        self.assertIn("clearTransientConnectionError()", model)
        self.assertIn("showingRuntimeActionReport = false", model)

    def test_control_center_coalesces_input_events_and_keeps_idle_artwork_static(self) -> None:
        app_model = (ROOT / "macos" / "RagImeControl" / "AppModel.swift").read_text(encoding="utf-8")
        companion = (ROOT / "macos" / "Shared" / "RagImeCompanionMark.swift").read_text(encoding="utf-8")

        self.assertIn("private var overviewRefreshTask", app_model)
        self.assertIn("private var destinationLoadTask", app_model)
        self.assertNotIn("@Published var destination", app_model)
        self.assertIn("destinationLoadTask?.cancel()", app_model)
        self.assertIn("await Task.yield()", app_model)
        self.assertIn("scheduleOverviewRefresh", app_model)
        self.assertIn("Task.sleep(for: .milliseconds(500))", app_model)
        self.assertIn("overviewRefreshTask?.cancel()", app_model)
        self.assertNotIn("await self?.refreshOverview()", app_model)
        self.assertIn("state == .listening || state == .thinking", companion)
        self.assertIn(".onChange(of: state)", companion)
        self.assertIn("Task.detached(priority: .utility)", companion)
        self.assertIn("CGImageSourceCreateThumbnailAtIndex", companion)
        self.assertNotIn("NSImage(contentsOf:", companion)

    def test_agent_transcript_coalesces_streaming_and_isolates_composer_redraws(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        store = (root / "Stores" / "AgentConversationStore.swift").read_text(encoding="utf-8")
        page = (root / "Pages" / "AgentConversationPage.swift").read_text(encoding="utf-8")

        self.assertIn("private let deltaFlushNanoseconds: UInt64 = 16_666_667", store)
        self.assertIn("bufferedTextDeltaEvents.append(event)", store)
        self.assertIn("var next = conversation", store)
        self.assertIn("if result != .ignored { conversation = next }", store)
        self.assertNotIn("if next != conversation", store)
        self.assertIn('guard message.role == "user" || message.role == "assistant"', store)
        self.assertIn("let replaceBlock = payload[\"replaceBlock\"]?.boolValue == true", store)
        self.assertIn("final class AgentComposerState: ObservableObject", store)
        self.assertNotIn("@Published var draft", store.split("final class AgentWorkspaceStore", 1)[1])

        self.assertIn("AgentComposerStateHost(state: store.composerState)", page)
        self.assertIn("await store.activate()", page)
        self.assertNotIn(".opacity(appeared", page)
        self.assertIn("AgentIncrementalTextSurface: NSViewRepresentable", page)
        self.assertIn("textStorage?.append(NSAttributedString", page)
        self.assertIn("private struct AgentMarkdownView", page)
        self.assertIn("case .code", page)
        self.assertIn("activityExpansionBySession", page)
        self.assertIn("AgentTranscriptSurface: NSViewRepresentable", page)
        self.assertIn("AgentTranscriptTableView: NSTableView", page)
        self.assertIn("tableView.usesAutomaticRowHeights = true", page)
        self.assertIn("tableView.makeView(", page)
        self.assertIn("refreshChangedVisibleRows", page)
        self.assertIn("makeIfNecessary: false", page)
        self.assertIn("newIds.starts(with: oldIds)", page)
        self.assertIn("if sessionChanged || (revisionChanged && wasNearBottom)", page)
        transcript = page.split("private var timeline: some View", 1)[1].split(
            "private var conversationWelcome", 1
        )[0]
        self.assertIn("AgentTranscriptSurface(", transcript)
        self.assertNotIn("ScrollViewReader", transcript)
        self.assertNotIn("LazyVStack", transcript)

    def test_unified_motion_system_limits_continuous_work_and_honors_reduce_motion(self) -> None:
        motion = (ROOT / "macos" / "Shared" / "RagImeMotion.swift").read_text(encoding="utf-8")
        companion = (ROOT / "macos" / "Shared" / "RagImeCompanionMark.swift").read_text(encoding="utf-8")
        page = (ROOT / "macos" / "RagImeControl" / "Pages" / "AgentConversationPage.swift").read_text(encoding="utf-8")
        root_view = (ROOT / "macos" / "RagImeControl" / "Navigation" / "ControlRootView.swift").read_text(encoding="utf-8")
        voice = (ROOT / "macos" / "RagImeVoice" / "VoiceOverlay.swift").read_text(encoding="utf-8")

        self.assertIn("enum RagImeMotion", motion)
        self.assertIn("static let maximumContinuousAnimationsPerSurface = 3", motion)
        self.assertIn("static func entrance(reduceMotion: Bool) -> Animation?", motion)
        self.assertIn("static func spring(reduceMotion: Bool) -> Animation?", motion)
        self.assertIn("reduceMotion ? nil", motion)
        self.assertIn("RagImeMotion.transition(reduceMotion: reduceMotion)", root_view)
        self.assertIn("RagImeMotion.Duration.transition", voice)

        full_body_float_rule = companion.split("struct RagImeFullBodyCompanion", 1)[1].split(
            "private func updateFloatingAnimation", 1
        )[0]
        self.assertNotIn("state == .idle", full_body_float_rule)
        self.assertIn("animatesAmbientMotion", companion)

        message_view = page.split("private struct AgentMessageView", 1)[1].split(
            "private struct AgentStreamingText", 1
        )[0]
        self.assertIn("animates: false", message_view)
        self.assertIn("AgentThinkingIndicator(", message_view)
        self.assertNotIn("repeatForever", message_view)
        self.assertIn("accessibilityDisplayShouldReduceMotion", page)

        self.assertIn("private var userFacingErrorTitle", page)
        self.assertIn("private var userFacingErrorDetail", page)
        self.assertIn(".help(rawErrorMessage)", page)
        self.assertNotIn('Label(block.data.objectValue["message"]?.stringValue', page)

    def test_agent_transcript_has_a_500_row_native_performance_gate(self) -> None:
        benchmark = (
            ROOT / "tests" / "swift" / "AgentTranscriptBenchmark.swift"
        ).read_text(encoding="utf-8")
        script = (ROOT / "scripts" / "benchmark_agent_transcript.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("(0..<520).map", benchmark)
        self.assertIn("realizedAtStart < 64", benchmark)
        self.assertIn("realizedAfterStream < 64", benchmark)
        self.assertIn("streamUpdates\": 120", benchmark)
        self.assertIn("streamTotalMs / 120 < 12", benchmark)

        activity_snapshot = (
            ROOT / "tests" / "swift" / "AgentActivityPanelSnapshot.swift"
        ).read_text(encoding="utf-8")
        activity_script = (
            ROOT / "scripts" / "render_agent_activity_snapshot.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('status: "working"', activity_snapshot)
        self.assertIn("AgentActivityPanel(items: items", activity_snapshot)
        self.assertIn("AgentActivityPanelSnapshot.swift", activity_script)
        self.assertIn("AgentTranscriptSurface.Coordinator()", benchmark)
        self.assertIn("! -name 'RagImeControlApp.swift'", script)
        self.assertIn("/usr/bin/time -l", script)

    def test_agent_center_has_versioned_personas_and_participant_aware_rooms(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        app = (root / "RagImeControlApp.swift").read_text(encoding="utf-8")
        api = (root / "API" / "AgentAPIClient.swift").read_text(encoding="utf-8")
        models = (root / "Models" / "AgentRoomModels.swift").read_text(encoding="utf-8")
        center = (root / "Pages" / "AgentCenterPage.swift").read_text(encoding="utf-8")
        rooms = (root / "Pages" / "AgentRoomsPage.swift").read_text(encoding="utf-8")
        transcript = (root / "Pages" / "AgentConversationPage.swift").read_text(encoding="utf-8")
        store = (root / "Stores" / "AgentRoomConversationStore.swift").read_text(encoding="utf-8")
        snapshot = (ROOT / "tests" / "swift" / "AgentRoomSheetSnapshot.swift").read_text(encoding="utf-8")
        render = (ROOT / "scripts" / "render_agent_room_snapshot.sh").read_text(encoding="utf-8")

        self.assertIn("AgentCenterNavigationModel", app)
        self.assertIn("AgentRoomWorkspaceStore", app)
        self.assertIn("case conversations", center)
        self.assertIn("case rooms", center)
        self.assertIn("case personas", center)
        self.assertIn("transaction.animation = nil", center)
        self.assertIn("struct AgentRoomParticipant", models)
        self.assertIn("struct AgentRoomEventEnvelope", models)
        self.assertIn('path: ["api", "agent", "rooms"]', api)
        self.assertIn('path: ["api", "agent", "rooms", roomId, "events"]', api)
        self.assertIn("deltaFlushNanoseconds: UInt64 = 16_666_667", store)
        self.assertIn("func selectRoomInteractively", store)
        self.assertIn("var canRouteDraft", store)
        self.assertIn("AgentTranscriptSurface(", rooms)
        self.assertIn(".participantMessage(entry.message", rooms)
        self.assertIn("case participantMessage", transcript)
        self.assertIn(".contentShape(Rectangle())", rooms)
        self.assertIn("AgentNewRoomSheet(roles: roles)", snapshot)
        self.assertIn("AgentRoomSheetSnapshot.swift", render)

    def test_memory_records_have_a_readable_detail_view(self) -> None:
        page = (ROOT / "macos/RagImeControl/Pages/MemoryPage.swift").read_text(encoding="utf-8")

        self.assertIn('Button("查看详情", systemImage: "doc.text.magnifyingglass"', page)
        self.assertIn("MemoryDetailSheet", page)
        self.assertIn('detailSection("完整内容")', page)
        self.assertIn('detailSection("标签")', page)
        self.assertIn('detailSection("包含的记忆")', page)
        self.assertIn("MemoryTagNetwork", page)
        self.assertIn('Label("关系图"', page)
        self.assertIn('Label("列表"', page)
        self.assertIn("个已联网", page)
        self.assertIn("个待整理", page)
        self.assertIn("Canvas", page)
        self.assertIn('detailSection("关联标签")', page)
        self.assertIn('detailSection("记录信息")', page)
        self.assertIn(".textSelection(.enabled)", page)

    def test_planning_and_configuration_pages_cover_daily_flow_and_safe_migration(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        planning = (root / "Pages" / "PlanningPage.swift").read_text(encoding="utf-8")
        configuration = (root / "Pages" / "ConfigurationPage.swift").read_text(encoding="utf-8")
        app_model = (root / "AppModel.swift").read_text(encoding="utf-8")

        for text in ("长期目标", "今日计划", "规划助手", "前一天", "回到今天", "后一天"):
            self.assertIn(text, planning)
        self.assertIn("recentDetectedCompletion", planning)
        self.assertIn("undoPlanningTaskEvent", planning)
        self.assertIn("pendingCompletionSuggestions", planning)
        self.assertIn('"api/planning/task-event/undo"', app_model)
        self.assertIn("planningDate", app_model)

        self.assertIn("rag-ime.config.yaml", configuration)
        self.assertIn('UTType(filenameExtension: "yaml")', configuration)
        self.assertIn("自动收紧为 0600", configuration)
        self.assertIn("不包含 API Key", configuration)
        self.assertIn("恢复前自动生成回滚包", configuration)
        self.assertIn('body: ["path": .string(path)]', app_model)
        self.assertIn('"api/configuration/restore-apply"', app_model)

    def test_input_method_page_has_review_bound_rime_lexicon_apply_and_rollback(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        page = (root / "Pages" / "InputMethodPage.swift").read_text(encoding="utf-8")
        app_model = (root / "AppModel.swift").read_text(encoding="utf-8")
        models = (root / "Models" / "ManagementModels.swift").read_text(encoding="utf-8")

        self.assertIn("词库建议", page)
        self.assertIn(".toggleStyle(.checkbox)", page)
        self.assertIn("应用已选", page)
        self.assertIn("confirmationDialog", page)
        self.assertIn('"api/rime-lexicon/review"', app_model)
        self.assertIn('"api/rime-lexicon/apply"', app_model)
        self.assertIn('"api/rime-lexicon/rollback"', app_model)
        self.assertIn('"reviewToken": .string(review.reviewToken)', app_model)
        self.assertIn('await run(action: "redeploy_rime")', app_model)
        self.assertIn("struct RimeLexiconReviewResponse", models)
        self.assertIn("struct RimeLexiconReviewEntry", models)

    def test_native_app_supervises_only_allowlisted_external_commands(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        app_model = (root / "AppModel.swift").read_text(encoding="utf-8")
        supervisor = (root / "ExternalRuntimeSupervisor.swift").read_text(encoding="utf-8")

        self.assertIn('case "external-supervisor-required"', app_model)
        self.assertIn("ExternalRuntimeSupervisor.execute", app_model)
        self.assertIn('api.get("api/health")', app_model)
        self.assertIn('api/runtime/job/\\(jobId)', app_model)
        self.assertIn("lastRuntimeActionReport", app_model)
        self.assertIn('URL(fileURLWithPath: "/bin/launchctl")', supervisor)
        self.assertIn('URL(fileURLWithPath: "/bin/bash")', supervisor)
        self.assertIn('"com.rag-ime.sidecar"', supervisor)
        self.assertIn('"com.rag-ime.mlx-predictor"', supervisor)
        self.assertIn('repairHelperNames: Set<String> = ["repair_rag_ime_launch_agents.sh"]', supervisor)
        self.assertIn("trustedHelperRoots", supervisor)
        self.assertNotIn('arguments = ["-c"', supervisor)
        self.assertNotIn("/bin/sh", supervisor)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS Swift frameworks")
    def test_external_command_policy_rejects_arbitrary_server_strings(self) -> None:
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is not available")

        supervisor = ROOT / "macos" / "RagImeControl" / "ExternalRuntimeSupervisor.swift"
        harness = r'''
import Foundation

@main
struct ExternalCommandPolicyHarness {
    static func expectRejected(_ body: () throws -> Void) {
        do {
            try body()
            fatalError("expected rejection")
        } catch { }
    }

    static func main() async throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let scripts = root.appendingPathComponent("scripts", isDirectory: true)
        try FileManager.default.createDirectory(at: scripts, withIntermediateDirectories: true)
        let helper = scripts.appendingPathComponent("repair_rag_ime_launch_agents.sh")
        try Data("#!/bin/bash\nexit 0\n".utf8).write(to: helper)

        let launchctl = try ExternalCommandPolicy.validate(
            action: "restart_sidecar",
            command: ["launchctl", "kickstart", "-k", "gui/501/com.rag-ime.sidecar"],
            uid: 501,
            trustedRoots: []
        )
        precondition(launchctl.executableURL.path == "/bin/launchctl")
        precondition(launchctl.arguments == ["kickstart", "-k", "gui/501/com.rag-ime.sidecar"])

        let repair = try ExternalCommandPolicy.validate(
            action: "repair_launch_agents",
            command: ["/bin/bash", helper.path],
            uid: 501,
            trustedRoots: [root]
        )
        precondition(repair.executableURL.path == "/bin/bash")
        precondition(repair.arguments == [helper.path])

        try Data("#!/bin/bash\necho supervised\necho repair-failed >&2\nexit 7\n".utf8).write(to: helper)
        let execution = try await ExternalRuntimeSupervisor.execute(
            action: "repair_launch_agents",
            command: ["/bin/bash", helper.path],
            timeoutSeconds: 5,
            trustedRoots: [root]
        )
        precondition(execution.exitCode == 7)
        precondition(execution.stdout == "supervised")
        precondition(execution.stderr == "repair-failed")
        precondition(!execution.succeeded)

        expectRejected {
            _ = try ExternalCommandPolicy.validate(
                action: "restart_sidecar",
                command: ["launchctl", "kickstart", "-k", "gui/501/com.rag-ime.mlx-predictor"],
                uid: 501,
                trustedRoots: []
            )
        }
        expectRejected {
            _ = try ExternalCommandPolicy.validate(
                action: "restart_sidecar",
                command: ["/bin/sh", "-c", "touch /tmp/pwned"],
                uid: 501,
                trustedRoots: []
            )
        }
        expectRejected {
            _ = try ExternalCommandPolicy.validate(
                action: "repair_launch_agents",
                command: ["/bin/bash", "-c", helper.path],
                uid: 501,
                trustedRoots: [root]
            )
        }
        let outside = root.deletingLastPathComponent().appendingPathComponent("scripts/repair_rag_ime_launch_agents.sh")
        try FileManager.default.createDirectory(at: outside.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("#!/bin/bash\nexit 0\n".utf8).write(to: outside)
        expectRejected {
            _ = try ExternalCommandPolicy.validate(
                action: "repair_launch_agents",
                command: ["/bin/bash", outside.path],
                uid: 501,
                trustedRoots: [root]
            )
        }
        let nested = root.appendingPathComponent("untrusted/scripts/repair_rag_ime_launch_agents.sh")
        try FileManager.default.createDirectory(at: nested.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("#!/bin/bash\nexit 0\n".utf8).write(to: nested)
        expectRejected {
            _ = try ExternalCommandPolicy.validate(
                action: "repair_launch_agents",
                command: ["/bin/bash", nested.path],
                uid: 501,
                trustedRoots: [root]
            )
        }
        expectRejected {
            _ = try ExternalCommandPolicy.validate(
                action: "delete_everything",
                command: ["launchctl", "kickstart", "-k", "gui/501/com.rag-ime.sidecar"],
                uid: 501,
                trustedRoots: []
            )
        }
    }
}
'''
        with tempfile.TemporaryDirectory(prefix="rag-ime-supervisor-test-") as temp_dir:
            temp = Path(temp_dir)
            harness_path = temp / "Harness.swift"
            binary = temp / "policy-test"
            trusted_root = temp / "trusted-source"
            harness_path.write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                [
                    swiftc,
                    "-module-cache-path",
                    str(temp / "module-cache"),
                    "-parse-as-library",
                    str(supervisor),
                    str(harness_path),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run(
                [str(binary), str(trusted_root)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS Swift compiler")
    def test_agent_protocol_fixtures_decode_in_swift(self) -> None:
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is not available")

        root = ROOT / "macos" / "RagImeControl" / "Models"
        harness = r'''
import Foundation

@main
struct AgentProtocolFixtureHarness {
    static func decode<T: Decodable>(_ type: T.Type, _ path: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(contentsOf: URL(fileURLWithPath: path)))
    }

    static func main() throws {
        let event = try decode(AgentEventEnvelope.self, CommandLine.arguments[1])
        let message = try decode(AgentMessage.self, CommandLine.arguments[2])
        let media = try decode(AgentMediaReceipt.self, CommandLine.arguments[3])
        let session = try decode(AgentSessionSummary.self, CommandLine.arguments[4])
        let approval = try decode(AgentApproval.self, CommandLine.arguments[5])
        let maintenance = try decode(AgentMemoryMaintenanceStatus.self, CommandLine.arguments[6])

        precondition(event.eventType == .toolProgress)
        precondition(event.sequence == 7)
        precondition(message.blocks.count == 2)
        precondition(message.blocks[0].type == .text)
        precondition(media.mimeType == "image/png")
        precondition(session.mode == "assistant")
        precondition(approval.state == "pending")
        precondition(approval.preview.objectValue["summary"]?.stringValue == "关闭模糊音")
        precondition(maintenance.policy == "review")
        precondition(maintenance.autoApply == false)
        precondition(maintenance.compileState.pendingEventCount == 7)
        precondition(maintenance.runs.first?.sourceCursor.objectValue["toEventId"]?.numberValue == 13023)

        let unknownJSON = Data("{\"schemaVersion\":\"rag-ime.agent-event.v1\",\"eventId\":\"e\",\"sessionId\":\"s\",\"turnId\":\"t\",\"sequence\":1,\"createdAtMs\":1,\"eventType\":\"future_event\",\"payload\":{},\"resumeToken\":\"s:1\"}".utf8)
        let unknown = try JSONDecoder().decode(AgentEventEnvelope.self, from: unknownJSON)
        precondition(unknown.eventType == .unknown("future_event"))
    }
}
'''
        fixtures = ROOT / "tests" / "fixtures" / "agent"
        with tempfile.TemporaryDirectory(prefix="rag-ime-agent-protocol-swift-") as temp_dir:
            temp = Path(temp_dir)
            harness_path = temp / "Harness.swift"
            binary = temp / "agent-protocol-test"
            harness_path.write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                [
                    swiftc,
                    "-module-cache-path",
                    str(temp / "module-cache"),
                    "-parse-as-library",
                    str(root / "ManagementModels.swift"),
                    str(root / "AgentModels.swift"),
                    str(harness_path),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run(
                [
                    str(binary),
                    str(fixtures / "agent-event.json"),
                    str(fixtures / "agent-message.json"),
                    str(fixtures / "agent-media.json"),
                    str(fixtures / "agent-session.json"),
                    str(fixtures / "agent-approval.json"),
                    str(fixtures / "agent-memory-maintenance-status.json"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS Swift compiler")
    def test_agent_conversation_reducer_tracks_activity_and_event_gaps(self) -> None:
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is not available")

        source = ROOT / "macos" / "RagImeControl"
        harness = r'''
import Foundation

@main
struct AgentConversationReducerHarness {
    static func event(_ sequence: Int, _ type: AgentEventKind, _ payload: JSONValue) -> AgentEventEnvelope {
        AgentEventEnvelope(
            schemaVersion: "rag-ime.agent-event.v1",
            eventId: "agent:test:\(sequence)",
            sessionId: "agent:test",
            turnId: "turn:1",
            sequence: sequence,
            createdAtMs: 1000 + sequence,
            eventType: type,
            payload: payload,
            resumeToken: "agent:test:\(sequence)"
        )
    }

    static func roomEvent(
        _ sequence: Int,
        _ type: AgentRoomEventKind,
        _ payload: JSONValue,
        participantId: String? = "participant:hermes"
    ) -> AgentRoomEventEnvelope {
        AgentRoomEventEnvelope(
            schemaVersion: "rag-ime.agent-room-event.v1",
            eventId: "room:test:\(sequence)",
            roomId: "room:test",
            sequence: sequence,
            turnId: "room-turn:1",
            eventType: type,
            participantId: participantId,
            sourceSessionId: participantId == nil ? "" : "agent:hermes",
            createdAtMs: 2000 + sequence,
            payload: payload,
            resumeToken: "room:test:\(sequence)"
        )
    }

    static func main() {
        var state = AgentConversationState()
        let busy = event(1, .statusChanged, .object(["status": .string("busy")]))
        precondition(AgentConversationReducer.reduce(state: &state, event: busy) == .applied)
        precondition(state.activity.first?.title == "理解问题中…")

        let started = event(2, .toolStarted, .object([
            "toolCallId": .string("tool:1"),
            "toolName": .string("ime_memory"),
            "args": .object(["op": .string("catalog")]),
            "isError": .bool(false),
        ]))
        _ = AgentConversationReducer.reduce(state: &state, event: started)
        precondition(state.activity.last?.title == "查找相关工具书中…")

        let finished = event(3, .toolFinished, .object([
            "toolCallId": .string("tool:1"),
            "toolName": .string("ime_memory"),
            "args": .object(["op": .string("catalog")]),
            "result": .object([
                "content": .array([.object(["type": .string("text"), "text": .string("result")])]),
                "details": .object([
                    "schemaVersion": .string("rag-ime.agent-tool-result.v1"),
                    "ok": .bool(true),
                    "tool": .string("ime_memory"),
                    "operation": .string("catalog"),
                    "result": .object([
                        "summary": .string("查询到 1 本工具书、1 个 Group、1 个 Tag"),
                        "items": .array([
                            .object(["kind": .string("book"), "title": .string("输入法项目")]),
                            .object(["kind": .string("group"), "title": .string("Agent Runtime")]),
                            .object(["kind": .string("tag"), "title": .string("Pi")]),
                        ]),
                    ]),
                ]),
            ]),
            "isError": .bool(false),
        ]))
        _ = AgentConversationReducer.reduce(state: &state, event: finished)
        precondition(state.activity.last?.state == .completed)
        precondition(state.activity.last?.detail.contains("书《输入法项目》") == true)
        precondition(state.activity.last?.detail.contains("Group「Agent Runtime」") == true)
        precondition(state.activity.last?.detail.contains("Tag #Pi") == true)
        precondition(state.activity.last?.references.map(\.kind) == [.book, .group, .tag])

        let recentStarted = event(4, .toolStarted, .object([
            "toolCallId": .string("tool:recent"),
            "toolName": .string("ime_memory"),
            "args": .object(["op": .string("recent")]),
            "isError": .bool(false),
        ]))
        _ = AgentConversationReducer.reduce(state: &state, event: recentStarted)
        precondition(state.activity.last?.title == "查近期对话中…")

        let recentFinished = event(5, .toolFinished, .object([
            "toolCallId": .string("tool:recent"),
            "toolName": .string("ime_memory"),
            "args": .object(["op": .string("recent")]),
            "result": .object(["details": .object([
                "schemaVersion": .string("rag-ime.agent-tool-result.v1"),
                "ok": .bool(true),
                "tool": .string("ime_memory"),
                "operation": .string("recent"),
                "result": .object([
                    "summary": .string("召回 3 段近期最终输入"),
                    "count": .number(3),
                    "items": .array([
                        .object(["kind": .string("source"), "text": .string("继续完善 Pi 控制中心")]),
                    ]),
                ]),
            ])]),
            "isError": .bool(false),
        ]))
        _ = AgentConversationReducer.reduce(state: &state, event: recentFinished)
        precondition(state.activity.last?.title == "已查近期对话")
        precondition(state.activity.last?.detail.contains("3 段") == true)
        precondition(state.activity.last?.references.first?.kind == .recent)
        precondition(state.activity.last?.references.first?.label.contains("Pi 控制中心") == true)

        let message = AgentMessage(
            schemaVersion: "rag-ime.agent-message.v1",
            id: "message:1",
            sessionId: "agent:test",
            turnId: "turn:1",
            role: "assistant",
            status: "completed",
            blocks: [AgentBlock(
                id: "block:1",
                type: .text,
                status: "completed",
                presentationKind: "markdown",
                data: .object(["text": .string("最终回答")])
            )],
            attachments: [],
            citations: [],
            createdAtMs: 1006,
            completedAtMs: 1006
        )
        let encoded = try! JSONEncoder().encode(message)
        let messageValue = try! JSONDecoder().decode(JSONValue.self, from: encoded)
        _ = AgentConversationReducer.reduce(
            state: &state,
            event: event(6, .messageCompleted, .object(["message": messageValue]))
        )
        precondition(state.messages.last?.blocks.first?.data.objectValue["text"]?.stringValue == "最终回答")
        precondition(AgentConversationReducer.reduce(state: &state, event: finished) == .ignored)

        let maintenance = event(7, .memoryMaintenanceUpdated, .object([
            "trigger": .string("session_switch"),
            "due": .bool(true),
            "summary": .string("新增最终消息已达到整理阈值"),
        ]))
        _ = AgentConversationReducer.reduce(state: &state, event: maintenance)
        precondition(state.activity.last?.title == "记忆整理已就绪")
        precondition(state.activity.last?.detail.contains("整理阈值") == true)

        let approvalRequired = event(8, .approvalRequired, .object([
            "approvalId": .string("approval:external"),
            "summary": .string("确认重启 Sidecar"),
        ]))
        _ = AgentConversationReducer.reduce(state: &state, event: approvalRequired)
        let externalPending = event(9, .approvalResolved, .object([
            "approvalId": .string("approval:external"),
            "state": .string("external_pending"),
        ]))
        _ = AgentConversationReducer.reduce(state: &state, event: externalPending)
        precondition(state.activity.last?.state == .waiting)
        precondition(state.activity.last?.title == "已批准，等待外部执行")
        precondition(state.status == "working")

        let externalApplied = event(10, .approvalResolved, .object([
            "approvalId": .string("approval:external"),
            "state": .string("applied"),
            "externalFinalized": .bool(true),
            "summary": .string("Sidecar 已由新进程确认"),
        ]))
        _ = AgentConversationReducer.reduce(state: &state, event: externalApplied)
        precondition(state.activity.last?.state == .completed)
        precondition(state.activity.last?.detail == "Sidecar 已由新进程确认")
        precondition(state.status == "idle")

        let gap = event(12, .statusChanged, .object(["status": .string("busy")]))
        precondition(AgentConversationReducer.reduce(state: &state, event: gap) == .reloadSnapshot)
        precondition(state.needsSnapshot)

        var room = AgentRoomConversationState()
        _ = AgentRoomConversationReducer.appendOptimisticUser(
            state: &room,
            roomId: "room:test",
            text: "@Hermes 请核对",
            nowMs: 1999
        )
        precondition(room.messages.count == 1)
        _ = AgentRoomConversationReducer.reduce(
            state: &room,
            event: roomEvent(
                1,
                .userMessage,
                .object(["text": .string("@Hermes 请核对")]),
                participantId: nil
            ),
            participantName: "Agent"
        )
        precondition(room.messages.count == 1)
        precondition(room.messages[0].message.status == "completed")
        _ = AgentRoomConversationReducer.reduce(
            state: &room,
            event: roomEvent(2, .routeDecision, .object([
                "targetDisplayName": .string("Hermes"),
            ])),
            participantName: "Hermes"
        )
        precondition(room.activeParticipantId == "participant:hermes")
        precondition(room.activity.last?.title == "已交给Hermes")
        _ = AgentRoomConversationReducer.reduce(
            state: &room,
            event: roomEvent(3, .participantDelta, .object([
                "data": .object([
                    "messageId": .string("message:hermes"),
                    "blockId": .string("block:text"),
                    "delta": .string("正在"),
                ]),
            ])),
            participantName: "Hermes"
        )
        _ = AgentRoomConversationReducer.reduce(
            state: &room,
            event: roomEvent(4, .participantDelta, .object([
                "data": .object([
                    "messageId": .string("message:hermes"),
                    "blockId": .string("block:text"),
                    "delta": .string("核对"),
                ]),
            ])),
            participantName: "Hermes"
        )
        precondition(room.messages.last?.participantId == "participant:hermes")
        precondition(room.messages.last?.message.blocks.first?.data.objectValue["text"]?.stringValue == "正在核对")
        _ = AgentRoomConversationReducer.reduce(
            state: &room,
            event: roomEvent(5, .turnCompleted, .object([:])),
            participantName: "Hermes"
        )
        precondition(room.status == "idle")
        precondition(room.activeParticipantId == nil)
        precondition(
            AgentRoomConversationReducer.reduce(
                state: &room,
                event: roomEvent(7, .participantStatus, .object(["status": .string("active")])),
                participantName: "Hermes"
            ) == .reloadFromBeginning
        )
    }
}
'''
        with tempfile.TemporaryDirectory(prefix="rag-ime-agent-reducer-swift-") as temp_dir:
            temp = Path(temp_dir)
            harness_path = temp / "Harness.swift"
            binary = temp / "agent-reducer-test"
            harness_path.write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                [
                    swiftc,
                    "-module-cache-path",
                    str(temp / "module-cache"),
                    "-parse-as-library",
                    str(source / "Models" / "ManagementModels.swift"),
                    str(source / "Models" / "AgentModels.swift"),
                    str(source / "Models" / "AgentRoomModels.swift"),
                    str(source / "API" / "ManagementAPIClient.swift"),
                    str(source / "API" / "AgentAPIClient.swift"),
                    str(source / "ExternalRuntimeSupervisor.swift"),
                    str(source / "Stores" / "AgentConversationStore.swift"),
                    str(source / "Stores" / "AgentRoomConversationStore.swift"),
                    str(harness_path),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run(
                [str(binary)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stderr)


if __name__ == "__main__":
    unittest.main()
