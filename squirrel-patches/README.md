# Squirrel Patch Pack

This directory contains patch files for testing RAG-IME inside upstream Squirrel without vendoring the full Squirrel source tree into this product repo.

## Base

- Upstream repo: `https://github.com/rime/squirrel`
- Verified base commit: `2158538`
- Patch: `0001-add-rag-ime-sidecar.patch`

The patch is intentionally small and frontend-only:

- keeps librime responsible for raw pinyin parsing, composition, paging, and normal candidate selection;
- adds a fail-closed Python sidecar client;
- uses a long-running HTTP sidecar when `rag_ime/sidecar_url` is configured, with CLI fallback;
- adds a display-list merge after Squirrel has already read Rime candidates;
- routes selection by display metadata, so Rime candidates still call `select_candidate_on_current_page` and side candidates insert `insertText` directly;
- records side-candidate commits and accepted RAG actions back to the local memory core;
- drops stale sidecar responses by request sequence and current raw input.

## Prepare A Patched Checkout

Recommended:

```bash
cd /Volumes/undo\ 4t/git/learnA/wisdom-weasel-rag-ime
scripts/prepare_squirrel_workspace.sh
```

This clones Squirrel into `/tmp/rag-ime-squirrel`, checks out `2158538`, applies the patch, runs `git diff --check`, typechecks the sidecar Swift files when `swiftc` is available, and writes:

```text
/tmp/rag-ime-squirrel/rag-ime.squirrel.custom.yaml
```

Copy that `rag_ime` block into Squirrel's `squirrel.yaml` while testing.

Run the doctor after preparing the checkout and starting the sidecar:

```bash
scripts/doctor_squirrel_integration.sh
```

Manual apply:

```bash
git clone https://github.com/rime/squirrel /tmp/squirrel-rag-ime
cd /tmp/squirrel-rag-ime
git checkout 2158538
git apply /Volumes/undo\ 4t/git/learnA/wisdom-weasel-rag-ime/squirrel-patches/0001-add-rag-ime-sidecar.patch
git diff --check
```

## Configure

Start the local sidecar before testing Squirrel:

```bash
cd /Volumes/undo\ 4t/git/learnA/wisdom-weasel-rag-ime
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

For normal local use, install it as a user LaunchAgent:

```bash
scripts/install_sidecar_launch_agent.sh
```

Remove it with:

```bash
scripts/uninstall_sidecar_launch_agent.sh
```

Add this to Squirrel's `squirrel.yaml` while testing:

```yaml
rag_ime:
  enabled: true
  sidecar_url: http://127.0.0.1:8766/api
  python: /usr/bin/python3
  repo_root: /Volumes/undo 4t/git/learnA/wisdom-weasel-rag-ime
  db_path: /Volumes/undo 4t/git/learnA/wisdom-weasel-rag-ime/.rag-ime-data/rag-ime.sqlite
  project: wisdom-weasel-rag-ime
  max_visible_candidates: 8
  max_side_candidates: 2
  latency_budget_ms: 180
  timeout_ms: 1200
```

`rag_ime/enabled` defaults to false. If it is false, Squirrel falls back to the original Rime candidate list. If `sidecar_url` fails, the patch falls back to `python -m rag_ime.cli`; if that also fails, Squirrel keeps the original Rime list.

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

The sidecar client was also typechecked with a temporary `SquirrelConfig` stub to verify its standalone Swift syntax. The Python HTTP sidecar endpoints are covered by unit tests. A full integration build still needs to be run in a macOS environment with Xcode installed.

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

When the user accepts a side candidate, the patch records:

- a `commit` event tagged with `squirrel` and `rime-sidecar`;
- an `action-json accepted` event when the candidate came from RAG memory and has `memoryId`, `suggestionId`, and `sourceEventId`.

These calls run in the background after insertion and fail closed so they do not block typing. With `sidecar_url`, they are HTTP POSTs to the long-running sidecar; without it, they use CLI fallback.
