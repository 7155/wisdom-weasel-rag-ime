# Wisdom-Weasel RAG IME - Single-File Context For Pro Model

Generated: 2026-07-05  
Repo path on the user's machine: `/Volumes/undo 4t/git/learnA/wisdom-weasel-rag-ime`  
Public repo URL, when accessible: `https://github.com/7155/wisdom-weasel-rag-ime`  
Current branch: `codex/wisdom-weasel-rag-ime-mvp`  
Purpose: this file is a self-contained handoff for a Pro model or engineer when
GitHub access is unavailable.

## Prompt To The Pro Model

You are reviewing a macOS Chinese input method project. The user is frustrated
because earlier iterations often proved only backend JSON, while the actual
foreground input method still felt unusable. Do not redefine success around
backend tests. Treat real foreground Squirrel/Rime behavior as the product.

Your job is to analyze the project from this single file, then propose or make
concrete fixes in the repository if available. Preserve these hard boundaries:

- Rime/Wanxiang stays the base IME for pinyin, fuzzy pinyin, dictionary
  candidates, paging, and fallback.
- This project adds side candidates from local LLM prediction and local
  RAG/memory.
- Realtime prediction must use a local small model. `x1api.top` is only for
  offline memory/RAG/lexicon cleanup.
- The final UX needs visible LLM/RAG/dictionary source distinction, number-key
  selection, correct Backspace/Delete context, and continuous prediction after
  selecting a side candidate.
- Use `Felix3322/Wisdom-Weasel` as the main behavioral reference, especially for
  context history, request/session identity, display candidate lists, feedback,
  and stale-result discard. Do not blindly port Windows TSF code.

## One-Screen Summary

This is a local-first macOS RAG input method prototype inspired by
`Felix3322/Wisdom-Weasel`.

Runtime shape:

```text
macOS Squirrel / Rime
  -> Rime parses pinyin and produces normal dictionary candidates
  -> patched Squirrel captures raw input, preedit, committed context, Rime candidates
  -> Python sidecar merges local model + RAG/memory + Rime fallback
  -> candidate panel displays source-aware candidates
  -> number keys select visible side candidates instead of inserting digits
  -> selection feedback updates local memory/frequency state
```

Current state:

- The repository has a patched Squirrel route and a debug-only native AppKit
  harness.
- The sidecar, local SQLite memory/RAG core, MLX local predictor, source-lane
  merge, feedback recording, and many tests exist.
- Recent verification showed `440 tests OK`.
- Earlier runtime repair verified selected input source
  `im.rag-ime.inputmethod.RagIme.Hans`, sidecar `127.0.0.1:8766`, MLX predictor
  `127.0.0.1:8767`, and mixed model/RAG candidates.
- Remaining core problems are product-quality and foreground UX, not only
  missing backend modules.

Most important unfinished item:

```text
real foreground continuous selection
-> local model top-3 logits seed branching
-> RAG/x1api offline database cleanup
-> source-colored candidate display polish
```

## User Requirements

Preserve these user statements as product requirements:

- "输入依旧没有 LLM 和 RAG 以及记忆" means backend data is not enough; LLM/RAG/memory
  must appear in the actual input method.
- "不是真实" and "预测感觉随机" mean the model lane must be traceable to active
  context, not generic filler.
- "上下文要按照实际输入，因为有删除的情况" means committed context must follow real
  foreground text after Backspace/Delete.
- "预测弹出框后选 123 没用，输入就是 123" means number keys must select live
  candidates, not insert literal digits when a side panel is active.
- "预测只有一个的话还不如 Tab" means one LLM candidate is not enough; the local
  model must produce multiple useful next-word or next-phrase candidates.
- "x1api 不要用来预测" means x1api is only for offline memory/RAG/lexicon
  optimization.
- "预测是本地的小模型" means realtime inference must remain local.
- "本地模型还能 KV" means the provider path should evolve toward prompt/KV cache
  and native local inference optimization.
- "四川人，模糊音必须可以设置，默认开启" means Sichuan fuzzy pinyin should be
  configurable and enabled by default in Rime bootstrap.
- "预测和 rag 以及词库用三种颜色" means the source lanes must be visually
  distinguishable.

The user's priority repair order:

1. Real foreground Squirrel install verification.
2. Backspace/Delete real context correctness.
3. RAG dedupe and database reorganization.
4. Local model multi-word continuous prediction quality.

## Expected Final Product

The acceptable product should behave like this:

```text
User types normally
  -> Rime/Wanxiang remains stable and immediate
  -> LLM appears as compact prediction candidates
  -> RAG/memory appears only when relevant to the actual current context
  -> dictionary/Rime fallback remains visible and selectable
  -> sources are visually distinct
  -> 1/2/3 selects the visible candidate bound to the current session
  -> selecting a side candidate immediately triggers the next prediction
  -> Backspace/Delete invalidates stale LLM/RAG context
```

Explicitly unacceptable:

- `/rime-suggest` returns JSON but foreground panel never shows it.
- RAG repeats old complaint/debug/input history unrelated to current context.
- LLM returns only one candidate or generic filler such as "下一步", "接下来",
  "根据上述".
- Backspace/Delete leaves deleted text in the model/RAG query.
- Candidate popup flashes too quickly to select.
- Number keys insert `1`, `2`, `3` while a live side candidate is visible.
- x1api or any cloud API is placed in the realtime per-keystroke prediction path.

## Source Repository Structure

Important root files:

- `README.md`: public overview and start points.
- `AGENTS.md`: short agent guide for public/code-model review.
- `PRO_MODEL_PROJECT_CONTEXT.md`: this single-file handoff.
- `pyproject.toml`: minimal Python project metadata.
- `.gitignore`: ignores `.env*`, SQLite databases, model files, logs, build
  outputs, archives, and local input history.

Active docs:

- `docs/project-status.md`: authoritative current project status, user
  requirements, acceptance criteria, and remaining work.
- `docs/design-decisions.md`: stable architecture decisions and boundaries.
- `docs/runtime-and-debug.md`: local run, install, doctor, and evaluation
  commands.
- `docs/eval/*.jsonl`: small regression/evaluation cases.
- `docs/archive/`: old process logs and superseded handoff/debug notes.

Core Python modules:

- `rag_ime/local_sqlite_core.py`: SQLite/FTS5/vector-ish local RAG and memory
  store; feedback, phrase stats, cleanup, RAG organization.
- `rag_ime/rime_sidecar.py`: HTTP sidecar logic for `/api/rime-suggest` and
  `/api/rime-select`, model/RAG/Rime merge, trigger policy, display payloads.
- `rag_ime/prediction_first.py`: prediction-first source-lane merge logic.
- `rag_ime/predictor.py`: predictor client abstraction and candidate parsing for
  OpenAI-compatible/Ollama/MLX services.
- `rag_ime/mlx_predictor_server.py`: resident local MLX model server.
- `rag_ime/memory_generator.py`: offline x1api-compatible memory/RAG/lexicon
  distillation.
- `rag_ime/debug_server.py`: debug and management endpoints.
- `rag_ime/history_context.py`: bounded recent-context construction and
  fingerprints.
- `rag_ime/models.py`: core dataclasses including input events, suggestions,
  model predictions, Rime snapshots, display items.

macOS frontend:

- `squirrel-patches/0001-add-rag-ime-sidecar.patch`: product route. This patches
  upstream Squirrel to call the local sidecar and show side candidates.
- `squirrel-patches/README.md`: patch preparation and Squirrel build notes.
- `macos/RagImeMac/`: debug-only native InputMethodKit/AppKit harness. Do not
  treat this as the shipping IME.

Scripts:

- `scripts/prepare_squirrel_workspace.sh`: clone/apply Squirrel patch.
- `scripts/build_patched_squirrel.sh`: build/install patched Squirrel.
- `scripts/restart_rag_ime_runtime.sh`: restart local MLX predictor + sidecar.
- `scripts/doctor_squirrel_integration.sh`: integration readiness doctor.
- `scripts/verify_squirrel_foreground_trace.sh`: foreground trace verifier.
- `scripts/check_squirrel_frontend_trace.py`: parse frontend JSONL trace.
- `scripts/install_sichuan_fuzzy_pinyin.sh`: Rime fuzzy-pinyin helper.
- `scripts/install_sidecar_launch_agent.sh`: user LaunchAgent for sidecar.
- `scripts/install_mlx_predictor_launch_agent.sh`: user LaunchAgent for MLX.
- `scripts/benchmark_mlx_model_matrix.py`: local model benchmark helper.

## Code Path Map

### Foreground Squirrel path

File: `squirrel-patches/0001-add-rag-ime-sidecar.patch`

Key responsibilities:

- Adds `RagImeSidecarClient.swift` and `RagImeSidecarModels.swift` to Squirrel.
- Captures Rime raw input, preedit, candidate page, labels, comments, and
  committed context.
- Schedules sidecar requests with request fingerprints and generation IDs.
- Applies sidecar `displayCandidates` only if current foreground context still
  matches.
- Holds post-commit candidates long enough for human selection.
- Routes number keys through visible `displayCandidates` before inserting
  literal digits.
- Records side-candidate commit and accepted RAG actions via `/rime-select`.
- Writes frontend trace to `~/Library/Logs/RagIme/squirrel-frontend.jsonl`.

Notable patch regions from current patch file:

- Sidecar client model definitions start around patch lines 188 and 525.
- State fields include `ragImeDisplayCandidates`, `ragImeDisplayRawInput`,
  `ragImeDisplayPreedit`, `ragImeDisplaySessionFingerprint`,
  `ragImeInputGeneration`, and holdover durations around patch lines 761-783.
- Delete-key invalidation and number-key routing appear around patch lines
  791-803.
- `selectCandidate` side-candidate commit path appears around patch lines
  810-855.
- `selectRagImeSideCandidate(forKey:)` appears around patch lines 939-963.
- `refreshRagImeSidecar(...)` request construction appears around patch lines
  965-1068.

Acceptance evidence should come from frontend trace events such as:

- `sidecar_request_scheduled`
- `sidecar_response_applied`
- `panel_display_candidates`
- `number_key_route`
- `side_candidate_commit`
- `committed_context_resynced_after_delete`
- `sidecar_response_dropped`

### Sidecar merge path

File: `rag_ime/rime_sidecar.py`

Important functions / structures:

- `RimeSideCandidateTriggerDecision` around line 231.
- `_ModelPredictionHoldover` around line 237.
- The main response payload assembly around lines 450-470 includes:
  `modelPredictions`, `ragCandidates`, `displayCandidates`,
  `predictionSession`, `selectionActions`, and `mergePolicy`.
- `suggest_rag_with_latency_budget(...)` around line 491.
- `realtime_model_candidate_limit(...)` around line 874.
- RAG repeat/context filters around lines 1052 and 1839.
- RAG/model lane status helpers around lines 1872 and 1891.
- Display payload helpers around lines 2826-2957.
- `_prediction_session_expiry_ms(...)` around line 2897.

Sidecar principle:

```text
Build semantic query from actual foreground state
  -> decide whether side candidates should refresh
  -> retrieve RAG with quality gates and overfetch
  -> request local model when useful
  -> merge model/RAG/Rime into displayCandidates
  -> attach sessionFingerprint and selection metadata
```

### Local MLX predictor path

File: `rag_ime/mlx_predictor_server.py`

Important functions:

- `class MlxLmEngine` around line 140.
- `MlxLmEngine.predict(...)` around line 201.
- `predict_no_input_continuation_branches(...)` around line 344.
- `predict_next_token_logits(...)` around line 491.
- `_stream_text_with_generate_step(...)` around line 657.
- `_build_mlx_dynamic_prompt(...)` around line 1081.
- `_top_logprob_indices(...)` around line 1487.
- `_continuation_branch_specs(...)` around line 1632.

Current implementation:

- Uses `mlx-lm` to load model/tokenizer in a resident server.
- This is not a hand-written Transformer runtime.
- The project-owned layer builds prompts, calls `generate_step()`, reads
  next-token `logprobs`, filters candidates, and converts outputs to IME
  candidates.
- Current `predict_next_token_logits()` probes the next-token logits with
  `max_tokens=1`.
- Current `no_input_prediction` can produce multiple candidates through
  `continuation-branches`, but this is a service-layer generation strategy, not
  true KV-cache sequence forking.
- Current doctor has reported `sequenceFork=false`.

Desired next local-model architecture:

```text
actual foreground context
-> tokenize
-> run prompt through local MLX model
-> inspect next-token logprobs
-> take top 3 seed tokens
-> fork or replay each seed as an independent continuation branch
-> extend each branch for a short phrase budget
-> decode into 3 LLM candidates
-> filter echo/prompt fragments/generic words
-> rerank with source diagnostics
-> mix with RAG and dictionary candidates using distinct source colors
```

Implementation advice:

- Do not modify hidden-layer internals before softmax unless absolutely needed.
- Work at the `generate_step()`/`logprobs` layer.
- First practical implementation can replay top-3 seed tokens against the
  prepared prompt cache if MLX-LM does not expose cheap cache cloning.
- Later optimization should use true KV cache copy/fork if available.
- Output should be phrase-oriented, not isolated high-probability filler tokens.

### Local RAG / memory path

File: `rag_ime/local_sqlite_core.py`

Important functions:

- `class LocalSqliteCoreClient` around line 54.
- `initialize()` around line 84.
- `record_event(...)` around line 246.
- `suggest_for_input(...)` around line 331.
- `retrieve_memories(...)` around line 362.
- `_retrieve_candidate_rows(...)` around line 413.
- `apply_action(...)` around line 449.
- `build_agent_context(...)` around line 493.
- `recent_input_context(...)` around line 514.
- `rebuild_vector_index(...)` around line 610.
- `list_memory_events(...)` around line 678.
- `core_optimization_snapshot(...)` around line 748.
- `hide_codex_history_noise(...)` around line 829.
- `organize_rag_database(...)` around line 910.

Data principles:

- SQLite event log stores committed input and memory events.
- FTS5 and optional embeddings support retrieval.
- Feedback actions such as accepted/skipped/downranked/pinned influence ranking.
- Generated one-off side candidates should not immediately become strong RAG
  memory without repeated acceptance, pinning, or frequency evidence.
- RAG must not dominate simply because a row is recent if the active context no
  longer supports it.

Offline cleanup:

- `x1api.top` can be used for memory distillation, phrase extraction, and cleanup
  suggestions.
- x1api must not be configured as the realtime predictor.
- Destructive cleanup should be advisory/dry-run until reviewed.

### Predictor client path

File: `rag_ime/predictor.py`

Responsibilities:

- Provider configs for OpenAI-compatible, Ollama, and MLX service.
- Candidate parsing from JSON, space-separated output, and raw generation.
- Low-value/meta candidate filtering.
- Environment-boundary logic so legacy `X1API_*` or generic API variables do
  not automatically configure realtime prediction.
- Predictor doctor and latency advice.

Important boundary:

```text
RAG_IME_PREDICTOR_* = realtime local predictor config
X1API_* / RAG_IME_AI_* = offline memory/RAG/lexicon cleanup config
```

### Debug server path

File: `rag_ime/debug_server.py`

Useful endpoints / methods:

- `health()`
- `rebuild_vector_index()`
- `memory_history()`
- `organize_rag_database()`
- `generate_memory()`
- `predictor_ttfc()`
- `cache_probe()`
- `rime_suggest()`
- `rime_select()`

Use it for diagnosing whether the model lane, RAG lane, cache, vector index, and
candidate source diagnostics are active.

## Current Verification Snapshot

Recent public-prep verification:

```bash
python3 -m unittest discover -s tests
```

Result:

```text
Ran 440 tests in 76.290s
OK
```

Recent project-public cleanup:

- Added root `AGENTS.md`.
- Updated `README.md` with public reviewer/pro-model start path.
- Expanded `.gitignore` for `.env*`, SQLite, logs, model weights, archives, and
  build outputs.
- Corrected `docs/runtime-and-debug.md` local MLX example to
  `RAG_IME_PREDICTOR_STREAM_FIRST=0` for multi-candidate behavior.
- Sensitive scan found no real API keys in active files. Tests contain fake
  fixture strings like `secret-value`.

Earlier runtime repair evidence:

- Selected input source:
  `im.rag-ime.inputmethod.RagIme.Hans`.
- Installed app:
  `~/Library/Input Methods/RAG-IME.app`.
- Sidecar:
  `http://127.0.0.1:8766`.
- MLX predictor:
  `http://127.0.0.1:8767`.
- Strict doctor previously passed with `failures=0 warnings=0`.
- Duplicate stale input method bundle was quarantined outside `Input Methods`.
- RAG DB cleanup hid 3 one-off polluted side-candidate rows, removed 3 hidden
  vectors, rebuilt 3990 local-hash vectors, and dry-run then returned
  `matchedNoise: 0`.
- Deployed sidecar verification returned 4 local model candidates and 2 RAG
  candidates for `我想设计一个候选展示方式`.

Treat this as strong but not final evidence. Final acceptance still requires
real foreground typing.

## Commands For A Fresh Reviewer

Basic code verification:

```bash
python3 -m unittest discover -s tests
git diff --check
```

Initialize local demo DB:

```bash
python3 -m rag_ime.cli init-db
python3 -m rag_ime.cli seed-demo --reset
```

Run sidecar directly:

```bash
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

Run local MLX predictor directly:

```bash
python3 -m rag_ime.cli mlx-predictor-server \
  --model "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local" \
  --host 127.0.0.1 \
  --port 8767 \
  --prompt-cache
```

Configure sidecar for local MLX:

```bash
export RAG_IME_PREDICTOR_PROVIDER=mlx
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767
export RAG_IME_PREDICTOR_MODEL="/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local"
export RAG_IME_PREDICTOR_PROFILE=instant
export RAG_IME_PREDICTOR_STREAM_FIRST=0
```

Restart local runtime:

```bash
scripts/restart_rag_ime_runtime.sh
```

Prepare and build patched Squirrel:

```bash
scripts/prepare_squirrel_workspace.sh
scripts/build_patched_squirrel.sh list
scripts/build_patched_squirrel.sh
scripts/build_patched_squirrel.sh install
```

Doctor:

```bash
scripts/doctor_squirrel_integration.sh
RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 scripts/doctor_squirrel_integration.sh
scripts/wait_squirrel_typing_ready.sh
scripts/verify_squirrel_foreground_trace.sh
```

Foreground trace:

```bash
tail -f "$HOME/Library/Logs/RagIme/squirrel-frontend.jsonl"
scripts/check_squirrel_frontend_trace.py "$HOME/Library/Logs/RagIme/squirrel-frontend.jsonl"
```

x1api offline optimization only:

```bash
cat > ~/.rag-ime-x1api.env <<'EOF'
X1API_BASE_URL=https://x1api.top/v1
X1API_API_KEY=replace-with-your-key
X1API_MODEL=replace-with-your-model
RAG_IME_AI_WIRE_API=chat_completions
EOF

RAG_IME_MODEL_ENV=~/.rag-ime-x1api.env \
python3 -m rag_ime.cli optimize-core \
  --db-path "$HOME/Library/Application Support/RagIme/rag-ime.sqlite" \
  --embedding-provider local-hash \
  --project wisdom-weasel-rag-ime \
  --dry-run
```

Review JSON output before removing `--dry-run`.

## Known Unfinished Work

### 1. Real foreground loop is not fully proven

The backend and doctor are healthy, but the user cares about the real input
panel. Automation can miss macOS focus/Accessibility state, so manual typing
remains important.

Acceptance scenario:

```text
Select RAG-IME - Simplified
Type a Chinese context in TextEdit/Codex/browser
Observe LLM/RAG/Rime source lanes
Press 1/2/3 and confirm candidate commits instead of digit insertion
Select one LLM candidate and wait briefly
Observe next prediction panel
Backspace/Delete text
Confirm next sidecar request uses the deleted-current context
```

### 2. Local top-3 seed branching is not implemented

Current MLX path has `next-token-logits` and `continuation-branches`, but not:

```text
top-3 next-token logprobs
-> fork/replay each seed
-> extend each to a phrase
-> return 3 branch candidates
```

This is the user's most important model-quality request.

### 3. Source colors need final foreground polish

The payload carries source identity (`sourceType`, `displayLane`,
`displayLayout`, comments such as `LLM`/`RAG`). The final Squirrel panel needs
clear source distinction:

- LLM / prediction: blue or compact inline style.
- RAG / memory: green/teal or evidence-backed block style.
- Rime / dictionary: orange or stable dictionary style.

### 4. RAG database cleanup is only conservative so far

Some stale generated/complaint rows were filtered or hidden, but full x1api
offline cleanup is still pending:

- summarize noisy history into stable memory facts;
- deduplicate similar old inputs;
- extract high-frequency phrases;
- downrank stale generated side candidates;
- provide reviewable cleanup suggestions.

### 5. Model quality is still weak

The current local 0.8B 4-bit model is usable for testing but often low quality.
Next steps:

- compare local models with fixed IME cases;
- measure first useful candidate latency and Hit@1/Hit@3;
- improve candidate filtering and branch generation;
- optionally train/LoRA/rerank after collecting real logs:
  `context -> shown candidates -> accepted/skipped -> next user text`.

### 6. Fuzzy pinyin needs final user-level confirmation

There is `scripts/install_sichuan_fuzzy_pinyin.sh`, and docs say Sichuan fuzzy
pinyin should be enabled by default. Confirm the actual user Rime config has the
expected fuzzy options after install.

### 7. Visual management UI is not final

The debug server has memory history and organization endpoints, but the polished
OpenLess-style visual management UI for history/RAG/memory/lexicon cleanup is
future work.

## Suggested Next Engineering Plan

### Step 1: Prove foreground continuity

Goal: produce one clean single-session trace proving:

- panel displays model/RAG/Rime source lanes;
- number key selects a visible side candidate;
- selection commits text;
- follow-up prediction appears;
- Backspace/Delete resyncs context;
- stale responses are dropped.

Files likely involved:

- `squirrel-patches/0001-add-rag-ime-sidecar.patch`
- `scripts/verify_squirrel_foreground_trace.sh`
- `scripts/check_squirrel_frontend_trace.py`
- `tests/test_squirrel_frontend_trace.py`

### Step 2: Implement local top-3 seed branching

Goal: upgrade `MlxLmEngine` to produce phrase candidates from top-3 next-token
seeds.

Likely target:

- `rag_ime/mlx_predictor_server.py`
- `tests/test_mlx_predictor_server.py`
- `tests/test_doctor_squirrel_integration.py`

Proposed API shape:

```python
def predict_top_seed_continuation_branches(
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int = 3,
    branch_count: int = 3,
    branch_max_tokens: int = 12,
) -> dict[str, Any]:
    ...
```

Implementation sketch:

```text
1. Build prompt from actual context.
2. Run generate_step(..., max_tokens=1) without sampler to obtain logprobs.
3. Pick top N token IDs after filtering obvious low-value tokens.
4. For each seed token:
   a. create prompt or token sequence including the seed;
   b. continue generation for branch_max_tokens with low temperature/top_p;
   c. decode seed + generated continuation;
   d. parse into phrase candidate;
   e. filter echo/meta/filler/repeated context.
5. Deduplicate candidates.
6. Attach candidateScores with seed token ID, logprob/probability, branch rank,
   mode="top-seed-continuation-branches".
7. Return fallback to existing continuation-branches if no branch quality passes.
```

Do not route x1api into this path.

### Step 3: RAG offline cleanup pass

Goal: make RAG memory useful instead of old-input repetition.

Likely target:

- `rag_ime/local_sqlite_core.py`
- `rag_ime/memory_generator.py`
- `rag_ime/debug_server.py`
- `tests/test_local_sqlite_core.py`
- `tests/test_memory_generator.py`
- `tests/test_debug_server.py`

Requirements:

- dry-run by default;
- no secrets retained;
- generated side candidates require repeated evidence before becoming strong
  RAG;
- user can inspect cleanup suggestions.

### Step 4: Final source-lane visual polish

Goal: real foreground panel visibly separates LLM/RAG/Rime.

Likely target:

- `squirrel-patches/0001-add-rag-ime-sidecar.patch`
- maybe Squirrel candidate rendering comments/layout methods;
- `macos/RagImeMac/Sources/RagCandidatePanel.swift` only as a visual reference,
  not as the product route.

Acceptance:

- screenshots or trace summaries prove source lane counts and selected item.

## Test Inventory

Important test files:

- `tests/test_mlx_predictor_server.py`: local model generation/candidate modes.
- `tests/test_rime_sidecar.py`: sidecar candidate merge and context behavior.
- `tests/test_doctor_squirrel_integration.py`: doctor/MLX/Squirrel integration
  payload validation.
- `tests/test_squirrel_frontend_trace.py`: frontend trace parsing and session
  assertions.
- `tests/test_local_sqlite_core.py`: RAG/memory ranking, cleanup, feedback.
- `tests/test_memory_generator.py`: x1api-style offline memory generation.
- `tests/test_predictor.py`: predictor config boundaries and candidate parsing.
- `tests/test_prediction_first.py`: source-lane merge.
- `tests/test_install_squirrel_rag_config.py`: Rime/Squirrel config install.
- `tests/test_check_macos_input_source.py`: macOS input source checking.

Run:

```bash
python3 -m unittest discover -s tests
```

## Public/Safety Notes

Do not commit:

- `.env` files;
- API keys;
- local SQLite databases;
- model weights;
- built `.app` bundles;
- personal input history;
- logs containing private input text.

Ignored patterns include `.rag-ime-data/`, `.env*`, `*.sqlite`, `*.db`,
`*.safetensors`, `*.gguf`, `*.mlmodel`, `*.log`, archives, and build outputs.

The repository currently has no final production license decision. Choose a
license before inviting broad reuse beyond analysis.

## What The Pro Model Should Return

Useful answer format:

1. Identify the highest-confidence root cause or missing implementation for the
   current remaining problem.
2. Point to exact files/functions to change.
3. Give a minimal patch plan.
4. Preserve the realtime-local-model and x1api-offline boundary.
5. Include verification commands and real foreground acceptance evidence.

The best next code contribution is likely either:

- a robust foreground trace/verification improvement proving continuous
  selection, or
- `MlxLmEngine` top-3 seed continuation branching with tests.

Do not spend the next iteration adding more scattered docs. Keep this file and
`docs/project-status.md` updated instead.
