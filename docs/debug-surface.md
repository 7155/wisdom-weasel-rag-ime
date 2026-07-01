# Debug Surface

## Goal

`debug/` is the browser test surface for inspecting the backend pipeline and candidate payloads.

It is not the product input method UI. The real input method UI is the native macOS `InputMethodKit` + AppKit panel under `macos/RagImeMac/`.

It is intentionally small:

- no build step;
- no frontend framework dependency;
- no cloud API;
- same local adapter contract as the Python CLI and Swift preview.

Run it with:

```bash
python3 -m rag_ime.cli seed-demo --reset
python3 -m rag_ime.cli debug-server
```

Tune or disable the short `/rime-suggest` cache:

```bash
RAG_IME_RIME_CACHE_TTL_MS=400 python3 -m rag_ime.cli debug-server
RAG_IME_RIME_CACHE_TTL_MS=0 python3 -m rag_ime.cli debug-server
```

Tune or disable the local-core suggestion cache:

```bash
RAG_IME_SUGGESTION_CACHE_SIZE=128 python3 -m rag_ime.cli debug-server
RAG_IME_SUGGESTION_CACHE_SIZE=0 python3 -m rag_ime.cli debug-server
```

Run it against the shared RAG/memory core instead of the local MVP database:

```bash
python3 -m rag_ime.cli --core-mode json \
  --core-command "node --experimental-strip-types /path/to/pi-rag-memory-extension/scripts/ime-json-core.mjs --cwd /path/to/workspace --namespace wisdom-weasel-ime --db-path /path/to/session-history.sqlite" \
  debug-server --no-seed
```

Use `--no-seed` for shared-core debugging when you want to inspect an existing memory database without adding demo events.

Open:

```text
http://127.0.0.1:8765/
```

## Interaction Model

The native input method uses one shared number-key set instead of splitting numbers between word candidates and paragraph candidates.

```text
1-8   prefer MLX/model and RAG/memory candidates
fallback rows choose Rime candidates when side lanes are unavailable or empty
Esc   cancel current composition
Enter commit the current composition
```

Reason:

- model candidates are short and should render inline/horizontally;
- RAG/memory candidates are sentence-like and should render as block rows;
- Rime remains available as deterministic parsing/fallback rather than the main ranked list;
- the same payload can drive the debug page and native AppKit panel;
- the IME panel stays small because it only shows one prediction row and up to three memory rows.

Native Squirrel layout contract:

```text
1-5   MLX/LLM short candidates, rendered in one horizontal inline row
6-8   RAG/memory sentence candidates, rendered as vertical block rows
```

The numbering is still global. The user does not switch number modes; the
frontend only changes visual grouping. The patched Squirrel frontend forces the
panel into horizontal TextKit orientation when `displayLayout=inline` model
candidates are present, uses spaces between adjacent inline candidates, and
uses newlines before `block/memory` candidates. The foreground trace event
`panel_text_layout` records the separators so the doctor can catch regressions
where MLX candidates accidentally become a vertical list again.

## Small-Area Constraint

The native input method panel should not cover the document.

Current browser prototype constraints:

- compact max height: about 214 px;
- expanded max height: about 356 px;
- compact state shows one short-candidate row and at most two memory summaries;
- evidence text is hidden until the user switches to the RAG layer or presses the evidence debug control.

The native `RagCandidatePanel` keeps the strict version of this behavior: compact by default, no pipeline text, no model labels, no debug JSON, and evidence only as a one-line hint unless the user explicitly expands elsewhere.

## Local API

The debug page calls `rag_ime.debug_server.DebugImeService`.

Endpoints:

```text
GET  /api/health
GET  /api/input-source
POST /api/seed
POST /api/suggest
POST /api/rime-suggest
POST /api/rime-select
POST /api/predictor-ttfc
POST /api/cache-probe
POST /api/action
POST /api/commit
```

`/api/suggest` returns the same stable frontend payload as:

```bash
python3 -m rag_ime.cli suggest-json ...
```

`/api/input-source` is the browser-facing readiness check for real macOS
typing. It wraps `scripts/check_macos_input_source.sh --require-hitoolbox-enabled`
and returns both raw facts (`enabled`, `selectable`, `selected`, `current`,
`hitoolboxEnabled`, `thirdPartyEnabled`) and a compact `readinessState`:

- `ready`: Squirrel is installed and currently selected;
- `switch`: Squirrel is installed but the active input source is still another
  input method such as ABC or Doubao;
- `install`: Squirrel is not enabled in every current-user input-source list,
  including the macOS third-party input-source list used by System Settings;
- `unavailable`: the local checker script is missing;
- `error`: the checker itself failed.

The debug page polls this endpoint every few seconds. The visible card keeps the
state compact but explicit:

```text
TIS      Squirrel is visible to macOS Text Input Source APIs
3rd      Squirrel is present in the third-party input-source list managed by System Settings
selected Squirrel is the active menu-bar input source
current  the active input-source id, shortened for scanning
```

The same payload also includes `manualAction`, `helperCommand`,
`verificationCommand`, and `readinessChecks`, so the page can say "run
`scripts/open_squirrel_input_source_settings.sh --wait` and add Squirrel in
System Settings" when `thirdPartyEnabled=false` instead of incorrectly telling
the user to switch to an input source that macOS has not fully enabled yet. This
keeps the browser surface aligned with the manual System Settings and menu-bar
steps without adding status text to the real compact IME candidate panel.

For local model debugging, use the CLI doctor before opening the debug page:

```bash
python3 -m rag_ime.cli predictor-doctor
```

The browser debug page shows predictor configuration through `/api/health`, but it does not intentionally run model probes on page load. `predictor-doctor` is the safer place to test `/v1/models` and one short candidate request without adding latency to ordinary debug refreshes.

`/api/health` also exposes predictor cooldown state when a local model is configured. A cooldown means the endpoint recently failed or returned a slow empty result; `/rime-suggest` will keep Rime and RAG candidates responsive while temporarily skipping model predictions.

The debug page has a manual Model TTFC probe backed by `POST /api/predictor-ttfc`.
It runs the same streaming first parsed candidate measurement as the CLI
`bench-ime-ttfc` path, but only when the user presses the probe button. The
visible card shows p50, p95, and over-budget count; the full JSON panel shows
the predictor status and benchmark summary. This belongs in the debug surface,
not the small IME panel.

The debug page also has a manual Cache probe backed by `POST /api/cache-probe`.
It repeats the same semantic request through both `/api/suggest` and
`/api/rime-suggest`, then reports warm-hit deltas for:

- the local/shared core suggestion cache;
- the Squirrel/Rime semantic `/rime-suggest` cache.

This is the IME-specific version of the VCP cache-hit concern: repeated
composition refreshes should be absorbed by semantic cache keys, not re-run
retrieval and local model work on every equivalent key event. The visible card
only shows core hits, Rime hits, and repeat count; the JSON panel keeps the full
before/after stats and samples.

The same probe is available without the browser:

```bash
python3 -m rag_ime.cli cache-probe "RAG 输入法" \
  --recent-context "用户正在调试输入法缓存" \
  --repeat 3 \
  --rime-candidate "RAG 输入法"
```

`/api/rime-suggest` returns the Squirrel/Rime side-candidate payload. It accepts structured Rime context:

```json
{
  "sessionId": "squirrel-debug",
  "requestSeq": 1,
  "rawInput": "ragshurufa",
  "preedit": "ragshurufa",
  "committedContext": "正在设计 RAG 输入法",
  "rimeContext": {
    "candidates": [
      {"label": "1", "text": "RAG 输入法", "comment": "rime"},
      {"label": "2", "text": "RAG 是", "comment": "rime"}
    ]
  }
}
```

The response includes `displayCandidates` where Rime candidates keep
`selectionAction: select_rime_candidate`, while model/RAG side candidates use
`selectionAction: commit_side_candidate`. Each display candidate carries both the
legacy visible `label` and explicit selection routing fields:

- `selectionKey`: the key that selects this visible row;
- `selectionRank`: the 1-based rank written to memory feedback; `0` maps to
  rank 10 for the shared `1-9,0` candidate-key convention.

The strict Squirrel doctor validates this contract through the live sidecar. In
`RAG_IME_DOCTOR_REQUIRE_TRYOUT=1` mode it requires model candidates to be
`inline/model`, RAG candidates to be `block/memory`, shared selection keys and
ranks to match the visible labels, and the merge policy to stay side-first with
`["model", "rag", "rime"]` fallback order. This catches backend/native-payload
regressions before the foreground AppKit panel test.

The same strict mode also requires the configured MLX predictor path to return
`next-token-logits` candidates with `candidate_scores`, no JSON fallback, and a
prepared prompt cache. This prevents the IME from silently regressing to slow
multi-token JSON generation while still showing plausible candidates.

For the foreground AppKit panel test, use the installed Squirrel frontend trace:

```bash
scripts/verify_squirrel_foreground_trace.sh
```

This wrapper selects `Squirrel - Simplified`, clears the old trace, opens a
small TextEdit test file, and waits for the same trace evidence as the lower
level checker. During the wait, type a semantic prefix such as `er qi`, then
press `6`, `7`, or `8` to accept a side sentence candidate. Use `--mixed-only`
when you only want to verify the horizontal/vertical panel layout without
committing a side candidate.

If the app running the command has macOS Accessibility permission, the wrapper
can attempt the foreground typing step:

```bash
scripts/verify_squirrel_foreground_trace.sh --auto-type
```

When macOS rejects simulated keystrokes, the script prints the Accessibility
path and falls back to the manual action. That failure means local UI automation
is blocked; it is not evidence that Squirrel, RAG-IME, or MLX failed.

The lower level checker is still useful when you have already produced trace
events and only want to inspect them:

```bash
python3 scripts/check_squirrel_frontend_trace.py \
  --require-mixed-panel \
  --require-side-commit \
  --print-last 8
```

The same foreground evidence can also be required through the Squirrel doctor
after manual typing:

```bash
RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 \
RAG_IME_DOCTOR_REQUIRE_FRONTEND_TRACE=1 \
RAG_IME_DOCTOR_FRONTEND_TRACE_WAIT=30 \
RAG_IME_SQUIRREL_WORKDIR=/tmp/rag-ime-squirrel-verify \
  scripts/doctor_squirrel_integration.sh
```

This is the preferred final gate for a local run because it checks sidecar
health, model/RAG merge contract, raw-pinyin guard, input-source readiness, and
the real Squirrel AppKit trace in one command.

The trace is written by the patched Squirrel app itself, not by the sidecar. A
passing `latestMixedPanel` proves the actual frontend used sidecar display
candidates and forced horizontal layout for the mixed panel. A passing
`latestMixedTextLayout` proves the rendered text separators are mixed correctly:
LLM/model inline candidates stay on one horizontal row, then the first
RAG/memory sentence starts a newline and later sentence candidates remain
vertical rows. A passing `latestNumberKeySideCommit` proves the same visible
number key first routed through `number_key_route`, then committed the matching
model/RAG side candidate through `side_candidate_commit` and triggered feedback
recording.

The semantic query is built from commit preview or Rime candidates before
falling back to raw input.

The response also includes `triggerDecision`. This is the backend guard that keeps the input method small and responsive:

- Rime candidates are kept as fallback rows when side candidates do not fill the visible list.
- Model/RAG side lanes are skipped for empty input and for raw pinyin fallback
  with no usable semantic signal. If raw composition has no Rime candidates but
  recent committed Chinese context exists, `/rime-suggest` uses that
  `committedContext` as a continuation signal instead of asking the model to
  decode the raw key sequence.
- The patched Squirrel frontend keeps `committedContext`-based side candidates
  visible for a short holdover window while raw input changes and Rime has no
  fallback candidates. This is the safe path for `asdioj`-style noise: continue
  from recent Chinese text, do not infer Chinese directly from the raw letters.
- `forceSideCandidates: true` can be used by debug tooling to force a refresh.
- Skipped refreshes return empty `modelPredictions` / `ragCandidates` and `mergePolicy.sideCandidatesEnabled: false`.

The strict Squirrel doctor now includes this raw-input safety check. It sends
one dirty raw-pinyin payload without context and expects `queryBasis:
rawInputFallback`, `shouldRefresh=false`, and no display candidates; then it
sends `asdioj` with recent committed Chinese context and expects
`queryBasis: committedContext` plus at least one model/RAG side candidate. This
keeps the project aligned with the current design: do not ask the LLM to decode
arbitrary key noise, but keep short continuation predictions alive from the
confirmed text the user just committed.

The response also includes `ragLane` and `modelLane`. These record whether each
side lane was allowed to run inside the request budget:

```json
{
  "latencyBudgetMs": 150,
  "ragLane": {
    "called": true,
    "timedOut": false,
    "latencyBudgetMs": 150,
    "suggestionCount": 2
  },
  "modelLane": {
    "called": true,
    "timedOut": false,
    "latencyBudgetMs": 150,
    "sideLaneMode": "parallel",
    "elapsedBeforeModelMs": 0,
    "predictionCount": 1
  }
}
```

If RAG is too slow, `ragLane.timedOut` becomes true and the response falls back
to Rime-only or Rime/model candidates. If the model is too slow,
`modelLane.timedOut` becomes true and `modelPredictions` is empty while RAG
candidates still return. If a previous side-lane request is still running, the
sidecar skips that lane with `skippedReason`.

The debug page probes `/api/rime-suggest` alongside `/api/suggest` and shows `queryBasis`, `triggerDecision`, `displayCandidates`, and cache metadata in the JSON panel. This is only for backend inspection; it does not change the browser prototype's visible candidate layout.

For repeatable CLI checks of the same path, use:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-rime-sidecar \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --repeat 2
```

This scores only model/RAG side candidates from the merged `displayCandidates` payload, so it catches failures that direct `eval-codex-history` cannot see: side-slot exhaustion, skipped trigger decisions, compact display text, and `/rime-suggest` cache misses.

The local HTTP server keeps a short TTL cache for repeated equivalent `/rime-suggest` payloads. The cache key is built from the parsed Rime snapshot, semantic query, trigger decision, memory event/action counts, project, and predictor configuration. It excludes `requestSeq` and `sessionId`, and it also ignores raw pinyin/preedit changes when the semantic query already comes from commit preview or stable Rime candidates. Cached responses rewrite `requestSeq`, `sessionId`, `rawInput`, `preedit`, and current Rime metadata before returning:

```json
{
  "cache": {
    "hit": true,
    "ttlMs": 400
  }
}
```

It also has an in-flight dedupe guard. If two equivalent `/rime-suggest` requests arrive before the first one finishes, the second waits for the first response and returns it with refreshed `sessionId` / `requestSeq` metadata. This is separate from the TTL cache: `cache.hit` is false, while `cache.inFlightHit` is true.

```json
{
  "cache": {
    "hit": false,
    "inFlightHit": true,
    "inFlightHits": 1
  }
}
```

`POST /api/commit`, `POST /api/action`, and `POST /api/seed` clear this cache.

The local SQLite core also exposes a process-local `suggestionCache` in `/api/health`. That cache stores final `InputSuggestion` lists for repeated equivalent `/api/suggest` or eval requests and is invalidated on commit/action/reset. It is separate from the short `/rime-suggest` TTL cache.

`/api/health` also exposes `predictor` status. This is a configuration check for the optional local model lane: it reports whether `RAG_IME_PREDICTOR_*` is configured, the active profile, prompt mode, endpoint, and model name. It does not call the model; use `predict-benchmark` or `eval-prediction` to prove the endpoint is alive and useful.

Prediction and sidecar payloads expose `historyContextMeta` / `requestMeta`
fingerprints. These are for debugging cacheability, not for user display:

```json
{
  "historyContextMeta": {
    "chars": 126,
    "fingerprint": "b904...",
    "hasHistory": true,
    "hasExplicitContext": true
  },
  "modelPredictions": [
    {
      "metadata": {
        "requestMeta": {
          "currentInputFingerprint": "6a8f...",
          "contextFingerprint": "b904...",
          "stablePrefixHash": "4d2c..."
        }
      }
    }
  ]
}
```

When testing a resident MLX or future llama.cpp provider, matching
`contextFingerprint` plus `stablePrefixHash` is the signal that the stable
history/context prefix can be reused; changing `currentInputFingerprint` should
only invalidate the dynamic tail.

`/api/rime-select` records a side-candidate acceptance with one stable payload:

```json
{
  "candidate": {
    "label": "4",
    "selectionKey": "4",
    "selectionRank": 4,
    "text": "先用 FTS5 证明召回收益",
    "insertText": "先用 FTS5 证明召回收益",
    "sourceType": "rag",
    "selectionAction": "commit_side_candidate",
    "memoryId": "event:4",
    "suggestionId": "sug-event:4",
    "sourceEventId": 4
  },
  "query": "RAG 输入法",
  "recentContext": "用户正在写输入法设计",
  "preedit": "ragshurufa"
}
```

It returns `rag-ime.rime-selection.v1`, records the committed text, and also records an `accepted` action when the selected candidate came from RAG memory. Model side candidates only record the committed text.

The page falls back to local mock suggestions if the API is unavailable, so visual iteration can continue while backend work is in progress.

## Native Porting Notes

Port in this order:

1. Keep `RagBridgeClient` unchanged unless the JSON contract changes.
2. Render compact evidence summaries first.
3. Add expanded evidence after number-key selection is stable.
4. Add richer action controls in a non-IME debug/preferences surface, not in the default candidate panel.
