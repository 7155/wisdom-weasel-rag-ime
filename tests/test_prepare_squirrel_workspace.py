from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "darwin", "requires macOS Squirrel tooling")
class PrepareSquirrelWorkspaceScriptTests(unittest.TestCase):
    def _create_minimal_squirrel_upstream(self, tmp_path: Path) -> tuple[Path, Path]:
        upstream = tmp_path / "upstream-squirrel"
        patch_file = tmp_path / "rag-ime-sidecar.patch"
        upstream.mkdir()
        (upstream / "sources").mkdir()
        subprocess.run(["git", "init"], cwd=upstream, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=upstream, check=True)
        subprocess.run(["git", "config", "user.name", "RAG IME Test"], cwd=upstream, check=True)
        (upstream / "README.md").write_text("fake squirrel\n", encoding="utf-8")
        (upstream / "sources" / "RagImeSidecarModels.swift").write_text(
            "import Foundation\nstruct RagImeSidecarRequest: Codable { let privacyDisposition: String }\n"
            "struct RagImeDisplayCandidate { let displayLayout: String? }\n"
            "struct RagImeWindowContextSnapshot {}\n",
            encoding="utf-8",
        )
        (upstream / "sources" / "RagImeSidecarClient.swift").write_text(
            "import Foundation\nstruct RagImeSidecarClient {\n"
            "  init?(config: SquirrelConfig?) {}\n"
            "  func call() { _ = \"rime-suggest\"; _ = \"rime-select\"; _ = \"rime-rank-feedback\" }\n"
            "  // request.privacyDisposition == \"allowed\"\n"
            "}\n",
            encoding="utf-8",
        )
        (upstream / "sources" / "RagImeSelectedTextProvider.swift").write_text(
            "import ApplicationServices\nfinal class RagImeForegroundContextResolver {}\n"
            "final class RagImeSelectedTextProvider {\n"
            "  func captureForegroundTextForSidecar() {\n"
            "    _ = kAXSelectedTextRangeAttribute\n"
            "    _ = kAXStringForRangeParameterizedAttribute\n"
            "    _ = kAXValueAttribute\n"
            "  }\n"
            '  // privacy_unknown_app_bundle_missing; isSensitive: false, reason: "privacy_unknown_ax_not_trusted"\n'
            "  // privacy_unknown_focused_element_missing privacy_unknown_metadata_read_failed\n"
            "  // privacy_unknown_text_field_metadata_missing sensitive_application_bundle\n"
            "  // RAG_IME_SENSITIVE_APP_BUNDLE_IDS RagImeSensitiveAppBundleTokens\n"
            "  // captureWindowContext AXUIElementCopyMultipleAttributeValues\n"
            "  // AXManualAccessibility AXUIElementGetPid\n"
            "}\n",
            encoding="utf-8",
        )
        (upstream / "sources" / "SquirrelInputController.swift").write_text(
            "\n".join(
                [
                    "final class SquirrelInputController {",
                    "  func selectRagImeSideCandidate() {}",
                    "  func ragImeRequestFingerprint() {}",
                    "  func mergedRagImePanelCandidates() {}",
                    "  func ragImePanelForcesHorizontalLayout() -> Bool { false }",
                    "  func ragImePanelUsesSideDisplay() -> Bool { false }",
                    '  // ragImePrivacyDisposition == "allowed"; privacyDisposition: ragImePrivacyDisposition',
                    "  func forceSideCandidates() { let forceSideCandidates = rawInput.isEmpty && preedit.isEmpty; _ = \"forceSideCandidates: forceSideCandidates\" }",
                    "  func traceRagImeFrontendEvent() {}",
                    "  // guard ragImeSidecarClient?.frontendTrace == true || isCaptureDeliveryEvent else { return }",
                    "  // guard !ragImeSensitiveFieldActive || sensitiveSafeEvents.contains(event) else { return }",
                    "  // ragImePrepareFrontendTraceLog .posixPermissions: 0o600 appendingPathExtension(\"1\")",
                    "  // let contextAnchor = ragImeStableTextHash(context)",
                    "  // queryAnchor: contextAnchor displayAnchor: contextAnchor",
                    "  func traceRagImePanelTextLayout() { _ = \"panel_text_layout\" }",
                    "  func traceSidecarRequestScheduled() { _ = \"sidecar_request_scheduled\" }",
                    "  func traceSidecarEmptyResponseCleared() { _ = \"sidecar_empty_response_cleared\" }",
                    "  func traceV2() { _ = \"rag-ime.foreground-trace.v2\" }",
                    "  func suppressCompositionAi() { _ = \"composition_ai_suppressed\" }",
                    "  func traceRimeComposition() { _ = \"rime_composition_started\"; _ = \"rime_composition_candidates_visible\" }",
                    "  func controlCenterMenu() { _ = \"打开 PAW...\"; _ = \"配置由控制中心管理\"; _ = \"重新启动后台服务\"; _ = \"诊断与修复...\"; _ = \"com.rag-ime.control\" }",
                    "  func suppressPostCommitOverlay() { _ = \"RAG_IME_ASSISTANT_OVERLAY_AUTO_PENDING\"; _ = \"assistant_overlay_local_placeholder_suppressed\" }",
                    "  func foregroundSnapshot() { _ = \"ragImeSelectedTextProvider.captureForegroundTextForSidecar\" }",
                    "  func queuedForegroundSnapshot() { _ = \"ragImeForegroundContextResolver.captureFromAccessibility(\" }",
                    "  func probeRagImeForegroundPrivacyAndContext() { _ = \"privacy_probe_timeout\" }",
                    '  // active_rag_window_context_capture_scheduled "usesScreenCapture": false',
                    "  func foregroundCaptureResolved() { _ = \"foreground_context_capture_resolved\" }",
                    "  func foregroundCaptureFailed() { _ = \"foreground_context_capture_failed\" }",
                    "  func sideCandidateFeedbackRecorded() { _ = \"side_candidate_feedback_recorded\" }",
                    "  // ragImeNativeSelectionSnapshot native_rime_rank_feedback_recorded",
                    "  // guard !enforceRagImeFastPrivacyGuard() else { return }",
                    "  // discardRagImeSensitiveNativeLearningTransaction",
                    "  // guard rimeAPI.get_status(session, &status) else { return false }",
                    "  // guard !isComposing else { return false } return !backspaceHandled",
                    "  // rimeAPI.process_key(session, Int32(XK_BackSpace), 0)",
                    '  // "forwardedToClient": false',
                    "  func assistantOverlayCandidateVisible() { _ = \"assistant_overlay_candidate_visible\" }",
                    "  func ragImeDisplayComment() { _ = \"candidate.sourceType == \\\"model\\\"\" }",
                    "}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (upstream / "sources" / "SquirrelPanel.swift").write_text(
            "final class SquirrelPanel { var ragImePanelLinear: Bool { true }; "
            "var ragImePanelUsesSideDisplay: Bool { false }; "
            "func nonGlassBackground() { _ = \"return NSView()\" }; "
            "func candidateSeparator(before index: Int) -> String { \"\\n\" }; "
            "func traceRagImePanelTextLayout() {} }\n",
            encoding="utf-8",
        )
        (upstream / "sources" / "Main.swift").write_text(
            "\n".join(
                [
                    "import Foundation",
                    "struct SquirrelApp {",
                    '  static let appDir = "/Library/Input Library/Squirrel.app".withCString { dir in',
                    "    URL(fileURLWithFileSystemRepresentation: dir, isDirectory: false, relativeTo: nil)",
                    "  }",
                    '  static let logDir = FileManager.default.temporaryDirectory.appending(component: "rime.squirrel", directoryHint: .isDirectory)',
                    "}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "README.md", "sources"], cwd=upstream, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=upstream, check=True, capture_output=True, text=True)

        (upstream / "sources" / "Main.swift").write_text(
            "\n".join(
                [
                    "import Foundation",
                    "struct SquirrelApp {",
                    "  static let appDir = Bundle.main.bundleURL",
                    '  static let logDir = FileManager.default.temporaryDirectory.appending(component: "rime.squirrel", directoryHint: .isDirectory)',
                    "}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        patch_file.write_text(
            subprocess.run(
                ["git", "diff", "--binary"],
                cwd=upstream,
                check=True,
                capture_output=True,
                text=True,
            ).stdout,
            encoding="utf-8",
        )
        subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=upstream, check=True, capture_output=True, text=True)
        return upstream, patch_file

    def test_prepare_squirrel_workspace_dry_run_reports_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-prepare-") as tmp:
            workdir = Path(tmp) / "squirrel"
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_SQUIRREL_DRY_RUN": "1",
                "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                "RAG_IME_SIDECAR_PORT": "18766",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "prepare_squirrel_workspace.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn(f"workdir={workdir}", result.stdout)
        self.assertIn("base_ref=2158538", result.stdout)
        self.assertIn("runtime_profile=foreground-rag-proof", result.stdout)
        self.assertIn("latency_budget_ms=900", result.stdout)
        self.assertIn("timeout_ms=1200", result.stdout)
        self.assertIn("max_side_candidates=5", result.stdout)
        self.assertIn("post_commit_idle_ms=420", result.stdout)
        self.assertIn("sidecar_url=http://127.0.0.1:18766/api", result.stdout)
        self.assertIn(f"repo_root={root}", result.stdout)
        self.assertIn(
            f"db_path={Path(tmp) / 'Library' / 'Application Support' / 'RagIme' / 'rag-ime.sqlite'}",
            result.stdout,
        )

    def test_prepare_squirrel_workspace_reset_recovers_invalid_git_checkout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-reset-") as tmp:
            tmp_path = Path(tmp)
            upstream, patch_file = self._create_minimal_squirrel_upstream(tmp_path)
            workdir = tmp_path / "patched-squirrel"
            (workdir / ".git").mkdir(parents=True)
            (workdir / "stale-marker.txt").write_text("broken checkout\n", encoding="utf-8")
            env = {
                **os.environ,
                "RAG_IME_SQUIRREL_REPO_URL": str(upstream),
                "RAG_IME_SQUIRREL_BASE_REF": "HEAD",
                "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                "RAG_IME_SQUIRREL_PATCH": str(patch_file),
                "RAG_IME_SQUIRREL_RESET": "1",
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_DB_PATH": str(tmp_path / "rag-ime.sqlite"),
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "prepare_squirrel_workspace.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

            git_check = subprocess.run(
                ["git", "-C", str(workdir), "rev-parse", "--is-inside-work-tree"],
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("Prepared patched Squirrel workdir", result.stdout)
        self.assertIn("Resetting Squirrel workdir", result.stderr)
        self.assertEqual(git_check.stdout.strip(), "true")
        self.assertFalse((workdir / "stale-marker.txt").exists())

    def test_prepare_squirrel_workspace_applies_patch_and_writes_config_offline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-prepare-") as tmp:
            tmp_path = Path(tmp)
            upstream = tmp_path / "upstream-squirrel"
            workdir = tmp_path / "patched-squirrel"
            patch_file = tmp_path / "rag-ime-sidecar.patch"
            upstream.mkdir()
            (upstream / "sources").mkdir()
            subprocess.run(["git", "init"], cwd=upstream, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=upstream, check=True)
            subprocess.run(["git", "config", "user.name", "RAG IME Test"], cwd=upstream, check=True)
            (upstream / "README.md").write_text("fake squirrel\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=upstream, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=upstream, check=True, capture_output=True, text=True)

            (upstream / "sources" / "RagImeSidecarModels.swift").write_text(
                "import CryptoKit\nimport Foundation\nstruct RagImeSidecarRequest: Codable { let privacyDisposition: String }\nstruct RagImeDisplayCandidate { let displayLayout: String? }\nstruct RagImeWindowContextSnapshot {}\n",
                encoding="utf-8",
            )
            (upstream / "sources" / "RagImeSidecarClient.swift").write_text(
                "\n".join(
                    [
                        "import Foundation",
                        "struct RagImeSidecarClient {",
                        "  init?(config: SquirrelConfig?) {}",
                        "  func call() {",
                        '    _ = "rime-suggest"',
                        '    _ = "rime-select"',
                        '    _ = "rime-rank-feedback"',
                        '    // request.privacyDisposition == "allowed"',
                        "  }",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (upstream / "sources" / "RagImeSelectedTextProvider.swift").write_text(
                "\n".join(
                    [
                        "import ApplicationServices",
                        "final class RagImeForegroundContextResolver {}",
                        "final class RagImeSelectedTextProvider {",
                        "  func captureForegroundTextForSidecar() {",
                        "    _ = kAXSelectedTextRangeAttribute",
                        "    _ = kAXStringForRangeParameterizedAttribute",
                        "    _ = kAXValueAttribute",
                        "  }",
                        '  // privacy_unknown_app_bundle_missing; isSensitive: false, reason: "privacy_unknown_ax_not_trusted"',
                        "  // privacy_unknown_focused_element_missing privacy_unknown_metadata_read_failed",
                        "  // privacy_unknown_text_field_metadata_missing sensitive_application_bundle",
                        "  // RAG_IME_SENSITIVE_APP_BUNDLE_IDS RagImeSensitiveAppBundleTokens",
                        "  // captureWindowContext AXUIElementCopyMultipleAttributeValues",
                        "  // AXManualAccessibility AXUIElementGetPid",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (upstream / "sources" / "SquirrelInputController.swift").write_text(
                "\n".join(
                    [
                        "final class SquirrelInputController {",
                        "  func selectRagImeSideCandidate() {}",
                        "  func ragImeRequestFingerprint() {}",
                        "  func mergedRagImePanelCandidates() {}",
                        "  func ragImePanelForcesHorizontalLayout() -> Bool { false }",
                        "  func ragImePanelUsesSideDisplay() -> Bool { false }",
                        '  // ragImePrivacyDisposition == "allowed"; privacyDisposition: ragImePrivacyDisposition',
                        "  func forceSideCandidates() { let forceSideCandidates = rawInput.isEmpty && preedit.isEmpty; _ = \"forceSideCandidates: forceSideCandidates\" }",
                        "  func traceRagImeFrontendEvent() {}",
                        "  // guard ragImeSidecarClient?.frontendTrace == true || isCaptureDeliveryEvent else { return }",
                        "  // guard !ragImeSensitiveFieldActive || sensitiveSafeEvents.contains(event) else { return }",
                        '  // ragImePrepareFrontendTraceLog .posixPermissions: 0o600 appendingPathExtension("1")',
                        "  // let contextAnchor = ragImeStableTextHash(context)",
                        "  // queryAnchor: contextAnchor displayAnchor: contextAnchor",
                        '  func traceRagImePanelTextLayout() { _ = "panel_text_layout" }',
                        '  func traceSidecarRequestScheduled() { _ = "sidecar_request_scheduled" }',
                        '  func traceSidecarEmptyResponseCleared() { _ = "sidecar_empty_response_cleared" }',
                        '  func traceV2() { _ = "rag-ime.foreground-trace.v2" }',
                        '  func suppressCompositionAi() { _ = "composition_ai_suppressed" }',
                        '  func traceRimeComposition() { _ = "rime_composition_started"; _ = "rime_composition_candidates_visible" }',
                        '  func controlCenterMenu() { _ = "打开 PAW..."; _ = "配置由控制中心管理"; _ = "重新启动后台服务"; _ = "诊断与修复..."; _ = "com.rag-ime.control" }',
                        '  func suppressPostCommitOverlay() { _ = "RAG_IME_ASSISTANT_OVERLAY_AUTO_PENDING"; _ = "assistant_overlay_local_placeholder_suppressed" }',
                        '  func foregroundSnapshot() { _ = "ragImeSelectedTextProvider.captureForegroundTextForSidecar" }',
                        '  func queuedForegroundSnapshot() { _ = "ragImeForegroundContextResolver.captureFromAccessibility(" }',
                        '  func probeRagImeForegroundPrivacyAndContext() { _ = "privacy_probe_timeout" }',
                        '  // active_rag_window_context_capture_scheduled "usesScreenCapture": false',
                        '  func foregroundCaptureResolved() { _ = "foreground_context_capture_resolved" }',
                        '  func foregroundCaptureFailed() { _ = "foreground_context_capture_failed" }',
                        '  func sideCandidateFeedbackRecorded() { _ = "side_candidate_feedback_recorded" }',
                        '  // ragImeNativeSelectionSnapshot native_rime_rank_feedback_recorded',
                        '  // guard !enforceRagImeFastPrivacyGuard() else { return }',
                        '  // discardRagImeSensitiveNativeLearningTransaction',
                        '  // guard rimeAPI.get_status(session, &status) else { return false }',
                        '  // guard !isComposing else { return false } return !backspaceHandled',
                        '  // rimeAPI.process_key(session, Int32(XK_BackSpace), 0)',
                        '  // "forwardedToClient": false',
                        '  func assistantOverlayCandidateVisible() { _ = "assistant_overlay_candidate_visible" }',
                        '  func ragImeDisplayComment() { _ = "candidate.sourceType == \\"model\\"" }',
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (upstream / "sources" / "Main.swift").write_text(
                "\n".join(
                    [
                        "import Foundation",
                        "struct SquirrelApp {",
                        '  static let logDir = FileManager.default.temporaryDirectory.appending(component: "rime.squirrel", directoryHint: .isDirectory)',
                        '  static let appDir = "/Library/Input Library/Squirrel.app".withCString { dir in',
                        "    URL(fileURLWithFileSystemRepresentation: dir, isDirectory: false, relativeTo: nil)",
                        "  }",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (upstream / "sources" / "SquirrelPanel.swift").write_text(
                "final class SquirrelPanel { var ragImePanelLinear: Bool { true }; var ragImePanelUsesSideDisplay: Bool { false }; func nonGlassBackground() { _ = \"return NSView()\" }; func candidateSeparator(before index: Int) -> String { \"\\n\" }; func traceRagImePanelTextLayout() {} }\n",
                encoding="utf-8",
            )
            (upstream / "sources" / "InputSource.swift").write_text(
                "\n".join(
                    [
                        "import Foundation",
                        "final class SquirrelInstaller {",
                        "  enum InputMode: String, CaseIterable {",
                        "    static let primary = Self.hans",
                        '    case hans = "im.rime.inputmethod.Squirrel.Hans"',
                        '    case hant = "im.rime.inputmethod.Squirrel.Hant"',
                        "  }",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (upstream / "sources" / "SquirrelApplicationDelegate.swift").write_text(
                "\n".join(
                    [
                        "final class SquirrelApplicationDelegate {",
                        "  func updateStatusItemVisibility(currentInputSourceID: String) -> Bool {",
                        '    currentInputSourceID.hasPrefix("im.rime.inputmethod.Squirrel")',
                        "  }",
                        "  func finalizeStrandedComposition(currentInputSourceID: String) -> Bool {",
                        '    currentInputSourceID.hasPrefix("im.rime.inputmethod.Squirrel")',
                        "  }",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "sources"], cwd=upstream, check=True)
            subprocess.run(["git", "commit", "-m", "add source stubs"], cwd=upstream, check=True, capture_output=True, text=True)

            (upstream / "sources" / "Main.swift").write_text(
                "\n".join(
                    [
                        "import Foundation",
                        "struct SquirrelApp {",
                        "  static let appDir = Bundle.main.bundleURL",
                        '  static let logDir = FileManager.default.temporaryDirectory.appending(component: "rime.squirrel", directoryHint: .isDirectory)',
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "sources/Main.swift"], cwd=upstream, check=True)
            patch = subprocess.run(
                ["git", "diff", "--cached", "--binary"],
                cwd=upstream,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            patch_file.write_text(patch, encoding="utf-8")
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=upstream, check=True, capture_output=True, text=True)

            env = {
                **os.environ,
                "RAG_IME_SQUIRREL_REPO_URL": str(upstream),
                "RAG_IME_SQUIRREL_BASE_REF": "HEAD",
                "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                "RAG_IME_SQUIRREL_PATCH": str(patch_file),
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_DB_PATH": str(tmp_path / "rag-ime.sqlite"),
                "RAG_IME_PROJECT": "offline-test",
                "RAG_IME_SIDECAR_PORT": "19866",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "prepare_squirrel_workspace.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertIn("Prepared patched Squirrel workdir", result.stdout)
            self.assertTrue((workdir / "sources" / "RagImeSidecarModels.swift").is_file())
            self.assertTrue((workdir / "sources" / "RagImeSidecarClient.swift").is_file())
            self.assertTrue((workdir / "sources" / "RagImeSelectedTextProvider.swift").is_file())
            self.assertTrue((workdir / "sources" / "SquirrelInputController.swift").is_file())
            self.assertIn(
                "static let appDir = Bundle.main.bundleURL",
                (workdir / "sources" / "Main.swift").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "traceRagImeProcessEvent",
                (workdir / "sources" / "Main.swift").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "static var inputSourceIDPrefix: String",
                (workdir / "sources" / "InputSource.swift").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "currentInputSourceID.hasPrefix(SquirrelInstaller.inputSourceIDPrefix)",
                (workdir / "sources" / "SquirrelApplicationDelegate.swift").read_text(encoding="utf-8"),
            )
            config = (workdir / "rag-ime.squirrel.custom.yaml").read_text(encoding="utf-8")
            self.assertIn("sidecar_url: http://127.0.0.1:19866/api", config)
            self.assertIn("project: offline-test", config)
            self.assertIn("frontend_trace: false", config)


if __name__ == "__main__":
    unittest.main()
