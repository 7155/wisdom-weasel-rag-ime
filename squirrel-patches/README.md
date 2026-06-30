# Squirrel Patch Pack

This directory contains patch files for testing RAG-IME inside upstream Squirrel without vendoring the full Squirrel source tree into this product repo.

## Base

- Upstream repo: `https://github.com/rime/squirrel`
- Verified base commit: `2158538`
- Patch: `0001-add-rag-ime-sidecar.patch`

The patch is intentionally small and frontend-only:

- keeps librime responsible for raw pinyin parsing, composition, paging, and normal candidate selection;
- adds a fail-closed Python sidecar client;
- adds a display-list merge after Squirrel has already read Rime candidates;
- routes selection by display metadata, so Rime candidates still call `select_candidate_on_current_page` and side candidates insert `insertText` directly;
- drops stale sidecar responses by request sequence and current raw input.

## Apply

```bash
git clone https://github.com/rime/squirrel /tmp/squirrel-rag-ime
cd /tmp/squirrel-rag-ime
git checkout 2158538
git apply /Volumes/undo\ 4t/git/learnA/wisdom-weasel-rag-ime/squirrel-patches/0001-add-rag-ime-sidecar.patch
git diff --check
```

## Configure

Add this to Squirrel's `squirrel.yaml` while testing:

```yaml
rag_ime:
  enabled: true
  python: /usr/bin/python3
  repo_root: /Volumes/undo 4t/git/learnA/wisdom-weasel-rag-ime
  db_path: /Volumes/undo 4t/git/learnA/wisdom-weasel-rag-ime/.rag-ime-data/rag-ime.sqlite
  project: wisdom-weasel-rag-ime
  max_visible_candidates: 8
  max_side_candidates: 2
  latency_budget_ms: 180
  timeout_ms: 1200
```

`rag_ime/enabled` defaults to false. If it is false, or if the sidecar fails, Squirrel falls back to the original Rime candidate list.

## Build And Verify

This machine currently has Command Line Tools but not full Xcode, so `xcodebuild -project Squirrel.xcodeproj -list` fails before project compilation with:

```text
xcode-select: error: tool 'xcodebuild' requires Xcode
```

Local checks that were run for this patch:

```bash
git -C /tmp/rag-ime-research/squirrel diff --check
swiftc -typecheck /tmp/rag-ime-research/squirrel/sources/RagImeSidecarModels.swift
```

The sidecar client was also typechecked with a temporary `SquirrelConfig` stub to verify its standalone Swift syntax. A full integration build still needs to be run in a macOS environment with Xcode installed.

## Runtime Shape

Rime remains the first-stage decoder:

```text
keyDown
  -> librime parses raw pinyin
  -> Squirrel reads preedit, commitTextPreview, candidates, comments, labels
  -> RAG-IME sidecar receives normalized Rime context
  -> sidecar returns displayCandidates
  -> Squirrel displays the merged list
```

Keyboard selection is intentionally narrow:

- if a number/key label points to a side candidate, Squirrel intercepts it and inserts the side candidate;
- otherwise the key continues through normal Rime processing.

The candidate panel only shows short candidate text and short comments. Evidence previews and pipeline timing belong in the debug surface, not in the small input-method panel.
