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
- measured Mac-local model gate: `qwen3.5:0.8b-mlx` can stream raw text well under 200 ms on a warm runner, but strict TTFC filters now reject half tokens and repeated current-input tokens; the 0.8B model is therefore a speed smoke path, not the default quality source;
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

The debug page calls `/api/input-source` and shows the four practical typing
gates: whether Squirrel is visible to TIS, whether it is present in the macOS
third-party input-source list, whether it is selected, and which input source is
currently active. This is the fastest way to spot the difference between
"Squirrel is registered", "Squirrel has been added in System Settings", and
"typing is actually going through Squirrel". The card refreshes automatically:
`install` means the System Settings add flow is still required, `switch` means
installed but not active, and `ready` means the real macOS typing gate can run.

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

`/rime-suggest` also returns a `triggerDecision`. Rime candidates are preserved as deterministic parsing/fallback, while model/RAG side candidates get first display priority when a stable semantic signal exists. Side lanes are skipped for raw pinyin fallback or unstable composing updates; raw key sequences such as `asdioj` should be handled by Rime candidates or a future pinyin-constrained logits path, not by unconstrained LLM guessing.

`latencyBudgetMs` is enforced on the RAG and model side lanes. RAG retrieval is
budgeted first, then the model is allowed to use only the remaining budget. If
RAG or model work exceeds the budget, `/rime-suggest` still returns the Rime
candidates it already has. The response exposes this as `ragLane.*` and
`modelLane.*` status fields.

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
`~/Library/Rime/squirrel.custom.yaml`, ad-hoc signs the copied bundle for local
use, bootstraps user Rime data with `scripts/bootstrap_squirrel_user_data.sh`,
and runs Squirrel postinstall unless `RAG_IME_SQUIRREL_SKIP_POSTINSTALL=1`
is set. The bootstrap step copies Squirrel `SharedSupport` data plus missing
Plum output into `~/Library/Rime`, runs `Squirrel --build` and `--reload` from
the user Rime directory, and fails on silent build errors such as
`missing input schema`. The strict doctor verifies that the macOS TIS source
`im.rime.inputmethod.Squirrel.Hans` is registered, enabled, and selectable. This
only proves Text Input Services can enumerate the source. For real user-level
install readiness, also require `hitoolboxEnabled=true`:

```bash
RAG_IME_REQUIRE_HITOOLBOX_ENABLED=1 \
  scripts/check_macos_input_source.sh im.rime.inputmethod.Squirrel.Hans
```

For a machine-wide install, set `RAG_IME_SQUIRREL_INSTALL_DIR="/Library/Input Methods"`.
If System Settings still does not show Squirrel after registration, run the local
debug helper once. It backs up `com.apple.HIToolbox` and
`com.apple.inputsources` to the Desktop, tries to add the Squirrel entries to
both the HIToolbox enabled-source list and the macOS third-party input-source
list, restarts `cfprefsd`, and re-runs the strict source check:

```bash
scripts/enable_squirrel_hitoolbox_input_source.sh
```

On macOS 27, System Settings may still require the UI route for the third-party
input-source list: Keyboard -> Input Sources -> Add -> Chinese, Simplified ->
Squirrel. If the check prints `thirdPartyEnabled=false`, command-line writes
were not accepted by macOS and the UI Add path is required.

To open the Keyboard settings pane and wait for the strict source-list check,
use:

```bash
scripts/open_squirrel_input_source_settings.sh --wait
```

The helper does not click System Settings or modify input-source preferences. It
opens the Keyboard settings pane when macOS accepts the settings URL, prints the
manual Add path, then runs the same strict wait gate. If System Settings is
already open, the wait gate can still be run directly:

```bash
scripts/wait_squirrel_input_source_added.sh
```

Before a real typing test, switch to `Squirrel - Simplified` from the macOS input
menu and wait for the selected-source plus sidecar check:

```bash
scripts/wait_squirrel_typing_ready.sh
```

After switching to Squirrel, run the machine-readable tryout gate:

```bash
python3 -m rag_ime.cli \
  --db-path "$HOME/Library/Application Support/RagIme/rag-ime.sqlite" \
  squirrel-tryout-gate \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --report-path /tmp/rag-ime-squirrel-tryout-report.json
```

`squirrel-tryout-gate` first checks the installed `Squirrel.app` bundle, the
actual `~/Library/Rime/squirrel.custom.yaml` managed block, and required
`~/Library/Rime/build` artifacts, then checks `readinessState=ready` for the
active macOS input source, then checks the user LaunchAgent and the running
sidecar `/health` plus a safe `/rime-suggest`
candidate probe, then runs the existing backend `quality-gate` with
`--require-input-source-ready`. If the input source is still `switch`, it fails
fast and skips the expensive quality gate. It does not install Squirrel, modify
HIToolbox, switch input sources, or type into a
foreground app, and it does not call `/rime-select` by default. The report also
includes `manualRequired` for the remaining foreground typing and candidate-panel
checks.

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

For a mature gold set, also gate ranking quality and noise, not only recall:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  quality-gate \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --force-side-candidates \
  --min-rag-pass-rate 0.9 \
  --min-rag-top1-accuracy 0.75 \
  --min-rag-mrr 0.8 \
  --max-rag-noise-rate 0.05 \
  --min-sidecar-pass-rate 0.9 \
  --min-sidecar-top1-accuracy 0.75 \
  --min-sidecar-mrr 0.8 \
  --max-sidecar-noise-rate 0.05 \
  --max-sidecar-rag-timeout-rate 0 \
  --max-sidecar-model-timeout-rate 0 \
  --require-input-source-ready \
  --require-model-ttfc \
  --model-ttfc-cases-file docs/eval/ime-ttfc-cases.example.jsonl \
  --model-ttfc-provider ollama \
  --model-ttfc-base-url http://127.0.0.1:11434 \
  --model-ttfc-models qwen3.5:0.8b-mlx \
  --model-ttfc-warmup-runs 1 \
  --model-ttfc-repeat 20 \
  --model-ttfc-latency-budget-ms 200 \
  --max-model-ttfc-p95-ms 200 \
  --max-model-ttfc-over-budget-rate 0
```

This matters for an IME because a hit at rank 5 still slows typing, and a
forbidden/noisy candidate is worse than a missed side candidate. The sidecar
timeout gates make the display-path contract stricter: RAG/model side lanes must
fit the IME budget instead of silently falling back on most requests.
`--require-input-source-ready` is the real macOS typing gate: it checks that
Squirrel is installed in the current user's input-source list and is the selected
active input source. Leave it off in non-macOS CI or when you are evaluating only
the backend RAG/model path.
`--require-model-ttfc` adds the local-model speed contract: the selected model
must produce a first parsed candidate within the configured p95 and over-budget
thresholds. `--model-ttfc-warmup-runs` separates cold model load from the
resident input-method path; still record cold-start results separately when
choosing a production runner. Leave the TTFC gate off when no local model server
is running.

For the final Wisdom-Weasel-style local model provider, add explicit capability
requirements. This should fail for Ollama/MLX smoke providers until a native
provider can prove stable prompt-cache reuse, sequence fork, and batch
candidate generation. When capability requirements are present, `quality-gate`
also probes runtime capability endpoints such as the MLX service `/health`; for
`promptCache`, the MLX service must report that the prepared cache was actually
used for generation, not only prepared at startup:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  quality-gate \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --force-side-candidates \
  --require-predictor-capability promptCache \
  --require-predictor-capability sequenceFork \
  --require-predictor-capability batchCandidates
```

See `docs/codex-history-eval.md`.

The report includes candidate-level ranking metrics such as `top1Accuracy`, `meanReciprocalRank`, `noiseRate`, end-to-end suggestion latency, and repeat/cache statistics, not just pass/fail recall.
When running against the local core, it also includes `cacheStats` so repeated-case evaluations can measure suggestion-cache hits. If optional vector recall is enabled, the same report includes `vectorStats`.
`eval-rime-sidecar` uses the same case format but scores only model/RAG side candidates from the merged `/rime-suggest` display payload. Use it after `eval-codex-history` to catch failures in side-first merge, side-slot limits, trigger policy, and `/rime-suggest` cache behavior.

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
first parsed candidate is available, then returns that early model side
candidate instead of waiting for the full JSON list. This is the latency
fallback for sub-200 ms first-visible candidates. Keep the flag off for quality
evals that need all model candidates; the long-term IME path should use a
resident MLX/llama.cpp backend that exposes logits/top-k or forked sequence
sampling so the panel can fill multiple inline model slots.

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
  --warmup-runs 1 \
  --repeat 20 \
  --latency-budget-ms 200
```

`bench-ime-ttfc` reports one summary per model with `p50FirstCandidateMs`,
`p95FirstCandidateMs`, `overBudgetCount`, `failureCount`, and a latency-only
winner. `--warmup-runs` runs full case passes before scoring so cold-load or
model-switch samples do not hide the resident IME path. Add `--include-cases`
when debugging individual samples.

The benchmark counts only usable first candidates. A raw token such as `R`, a
JSON prefix such as `["`, or a model echo of the current input such as `RAG`
does not satisfy TTFC. On 2026-07-01, `qwen3.5:0.8b-mlx` stayed fast on the
Mac warm path, but it frequently repeated mixed English/Chinese technical
input (`RAG`, `Squirrel`, `Wisdom-Weasel`), so the strict TTFC gate correctly
reported many missing candidates. That is the expected decision point: keep
Rime/RAG as the primary lane, and test larger or completion-oriented local
models before enabling model side candidates by default.
Once a model is chosen, wire the same TTFC cases into `quality-gate` with
`--require-model-ttfc`; this makes first-candidate latency part of the normal
release gate instead of a manual benchmark result.

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

This command prefers model/RAG side candidates in the visible slots, then fills remaining rows with Rime fallback candidates. Model candidates are marked `displayLayout: inline` for horizontal rendering, RAG/memory candidates are marked `displayLayout: block`, and Rime fallback candidates are marked `displayLayout: fallback`.

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
