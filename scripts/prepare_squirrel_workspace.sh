#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQUIRREL_REPO_URL="${RAG_IME_SQUIRREL_REPO_URL:-https://github.com/rime/squirrel.git}"
SQUIRREL_BASE_REF="${RAG_IME_SQUIRREL_BASE_REF:-2158538}"
SQUIRREL_WORKDIR="${RAG_IME_SQUIRREL_WORKDIR:-/tmp/rag-ime-squirrel}"
PATCH_FILE="${RAG_IME_SQUIRREL_PATCH:-$ROOT/squirrel-patches/0001-add-rag-ime-sidecar.patch}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
RUNTIME_PROFILE="${RAG_IME_RUNTIME_PROFILE:-v1-proof}"
eval "$(PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_EXECUTABLE" -m rag_ime.runtime_profile --profile "$RUNTIME_PROFILE" --format shell)"
DB_PATH="${RAG_IME_DB_PATH:-$HOME/Library/Application Support/RagIme/rag-ime.sqlite}"
PROJECT="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
SIDECAR_HOST="${RAG_IME_SIDECAR_HOST:-127.0.0.1}"
SIDECAR_PORT="${RAG_IME_SIDECAR_PORT:-8766}"
MAX_VISIBLE_CANDIDATES="${RAG_IME_SQUIRREL_MAX_VISIBLE_CANDIDATES:-8}"
MAX_SIDE_CANDIDATES="${RAG_IME_SQUIRREL_MAX_SIDE_CANDIDATES:-5}"
LATENCY_BUDGET_MS="${RAG_IME_SQUIRREL_LATENCY_BUDGET_MS:-$RAG_IME_PROFILE_SQUIRREL_LATENCY_BUDGET_MS}"
DEBOUNCE_MS="${RAG_IME_SQUIRREL_DEBOUNCE_MS:-80}"
TIMEOUT_MS="${RAG_IME_SQUIRREL_TIMEOUT_MS:-$RAG_IME_PROFILE_SQUIRREL_TIMEOUT_MS}"
FRONTEND_TRACE="${RAG_IME_SQUIRREL_FRONTEND_TRACE:-true}"
RESET="${RAG_IME_SQUIRREL_RESET:-0}"
DRY_RUN="${RAG_IME_SQUIRREL_DRY_RUN:-0}"

if [[ ! -f "$PATCH_FILE" ]]; then
  echo "patch file not found: $PATCH_FILE" >&2
  exit 1
fi

if [[ "$DRY_RUN" == "1" || "$DRY_RUN" == "true" || "$DRY_RUN" == "TRUE" ]]; then
  cat <<EOF
repo_url=$SQUIRREL_REPO_URL
base_ref=$SQUIRREL_BASE_REF
runtime_profile=$RUNTIME_PROFILE
workdir=$SQUIRREL_WORKDIR
patch=$PATCH_FILE
sidecar_url=http://$SIDECAR_HOST:$SIDECAR_PORT/api
repo_root=$ROOT
db_path=$DB_PATH
python=$PYTHON_EXECUTABLE
project=$PROJECT
max_visible_candidates=$MAX_VISIBLE_CANDIDATES
max_side_candidates=$MAX_SIDE_CANDIDATES
latency_budget_ms=$LATENCY_BUDGET_MS
debounce_ms=$DEBOUNCE_MS
timeout_ms=$TIMEOUT_MS
frontend_trace=$FRONTEND_TRACE
EOF
  exit 0
fi

reset_squirrel_workdir() {
  if [[ -z "$SQUIRREL_WORKDIR" || "$SQUIRREL_WORKDIR" == "/" ]]; then
    echo "refusing to reset unsafe Squirrel workdir: $SQUIRREL_WORKDIR" >&2
    exit 1
  fi
  echo "Resetting Squirrel workdir because RAG_IME_SQUIRREL_RESET=1: $SQUIRREL_WORKDIR" >&2
  rm -rf "$SQUIRREL_WORKDIR"
}

if [[ -e "$SQUIRREL_WORKDIR" && ! -d "$SQUIRREL_WORKDIR/.git" ]]; then
  if [[ "$RESET" == "1" ]]; then
    reset_squirrel_workdir
  else
    echo "target exists but is not a git checkout: $SQUIRREL_WORKDIR" >&2
    exit 1
  fi
fi

if [[ -d "$SQUIRREL_WORKDIR/.git" ]] && ! git -C "$SQUIRREL_WORKDIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [[ "$RESET" == "1" ]]; then
    reset_squirrel_workdir
  else
    echo "target contains an invalid git checkout: $SQUIRREL_WORKDIR" >&2
    echo "Set RAG_IME_SQUIRREL_RESET=1 to recreate that Squirrel workdir." >&2
    exit 1
  fi
fi

if [[ ! -d "$SQUIRREL_WORKDIR/.git" ]]; then
  mkdir -p "$(dirname "$SQUIRREL_WORKDIR")"
  git clone "$SQUIRREL_REPO_URL" "$SQUIRREL_WORKDIR"
fi

if [[ -n "$(git -C "$SQUIRREL_WORKDIR" status --short)" && "$RESET" != "1" ]]; then
  echo "Squirrel workdir has local changes: $SQUIRREL_WORKDIR" >&2
  echo "Set RAG_IME_SQUIRREL_RESET=1 to discard changes in that Squirrel workdir." >&2
  exit 1
fi

git -C "$SQUIRREL_WORKDIR" fetch --tags --quiet origin || true
git -C "$SQUIRREL_WORKDIR" checkout "$SQUIRREL_BASE_REF" --quiet
git -C "$SQUIRREL_WORKDIR" reset --hard "$SQUIRREL_BASE_REF" --quiet
git -C "$SQUIRREL_WORKDIR" clean -fd --quiet
git -C "$SQUIRREL_WORKDIR" apply --recount --check "$PATCH_FILE"
git -C "$SQUIRREL_WORKDIR" apply --recount "$PATCH_FILE"

install_assistant_overlay_v2_sources() {
  local source_dir="$ROOT/squirrel-patches/sources"
  local project_file="$SQUIRREL_WORKDIR/Squirrel.xcodeproj/project.pbxproj"
  local files=(
    RagImeAssistantSurfaceState.swift
    RagImeSuggestionCardView.swift
    RagImeSuggestionRowView.swift
    RagImeNonActivatingPanel.swift
    RagImeAssistantPanelController.swift
  )
  for file in "${files[@]}"; do
    if [[ ! -f "$source_dir/$file" ]]; then
      echo "assistant overlay v2 source missing: $source_dir/$file" >&2
      exit 1
    fi
    cp "$source_dir/$file" "$SQUIRREL_WORKDIR/sources/$file"
  done

  if [[ ! -f "$project_file" ]]; then
    return 0
  fi
  "$PYTHON_EXECUTABLE" - "$project_file" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

def insert_after(needle: str, addition: str) -> None:
    global text
    if addition.strip() in text:
        return
    if needle not in text:
        raise SystemExit(f"Squirrel project did not contain expected Assistant Overlay marker: {needle.strip()}")
    text = text.replace(needle, needle + addition, 1)

insert_after(
    '\t\tB3A777082F330001009D156B /* RagImeAssistantPanelController.swift in Sources */ = {isa = PBXBuildFile; fileRef = B3A777072F330001009D156B /* RagImeAssistantPanelController.swift */; };\n',
    '\t\tB3A778022F330001009D156B /* RagImeAssistantSurfaceState.swift in Sources */ = {isa = PBXBuildFile; fileRef = B3A778012F330001009D156B /* RagImeAssistantSurfaceState.swift */; };\n'
    '\t\tB3A778042F330001009D156B /* RagImeSuggestionCardView.swift in Sources */ = {isa = PBXBuildFile; fileRef = B3A778032F330001009D156B /* RagImeSuggestionCardView.swift */; };\n'
    '\t\tB3A778062F330001009D156B /* RagImeSuggestionRowView.swift in Sources */ = {isa = PBXBuildFile; fileRef = B3A778052F330001009D156B /* RagImeSuggestionRowView.swift */; };\n'
    '\t\tB3A778082F330001009D156B /* RagImeNonActivatingPanel.swift in Sources */ = {isa = PBXBuildFile; fileRef = B3A778072F330001009D156B /* RagImeNonActivatingPanel.swift */; };\n',
)
insert_after(
    '\t\tB3A777072F330001009D156B /* RagImeAssistantPanelController.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; name = RagImeAssistantPanelController.swift; path = sources/RagImeAssistantPanelController.swift; sourceTree = "<group>"; };\n',
    '\t\tB3A778012F330001009D156B /* RagImeAssistantSurfaceState.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; name = RagImeAssistantSurfaceState.swift; path = sources/RagImeAssistantSurfaceState.swift; sourceTree = "<group>"; };\n'
    '\t\tB3A778032F330001009D156B /* RagImeSuggestionCardView.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; name = RagImeSuggestionCardView.swift; path = sources/RagImeSuggestionCardView.swift; sourceTree = "<group>"; };\n'
    '\t\tB3A778052F330001009D156B /* RagImeSuggestionRowView.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; name = RagImeSuggestionRowView.swift; path = sources/RagImeSuggestionRowView.swift; sourceTree = "<group>"; };\n'
    '\t\tB3A778072F330001009D156B /* RagImeNonActivatingPanel.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; name = RagImeNonActivatingPanel.swift; path = sources/RagImeNonActivatingPanel.swift; sourceTree = "<group>"; };\n',
)
insert_after(
    '\t\t\t\tB3A777072F330001009D156B /* RagImeAssistantPanelController.swift */,\n',
    '\t\t\t\tB3A778012F330001009D156B /* RagImeAssistantSurfaceState.swift */,\n'
    '\t\t\t\tB3A778032F330001009D156B /* RagImeSuggestionCardView.swift */,\n'
    '\t\t\t\tB3A778052F330001009D156B /* RagImeSuggestionRowView.swift */,\n'
    '\t\t\t\tB3A778072F330001009D156B /* RagImeNonActivatingPanel.swift */,\n',
)
insert_after(
    '\t\t\t\tB3A777082F330001009D156B /* RagImeAssistantPanelController.swift in Sources */,\n',
    '\t\t\t\tB3A778022F330001009D156B /* RagImeAssistantSurfaceState.swift in Sources */,\n'
    '\t\t\t\tB3A778042F330001009D156B /* RagImeSuggestionCardView.swift in Sources */,\n'
    '\t\t\t\tB3A778062F330001009D156B /* RagImeSuggestionRowView.swift in Sources */,\n'
    '\t\t\t\tB3A778082F330001009D156B /* RagImeNonActivatingPanel.swift in Sources */,\n',
)
path.write_text(text, encoding="utf-8")
PY
}

wire_assistant_overlay_v2_controller() {
  local controller_file="$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift"
  if ! grep -Fq "ragImeAssistantOverlayController.update(payload, anchor: currentRagImeInputAnchor())" "$controller_file"; then
    return 0
  fi
  "$PYTHON_EXECUTABLE" - "$controller_file" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

old_key = '''      if isRagImeDeleteKey(keyCode, modifiers: modifiers) {
'''
new_key = '''      if keyCode == 125
        && modifiers.contains(.option)
        && !modifiers.contains(.command)
        && !modifiers.contains(.control)
        && ragImeAssistantOverlayController.expandPredictions() {
        traceRagImeFrontendEvent("assistant_surface_state_changed", fields: [
          "surfaceState": "expandedPredictions",
          "reason": "option_down",
        ])
        return true
      }
      if isRagImeDeleteKey(keyCode, modifiers: modifiers) {
'''
if new_key not in text:
    if old_key not in text:
        raise SystemExit("SquirrelInputController.swift missing key route insertion marker")
    text = text.replace(old_key, new_key, 1)

old_update = '''    ragImeAssistantOverlayController.update(payload, anchor: currentRagImeInputAnchor()) { [weak self] candidate, index in
      _ = self?.commitRagImeAssistantCandidate(candidate, route: "click", index: index)
    }
'''
new_update = '''    ragImeAssistantOverlayController.update(
      payload,
      anchor: currentRagImeInputAnchor(),
      onSelect: { [weak self] candidate, index in
        _ = self?.commitRagImeAssistantCandidate(candidate, route: "click", index: index)
      },
      onAction: { [weak self] action in
        guard let self else { return }
        switch action {
        case .stop:
          self.ragImeActiveRagSelectedTextHash = ""
          self.dismissRagImeAssistantOverlay(reason: "explicit_generation_stopped")
        case .retry:
          self.dismissRagImeAssistantOverlay(reason: "explicit_generation_retry")
          _ = self.startRagImeActiveRagAssistFromShortcut()
        default:
          break
        }
      },
      onTrace: { [weak self] event, fields in
        self?.traceRagImeFrontendEvent(event, fields: fields)
      }
    )
'''
if new_update not in text:
    if old_update not in text:
        raise SystemExit("SquirrelInputController.swift missing Assistant Overlay update marker")
    text = text.replace(old_update, new_update, 1)

old_accept = '''    dismissRagImeAssistantOverlay(reason: "candidate_accepted")
    rimeUpdate(clearReservedComments: false, requestSidecar: false)
'''
new_accept = '''    ragImeAssistantOverlayController.showConfirmation()
    clearRagImeAssistantOverlayState()
    rimeUpdate(clearReservedComments: false, requestSidecar: false)
'''
if new_accept not in text:
    if old_accept not in text:
        raise SystemExit("SquirrelInputController.swift missing Assistant Overlay acceptance marker")
    text = text.replace(old_accept, new_accept, 1)

old_dismiss = '''  func dismissRagImeAssistantOverlay(reason: String) {
    ragImeAssistantOverlayController.dismiss(reason: reason)
    ragImeOverlayCandidates = []
'''
new_dismiss = '''  func dismissRagImeAssistantOverlay(reason: String) {
    ragImeAssistantOverlayController.dismiss(reason: reason)
    clearRagImeAssistantOverlayState()
    traceRagImeFrontendEvent("assistant_overlay_dismissed", fields: [
      "reason": reason,
    ])
  }

  func clearRagImeAssistantOverlayState() {
    ragImeOverlayCandidates = []
'''
if new_dismiss not in text:
    if old_dismiss not in text:
        raise SystemExit("SquirrelInputController.swift missing Assistant Overlay dismiss marker")
    text = text.replace(old_dismiss, new_dismiss, 1)
    old_tail = '''    ragImeOverlayExpiresAt = nil
    traceRagImeFrontendEvent("assistant_overlay_dismissed", fields: [
      "reason": reason,
    ])
  }

  func ragImeLocalDeepSeekActionCandidate'''
    new_tail = '''    ragImeOverlayExpiresAt = nil
  }

  func ragImeLocalDeepSeekActionCandidate'''
    if old_tail not in text:
        raise SystemExit("SquirrelInputController.swift missing Assistant Overlay dismiss tail")
    text = text.replace(old_tail, new_tail, 1)

path.write_text(text, encoding="utf-8")
PY
}

make_input_source_prefix_brandable() {
  local input_source_file="$SQUIRREL_WORKDIR/sources/InputSource.swift"
  local app_delegate_file="$SQUIRREL_WORKDIR/sources/SquirrelApplicationDelegate.swift"
  if [[ ! -f "$input_source_file" || ! -f "$app_delegate_file" ]]; then
    return 0
  fi

  "$PYTHON_EXECUTABLE" - "$input_source_file" "$app_delegate_file" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

input_source_path = Path(sys.argv[1])
app_delegate_path = Path(sys.argv[2])

input_source = input_source_path.read_text(encoding="utf-8")
old_input_mode = """  enum InputMode: String, CaseIterable {
    static let primary = Self.hans
    case hans = "im.rime.inputmethod.Squirrel.Hans"
    case hant = "im.rime.inputmethod.Squirrel.Hant"
  }
"""
new_input_mode = r"""  enum InputMode: CaseIterable {
    case hans
    case hant

    static let primary = Self.hans

    init?(rawValue: String) {
      switch rawValue {
      case Self.hans.rawValue:
        self = .hans
      case Self.hant.rawValue:
        self = .hant
      default:
        return nil
      }
    }

    var rawValue: String {
      switch self {
      case .hans:
        return "\(Self.inputSourceIDPrefix).Hans"
      case .hant:
        return "\(Self.inputSourceIDPrefix).Hant"
      }
    }

    private static var inputSourceIDPrefix: String {
      SquirrelInstaller.inputSourceIDPrefix
    }
  }

  static var inputSourceIDPrefix: String {
    if let id = Bundle.main.object(forInfoDictionaryKey: "TISInputSourceID") as? String, !id.isEmpty {
      return id
    }
    if let id = Bundle.main.bundleIdentifier, !id.isEmpty {
      return id
    }
    return "im.rime.inputmethod.Squirrel"
  }
"""
if old_input_mode not in input_source:
    if "static var inputSourceIDPrefix: String" not in input_source:
        raise SystemExit("InputSource.swift did not match the expected Squirrel input mode block")
else:
    input_source = input_source.replace(old_input_mode, new_input_mode)
    input_source_path.write_text(input_source, encoding="utf-8")

app_delegate = app_delegate_path.read_text(encoding="utf-8")
app_delegate = app_delegate.replace(
    'currentInputSourceID.hasPrefix("im.rime.inputmethod.Squirrel")',
    "currentInputSourceID.hasPrefix(SquirrelInstaller.inputSourceIDPrefix)",
)
app_delegate_path.write_text(app_delegate, encoding="utf-8")
PY
}

add_process_trace_hooks() {
  local main_file="$SQUIRREL_WORKDIR/sources/Main.swift"
  local controller_file="$SQUIRREL_WORKDIR/sources/SquirrelInputController.swift"
  if [[ ! -f "$main_file" ]]; then
    return 0
  fi

  "$PYTHON_EXECUTABLE" - "$main_file" "$controller_file" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

main_path = Path(sys.argv[1])
controller_path = Path(sys.argv[2])
main = main_path.read_text(encoding="utf-8")

trace_func = r'''  static func traceRagImeProcessEvent(_ event: String, fields: [String: Any] = [:]) {
    var payload = fields
    payload["event"] = event
    payload["schemaVersion"] = "rag-ime.squirrel-process-trace.v1"
    payload["timestampMs"] = Int(Date().timeIntervalSince1970 * 1000)
    payload["pid"] = ProcessInfo.processInfo.processIdentifier
    payload["arguments"] = CommandLine.arguments
    payload["bundlePath"] = Bundle.main.bundleURL.path
    payload["bundleIdentifier"] = Bundle.main.bundleIdentifier ?? ""
    payload["connectionName"] = Bundle.main.object(forInfoDictionaryKey: "InputMethodConnectionName") as? String ?? ""
    payload["inputSourceID"] = Bundle.main.object(forInfoDictionaryKey: "TISInputSourceID") as? String ?? ""

    guard JSONSerialization.isValidJSONObject(payload) else { return }
    do {
      let logDirectory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Logs/RagIme", isDirectory: true)
      try FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
      let logFile = logDirectory.appendingPathComponent("squirrel-process.jsonl")
      var data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
      data.append(0x0a)
      if !FileManager.default.fileExists(atPath: logFile.path) {
        FileManager.default.createFile(atPath: logFile.path, contents: nil)
      }
      let handle = try FileHandle(forWritingTo: logFile)
      defer { try? handle.close() }
      try handle.seekToEnd()
      handle.write(data)
    } catch {
      print("RAG IME process trace failed: \(error)")
    }
  }
'''

if "traceRagImeProcessEvent" not in main:
    needle = '  static let logDir = FileManager.default.temporaryDirectory.appending(component: "rime.squirrel", directoryHint: .isDirectory)\n'
    if needle not in main:
        raise SystemExit("Main.swift did not contain expected logDir line for RAG-IME process tracing")
    main = main.replace(needle, needle + "\n" + trace_func + "\n", 1)

replacements = [
    (
        '      let connectionName = main.object(forInfoDictionaryKey: "InputMethodConnectionName") as! String\n'
        '      _ = IMKServer(name: connectionName, bundleIdentifier: main.bundleIdentifier!)\n',
        '      let connectionName = main.object(forInfoDictionaryKey: "InputMethodConnectionName") as! String\n'
        '      traceRagImeProcessEvent("before_imk_server", fields: [\n'
        '        "connectionName": connectionName,\n'
        '        "bundleIdentifier": main.bundleIdentifier ?? "",\n'
        '      ])\n'
        '      _ = IMKServer(name: connectionName, bundleIdentifier: main.bundleIdentifier!)\n'
        '      traceRagImeProcessEvent("after_imk_server")\n',
    ),
    (
        '      app.run()\n'
        '      print("Squirrel is quitting...")\n',
        '      traceRagImeProcessEvent("before_app_run")\n'
        '      app.run()\n'
        '      print("Squirrel is quitting...")\n'
        '      traceRagImeProcessEvent("after_app_run")\n',
    ),
]
for old, new in replacements:
    if old in main and new not in main:
        main = main.replace(old, new, 1)
main_path.write_text(main, encoding="utf-8")

if controller_path.is_file():
    controller = controller_path.read_text(encoding="utf-8")
    controller = controller.replace(
        '    guard ragImeSidecarClient?.frontendTrace == true || event == "sidecar_not_configured" else { return }\n',
        '',
    )
    controller_path.write_text(controller, encoding="utf-8")
PY
}

install_assistant_overlay_v2_sources
wire_assistant_overlay_v2_controller
make_input_source_prefix_brandable
add_process_trace_hooks
git -C "$SQUIRREL_WORKDIR" diff --check

require_patch_file() {
  local path="$1"
  if [[ ! -f "$SQUIRREL_WORKDIR/$path" ]]; then
    echo "patched Squirrel workdir is missing required RAG-IME file: $path" >&2
    exit 1
  fi
}

require_patch_text() {
  local path="$1"
  local text="$2"
  local description="$3"
  if ! grep -Fq "$text" "$SQUIRREL_WORKDIR/$path"; then
    echo "patched Squirrel workdir is missing $description in $path" >&2
    exit 1
  fi
}

require_patch_file "sources/RagImeSidecarModels.swift"
require_patch_file "sources/RagImeSidecarClient.swift"
require_patch_file "sources/RagImeSelectedTextProvider.swift"
require_patch_file "sources/RagImeAssistantSurfaceState.swift"
require_patch_file "sources/RagImeSuggestionCardView.swift"
require_patch_file "sources/RagImeSuggestionRowView.swift"
require_patch_file "sources/RagImeNonActivatingPanel.swift"
require_patch_file "sources/RagImeAssistantPanelController.swift"
require_patch_file "sources/SquirrelInputController.swift"
require_patch_file "sources/SquirrelPanel.swift"
require_patch_text "sources/RagImeSidecarClient.swift" "rime-suggest" "sidecar suggestion request hook"
require_patch_text "sources/RagImeSidecarClient.swift" "rime-select" "side candidate selection writeback hook"
require_patch_text "sources/RagImeSidecarModels.swift" "displayLayout" "per-candidate display layout metadata"
require_patch_text "sources/SquirrelInputController.swift" "selectRagImeSideCandidate" "number-key side-candidate routing"
require_patch_text "sources/SquirrelInputController.swift" "ragImeRequestFingerprint" "stale response fingerprint guard"
require_patch_text "sources/SquirrelInputController.swift" "mergedRagImePanelCandidates" "Rime and side candidate display merge"
require_patch_text "sources/SquirrelInputController.swift" "ragImePanelForcesHorizontalLayout" "LLM horizontal-lane layout guard"
require_patch_text "sources/SquirrelInputController.swift" "ragImePanelUsesSideDisplay" "RAG-IME side-display panel marker"
require_patch_text "sources/SquirrelInputController.swift" "traceRagImeFrontendEvent" "foreground frontend trace hook"
require_patch_text "sources/SquirrelInputController.swift" "panel_text_layout" "actual frontend mixed-layout trace event"
require_patch_text "sources/SquirrelInputController.swift" "sidecar_request_scheduled" "real foreground sidecar request trace event"
require_patch_text "sources/SquirrelInputController.swift" "sidecar_empty_response_cleared" "empty sidecar response guard"
require_patch_text "sources/SquirrelInputController.swift" "rag-ime.foreground-trace.v2" "foreground trace v2 marker"
require_patch_text "sources/SquirrelInputController.swift" "let forceSideCandidates = rawInput.isEmpty && preedit.isEmpty" "foreground post-commit-only LLM/RAG candidate request"
require_patch_text "sources/SquirrelInputController.swift" "forceSideCandidates: forceSideCandidates" "foreground dynamic LLM/RAG candidate request"
require_patch_text "sources/SquirrelInputController.swift" "composition_ai_suppressed" "composition-phase AI overlay suppression"
require_patch_text "sources/SquirrelInputController.swift" "RAG_IME_ASSISTANT_OVERLAY_AUTO_PENDING" "post-commit assistant overlay opt-in guard"
require_patch_text "sources/SquirrelInputController.swift" "assistant_overlay_local_placeholder_suppressed" "post-commit local placeholder suppression"
require_patch_text "sources/SquirrelInputController.swift" "ragImeSelectedTextProvider.captureForegroundTextForSidecar" "focused text accessibility foreground snapshot request"
require_patch_text "sources/RagImeSelectedTextProvider.swift" "kAXSelectedTextRangeAttribute" "focused text selected range accessibility capture"
require_patch_text "sources/RagImeSelectedTextProvider.swift" "kAXStringForRangeParameterizedAttribute" "focused text surrounding range accessibility capture"
require_patch_text "sources/RagImeSelectedTextProvider.swift" "RagImeForegroundContextResolver" "delayed IMK to Accessibility foreground context resolver"
require_patch_text "sources/SquirrelInputController.swift" "foreground_context_capture_resolved" "foreground context capture success trace"
require_patch_text "sources/SquirrelInputController.swift" "foreground_context_capture_failed" "foreground context capture failure trace"
require_patch_text "sources/SquirrelInputController.swift" "side_candidate_feedback_recorded" "selection feedback receipt trace"
require_patch_text "sources/SquirrelInputController.swift" "assistant_overlay_candidate_visible" "assistant overlay candidate trace"
require_patch_text "sources/RagImeAssistantPanelController.swift" "same_snapshot_stable_ids" "assistant overlay snapshot diff"
require_patch_text "sources/RagImeAssistantPanelController.swift" "passive_anchor_missing" "passive missing-anchor suppression"
require_patch_text "sources/RagImeAssistantPanelController.swift" "assistant_panel_created" "assistant overlay lifecycle trace"
require_patch_text "sources/RagImeSelectedTextProvider.swift" "kAXValueAttribute" "focused text whole-value fallback"
require_patch_text "sources/SquirrelInputController.swift" "candidate.sourceType" "compact model inline candidate comments"
require_patch_text "sources/SquirrelPanel.swift" "candidateSeparator" "mixed inline/block candidate layout"
require_patch_text "sources/SquirrelPanel.swift" "ragImePanelLinear" "forced horizontal panel layout for LLM inline candidates"
require_patch_text "sources/SquirrelPanel.swift" "ragImePanelUsesSideDisplay" "RAG-IME side-display panel clamp"
require_patch_text "sources/SquirrelPanel.swift" "return NSView()" "plain non-glass macOS 26 panel background"
require_patch_text "sources/SquirrelPanel.swift" "traceRagImePanelTextLayout" "actual frontend mixed-layout trace"
require_patch_text "sources/Main.swift" "static let appDir = Bundle.main.bundleURL" "dynamic input-source registration bundle path"
require_patch_text "sources/Main.swift" "traceRagImeProcessEvent" "foreground process trace hook"
if [[ -f "$SQUIRREL_WORKDIR/sources/InputSource.swift" ]]; then
  require_patch_text "sources/InputSource.swift" "static var inputSourceIDPrefix: String" "brandable input-source prefix"
fi

CONFIG_PATH="$SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml"
ROOT="$ROOT" \
DB_PATH="$DB_PATH" \
PYTHON_EXECUTABLE="$PYTHON_EXECUTABLE" \
PROJECT="$PROJECT" \
SIDECAR_HOST="$SIDECAR_HOST" \
SIDECAR_PORT="$SIDECAR_PORT" \
CONFIG_PATH="$CONFIG_PATH" \
MAX_VISIBLE_CANDIDATES="$MAX_VISIBLE_CANDIDATES" \
MAX_SIDE_CANDIDATES="$MAX_SIDE_CANDIDATES" \
LATENCY_BUDGET_MS="$LATENCY_BUDGET_MS" \
DEBOUNCE_MS="$DEBOUNCE_MS" \
TIMEOUT_MS="$TIMEOUT_MS" \
FRONTEND_TRACE="$FRONTEND_TRACE" \
"$PYTHON_EXECUTABLE" - <<'PY'
import os
from pathlib import Path

payload = f"""# Copy this rag_ime block into squirrel.yaml while testing RAG-IME.
rag_ime:
  enabled: true
  sidecar_url: http://{os.environ["SIDECAR_HOST"]}:{os.environ["SIDECAR_PORT"]}/api
  python: {os.environ["PYTHON_EXECUTABLE"]}
  repo_root: {os.environ["ROOT"]}
  db_path: {os.environ["DB_PATH"]}
  project: {os.environ["PROJECT"]}
  max_visible_candidates: {os.environ["MAX_VISIBLE_CANDIDATES"]}
  max_side_candidates: {os.environ["MAX_SIDE_CANDIDATES"]}
  latency_budget_ms: {os.environ["LATENCY_BUDGET_MS"]}
  debounce_ms: {os.environ["DEBOUNCE_MS"]}
  timeout_ms: {os.environ["TIMEOUT_MS"]}
  frontend_trace: {os.environ["FRONTEND_TRACE"]}
"""
Path(os.environ["CONFIG_PATH"]).write_text(payload, encoding="utf-8")
PY

if command -v swiftc >/dev/null 2>&1; then
  tmpdir="$(mktemp -d /tmp/rag-ime-squirrel-stub.XXXXXX)"
  stubfile="$tmpdir/SquirrelConfigStub.swift"
  module_cache="$tmpdir/module-cache"
  mkdir -p "$module_cache"
  printf 'import Foundation\nfinal class SquirrelConfig {\n  func getBool(_ option: String) -> Bool? { nil }\n  func getString(_ option: String) -> String? { nil }\n  func getDouble(_ option: String) -> Double? { nil }\n}\n' > "$stubfile"
  swiftc -typecheck \
    -module-cache-path "$module_cache" \
    "$SQUIRREL_WORKDIR/sources/RagImeSidecarModels.swift" \
    "$SQUIRREL_WORKDIR/sources/RagImeSidecarClient.swift" \
    "$stubfile"
  if grep -Fq "struct RagImeAssistantOverlayPayload" "$SQUIRREL_WORKDIR/sources/RagImeSidecarModels.swift"; then
    swiftc -typecheck \
      -module-cache-path "$module_cache" \
      "$SQUIRREL_WORKDIR/sources/RagImeSidecarModels.swift" \
      "$SQUIRREL_WORKDIR/sources/RagImeAssistantSurfaceState.swift" \
      "$SQUIRREL_WORKDIR/sources/RagImeNonActivatingPanel.swift" \
      "$SQUIRREL_WORKDIR/sources/RagImeSuggestionRowView.swift" \
      "$SQUIRREL_WORKDIR/sources/RagImeSuggestionCardView.swift" \
      "$SQUIRREL_WORKDIR/sources/RagImeAssistantPanelController.swift"
  fi
  rm -rf "$tmpdir"
fi

cat <<EOF
Prepared patched Squirrel workdir:
$SQUIRREL_WORKDIR

Generated config snippet:
$CONFIG_PATH

Start sidecar:
cd "$ROOT" && scripts/install_sidecar_launch_agent.sh

Then copy the rag_ime block into Squirrel's squirrel.yaml and build Squirrel with Xcode.
EOF
