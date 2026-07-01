# Wisdom-Weasel RAG IME

Local-first RAG input method MVP inspired by Wisdom-Weasel.

This repository is a standalone product repo, not a fork/PR branch of `scukeqi/Wisdom-Weasel`.
Wisdom-Weasel remains an upstream reference for the existing LLM input method flow.

## Current Boundary

The RAG/memory layer is being extracted into a shared core so PI and this input method do not build duplicate databases or ranking logic.

This repo should focus on:

- input-method adapter contracts;
- committed input event capture;
- local SQLite/FTS5 MVP backend until the shared core exposes stable write/action APIs;
- short candidate generation from shared-core retrieval results;
- evidence preview / expanded evidence UI prototype;
- pin / downrank / delete action wiring;
- Agent first-run context hook;
- macOS InputMethodKit frontend adapter prototype;
- Rime/Squirrel production frontend integration plan;
- optional local OpenAI-compatible model prediction lane;
- history-input context for local model prediction;
- measured Mac-local model TTFT gate: `qwen3.5:0.8b-mlx` reached 46 ms p50 first chunk in a warm sequential smoke, but still fails project-memory quality gates, so RAG remains the source of truth;
- Mac-local acceptance scenarios.

This repo should not duplicate:

- SQLite memory store;
- FTS5 index implementation;
- accepted/skipped/pinned/downranked/delete governance state;
- PI-specific runtime/tool registration;
- cloud GPT/Claude default prediction;
- model fine-tuning.

See `docs/shared-core-adapter-contract.md` for the shared-core requirements.

## Privacy Defaults

- Personal input history stays local by default.
- Generated SQLite databases, traces, and reports are ignored by Git.
- Cloud model calls are not part of the default prediction chain.
- Fine-tuning is out of scope for the Mac MVP.

## Planned Runtime Shape

```text
macOS InputMethodKit adapter / CLI prototype
  -> Swift RagBridgeClient JSON command
  -> LocalSqliteCoreClient or shared rag-memory core API/JSON CLI
  -> SQLite/FTS5 personal memory
  -> RetrievedMemory[]
  -> InputSuggestion[]
  -> short candidate list + evidence preview
  -> user action
  -> shared core governance action
```

The production macOS frontend should not remain a custom pinyin engine. The accepted framework route is Rime/Squirrel:

```text
Squirrel / InputMethodKit
  -> librime handles raw key input, schemes, dictionaries, spelling, paging
  -> Rime candidates + labels + comments
  -> RAG-IME side candidates from local model and local memory
  -> compact shared candidate panel
```

The current InputMethodKit app is kept as the fast prototype and debug harness. See `docs/rime-squirrel-framework-decision.md` for the framework decision.

## Current Commands

Initialize the local SQLite/FTS5 database:

```bash
python3 -m rag_ime.cli init-db
```

Seed deterministic demo memories:

```bash
python3 -m rag_ime.cli seed-demo --reset
```

Record a committed input event:

```bash
python3 -m rag_ime.cli commit "默认本地完成, 不上传个人输入历史" \
  --recent-context "隐私边界" \
  --tag privacy
```

Run the adapter tests:

```bash
python3 -m unittest discover -s tests
```

Render the three UI scenarios:

```bash
python3 -m rag_ime.cli demo --top-k 3
```

Run deterministic adapter acceptance:

```bash
python3 scripts/acceptance.py
```

Run the browser debug surface:

```bash
python3 -m rag_ime.cli seed-demo --reset
python3 -m rag_ime.cli debug-server
```

Then open:

```text
http://127.0.0.1:8765/
```

Run the lightweight HTTP sidecar for patched Squirrel:

```bash
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

The sidecar exposes `/rime-suggest` for merged Rime/RAG/model candidates and `/rime-select` for accepted side-candidate feedback. `/rime-select` records the committed text and, for RAG candidates, the accepted memory action in one request.

The sidecar uses a short `/rime-suggest` cache to absorb repeated equivalent Squirrel refreshes:

```bash
export RAG_IME_RIME_CACHE_TTL_MS=400
```

The cache key is based on the parsed Rime snapshot and semantic query, not the raw request sequence. When Rime candidates or commit preview already provide the semantic query, raw pinyin/preedit changes do not force another model/RAG call; cached responses still rewrite `sessionId`, `requestSeq`, `rawInput`, and `preedit` to the current request. Set it to `0` while debugging cache behavior.

The sidecar also deduplicates equivalent `/rime-suggest` requests that are already in flight. This is the VCP-style pending-request cache for the IME path: concurrent refreshes wait for the first request and reuse its response instead of calling the model/RAG pipeline twice. Health and response cache payloads expose `inFlightHits` / `inFlightHit` separately from TTL cache `hits`.

`/rime-suggest` also returns a `triggerDecision`. Rime candidates are always preserved, but model/RAG side candidates are skipped for raw pinyin fallback, unstable composing updates, or full visible Rime candidate pages. This is the backend safety valve that prevents the local model and retrieval stack from running on every key event.

The local SQLite core also keeps a small process-local suggestion cache for repeated equivalent RAG requests:

```bash
export RAG_IME_SUGGESTION_CACHE_SIZE=128
```

Set it to `0` to measure uncached retrieval in evaluations.

Probe both warm caches without opening the browser debug page:

```bash
python3 -m rag_ime.cli cache-probe "RAG 输入法" \
  --recent-context "用户正在调试输入法缓存" \
  --repeat 3 \
  --rime-candidate "RAG 输入法"
```

The report includes `suggestionCache` and `rimeSuggestCache` hit deltas. This is
the terminal gate for the VCP-style cache-hit concern: equivalent IME refreshes
should warm-hit instead of re-running retrieval/model work.

Install it as a user LaunchAgent so it starts at login:

```bash
scripts/install_sidecar_launch_agent.sh
```

The installer copies the runtime Python package into `~/Library/Application Support/RagIme/app` and stores the default sidecar database at `~/Library/Application Support/RagIme/rag-ime.sqlite`. This keeps the login service independent of the repository path and avoids launchd startup issues on external volumes.

If the IME should use a local model lane at login, export the predictor
variables before running the installer. The installer writes a whitelist of
`RAG_IME_PREDICTOR_*`, history-context, and cache variables into the plist:

```bash
export RAG_IME_PREDICTOR_PROVIDER=ollama
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434
export RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b-mlx
export RAG_IME_PREDICTOR_PROFILE=instant
export RAG_IME_PREDICTOR_STREAM_FIRST=1
scripts/install_sidecar_launch_agent.sh
```

Remove the LaunchAgent:

```bash
scripts/uninstall_sidecar_launch_agent.sh
```

Check the Squirrel/sidecar integration state:

```bash
scripts/doctor_squirrel_integration.sh
```

Before trying patched Squirrel as a real input source, run the strict readiness
gate:

```bash
RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 scripts/doctor_squirrel_integration.sh
```

Check and configure the full Xcode requirement for patched Squirrel:

```bash
scripts/setup_xcode_for_squirrel.sh
```

After a full Xcode is available and the patched checkout is prepared, inspect
build, and install patched Squirrel:

```bash
scripts/build_patched_squirrel.sh list
scripts/build_patched_squirrel.sh
scripts/build_patched_squirrel.sh install
```

The `install` action copies `Squirrel.app` into `~/Library/Input Methods` by
default, writes the managed RAG-IME block into
`~/Library/Rime/squirrel.custom.yaml`, and runs Squirrel postinstall unless
`RAG_IME_SQUIRREL_SKIP_POSTINSTALL=1` is set. For a machine-wide install, set
`RAG_IME_SQUIRREL_INSTALL_DIR="/Library/Input Methods"`.

See `docs/xcode-squirrel-setup.md` for the external-disk install route and the `DEVELOPER_DIR`/`xcode-select` commands.

Show memory action effects:

```bash
python3 -m rag_ime.cli action-demo
```

Build the Agent first-run memory block:

```bash
python3 -m rag_ime.cli agent-hook --top-k 3
```

Preview and import local Codex history for memory/RAG evaluation:

```bash
python3 -m rag_ime.cli import-codex-history \
  --path "$HOME/.codex/session_index.jsonl" \
  --dry-run \
  --limit 20
```

Evaluate retrieval quality against explicit cases:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-codex-history \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --top-k 5 \
  --repeat 3
```

Evaluate the actual Rime sidecar display path:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-rime-sidecar \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --match any \
  --repeat 2
```

Run the local aggregate quality gate:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  quality-gate \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --repeat 1 \
  --force-side-candidates \
  --require-suggestion-cache
```

`quality-gate` runs deterministic adapter acceptance, direct RAG eval,
`/rime-suggest` sidecar eval, and repeated cache probing in one command. It
returns exit code `0` only when every sub-gate passes. The default report is a
summary; add `--include-cases` when debugging individual failed cases. For a
real Codex-history DB, raise `--min-rag-pass-rate` and
`--min-sidecar-pass-rate` as the benchmark improves.

See `docs/codex-history-eval.md`.

The report includes candidate-level ranking metrics such as `top1Accuracy`, `meanReciprocalRank`, `noiseRate`, end-to-end suggestion latency, and repeat/cache statistics, not just pass/fail recall.
When running against the local core, it also includes `cacheStats` so repeated-case evaluations can measure suggestion-cache hits. If optional vector recall is enabled, the same report includes `vectorStats`.
`eval-rime-sidecar` uses the same case format but scores only model/RAG side candidates from the merged `/rime-suggest` display payload. Use it after `eval-codex-history` to catch failures in Rime-first merge, side-slot limits, trigger policy, and `/rime-suggest` cache behavior.

Optional vector recall can be enabled without changing the input-method adapter. `local-hash` is a deterministic local baseline for testing the side-index contract, not a semantic model:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  --embedding-provider local-hash \
  rebuild-vector-index --project wisdom-weasel-rag-ime
```

For real semantic recall, point `--embedding-provider openai-compatible` at a local or user-owned WSL embedding endpoint with `RAG_IME_EMBEDDING_BASE_URL` and `RAG_IME_EMBEDDING_MODEL`.

Inspect trigger policy:

```bash
python3 -m rag_ime.cli trigger-demo "这个项目" --idle-ms 300
```

Use a local OpenAI-compatible small model for the short prediction lane:

```bash
export RAG_IME_PREDICTOR_PROVIDER=openai-compatible
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000
export RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B
export RAG_IME_PREDICTOR_PROFILE=instant
export RAG_IME_PREDICTOR_EXTRA_BODY_JSON='{"seed":7}'
export RAG_IME_HISTORY_CONTEXT_EVENTS=6
export RAG_IME_HISTORY_CONTEXT_CHARS=420

python3 -m rag_ime.cli suggest-json "输入法 个人记忆" --recent-context "local-first RAG" --top-k 3
```

`suggest-json` merges the explicit `--recent-context` with recent committed input history before calling the local model. Set `RAG_IME_HISTORY_CONTEXT_EVENTS=0` to disable this history lane.

`RAG_IME_PREDICTOR_PROFILE=instant` is the recommended first profile for Qwen-style small instruct models. It uses chat mode, a 350 ms timeout, 8 output tokens, low sampling temperature, and `chat_template_kwargs.enable_thinking=false`. Individual env vars such as `RAG_IME_PREDICTOR_TIMEOUT_MS`, `RAG_IME_PREDICTOR_MAX_TOKENS`, or `RAG_IME_PREDICTOR_DISABLE_THINKING` can still override the profile. `RAG_IME_PREDICTOR_EXTRA_BODY_JSON` can add server-specific fields such as seeds or sampling controls.

For Ollama `qwen3.5` small-model smoke tests, use the native Ollama lane. The
OpenAI-compatible `/v1` endpoint can keep Qwen thinking output in a separate
reasoning field and return empty `content`; the native `/api/chat` route lets
RAG-IME send `think:false`.

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  ollama pull qwen3.5:0.8b

env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  OLLAMA_MODELS="/Volumes/undo 4t/ollama-models" \
  ollama serve

export RAG_IME_PREDICTOR_PROVIDER=ollama
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434
export RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b
export RAG_IME_PREDICTOR_PROFILE=instant
```

On 2026-07-01, the local Mac smoke result for `qwen3.5:0.8b` was:
downloaded size 1.0 GB, `/api/tags` found the configured model, and warm short
predictions returned 3 parsed candidates. Observed latency varied from about
0.48 s to 1.16 s, so it can pass a debug budget but is not acceptable for the
default per-keystroke IME path. This proves the adapter path, not final model
quality. The 0.8B thinking model still tends to produce generic candidates such
as `RAG`, `智能检索`, and `知识图谱`; a non-thinking instruction-tuned small
model such as `qwen2.5:0.5b` or `qwen2.5:1.5b` remains the next candidate to
test before enabling model side candidates by default.

For Mac-specific speed work, the next test order is: Ollama `qwen3.5:0.8b-mlx`
smoke first, then direct MLX-LM resident service with `stream_generate` and
prompt cache, then a native llama.cpp/Metal provider with stable prompt KV
cache and multi-sequence candidate sampling. See
`docs/model-ttft-kv-cache-plan.md` and
`docs/local-model-prediction-benchmark.md` for the backend decision and commands.

When the Ollama or MLX lane is used for real IME side candidates, enable the
stream-first path:

```bash
export RAG_IME_PREDICTOR_STREAM_FIRST=1
```

With this flag, `predict()` reads `/api/chat` or `/predict-stream` until the
first parsed candidate is available, then returns one model side candidate
instead of waiting for the full JSON list. This is the product path for
sub-200 ms first-visible candidates. Keep the flag off for quality evals that
need all model candidates.

Run the resident MLX-LM service when testing the next Mac fast lane:

```bash
python3 -m rag_ime.cli mlx-predictor-server \
  --model <mlx-compatible-qwen-model-id> \
  --host 127.0.0.1 \
  --port 8767 \
  --prompt-cache

export RAG_IME_PREDICTOR_PROVIDER=mlx
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767
export RAG_IME_PREDICTOR_MODEL=<same-model-id>
export RAG_IME_PREDICTOR_PROFILE=instant
```

The MLX service exposes `/predict`, `/predict-stream`, `/health`, and
`/v1/models`. It loads the model once and lets `predictor-ttft` measure the
first streamed candidate without going through an OpenAI-compatible chat layer.
With `--prompt-cache`, it prepares the stable system-prompt cache at startup and
uses a fresh loaded prompt-cache copy for each `generate_step` streaming
request, so `promptCache.usedForGeneration` can turn true without mutating the
shared stable-prefix cache file. This still needs real-model TTFT and quality
verification before enabling the MLX lane by default.

The model lane also has a default failure cooldown. If the configured endpoint times out or returns a slow empty result, subsequent prediction calls are skipped for a short window so composing refreshes do not pay one model timeout per key event:

```bash
export RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=5000
export RAG_IME_PREDICTOR_FAILURE_LATENCY_MS=250
```

Set `RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0` only for endpoint debugging when you intentionally want every request to hit the model server.

Use `RAG_IME_PREDICTOR_PROFILE=completion-instant` for base-model or llama.cpp-style `/v1/completions` servers. That mode sends `history + current_input` as a prefix and requests multiple candidates with `n`, matching Wisdom-Weasel's faster base-completion direction more closely than chat prompting. It is still an OpenAI-compatible baseline; native llama.cpp KV-cache/batch sampling remains a later provider.

Check whether the model lane is configured without calling the model:

```bash
python3 -m rag_ime.cli predictor-status
```

`configured: true` means the `RAG_IME_PREDICTOR_*` environment is set. It does not prove the local model server is running.

Probe the configured endpoint, `/v1/models`, one short prediction, local runner commands, and the latency budget:

```bash
python3 -m rag_ime.cli predictor-doctor \
  --case "RAG 输入法" \
  --recent-context "用户正在写本地记忆和候选预测" \
  --latency-budget-ms 150
```

Use `predictor-doctor` before deeper evaluations. It distinguishes common failures: no env config, server not started, model id not listed by `/v1/models`, no parsed candidates, and latency over budget.

Benchmark local model prediction latency before using it in the input-method lane:

```bash
python3 -m rag_ime.cli predict-benchmark \
  --case "RAG 输入法" \
  --case "Squirrel 候选" \
  --recent-context "用户正在写本地记忆和候选预测" \
  --latency-budget-ms 150
```

For input methods, also measure streaming first-candidate latency. This is the
metric that approximates "when the first usable model-side candidate can
appear":

```bash
python3 -m rag_ime.cli predictor-ttft \
  --case "RAG 输入法" \
  --recent-context "用户正在写本地记忆和候选预测" \
  --repeat 8 \
  --latency-budget-ms 200
```

`predictor-ttft` currently supports the native Ollama lane and the resident MLX
service. It reports
`firstChunkMs`, `firstCandidateMs`, `totalMs`, parsed candidates, and
over-budget counts. The latency budget is evaluated against the first parsed
candidate, not against raw JSON/token chunks. See
`docs/mac-local-inference-fast-path.md` and
`docs/model-ttft-kv-cache-plan.md` for why Ollama is only the baseline and why
the final low-latency path should copy Wisdom-Weasel's native llama.cpp
system-prompt KV cache plus multi-sequence batch sampling.

Run the IME TTFC matrix after downloading candidate models. This is the
speed-only gate for first parsed candidates; it accepts cases without
`expectedTerms` because quality is evaluated separately:

```bash
python3 -m rag_ime.cli --core-mode fixture \
  bench-ime-ttfc \
  --cases-file docs/eval/ime-ttfc-cases.example.jsonl \
  --provider ollama \
  --base-url http://127.0.0.1:11434 \
  --models qwen3.5:0.8b-mlx,qwen3.5:2b-mlx \
  --repeat 20 \
  --latency-budget-ms 200
```

`bench-ime-ttfc` reports one summary per model with `p50FirstCandidateMs`,
`p95FirstCandidateMs`, `overBudgetCount`, `failureCount`, and a latency-only
winner. Add `--include-cases` when debugging individual samples.

Evaluate local model prediction quality against the same JSONL case format used by RAG evaluation:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-prediction \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --max-candidates 3 \
  --latency-budget-ms 150
```

Use this before switching between Qwen, MLX, llama.cpp, or other local OpenAI-compatible servers. It reports the same `top1Accuracy`, `meanReciprocalRank`, forbidden-term noise checks, and per-case `elapsedMs` as the RAG eval, plus a `prediction` block for provider and latency-budget status.

Compare several local model ids on the same cases:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-model-matrix \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --base-url http://127.0.0.1:11434/v1 \
  --models qwen3.5:0.8b,qwen3.5:2b,qwen3.5:4b \
  --max-candidates 3 \
  --latency-budget-ms 150
```

This is the preferred gate after downloading candidate models. It reports pass rate, `top1Accuracy`, `meanReciprocalRank`, p95 latency, candidate availability, local runner availability, and a winner summary. Add `--include-cases` only when debugging individual failures.

Compare local RAG suggestions and model predictions on the same cases:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-comparison \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --top-k 5 \
  --max-candidates 3 \
  --repeat 2
```

This emits a `rag` report, a `model` report, and a `comparison` block with `ragOnlyPassed`, `modelOnlyPassed`, `bothPassed`, `winnerByPassRate`, `winnerByTop1Accuracy`, and per-case surfaces. Use it when deciding whether a local Qwen/MLX/llama.cpp endpoint is good enough to enable in the IME lane.

Build the macOS frontend adapter:

```bash
scripts/build_macos_frontend.sh
```

Inspect the runtime bridge config:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --print-config
```

Verify the Swift frontend can call the Python RAG backend:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-json
```

Verify the Swift frontend can call and decode the Squirrel/Rime side-candidate contract:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-sidecar-json
```

Prepare a patched Squirrel checkout:

```bash
scripts/prepare_squirrel_workspace.sh
```

This creates `/tmp/rag-ime-squirrel`, applies the Squirrel patch, runs local checks, and writes `rag-ime.squirrel.custom.yaml` with the `rag_ime` config block to copy into Squirrel's `squirrel.yaml`.

Preview the Squirrel/Rime side-candidate contract:

```bash
cat > /tmp/rime-sidecar-request.json <<'JSON'
{
  "sessionId": "squirrel-demo",
  "requestSeq": 1,
  "rawInput": "ragshurufa",
  "preedit": "ragshurufa",
  "committedContext": "正在设计 RAG 输入法",
  "maxVisibleCandidates": 6,
  "maxSideCandidates": 3,
  "rimeContext": {
    "candidates": [
      {"label": "1", "text": "RAG 输入法", "comment": "rime"},
      {"label": "2", "text": "RAG 是", "comment": "rime"}
    ],
    "highlightedIndex": 0,
    "page": 0,
    "isLastPage": true
  }
}
JSON

python3 -m rag_ime.cli --core-mode fixture rime-suggest-json \
  --payload-file /tmp/rime-sidecar-request.json
```

This command keeps Rime candidates first, appends model/RAG side candidates only if visible slots remain, reserves side slots for RAG/memory after at most one model prediction, and uses Rime candidates or commit preview as the semantic query instead of asking the model to decode raw pinyin.

Open the native AppKit candidate panel preview:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-panel
```

Install the local input method app:

```bash
scripts/install_macos_frontend.sh
```

The installer writes a user-level bridge config at `~/Library/Application Support/RagImeMac/bridge-config.json` so the installed input method can find this checkout, the local SQLite DB, and the Python executable.

Use the shared-core JSON command from `pi-rag-memory-extension`:

```bash
python3 -m rag_ime.cli --core-mode json \
  --core-command "node --experimental-strip-types /path/to/pi-rag-memory-extension/scripts/ime-json-core.mjs --cwd /path/to/workspace --namespace wisdom-weasel-ime --db-path /path/to/session-history.sqlite" \
  suggest-json "输入法 个人记忆" --recent-context "local-first RAG" --top-k 3
```

Run the browser debug surface against the same shared core:

```bash
python3 -m rag_ime.cli --core-mode json \
  --core-command "node --experimental-strip-types /path/to/pi-rag-memory-extension/scripts/ime-json-core.mjs --cwd /path/to/workspace --namespace wisdom-weasel-ime --db-path /path/to/session-history.sqlite" \
  debug-server --no-seed
```

## Current Status

Implemented in this repo:

- adapter data models;
- shared-core client boundary;
- local SQLite/FTS5 CoreClient;
- committed input event recording;
- durable memory actions for accepted/skipped/pin/downrank/delete/restore;
- SuggestionCompiler for `RetrievedMemory -> InputSuggestion`;
- conservative RAG refresh trigger policy;
- fixture core for adapter/UI unit tests only;
- short candidate rendering;
- evidence preview and expanded evidence panel text;
- pin/downrank/delete action wiring;
- Agent first-run hook wrapper;
- macOS InputMethodKit shell;
- AppKit `NSPanel` candidate/evidence overlay;
- Swift-to-Python JSON bridge;
- browser debug page with the same local backend contract;
- shared-core JSON command integration for CLI/debug-server;
- Squirrel/Rime-aware side-candidate JSON contract;
- Swift bridge models and preview command for the Rime side-candidate contract;
- Squirrel patch pack for a fail-closed Rime sidecar frontend integration with HTTP sidecar and side-candidate commit/action recording;
- optional local OpenAI-compatible model prediction lane;
- bounded history-input context for model/RAG prediction;
- shared number-key selection for top model predictions and lower RAG/memory candidates;
- three realistic UI scenarios;
- unittest and acceptance script.

Not implemented in this repo by design:

- vector recall;
- PI runtime integration.

The local SQLite client is still the easiest Mac MVP backend. The shared RAG/memory core can now be selected through `--core-mode json` when the PI memory extension checkout is available.

## macOS Frontend Route

Implemented prototype route:

1. Keep this CLI adapter as the product contract and test harness.
2. Add `suggest-json` and `action-json` as the native frontend protocol.
3. Build a macOS InputMethodKit prototype that captures committed text and calls:
   - `record_event` after commit;
   - `suggest_for_input` while preedit/current context changes;
   - `apply_action` when the user accepts, pins, downranks, or deletes a suggestion.
4. Render a normal candidate bar for short suggestions.
5. Render compact model predictions above RAG/memory candidates, using one shared number-key sequence.
6. Render evidence preview in an expanded panel or WebView-style overlay.

Production route:

1. Base the real macOS IME on Squirrel/Rime rather than extending the prototype into a full pinyin engine.
2. Preserve Rime schemes, dictionaries, spelling correction, paging, labels, and comments.
3. Add RAG/model candidates after librime has produced structured composition state.
4. Follow Wisdom-Weasel's proven constraints: async prediction, stale-result guard, side-candidate merge, local provider, and pinyin constraints only when supplied by the engine.
5. Keep the current InputMethodKit prototype as the debug/contract harness while the Squirrel integration is developed.

See `docs/interview-project-difficulties.md` for the Chinese interview material that records the project difficulties and engineering choices.

See `docs/macos-frontend-adapter.md` for the macOS frontend research and implementation notes.

See `docs/rime-squirrel-framework-decision.md` for the accepted Rime/Squirrel framework route.

See `squirrel-patches/README.md` for the patch-pack base commit, config keys, and validation commands.

See `docs/wisdom-weasel-issues-map.md` for the Wisdom-Weasel open-issues compatibility map.
