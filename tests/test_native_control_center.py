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
    def test_native_app_has_seven_pages_and_no_web_runtime(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.swift"))

        for page in ("OverviewPage", "InputMethodPage", "VoiceInputPage", "MemoryPage", "RagAndModelsPage", "HistoryPage", "DiagnosticsPage"):
            self.assertIn(page, text)
        for forbidden in ("WKWebView", "Electron", "Tauri", "node_modules"):
            self.assertNotIn(forbidden, text)
        self.assertIn("NSTableView", text)
        self.assertIn("applicationShouldTerminateAfterLastWindowClosed", text)
        self.assertIn("defaultSize(width: 1280, height: 820)", text)
        self.assertIn("frame(minWidth: 1080, minHeight: 720)", text)

    def test_bundle_and_build_script_contract(self) -> None:
        with (ROOT / "macos" / "RagImeControl" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        script = (ROOT / "scripts" / "build_control_center.sh").read_text(encoding="utf-8")

        self.assertEqual(info["CFBundleIdentifier"], "com.rag-ime.control")
        self.assertIn("$HOME/Applications/RagImeControl.app", script)
        self.assertIn("codesign --verify", script)
        self.assertIn("scripts/support/build_app_icon.sh", script)
        self.assertNotIn("RagImeMac.app", script)
        self.assertNotIn("open \"$DEST\"", script)

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
        self.assertIn(
            "case .knowledgeAnswer, .longForm, .recall, .organizeDatabase: return 0",
            models,
        )

    def test_overview_does_not_apply_a_profile_during_programmatic_startup_sync(self) -> None:
        source = (ROOT / "macos" / "RagImeControl" / "Pages" / "OverviewPage.swift").read_text(encoding="utf-8")
        components = (ROOT / "macos" / "RagImeControl" / "Components" / "ControlComponents.swift").read_text(encoding="utf-8")

        self.assertIn('Picker("运行模式", selection: profileSelection)', source)
        self.assertIn("private var profileSelection: Binding<String>", source)
        self.assertNotIn(".onChange(of: selectedProfile)", source)
        self.assertIn("SourceLaneLabel", source)
        self.assertIn('case "生成": return "bolt.horizontal.circle"', components)
        self.assertIn('case "RAG": return "doc.text.magnifyingglass"', components)
        self.assertIn('default: return "本地实时补全"', components)
        self.assertIn('value: "\\(memory.retrievalDocCount)"', source)
        self.assertIn('Text("\\(prediction.providerCallCount ?? 0) 次调用")', source)

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
                [swiftc, "-parse-as-library", str(supervisor), str(harness_path), "-o", str(binary)],
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


if __name__ == "__main__":
    unittest.main()
