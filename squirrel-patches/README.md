# Squirrel Patch Pack

This directory carries the pinned frontend patch used by the supported macOS
product route. It does not vendor the full Squirrel checkout.

## Base And License

- Upstream: [rime/squirrel](https://github.com/rime/squirrel)
- Base commit: `2158538`
- Patch: `0001-add-rag-ime-sidecar.patch`
- Upstream license: GPL-3.0

The patch produces a modified Squirrel work. Before distributing a patched
binary or source archive, satisfy the GPL source and notice obligations described
in [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

## Architecture Boundary

Rime keeps ownership of composition:

```text
keyDown
  -> librime parses pinyin, pages candidates, learns user frequency
  -> Squirrel displays the ordinary Rime composition panel
  -> successful native selection commits through librime
```

RAG-IME assistance starts after commit:

```text
trusted foreground snapshot
  -> POST /rime-suggest
  -> local model / local RAG / memory
  -> separate non-activating Assistant Overlay
  -> Tab or Option+number commit
  -> POST /rime-select feedback
```

The patch therefore does **not** insert LLM/RAG rows into the live pinyin
composition list. Passive HTTP failure, stale context, an empty model result, or
a sensitive field leaves normal Rime behavior intact. Passive prediction never
spawns a Python CLI fallback process on the keystroke path.

Native Rime selections have a separate local audit lane:

- Squirrel posts `/rime-rank-feedback` only after librime reports selection
  success;
- the sensitive-field guard runs before the background write;
- the payload is fixed to `sourceType=rime`, so model/RAG output cannot train
  the Rime export;
- Rime's own userdb remains the live ranking authority;
- RAG-IME only produces a reviewable, confirmed, rollback-capable custom
  dictionary export.

## Prepare

From the repository root:

```bash
scripts/prepare_squirrel_workspace.sh
```

The script clones or resets `/tmp/rag-ime-squirrel`, checks out `2158538`,
applies the patch, synchronizes the current Assistant Overlay source files,
registers them in the Xcode project, runs `git diff --check`, typechecks the
standalone Swift contracts, and writes the generated local config snippet.

Manual patch inspection is also possible:

```bash
git clone https://github.com/rime/squirrel /tmp/squirrel-rag-ime
git -C /tmp/squirrel-rag-ime checkout 2158538
git -C /tmp/squirrel-rag-ime apply \
  "$PWD/squirrel-patches/0001-add-rag-ime-sidecar.patch"
git -C /tmp/squirrel-rag-ime diff --check
```

## Build

Full Xcode is required:

```bash
scripts/build_patched_squirrel.sh list
scripts/build_patched_squirrel.sh build
```

The wrapper validates the patch markers, runs `xcodebuild -list`, performs a
Release build with isolated derived data, and checks the resulting bundle. The
current project has completed real Release builds; this is no longer an
unverified Command Line Tools-only path.

Installing or selecting an input method changes user-level macOS state. Do that
only during an attended foreground acceptance run:

```bash
scripts/build_patched_squirrel.sh install
scripts/doctor_squirrel_integration.sh
scripts/verify_squirrel_foreground_trace.sh
```

Backend health is not sufficient. The acceptance trace must separately prove
Rime composition, visible post-commit assistance, selection/commit, stale-drop,
delete resync, app-switch invalidation, and source-correct feedback.

## Runtime Configuration

`scripts/prepare_squirrel_workspace.sh` generates
`/tmp/rag-ime-squirrel/rag-ime.squirrel.custom.yaml`. The effective values come
from the script environment rather than machine paths committed to this repo.
The important boundary is:

```yaml
rag_ime:
  enabled: true
  sidecar_url: http://127.0.0.1:8766/api
  max_visible_candidates: 8
  max_side_candidates: 5
  latency_budget_ms: 900
  debounce_ms: 80
  post_commit_idle_ms: 420
  timeout_ms: 1200
  frontend_trace: true
```

When `rag_ime/enabled` is false or the Sidecar is unavailable, Squirrel keeps
the native Rime composition route. Side-candidate acceptance prefers one HTTP
`POST /rime-select`; its legacy commit/action fallback is off the passive
request path and exists only for accepted feedback compatibility.

## Narrow Verification

```bash
python3 -m unittest -v \
  tests.test_build_patched_squirrel \
  tests.test_rime_native_feedback \
  tests.test_rime_rank_export \
  tests.test_squirrel_frontend_trace
```
