#!/usr/bin/env python3
"""Compile and render the real RAG-IME AppKit assistant card.

The patched Squirrel source is intentionally not built or installed here.  The
driver extracts the model source from the checked-in patch, compiles the real
card/panel sources in a temporary directory, and writes offscreen PNGs plus a
small JSON evidence report.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch"
SOURCE_DIR = ROOT / "squirrel-patches" / "sources"
SOURCE_NAMES = (
    "RagImeAssistantSurfaceState.swift",
    "RagImeNonActivatingPanel.swift",
    "RagImeSuggestionRowView.swift",
    "RagImeSuggestionCardView.swift",
    "RagImeAssistantPanelController.swift",
)


def extract_added_file(patch: Path, relative_path: str) -> str:
    """Extract one /dev/null -> added file from a unified diff."""

    needle = f"diff --git a/{relative_path} b/{relative_path}"
    lines = patch.read_text(encoding="utf-8").splitlines(keepends=True)
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip("\n") == needle)
    except StopIteration as exc:
        raise RuntimeError(f"missing added file in patch: {relative_path}") from exc
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("diff --git "):
            break
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            body.append(line[1:])
    if not body:
        raise RuntimeError(f"empty added file in patch: {relative_path}")
    return "".join(body)


def swift_driver() -> str:
    """Return the small executable that owns AppKit and PNG rendering."""

    return f'''import AppKit
import Foundation

@main
struct RagImeAssistantPreviewMain {{
  struct Scenario {{
    let name: String
    let state: RagImeAssistantSurfaceState
    let payload: RagImeAssistantOverlayPayload
    let width: CGFloat
    let height: CGFloat
    let clickDetails: Bool
  }}

  static func main() {{
    do {{
      let outputURL = try argumentURL(named: "--output-dir")
      try FileManager.default.createDirectory(at: outputURL, withIntermediateDirectories: true)
      let app = NSApplication.shared
      app.setActivationPolicy(.accessory)
      app.finishLaunching()
      let scenarios = try makeScenarios()
      var reports: [[String: Any]] = []
      for appearance in [NSAppearance.Name.aqua, NSAppearance.Name.darkAqua] {{
        for scenario in scenarios {{
          let result = try render(
            scenario: scenario,
            appearanceName: appearance,
            outputURL: outputURL
          )
          reports.append(result)
        }}
      }}
      let reportURL = outputURL.appendingPathComponent("preview-report.json")
      let reportData = try JSONSerialization.data(
        withJSONObject: reports.map {{ jsonSafe($0) }},
        options: [.prettyPrinted, .sortedKeys]
      )
      try reportData.write(to: reportURL, options: .atomic)
      print("RAG_IME_PREVIEW_REPORT=\\(reportURL.path)")
    }} catch {{
      fputs("preview_assistant_generation: \\(error)\\n", stderr)
      exit(1)
    }}
  }}

  static func argumentURL(named name: String) throws -> URL {{
    guard let index = CommandLine.arguments.firstIndex(of: name), index + 1 < CommandLine.arguments.count else {{
      throw PreviewError("missing \\(name) argument")
    }}
    let path = CommandLine.arguments[index + 1]
    guard path.hasPrefix("/") else {{ throw PreviewError("--output-dir must be absolute") }}
    return URL(fileURLWithPath: path, isDirectory: true)
  }}

  static func makeScenarios() throws -> [Scenario] {{
    [
      Scenario(
        name: "generating-collapsed",
        state: .explicitGenerating,
        payload: try decodeFixture(generatingFixture),
        width: RagImeSuggestionCardView.thinkingWidth,
        height: RagImeSuggestionCardView.thinkingHeight,
        clickDetails: false
      ),
      Scenario(
        name: "generating-expanded",
        state: .explicitGenerating,
        payload: try decodeFixture(generatingFixture),
        width: RagImeSuggestionCardView.thinkingWidth,
        height: RagImeSuggestionCardView.thinkingHeight,
        clickDetails: true
      ),
      Scenario(
        name: "slow",
        state: .explicitGenerating,
        payload: try decodeFixture(slowFixture),
        width: 280,
        height: RagImeSuggestionCardView.thinkingHeight,
        clickDetails: false
      ),
      Scenario(
        name: "empty-retrieval",
        state: .explicitGenerating,
        payload: try decodeFixture(emptyRetrievalFixture),
        width: 320,
        height: RagImeSuggestionCardView.thinkingHeight,
        clickDetails: false
      ),
      Scenario(
        name: "stream",
        state: .explicitResult,
        payload: try decodeFixture(streamFixture),
        width: 380,
        height: 220,
        clickDetails: false
      ),
      Scenario(
        name: "recovered",
        state: .explicitResult,
        payload: try decodeFixture(recoveredFixture),
        width: 380,
        height: 220,
        clickDetails: false
      ),
      Scenario(
        name: "pending-recovered",
        state: .explicitResult,
        payload: try decodeFixture(pendingRecoveredFixture),
        width: 320,
        height: 220,
        clickDetails: false
      ),
      Scenario(
        name: "error",
        state: .explicitError,
        payload: try decodeFixture(errorFixture),
        width: 320,
        height: RagImeSuggestionCardView.errorHeight,
        clickDetails: false
      ),
    ]
  }}

  static func decodeFixture(_ value: String) throws -> RagImeAssistantOverlayPayload {{
    guard let data = value.data(using: .utf8) else {{ throw PreviewError("fixture is not UTF-8") }}
    return try JSONDecoder().decode(RagImeAssistantOverlayPayload.self, from: data)
  }}

  static func render(
    scenario: Scenario,
    appearanceName: NSAppearance.Name,
    outputURL: URL
  ) throws -> [String: Any] {{
    let appearance = NSAppearance(named: appearanceName)!
    let cardSize = NSSize(width: scenario.width, height: scenario.height)
    let panel = RagImeNonActivatingPanel(
      contentRect: NSRect(origin: .zero, size: cardSize),
      styleMask: [.borderless, .nonactivatingPanel],
      backing: .buffered,
      defer: false
    )
    panel.isReleasedWhenClosed = false
    panel.isFloatingPanel = true
    panel.backgroundColor = .clear
    panel.isOpaque = false
    panel.hasShadow = false
    panel.appearance = appearance

    let card = RagImeSuggestionCardView(frame: NSRect(origin: .zero, size: cardSize))
    card.appearance = appearance
    panel.contentView = card
    card.frame = NSRect(origin: .zero, size: cardSize)
    panel.setContentSize(cardSize)
    let keyWindowBefore = NSApp.keyWindow?.windowNumber ?? 0
    let mainWindowBefore = NSApp.mainWindow?.windowNumber ?? 0
    var layoutCallbackCount = 0
    card.onLayoutChange = {{
      layoutCallbackCount += 1
      let resized = NSSize(width: card.bounds.width, height: card.generationHeight)
      panel.setContentSize(resized)
      card.frame = NSRect(origin: .zero, size: resized)
      card.needsLayout = true
      card.layoutSubtreeIfNeeded()
    }}
    var actionEvents: [String] = []
    card.onAction = {{ action in
      actionEvents.append(String(describing: action))
    }}
    _ = card.apply(state: scenario.state, payload: scenario.payload, animationsEnabled: false)
    card.needsLayout = true
    card.layoutSubtreeIfNeeded()
    panel.contentView?.layoutSubtreeIfNeeded()
    let directDetailsBefore: Bool = card.generationDetailsExpanded
    let directGenerationHeightBefore: CGFloat = card.generationHeight
    let detailsButton = findButton(in: card, identifier: "ragIme.assistant.generationDetails")
    let detailsButtonBefore = detailsButtonSnapshot(detailsButton)
    var detailsClicked = false
    var expandedImageName = "\\(scenario.name)-\\(appearanceToken(appearanceName))"
    if scenario.clickDetails, let detailsButton, !detailsButton.isHidden, detailsButton.isEnabled {{
      detailsClicked = true
      detailsButton.performClick(nil)
      drainRunLoop()
      card.needsLayout = true
      card.layoutSubtreeIfNeeded()
      panel.contentView?.layoutSubtreeIfNeeded()
      expandedImageName += "-details-expanded"
    }}
    let directDetailsAfter: Bool = card.generationDetailsExpanded
    let directGenerationHeightAfter: CGFloat = card.generationHeight
    let detailsButtonAfter = detailsButtonSnapshot(detailsButton)
    let generationDetailsBeforeValue: Any = directDetailsBefore
    let generationDetailsAfterValue: Any = directDetailsAfter
    let generationHeightBeforeValue: Any = Double(directGenerationHeightBefore)
    let generationHeightAfterValue: Any = Double(directGenerationHeightAfter)
    let pngURL = outputURL.appendingPathComponent(expandedImageName + ".png")
    try writePNG(card, to: pngURL)
    let keyWindowAfter = NSApp.keyWindow?.windowNumber ?? 0
    let mainWindowAfter = NSApp.mainWindow?.windowNumber ?? 0
    let stopButtons = allButtons(in: card).filter {{ button in
      let title = button.title
      let toolTip = button.toolTip ?? ""
      let accessibilityLabel = button.accessibilityLabel() ?? ""
      let text = (title + " " + toolTip + " " + accessibilityLabel).lowercased()
      return text.contains("停止") || text.contains("stop")
    }}
    let stopButton = stopButtons.first {{ $0.title == "停止" }}
    let insertButtonVisible = allButtons(in: card).contains {{ $0.title == "插入" && !$0.isHidden }}
    let replaceButtonVisible = allButtons(in: card).contains {{ $0.title == "替换" && !$0.isHidden }}
    let stopButtonVisible = stopButton?.isHidden == false
    if ["generating-collapsed", "generating-expanded", "slow", "empty-retrieval", "stream", "pending-recovered"].contains(scenario.name) {{
      guard let stopButton else {{ throw PreviewError("streaming stop control missing") }}
      try assertVisibleControl(stopButton, in: card, name: "stop")
      guard !stopButton.isHidden, stopButton.isEnabled, stopButton.title == "停止" else {{
        throw PreviewError("streaming stop control is not visibly titled 停止")
      }}
      stopButton.performClick(nil)
      drainRunLoop()
      guard actionEvents.contains("stop") else {{ throw PreviewError("stop button did not dispatch .stop") }}
    }}
    if ["stream", "pending-recovered"].contains(scenario.name) {{
      guard stopButtonVisible, !insertButtonVisible else {{
        throw PreviewError("streaming result exposed insert while generation is pending")
      }}
    }}
    if scenario.name == "recovered" {{
      guard !stopButtonVisible, insertButtonVisible else {{
        throw PreviewError("recovered result did not expose insert without a pending worker")
      }}
    }}
    if scenario.name == "generating-expanded" {{
      guard directDetailsBefore == false,
        directDetailsAfter == true,
        abs(directGenerationHeightBefore - RagImeSuggestionCardView.thinkingHeight) < 0.5,
        abs(directGenerationHeightAfter - RagImeSuggestionCardView.expandedThinkingHeight) < 0.5,
        layoutCallbackCount > 0,
        abs(card.bounds.height - directGenerationHeightAfter) < 0.5 else {{
        throw PreviewError("generation disclosure did not resize through onLayoutChange")
      }}
    }}
    try assertVisibleControlsFit(in: card)
    let animationKeys = layerAnimationKeys(in: card)
    guard animationKeys.isEmpty else {{
      throw PreviewError("animations leaked with animationsEnabled=false: \\(animationKeys)")
    }}
    let report: [String: Any] = [
      "scenario": scenario.name,
      "appearance": appearanceToken(appearanceName),
      "state": card.surfaceState.rawValue,
      "png": pngURL.path,
      "cardBounds": rectDictionary(card.bounds),
      "panelClass": String(describing: type(of: panel)),
      "panelStyleMask": panel.styleMask.rawValue,
      "panelCanBecomeKey": panel.canBecomeKey,
      "panelCanBecomeMain": panel.canBecomeMain,
      "keyWindowBefore": keyWindowBefore,
      "keyWindowAfter": keyWindowAfter,
      "mainWindowBefore": mainWindowBefore,
      "mainWindowAfter": mainWindowAfter,
      "focusUnchanged": keyWindowBefore == keyWindowAfter && mainWindowBefore == mainWindowAfter,
      "layoutCallbackCount": layoutCallbackCount,
      "detailsContractCompiled": true,
      "generationDetailsExpandedBefore": generationDetailsBeforeValue,
      "generationDetailsExpandedAfter": generationDetailsAfterValue,
      "generationHeightBefore": generationHeightBeforeValue,
      "generationHeightAfter": generationHeightAfterValue,
      "detailsButtonFound": detailsButton != nil,
      "detailsClicked": detailsClicked,
      "detailsButtonBefore": detailsButtonBefore,
      "detailsButtonAfter": detailsButtonAfter,
      "stopButtons": stopButtons.map(buttonSnapshot),
      "stopActionTriggered": actionEvents.contains("stop"),
      "stopButtonVisible": stopButtonVisible,
      "insertButtonVisible": insertButtonVisible,
      "replaceButtonVisible": replaceButtonVisible,
      "animationKeys": animationKeys,
      "visibleTextLabels": visibleTextLabels(in: card),
    ]
    print("RAG_IME_PREVIEW=\\(jsonLine(report))")
    panel.orderOut(nil)
    return report
  }}

  static func appearanceToken(_ appearance: NSAppearance.Name) -> String {{
    appearance == .darkAqua ? "dark" : "light"
  }}

  static func drainRunLoop() {{
    let deadline = Date().addingTimeInterval(0.03)
    while Date() < deadline {{
      RunLoop.main.run(mode: .default, before: Date().addingTimeInterval(0.005))
    }}
  }}

  static func writePNG(_ view: NSView, to url: URL) throws {{
    let scale: CGFloat = 2
    let bounds = view.bounds
    guard let rep = NSBitmapImageRep(
      bitmapDataPlanes: nil,
      pixelsWide: max(1, Int(ceil(bounds.width * scale))),
      pixelsHigh: max(1, Int(ceil(bounds.height * scale))),
      bitsPerSample: 8,
      samplesPerPixel: 4,
      hasAlpha: true,
      isPlanar: false,
      colorSpaceName: .deviceRGB,
      bitmapFormat: [],
      bytesPerRow: 0,
      bitsPerPixel: 0
    ) else {{ throw PreviewError("cannot allocate bitmap") }}
    rep.size = bounds.size
    view.cacheDisplay(in: bounds, to: rep)
    guard let data = rep.representation(using: .png, properties: [:]) else {{
      throw PreviewError("cannot encode PNG")
    }}
    try data.write(to: url, options: .atomic)
  }}

  static func findButton(in view: NSView, identifier: String) -> NSButton? {{
    if let button = view as? NSButton, button.identifier?.rawValue == identifier {{ return button }}
    for child in view.subviews {{
      if let button = findButton(in: child, identifier: identifier) {{ return button }}
    }}
    return nil
  }}

  static func allButtons(in view: NSView) -> [NSButton] {{
    var result: [NSButton] = []
    if let button = view as? NSButton {{ result.append(button) }}
    for child in view.subviews {{ result.append(contentsOf: allButtons(in: child)) }}
    return result
  }}

  static func buttonSnapshot(_ button: NSButton) -> [String: Any] {{
    [
      "title": button.title,
      "toolTip": button.toolTip ?? "",
      "accessibilityLabel": button.accessibilityLabel() ?? "",
      "identifier": button.identifier?.rawValue ?? "",
      "hidden": button.isHidden,
      "enabled": button.isEnabled,
      "frame": rectDictionary(button.frame),
    ]
  }}

  static func detailsButtonSnapshot(_ button: NSButton?) -> [String: Any] {{
    guard let button else {{ return ["found": false] }}
    var value = buttonSnapshot(button)
    value["found"] = true
    return value
  }}

  static func visibleTextLabels(in view: NSView) -> [String] {{
    var result: [String] = []
    if let label = view as? NSTextField, !label.isHidden, !label.stringValue.isEmpty {{
      result.append(label.stringValue)
    }}
    for child in view.subviews {{ result.append(contentsOf: visibleTextLabels(in: child)) }}
    return result
  }}

  static func assertVisibleControl(_ control: NSView, in root: NSView, name: String) throws {{
    guard !control.isHidden else {{ throw PreviewError("\\(name) is hidden") }}
    let frame = control.convert(control.bounds, to: root)
    let tolerance: CGFloat = 0.5
    guard root.bounds.insetBy(dx: -tolerance, dy: -tolerance).contains(frame) else {{
      throw PreviewError("\\(name) is clipped: \\(rectDictionary(frame)) outside \\(rectDictionary(root.bounds))")
    }}
  }}

  static func assertVisibleControlsFit(in root: NSView) throws {{
    func walk(_ view: NSView, hiddenByAncestor: Bool) throws {{
      let hidden = hiddenByAncestor || view.isHidden
      if !hidden, view is NSButton || view is NSTextField || view is NSScrollView {{
        try assertVisibleControl(view, in: root, name: String(describing: type(of: view)))
      }}
      for child in view.subviews {{ try walk(child, hiddenByAncestor: hidden) }}
    }}
    try walk(root, hiddenByAncestor: false)
  }}

  static func layerAnimationKeys(in view: NSView) -> [String] {{
    var result: [String] = view.layer?.animationKeys() ?? []
    for child in view.subviews {{ result.append(contentsOf: layerAnimationKeys(in: child)) }}
    return result
  }}

  static func rectDictionary(_ rect: NSRect) -> [String: Double] {{
    ["x": Double(rect.origin.x), "y": Double(rect.origin.y), "width": Double(rect.width), "height": Double(rect.height)]
  }}

  static func jsonLine(_ value: [String: Any]) -> String {{
    guard let data = try? JSONSerialization.data(withJSONObject: jsonSafe(value), options: [.sortedKeys]),
      let text = String(data: data, encoding: .utf8) else {{ return "{{}}" }}
    return text
  }}

  static func jsonSafe(_ value: Any) -> Any {{
    if value is NSNull {{ return NSNull() }}
    if let value = value as? String {{ return value }}
    if let value = value as? Bool {{ return value }}
    if let value = value as? Int {{ return value }}
    if let value = value as? Double {{ return value }}
    if let value = value as? CGFloat {{ return Double(value) }}
    if let value = value as? UInt {{ return Int(value) }}
    if let value = value as? [String: Any] {{
      return value.mapValues {{ jsonSafe($0) }}
    }}
    if let value = value as? [Any] {{ return value.map {{ jsonSafe($0) }} }}
    return String(describing: value)
  }}

  static let generatingFixture = """
  {{
    "schemaVersion": "rag-ime.assistant-overlay.v1",
    "visible": true,
    "uiMode": "active_rag",
    "phase": "active_rag",
    "inputMode": "explicit",
    "statusText": "正在生成",
    "animation": {{"kind": "progress", "frame": 0}},
    "candidates": [],
    "sourceCards": [],
    "snapshotId": "preview-streaming",
    "sessionFingerprint": "preview-session",
    "expiresAfterMs": 12000,
    "progressive": {{"enabled":true,"partial":true,"shouldFollowUp":true,"pendingLanes":["model"],"firstResponseBudgetMs":900,"retryAfterMs":160}},
    "frontendTransaction": {{"diagnosticStatus":"generating","progressStage":"capturing_context","progressElapsedMs":0,"foregroundContextChars":128,"windowContextNodes":3,"contextView":{{"schemaVersion":"rag-ime.context.v1","currentRequest":"写一段项目说明","currentContext":"输入法助手正在读取当前窗口上下文","selectedText":"","windowContext":{{"sourceNodeCount":3}},"groundingEvidence":[]}},"evidenceCount":0,"retrievalAttempted":false,"remoteModelReady":true}},
    "dismissReason": ""
  }}
  """

  static let slowFixture = generatingFixture
    .replacingOccurrences(of: "\\\"progressStage\\\":\\\"capturing_context\\\"", with: "\\\"progressStage\\\":\\\"generating\\\"")
    .replacingOccurrences(of: "\\\"progressElapsedMs\\\":0", with: "\\\"progressElapsedMs\\\":17000")
    .replacingOccurrences(of: "\\\"evidenceCount\\\":0", with: "\\\"evidenceCount\\\":3")
    .replacingOccurrences(of: "\\\"retrievalAttempted\\\":false", with: "\\\"retrievalAttempted\\\":true")
    .replacingOccurrences(of: "\\\"remoteModelReady\\\":true", with: "\\\"remoteModelReady\\\":true,\\\"timelineRecentInputUsedForGeneration\\\":true,\\\"timelineRecentInputRecordCount\\\":2,\\\"timelineRecentInputChars\\\":96")

  static let emptyRetrievalFixture = generatingFixture
    .replacingOccurrences(of: "\\\"progressStage\\\":\\\"capturing_context\\\"", with: "\\\"progressStage\\\":\\\"retrieval_complete\\\"")
    .replacingOccurrences(of: "\\\"retrievalAttempted\\\":false", with: "\\\"retrievalAttempted\\\":true")

  static let streamFixture = recoveredFixture
    .replacingOccurrences(of: "preview-recovered", with: "preview-stream")
    .replacingOccurrences(of: "已恢复片段", with: "正在接收")
    .replacingOccurrences(of: "这是一次被中断后保留的完整片段。\\\\n\\\\n当前结果仍然可以插入。", with: "这是流式传入的内容。")
    .replacingOccurrences(of: "\\\"streamInterrupted\\\":true,\\\"partialRecovered\\\":true", with: "\\\"streamingPartial\\\":true")

  static let errorFixture = """
  {{
    "schemaVersion": "rag-ime.assistant-overlay.v1",
    "visible": true,
    "uiMode": "active_rag",
    "phase": "active_rag",
    "inputMode": "explicit",
    "statusText": "暂未完成，可以重试",
    "animation": {{"kind": "none", "frame": 0}},
    "candidates": [],
    "sourceCards": [],
    "snapshotId": "preview-error",
    "sessionFingerprint": "preview-session",
    "expiresAfterMs": 6000,
    "frontendTransaction": {{"diagnosticStatus":"provider_unavailable","contextView":{{"schemaVersion":"rag-ime.context.v1","currentRequest":"请继续","currentContext":"","selectedText":"","windowContext":{{"sourceNodeCount":0}},"groundingEvidence":[]}},"retrievalAttempted":true,"remoteModelReady":false}},
    "dismissReason": "provider_unavailable"
  }}
  """

  static let recoveredFixture = """
  {{
    "schemaVersion": "rag-ime.assistant-overlay.v1",
    "visible": true,
    "uiMode": "active_rag",
    "phase": "active_rag",
    "inputMode": "explicit",
    "statusText": "",
    "animation": {{"kind": "none", "frame": 0}},
    "candidates": [
      {{"label":"1","visibleLabel":"已恢复片段","selectionKey":"1","selectionRank":1,"candidateOrdinal":0,"candidateStableId":"recovered-1","snapshotId":"preview-recovered","snapshotGeneration":1,"text":"这是一次被中断后保留的完整片段。\\\\n\\\\n当前结果仍然可以插入。","insertText":"这是一次被中断后保留的完整片段。\\\\n\\\\n当前结果仍然可以插入。","sourceType":"model","selectionAction":"insert","sourceIndex":0,"comment":"","badge":"已恢复","sourceBadge":"模型","colorToken":"orange","sourceStability":"stable","hardContextAnchor":"","queryAnchor":"","displayAnchor":"","expiresAtMs":null,"minVisibleUntilMs":null,"evidencePreview":"已保留已生成内容","suggestionId":"recovered-1","memoryId":"","sourceEventId":null,"rimeIndex":null,"displayLayout":"result","displayLane":"model","group":"model","groupLabel":"模型","isSelectable":true,"isStatus":false,"metadata":{{"streamInterrupted":true,"partialRecovered":true}}}}
    ],
    "sourceCards": [],
    "snapshotId": "preview-recovered",
    "sessionFingerprint": "preview-session",
    "expiresAfterMs": 10000,
    "dismissReason": ""
  }}
  """

  static let pendingRecoveredFixture = recoveredFixture
    .replacingOccurrences(of: "\\\"expiresAfterMs\\\": 10000,", with: "\\\"expiresAfterMs\\\": 10000,\\\"frontendTransaction\\\":{{\\\"workerPending\\\":true}},")
}}

struct PreviewError: Error, CustomStringConvertible {{
  let message: String
  init(_ message: String) {{ self.message = message }}
  var description: String {{ message }}
}}
'''


def run(args: argparse.Namespace) -> int:
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        raise RuntimeError("swiftc is required on macOS")
    if sys.platform != "darwin":
        raise RuntimeError("this AppKit harness must run on macOS")
    for source_name in SOURCE_NAMES:
        source_path = SOURCE_DIR / source_name
        if not source_path.is_file():
            raise RuntimeError(f"missing source: {source_path}")

    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        raise RuntimeError("--output-dir must be an absolute path")
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="rag-ime-native-preview-") as temporary:
        build_dir = Path(temporary)
        model_path = build_dir / "RagImeSidecarModels.swift"
        model_path.write_text(extract_added_file(PATCH_PATH, "sources/RagImeSidecarModels.swift"), encoding="utf-8")
        driver_path = build_dir / "PreviewMain.swift"
        driver_path.write_text(
            swift_driver(),
            encoding="utf-8",
        )
        binary_path = build_dir / "rag-ime-native-preview"
        compile_command = [
            swiftc,
            "-swift-version",
            "5",
            "-module-name",
            "RagImeNativePreview",
            "-parse-as-library",
            "-o",
            str(binary_path),
            str(model_path),
            *(str(SOURCE_DIR / name) for name in SOURCE_NAMES),
            str(driver_path),
        ]
        if args.typecheck_only:
            compile_command[compile_command.index("-o") : compile_command.index("-o") + 2] = ["-typecheck"]
        compile = subprocess.run(compile_command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        if compile.returncode != 0:
            sys.stderr.write(compile.stdout)
            sys.stderr.write(compile.stderr)
            return compile.returncode
        if args.typecheck_only:
            print("swiftc typecheck passed")
            return 0

        environment = os.environ.copy()
        environment.setdefault("NSUnbufferedIO", "YES")
        execution = subprocess.run(
            [str(binary_path), "--output-dir", str(output_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=environment,
            timeout=30,
        )
        sys.stdout.write(execution.stdout)
        sys.stderr.write(execution.stderr)
        if execution.returncode != 0:
            return execution.returncode
        report_path = output_dir / "preview-report.json"
        if not report_path.is_file():
            raise RuntimeError(f"preview binary did not write {report_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print(f"rendered {len(report)} PNGs to {output_dir}")
        for item in report:
            print(
                f"{item['appearance']}/{item['scenario']}: "
                f"state={item['state']} bounds={item['cardBounds']['width']}x{item['cardBounds']['height']} "
                f"detailsFound={item['detailsButtonFound']} clicked={item['detailsClicked']} "
                f"focusUnchanged={item['focusUnchanged']}"
            )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="absolute directory for PNGs and preview-report.json")
    parser.add_argument("--typecheck-only", action="store_true", help="compile contracts without rendering")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
